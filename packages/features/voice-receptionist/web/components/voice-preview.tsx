"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Play, Square } from "lucide-react";
import { Button, TwoColumns } from "@clinic/ui";
import { LANGUAGES } from "../lib/inbound/draft";
import { ApiError, type InboundApi } from "../lib/inbound/api";

/** Speak the current unsaved first message; all supported languages share this path. */
export function VoicePreview({
  voice,
  language,
  api,
  greeting,
  agentName,
  children,
}: {
  voice: string;
  language: string;
  api: InboundApi;
  greeting: string;
  agentName: string;
  children: ReactNode;
}) {
  const playback = useRef<HTMLAudioElement | null>(null);
  const objectUrl = useRef<string | null>(null);
  const generation = useRef(0);
  const request = useRef<AbortController | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "playing">("idle");
  const [error, setError] = useState("");
  const languageName = LANGUAGES.find(([code]) => code === language)?.[1];

  function release() {
    generation.current += 1;
    request.current?.abort();
    request.current = null;
    const audio = playback.current;
    if (audio) {
      audio.onended = null;
      audio.onerror = null;
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
    }
    playback.current = null;
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    objectUrl.current = null;
  }

  useEffect(() => {
    setState("idle");
    setError("");
    return release;
  }, [voice, language, greeting, agentName, api]);

  async function toggle() {
    if (state !== "idle") {
      release();
      setState("idle");
      return;
    }
    const current = ++generation.current;
    setError("");
    setState("loading");
    try {
      request.current = new AbortController();
      const blob = await api.previewVoice(
        { language, voice, greeting, agent_name: agentName },
        request.current.signal,
      );
      if (current !== generation.current) return;
      objectUrl.current = URL.createObjectURL(blob);
      const audio = new Audio(objectUrl.current);
      playback.current = audio;
      audio.onended = () => {
        release();
        setState("idle");
      };
      audio.onerror = () => {
        release();
        setState("idle");
        setError("Could not play the sample. Please retry.");
      };
      await audio.play();
      if (current === generation.current) setState("playing");
    } catch (e) {
      if (current !== generation.current) return;
      release();
      setState("idle");
      setError(
        e instanceof ApiError
          ? e.message
          : "Could not play the sample. Please retry.",
      );
    }
  }

  return (
    <div
      className="mb-[21px] flex flex-col gap-2"
      role="group"
      aria-label="Voice sample preview"
    >
      <TwoColumns className="items-end">
        {children}
        <Button
          className="h-[45px]"
          type="button"
          variant="outline"
          disabled={state === "idle" && (!greeting.trim() || !languageName)}
          onClick={() => void toggle()}
          aria-label={
            state === "idle"
              ? `Listen to ${voice} voice sample`
              : "Stop voice sample"
          }
        >
          {state === "idle" ? (
            <Play size={16} aria-hidden />
          ) : (
            <Square size={16} aria-hidden />
          )}
          {state === "loading"
            ? "Cancel loading"
            : state === "playing"
              ? "Stop sample"
              : "Listen to sample"}
        </Button>
      </TwoColumns>
      <small className="text-muted" aria-live="polite">
        {state === "loading"
          ? "Loading sample… "
          : state === "playing"
            ? "Playing sample. "
            : ""}
        {!languageName
          ? "Choose a supported language to preview."
          : !greeting.trim()
            ? "Enter a first message to hear it."
            : `Your first message in ${languageName} · No save needed.`}
      </small>
      {error && (
        <small className="text-danger" role="alert">
          {error}
        </small>
      )}
    </div>
  );
}
