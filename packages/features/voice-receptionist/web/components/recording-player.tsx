"use client";
import { useEffect, useRef, useState } from "react";
import { Pause, Play } from "lucide-react";
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
      <div className="recording" role="status">
        <p className="muted">
          This call was set to be recorded, but the recording could not be
          saved.
        </p>
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
    <div className="recording">
      <h3>Recording</h3>
      <div
        className="player"
        onContextMenu={(e) => e.preventDefault()}
        role="group"
        aria-label="Call recording"
      >
        <button
          className="primary player-play"
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
        </button>
        <span className="player-time">{clock(position)}</span>
        <input
          className="player-seek"
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
        <span className="player-time">{length ? clock(length) : "–:––"}</span>
        <button
          className="player-speed"
          onClick={cycleSpeed}
          aria-label={`Playback speed ${speed}×, change`}
        >
          {speed}×
        </button>
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
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      <p className="muted">
        Caller on the left, agent on the right. Each listen is recorded.
      </p>
    </div>
  );
}
