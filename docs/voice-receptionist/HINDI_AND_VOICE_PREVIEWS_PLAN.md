# Conversation languages and dynamic first-message previews

Branch: `codex/voice-hindi-previews`, based on main `1e3316e`.
Status: implemented and validated locally; prepared for pull request review. Production deployment and acoustic acceptance remain pending.

## Confirmed behavior

- The editor offers exactly **English (`en-US`), Hindi (`hi-IN`), Spanish (`es-US`)**, in this order. Locale codes specify the provider variants; no other languages are advertised as operational in the dropdown. Existing saved legacy locale values are not silently rewritten or migrated. Select a supported language to enable preview for a legacy agent.
- The editable prompt and First message stay unchanged. Runtime call policy tells the model to speak the selected language, including translating the configured opening into that language while retaining its meaning. The caller can request a language switch. Both browser and Twilio calls use the shared call engine and snapshot policy.
- Transcripts preserve the actual language spoken. Captured descriptions use English; names are transliterated into Latin letters. Structured numbers, booleans, dates, phones, email and exact configured enum options/identifiers keep their canonical formats. Non-Latin free-text capture is rejected with a translation/transliteration retry message. Validation is not a semantic translator: English wording and name accuracy still require real-conversation review. Existing records, external tool responses, knowledge documents and user-authored configuration are not retrospectively translated.

## Listen to sample

Pressing **Listen to sample** submits the current unsaved First message, voice, language and agent name to `POST /features/voice_receptionist/inbound/voice-preview`. No saved agent ID or system prompt is required. It speaks the message once, translating into the selected language when necessary. It is an isolated opening preview, not a complete call simulation or a promise that conversational delivery will be identical.

The server resolves workspace/custom variables using the existing resolver, including `{{clinic_name}}` and the unsaved `{{agent_name}}`. Unknown variables are rejected. `{{caller_number}}` is `not available`, as in a browser call. Date/time values are the workspace-local current time. The server gets workspace context from the authenticated membership, never the body. No tools, arbitrary endpoint or caller microphone are enabled. Previews do not save agents, call history, transcripts or recordings, and never overwrite the configured text.

The aligned Voice/preview control uses existing shared UI components and Tailwind. Empty First message disables preview. States include loading/cancel, playing/stop, end and retryable failure. Changes to message, agent name, voice or language, and component unmount, stop/release playback and abort stale browser requests. An aborted request may already have incurred model processing; generation is bounded independently on the server.

## Backend limits and privacy

- Reuses the configured Vertex Live model, region, service identity and existing voice allowlist. Preview generation needs no new environment variables, database tables, infrastructure, workers or background generation. The separate speech-sensitivity follow-up adds a column to existing agents.
- Existing authentication, CSRF on writes, feature entitlements and manager configuration permissions apply. Owner and Office Manager can preview; other roles cannot. The preview cannot execute tools.
- Request: nonblank first message, at most 1,000 characters; agent name at most 200; supported locale/voice only. Resolved message at most 4,000 characters. Unknown template variables return 422.
- Durable rate counters: six requests/minute per actor/workspace and twenty/minute per workspace, including cache hits and provider failures. In-flight generation: two per API instance; duplicates already generating return retryable 429. These concurrency bounds are per instance, not a global quota.
- Generation timeout 45 seconds, at most 45 seconds of mono PCM16 audio at 24 kHz, returned as WAV. Long messages can hit that limit: shorten and retry. Provider failures return a sanitized 503; prompts/credentials/provider errors are not exposed or logged by the preview code.
- Successful audio is cached only in bounded process memory: three-minute TTL with scheduled cleanup, 32 entries and 12 MiB maximum per instance. Keys hash authenticated workspace, resolved text, voice, language, model, provider project/location and policy version. No cross-workspace cache reuse. Browser responses use `private, no-store`. Restarts drop the cache; different instances may generate the same preview. No production audio is committed or persisted to disk/storage.
- Dynamic previews are paid model requests on cache miss and have model/network latency. No request occurs merely by opening the editor. The original fixed-recording implementation and generation utility/assets were removed.

## Code locations

- Language policy: `src/clinic_voice_receptionist/inbound/live/language.py`; prompt/opening: `live/prompt.py`, `live/session.py`.
- Preview input, authorization, variable resolution and rate budget: `src/clinic_voice_receptionist/voice_preview/router.py`.
- Tool-free model request, WAV encoding, timeout/size bounds and workspace cache: `voice_preview/service.py`.
- Frontend: `web/components/voice-preview.tsx`, integrated in `agent-fields.tsx`; request adapter: `web/lib/inbound/api.ts`; editor language list: `web/lib/inbound/draft.ts`.
- Tests use a test-only tone generator injected through the existing optional feature test hook; ordinary browser tests never call Vertex. Real-model checks run explicitly outside CI.

## Rule for future languages

Every newly supported language must use this same dynamic First-message preview path. **Do not add hardcoded greetings, pre-recorded audio, browser speech synthesis, silent English fallback or a separate per-language service.**

1. Verify language code and voice compatibility for the exact configured Vertex model and SDK. Verify live conversation and real preview audio, not just dropdown availability.
2. Add its locale/label to backend `SUPPORTED_LANGUAGES`/language name mapping and frontend `LANGUAGES`, preserving existing codes. The preview component sends the selected locale directly; it has no language-specific audio mapping or fixed text.
3. Extend preview, opening-language, extraction and transcript tests. Check translated greetings, proper names, interruptions, tool capture, mixed speech and caller-requested switches using an actual browser and phone call where supported.
4. Regenerate the API contract after schema changes; run build, lint, typechecks, boundaries and relevant/full suites. Document any unsupported voices or variants before exposing the new option.

## Local acceptance

Start the existing database/Redis, apply current main migrations if not already done, then use the normal `pnpm dev` workflow. No extra keys are required. The later speech-sensitivity follow-up adds migration `20261030_voice_sensitivity`.

Open an agent, change First message without saving, select English/Hindi/Spanish and a voice, then press Listen. Confirm the new text is used and speech follows the selected language. Change it again, retry and verify no stale audio plays. Preview variables, blank input, failures/retry and mobile alignment. Then save, make a Test studio call and inspect original-language transcripts and English captured fields. Test the Twilio path if configured. Human listening and translation/transliteration accuracy remain local acceptance checks.

Sources consulted during planning: [Vertex Live language/voice configuration](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/live-api/configure-language-voice). No model upgrade was introduced.

## Validation completed (30 October 2026)

- Full Python suite: **1,268 passed, 4 expected failures**. Voice backend slice: **322 passed**.
- Voice browser suite: **22 passed**, including current draft text, the three dropdown choices, preview request payloads, blank-message disabling, no agent write, changes stopping playback and actual browser audio decoding (test-only generated tone).
- Explicit real Vertex checks generated audio successfully for the same English first message with English, Hindi and Spanish selected. These were three bounded provider calls outside routine tests; human listening accuracy remains an acceptance step.
- Production web build, feature typecheck, web ESLint, Ruff, Python/frontend boundaries and whitespace checks passed. The final preview-specific rate-limit wording adjustment was verified with **22 passing preview/language tests** afterward.
- API client schema regenerated. No fixed WAV assets or generation utility remain. No production deployment was performed during validation.

## Browser call startup and audio reliability follow-up

Local metadata review found two short caller-ended calls with early model interruption events; one had zero completed agent turns. No transcript text or audio was read for this diagnosis. This supports investigating greeting barge-in; it does not prove whether the input was room noise, echo or intentional caller speech, and does not rule out transient network delays.

Changes:
- Unlock/resume the AudioContext directly from the Start click, before the ticket request and microphone permission wait, following browser autoplay requirements.
- Treat WebSocket `ready` as transport acceptance. The shared call engine emits `model_ready` only after provider connection/opening setup; browser microphone frames and the Live indicator wait for it, so startup input is not queued as stale speech while the model connects.
- Original PR #25 used LOW globally to reduce spurious interruptions. This is superseded by the per-agent follow-up below: HIGH is restored by default and LOW requires an explicit choice. End-of-speech timing remains unchanged.
- Bound model connection (20 seconds), opening send (10 seconds) and browser connection wait (35 seconds). A stalled service cannot leave an indefinitely Live-looking session.
- Expose an Enable audio action if the browser suspends/interrupts audio, allowing the same session to continue. Pause microphone forwarding while speaker audio is paused, stop stale queued playback and release device resources on cancel. Previously missed speech is not replayed automatically: ask the agent to repeat if necessary.
- Allow cancelling while Connecting, handle late microphone permission resolution without leaking tracks, and stop audio immediately on caller hangup; only the agent's natural goodbye drains before closing.

Validation: **324 voice backend tests** and **24 voice browser journeys** passed, including delayed model readiness, connection timeout, gesture-backed audio startup and suspending/resuming audio without creating a second call. Typecheck, lint and whitespace checks passed. A physical microphone/headphone acceptance call is still needed; synthetic tests do not recreate the user's exact acoustic/network conditions.

References: [browser AudioContext activation](https://developer.mozilla.org/en-US/docs/Web/API/Web_Audio_API/Best_practices), [Gemini speech sensitivity values](https://ai.google.dev/api/live).

Final follow-up validation: repository Python suite **1,270 passed, 4 expected failures**; production web build and architecture boundaries passed. Local API readiness returned 200. No real microphone recording was inspected, no production configuration changed, and no production deployment was performed.


## Review follow-up: per-agent speech detection

Updated the same branch from merged main `69e831c`. Removed the global LOW speech-start override. New/existing agents now default to HIGH, restoring the pre-tuning behavior. Added an Owner/Office-Manager-editable `speech_start_sensitivity` enum (`high`/`low`), persisted on `voice.agents`, returned in API responses, editable under Speech detection, and copied into the shared browser/Twilio call snapshot. The Gemini connector uses LOW only when explicitly present in that snapshot; missing/unknown legacy values use HIGH. End sensitivity, 700 ms silence and prefix padding are unchanged. The browser gesture/readiness/recovery fixes remain in place.

The additive migration `20261030_voice_sensitivity` follows `0282a1e9855e`, adds a non-null server-default HIGH column and a high/low check constraint. Old API inserts can omit it. Existing agents were not implicitly opted into LOW by the previous hard-coded implementation; the migration deliberately restores HIGH for them. Already-created snapshots with explicit settings retain their own values when an agent is edited.

Completed a disposable-database upgrade test containing a pre-migration agent: its new value is HIGH. Alembic reports no model drift. Configuration tests cover HIGH/LOW/legacy fallback, API persistence/validation/permissions, browser snapshots, and a signed Twilio webhook/stream path retaining the chosen sensitivity after a later agent edit. These tests verify configuration and authorization, **not** physical speech-detection accuracy.

### Required phone acceptance before opting into LOW

Use a real inbound Twilio call, not a preview or scripted browser model. Compare HIGH and LOW on the same agent/device and record the result:

| Language | Short replies | Interruptions | Quiet room | Background noise | Result |
| --- | --- | --- | --- | --- | --- |
| English | yes / no | normal and quiet speech | Pending | Pending | Pending human test |
| Hindi | हाँ / नहीं | normal and quiet speech | Pending | Pending | Pending human test |
| Spanish | sí / no | normal and quiet speech | Pending | Pending | Pending human test |

Confirm the opening is audible, short answers are recognized, callers can interrupt naturally and interruptions clear Twilio playback. Keep HIGH unless the actual call results justify LOW. Per-agent configuration makes the tradeoff explicit; it does not guarantee either value handles every noise level. No real phone call was placed or production deployment changed by this follow-up.

Follow-up validation: **1,283 Python tests passed, 4 existing Lead Response permission xfails**; **25 voice browser journeys passed**; targeted sensitivity/Twilio slice **40 passed**. Production web build, feature typecheck, web ESLint, Ruff, architecture boundaries and whitespace checks passed. One Alembic head (`20261030_voice_sensitivity`), upgrade of a pre-existing agent and no model drift verified. Local development database was migrated; production was not touched. The real-phone acceptance table remains pending and must not be reported as passed.
