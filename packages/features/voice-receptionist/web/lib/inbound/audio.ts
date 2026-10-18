/** Audio plumbing for the browser end of a call. PCM16 mono: 16 kHz up to the agent, 24 kHz back. */

export const CAPTURE_RATE = 16_000;
export const FRAME_SAMPLES = 320; // 20 ms at 16 kHz
const PLAYBACK_CUSHION_S = 0.06; // jitter cushion before agent audio starts, and again after any gap

/**
 * Runs on the audio thread. Averages each window of input samples into one 16 kHz sample (a simple
 * low-pass, so speech survives downsampling from the device rate), packs 20 ms frames as PCM16 and
 * posts them to the page along with a level for the meter. Loaded from a Blob so no bundler setup is needed.
 */
export const CAPTURE_WORKLET = `
class Capture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / ${CAPTURE_RATE};
    this.pos = 0; this.sum = 0; this.n = 0;
    this.frame = new Int16Array(${FRAME_SAMPLES}); this.i = 0; this.sq = 0;
  }
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) return true;
    for (let k = 0; k < channel.length; k++) {
      this.sum += channel[k]; this.n++; this.pos++;
      if (this.pos < this.ratio) continue;
      this.pos -= this.ratio;
      const v = Math.max(-1, Math.min(1, this.sum / this.n));
      this.sum = 0; this.n = 0;
      this.frame[this.i++] = v < 0 ? v * 0x8000 : v * 0x7fff;
      this.sq += v * v;
      if (this.i === this.frame.length) {
        this.port.postMessage({ pcm: this.frame.buffer, level: Math.sqrt(this.sq / this.i) }, [this.frame.buffer]);
        this.frame = new Int16Array(${FRAME_SAMPLES}); this.i = 0; this.sq = 0;
      }
    }
    return true;
  }
}
registerProcessor("capture", Capture);
`;

export function pcm16ToFloat(pcm: ArrayBuffer): Float32Array {
  const samples = new Int16Array(pcm, 0, Math.floor(pcm.byteLength / 2));
  const out = new Float32Array(samples.length);
  for (let i = 0; i < samples.length; i++) out[i] = (samples[i] ?? 0) / 0x8000;
  return out;
}

/** Schedules agent audio back to back, and can cut it off instantly when the caller interrupts. */
export class Player {
  private next = 0;
  private sources = new Set<AudioBufferSourceNode>();

  constructor(
    private ctx: AudioContext,
    private rate: number,
  ) {}

  play(pcm: ArrayBuffer): void {
    const samples = pcm16ToFloat(pcm);
    if (!samples.length) return;
    const buffer = this.ctx.createBuffer(1, samples.length, this.rate);
    buffer.copyToChannel(new Float32Array(samples), 0);
    const source = this.ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(this.ctx.destination);
    const startAt = Math.max(
      this.ctx.currentTime + PLAYBACK_CUSHION_S,
      this.next,
    );
    source.start(startAt);
    this.next = startAt + buffer.duration;
    this.sources.add(source);
    source.onended = () => this.sources.delete(source);
  }

  /** Barge-in: stop everything that is queued or playing. */
  stop(): void {
    for (const source of this.sources) {
      try {
        source.stop();
      } catch {
        // already ended
      }
    }
    this.sources.clear();
    this.next = 0;
  }

  get drained(): boolean {
    return this.ctx.currentTime >= this.next;
  }
}
