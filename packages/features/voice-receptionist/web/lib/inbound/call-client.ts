import { CAPTURE_WORKLET, Player } from "./audio";

export type CallState = "idle" | "connecting" | "live" | "ended" | "error";

export type CallListener = {
  state: (state: CallState) => void;
  transcript: (speaker: "caller" | "agent", text: string) => void;
  fields: (values: Record<string, unknown>) => void;
  level: (level: number) => void; // 0..1 microphone level
  interrupted: () => void;
  audioBlocked: (blocked: boolean) => void;
  tool: (
    name: string,
    status: "running" | "ok" | "failed",
    durationMs?: number,
  ) => void;
  ended: (reason: string) => void;
  error: (message: string) => void;
};

const MAX_BUFFERED_BYTES = 64_000; // about 2 s of caller audio; beyond that frames are dropped, not queued

function wsBase(): string {
  const api = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  return api.replace(/^http/, "ws").replace(/\/$/, "");
}

function micMessage(error: unknown): string {
  const name = error instanceof DOMException ? error.name : "";
  if (name === "NotAllowedError")
    return "Microphone access was blocked. Allow it in your browser and try again.";
  if (name === "NotFoundError")
    return "No microphone was found on this device.";
  return "Could not start the microphone.";
}

const CLOSE_MESSAGES: Record<number, string> = {
  1008: "The call could not be opened. The link may have expired; start a new test call.",
  1013: "The voice service is busy. Try again in a moment.",
};

/** One browser call: microphone -> WebSocket -> agent, and agent audio back to the speakers. */
export class CallClient {
  private ws: WebSocket | null = null;
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private player: Player | null = null;
  private finished = false;
  private live = false;
  private connectionTimer: ReturnType<typeof setTimeout> | null = null;

  get active(): boolean {
    return !this.finished;
  }

  /** Called directly from the Start click, before any API or microphone await. */
  async prepare(): Promise<void> {
    if (this.finished) return;
    if (typeof AudioContext === "undefined")
      throw new Error(
        "This browser cannot play call audio. Use a current browser.",
      );
    if (!this.ctx) this.ctx = new AudioContext({ latencyHint: "interactive" });
    const ctx = this.ctx;
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        ctx.resume(),
        new Promise<never>((_, reject) => {
          timer = setTimeout(
            () =>
              reject(
                new Error(
                  "Audio could not start. Click Call again to enable your speakers.",
                ),
              ),
            5000,
          );
        }),
      ]);
      if (this.finished) return;
      if (ctx.state !== "running")
        throw new Error(
          "Audio is blocked. Click Call again to enable your speakers.",
        );
      ctx.onstatechange = () => {
        if (this.finished || ctx.state === "closed") return;
        const blocked = ctx.state !== "running";
        if (blocked) this.player?.stop();
        this.listener.audioBlocked(blocked);
      };
    } finally {
      if (timer) clearTimeout(timer);
    }
  }

  async resumeAudio(): Promise<void> {
    try {
      await this.ctx?.resume();
      this.listener.audioBlocked(this.ctx?.state !== "running");
    } catch {
      this.listener.audioBlocked(true);
    }
  }

  constructor(private listener: CallListener) {}

  async start(opts: {
    path: string;
    ticket: string;
    outputRate: number;
  }): Promise<void> {
    this.listener.state("connecting");
    try {
      if (
        !navigator.mediaDevices?.getUserMedia ||
        typeof AudioWorkletNode === "undefined"
      )
        throw new Error(
          "This browser cannot capture audio for calls. Use a current Chrome, Edge, Safari or Firefox.",
        );
      await this.prepare();
      if (this.finished) return;
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      if (this.finished) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      this.stream = stream;
      const ctx = this.ctx;
      if (!ctx) return;
      const url = URL.createObjectURL(
        new Blob([CAPTURE_WORKLET], { type: "application/javascript" }),
      );
      try {
        await ctx.audioWorklet.addModule(url);
      } finally {
        URL.revokeObjectURL(url);
      }
      if (this.finished) return;
      this.player = new Player(ctx, opts.outputRate);
      this.openSocket(
        `${wsBase()}${opts.path}?ticket=${encodeURIComponent(opts.ticket)}`,
      );
      this.startCapture();
    } catch (error) {
      this.fail(
        error instanceof Error && !(error instanceof DOMException)
          ? error.message
          : micMessage(error),
      );
    }
  }

  private openSocket(url: string): void {
    const ws = new WebSocket(url);
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    this.connectionTimer = setTimeout(() => {
      this.fail(
        "The voice service took too long to connect. Please try again.",
      );
    }, 35_000);
    ws.onmessage = (message) => {
      if (this.finished) return;
      if (message.data instanceof ArrayBuffer) {
        if (this.ctx?.state !== "running") {
          this.listener.audioBlocked(true);
          return;
        }
        try {
          this.player?.play(message.data);
        } catch {
          this.fail(
            "Your browser could not play the call audio. Check your audio device and try again.",
          );
        }
        return;
      }
      let event: { type: string; [key: string]: unknown };
      try {
        event = JSON.parse(String(message.data));
      } catch {
        return;
      }
      this.onEvent(event);
    };
    ws.onclose = (close) => {
      if (this.finished) return;
      this.fail(CLOSE_MESSAGES[close.code] ?? "The call connection was lost.");
    };
  }

  private onEvent(event: { type: string; [key: string]: unknown }): void {
    switch (event.type) {
      case "ready":
        // WebSocket accepted is not the same as a connected speech model.
        break;
      case "model_ready":
        if (this.connectionTimer) clearTimeout(this.connectionTimer);
        this.connectionTimer = null;
        this.live = true;
        this.listener.state("live");
        break;
      case "transcript":
        this.listener.transcript(
          event.speaker as "caller" | "agent",
          String(event.text),
        );
        break;
      case "fields":
        this.listener.fields(event.values as Record<string, unknown>);
        break;
      case "tool":
        this.listener.tool(
          String(event.name),
          event.status as "running" | "ok" | "failed",
          typeof event.duration_ms === "number" ? event.duration_ms : undefined,
        );
        break;
      case "interrupted":
        this.player?.stop(); // the caller spoke over the agent
        this.listener.interrupted();
        break;
      case "ended":
        this.finish(String(event.reason));
        break;
    }
  }

  private startCapture(): void {
    const ctx = this.ctx;
    const stream = this.stream;
    if (!ctx || !stream) return;
    const source = ctx.createMediaStreamSource(stream);
    const capture = new AudioWorkletNode(ctx, "capture", {
      numberOfInputs: 1,
      numberOfOutputs: 1,
      channelCount: 1,
    });
    const mute = ctx.createGain();
    mute.gain.value = 0; // keeps the node running without playing the microphone back
    source.connect(capture).connect(mute).connect(ctx.destination);
    capture.port.onmessage = (
      message: MessageEvent<{ pcm: ArrayBuffer; level: number }>,
    ) => {
      this.listener.level(Math.min(1, message.data.level * 4));
      const ws = this.ws;
      if (
        this.live &&
        this.ctx?.state === "running" &&
        ws?.readyState === WebSocket.OPEN &&
        ws.bufferedAmount < MAX_BUFFERED_BYTES
      )
        ws.send(message.data.pcm);
    };
  }

  /** Ask the server to end the call; the agent's last words finish playing first. */
  hangup(): void {
    if (this.finished) return;
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "hangup" }));
      setTimeout(() => this.finish("caller_hangup"), 3000); // if the server never answers
    } else {
      this.finish("caller_hangup");
    }
  }

  private finish(reason: string): void {
    if (this.finished) return;
    this.finished = true;
    this.listener.ended(reason);
    this.listener.state("ended");
    this.release(reason === "agent_ended");
  }

  private fail(message: string): void {
    if (this.finished) return;
    this.finished = true;
    this.listener.error(message);
    this.listener.state("error");
    this.release(false);
  }

  /** Stop the microphone at once; let the agent's closing audio drain before closing the speakers. */
  private release(drain: boolean): void {
    if (this.connectionTimer) clearTimeout(this.connectionTimer);
    this.connectionTimer = null;
    this.live = false;
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
    if (this.ws && this.ws.readyState <= WebSocket.OPEN) this.ws.close();
    const ctx = this.ctx;
    const player = this.player;
    this.ctx = this.player = null;
    if (!ctx) return;
    ctx.onstatechange = null;
    const close = () => void ctx.close().catch(() => undefined);
    if (!drain || !player) return close();
    const deadline = Date.now() + 4000;
    const wait = setInterval(() => {
      if (player.drained || Date.now() > deadline) {
        clearInterval(wait);
        close();
      }
    }, 100);
  }

  dispose(): void {
    if (!this.finished) {
      this.finished = true;
      this.release(false);
    }
  }
}
