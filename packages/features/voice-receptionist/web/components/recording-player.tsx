"use client";
import { useEffect, useRef, useState } from "react";
import { Pause, Play } from "lucide-react";
import { Alert, Button, H3, Muted } from "@clinic/ui";
import { ApiError, type InboundApi } from "../lib/inbound/api";

const SPEEDS = [0.75, 1, 1.25, 1.5, 2];

const clock = (seconds: number) => {
  const whole = Math.max(0, Math.floor(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
};

/**
 * The call's audio, with our own controls: play or pause, a seek bar and the playback speed. There is no
 * download control. The file is fetched only when someone first presses Play, so merely opening a call does not
 * download patient audio, and each listen is recorded on the server.
 */
export function RecordingPlayer({
  callId,
  status,
  api,
}: {
  callId: string;
  status: string | null | undefined;
  api: InboundApi;
}) {
  const audio = useRef<HTMLAudioElement>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState(0);
  const [length, setLength] = useState(0);
  const [speed, setSpeed] = useState(1);

  useEffect(
    () => () => {
      if (url) URL.revokeObjectURL(url);
    },
    [url],
  );
  // The element exists only once the file has arrived; start it then.
  useEffect(() => {
    if (url) void audio.current?.play().catch(() => setPlaying(false));
  }, [url]);

  if (!status) return null;
  if (status !== "saved")
    return (
      <div className="mb-2 border-b border-line pb-4" role="status">
        <Muted>
          This call was set to be recorded, but the recording could not be
          saved.
        </Muted>
      </div>
    );

  async function toggle() {
    if (url) {
      const el = audio.current;
      if (!el) return;
      if (el.paused) void el.play();
      else el.pause();
      return;
    }
    setLoading(true);
    setError("");
    try {
      setUrl(URL.createObjectURL(await api.getRecording(callId)));
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 404
          ? "The recording is no longer available."
          : "Could not load the recording. Please retry.",
      );
    } finally {
      setLoading(false);
    }
  }

  function cycleSpeed() {
    const next = SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.length] ?? 1;
    setSpeed(next);
    if (audio.current) audio.current.playbackRate = next;
  }

  const progress = length ? (position / length) * 100 : 0;
  return (
    <div className="mb-2 grid gap-2 border-b border-line pb-4">
      <H3 flush>Recording</H3>
      <div
        className="flex max-w-[560px] items-center gap-3 rounded-xl border border-line bg-white px-3.5 py-2.5"
        onContextMenu={(e) => e.preventDefault()}
        role="group"
        aria-label="Call recording"
      >
        <Button
          variant="brand"
          size="icon"
          className="shrink-0"
          onClick={toggle}
          disabled={loading}
          aria-label={
            loading
              ? "Loading recording"
              : playing
                ? "Pause recording"
                : "Play recording"
          }
        >
          {playing ? <Pause size={16} /> : <Play size={16} />}
        </Button>
        <span className="min-w-9 shrink-0 text-[13px] tabular-nums text-muted">
          {clock(position)}
        </span>
        <input
          className="focus-ring m-0 h-1.5 min-w-20 flex-1 cursor-pointer appearance-none rounded-full bg-[linear-gradient(to_right,var(--color-brand)_var(--progress,0%),var(--color-line)_var(--progress,0%))] disabled:cursor-default [&::-moz-range-thumb]:size-3 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-2 [&::-moz-range-thumb]:border-ink [&::-moz-range-thumb]:bg-white [&::-webkit-slider-thumb]:size-3.5 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-ink [&::-webkit-slider-thumb]:bg-white disabled:[&::-webkit-slider-thumb]:invisible"
          type="range"
          aria-label="Seek"
          min={0}
          max={length || 1}
          step={0.1}
          value={Math.min(position, length || 1)}
          disabled={!url || !length}
          style={{ "--progress": `${progress}%` } as React.CSSProperties}
          onChange={(e) => {
            const at = Number(e.target.value);
            setPosition(at);
            if (audio.current) audio.current.currentTime = at;
          }}
        />
        <span className="min-w-9 shrink-0 text-[13px] tabular-nums text-muted">
          {length ? clock(length) : "–:––"}
        </span>
        <Button
          variant="brand"
          size="pill"
          onClick={cycleSpeed}
          aria-label={`Playback speed ${speed}×, change`}
        >
          {speed}×
        </Button>
        {url && (
          <audio
            ref={audio}
            src={url}
            preload="auto"
            controlsList="nodownload noplaybackrate"
            onLoadedMetadata={(e) => {
              setLength(e.currentTarget.duration);
              e.currentTarget.playbackRate = speed;
            }}
            onTimeUpdate={(e) => setPosition(e.currentTarget.currentTime)}
            onPlay={() => setPlaying(true)}
            onPause={() => setPlaying(false)}
            onEnded={() => setPlaying(false)}
          />
        )}
      </div>
      {error && <Alert>{error}</Alert>}
      <Muted>
        Caller on the left, agent on the right. Each listen is recorded.
      </Muted>
    </div>
  );
}
