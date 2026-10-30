"use client";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "@clinic/core/web/auth/provider";
import { Alert, Button, Dialog, DialogActions, PageHeading, Panel } from "@clinic/ui";

import { browserClient } from "../lib/client";
import { FOCUS, LINK } from "../lib/look";
import {
  ackCounter,
  classifySave,
  formatSavedAt,
  holdingExample,
  hoursExample,
  RESET_LABEL,
  RESET_NOTE,
  ROLE_CHOICES,
  SAVE_PROBLEMS,
  slaExample,
  statusLine,
  type SaveKind,
} from "../lib/messages";
import { saveOutcome, type Outcome } from "../lib/save";
import {
  applyForm,
  DAYS,
  errorList,
  formFromConfig,
  isStandard,
  sameForm,
  validate,
  type Config,
  type Day,
  type Errors,
  type FormState,
  type WindowForm,
} from "../lib/settings";
import { AiSection, ComingLater } from "./ai-section";
import { NumberField, SelectField, TextAreaField, WarnIcon } from "./fields";
import { HoursEditor } from "./hours-editor";
import { Notice } from "./notices";
import { SaveBar } from "./save-bar";

export type Initial = { version: number; config: Config; defaults: Config; timezone: string; updatedAt: string | null };
type Result = { kind: "outcome"; outcome: Outcome } | { kind: "reset" } | { kind: "problem"; problem: SaveKind };

function Section({ id, title, hint, tag, children }: { id: string; title: string; hint?: string; tag?: boolean; children: React.ReactNode }) {
  return (
    <Panel aria-labelledby={id} className="mb-5">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h2 id={id} className="m-0 text-[20px] font-[650] tracking-[-0.4px]">
            {title}
          </h2>
          {hint && <p className="mt-1 mb-0 text-[14px] text-muted">{hint}</p>}
        </div>
        {tag && <ComingLater />}
      </div>
      {children}
    </Panel>
  );
}

/** Which errors the person has earned: all of them after a Save attempt, otherwise only those of boxes they have left. */
function visible(errors: Errors, touched: Set<string>, attempted: boolean): Errors {
  if (attempted) return errors;
  const out: Errors = {};
  for (const key of ["ack", "holding", "sla", "role", "quiet"] as const) if (errors[key] && touched.has(key)) out[key] = errors[key];
  for (const day of DAYS) {
    const message = errors.hours?.[day];
    if (message && touched.has(`hours-${day}`)) (out.hours ??= {})[day] = message;
  }
  return out;
}

export function SettingsForm({ initial }: { initial: Initial }) {
  const { auth } = useAuth();
  const router = useRouter();
  const client = useMemo(() => browserClient(auth.csrf_token, auth.workspace?.id), [auth.csrf_token, auth.workspace?.id]);
  const [saved, setSaved] = useState({ version: initial.version, config: initial.config });
  const [updatedAt, setUpdatedAt] = useState(initial.updatedAt);
  const [form, setForm] = useState<FormState>(() => formFromConfig(initial.config));
  const [touched, setTouched] = useState<Set<string>>(new Set());
  const [attempted, setAttempted] = useState(false);
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const [leaveTo, setLeaveTo] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [focusSummary, setFocusSummary] = useState(0);
  const summary = useRef<HTMLDivElement>(null);
  const problem = useRef<HTMLDivElement>(null);
  const skipWarning = useRef(false);

  const original = useMemo(() => formFromConfig(saved.config), [saved]);
  const dirty = !sameForm(form, original);
  const errors = validate(form);
  const problems = errorList(errors);
  const shown = visible(errors, touched, attempted);
  const standard = isStandard(form, initial.defaults);

  useEffect(() => setReady(true), []);
  useEffect(() => {
    if (focusSummary > 0) summary.current?.focus();
  }, [focusSummary]);
  useEffect(() => {
    if (result?.kind === "problem") problem.current?.focus();
  }, [result]);

  // Leaving with unsaved changes: the browser asks for a reload, close or outside link; our own links ask in a dialog.
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => {
      if (!skipWarning.current) e.preventDefault();
    };
    const click = (e: MouseEvent) => {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const link = (e.target as HTMLElement).closest?.("a[href]") as HTMLAnchorElement | null;
      if (!link || (link.target && link.target !== "_self") || link.hasAttribute("download")) return;
      const url = new URL(link.href, window.location.href);
      if (url.origin !== window.location.origin) return;
      if (url.pathname === window.location.pathname && url.search === window.location.search) return;
      e.preventDefault();
      e.stopPropagation();
      setLeaveTo(url.pathname + url.search + url.hash);
    };
    window.addEventListener("beforeunload", warn);
    document.addEventListener("click", click, true);
    return () => {
      window.removeEventListener("beforeunload", warn);
      document.removeEventListener("click", click, true);
    };
  }, [dirty]);

  const touch = (key: string) => setTouched((t) => (t.has(key) ? t : new Set(t).add(key)));
  function edit(patch: Partial<FormState>) {
    setResult(null);
    setForm((f) => ({ ...f, ...patch }));
  }
  const editDay = (day: Day, windows: WindowForm[]) => edit({ hours: { ...form.hours, [day]: windows } });

  async function save() {
    if (saving || !dirty) return;
    if (problems.length > 0) {
      setAttempted(true);
      setFocusSummary((n) => n + 1);
      return;
    }
    setSaving(true);
    setResult(null);
    try {
      const { data, error, response } = await client.PUT("/features/lead_response/settings", {
        params: { header: { "if-match": String(saved.version) } },
        body: applyForm(saved.config, form),
      });
      if (data) {
        const next = { version: data.version, config: data.config as Config };
        setResult({ kind: "outcome", outcome: saveOutcome(saved, next) });
        setSaved(next);
        setUpdatedAt(data.updated_at ?? null);
        setForm(formFromConfig(next.config)); // what the server stored: trimmed text, windows in order
        setTouched(new Set());
        setAttempted(false);
      } else {
        setResult({ kind: "problem", problem: classifySave(response.status, (error as { detail?: unknown } | undefined)?.detail) });
      }
    } catch {
      setResult({ kind: "problem", problem: "failed" });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div data-testid="settings-form" data-ready={ready || undefined}>
      <PageHeading
        title="Settings"
        description="How your clinic answers a new lead who texts, and when your team is reminded."
        actions={
          <Button
            type="button"
            variant="outline"
            disabled={standard || saving}
            onClick={() => {
              setForm(formFromConfig(initial.defaults));
              setTouched(new Set());
              setAttempted(false);
              setResult({ kind: "reset" });
            }}
            data-testid="reset"
          >
            {RESET_LABEL}
          </Button>
        }
      />
      <p className="mb-5 text-[14px] text-muted" data-testid="settings-status">
        {statusLine(saved.version)}
        {saved.version > 0 && updatedAt && ` Last saved ${formatSavedAt(updatedAt, initial.timezone)}.`}
      </p>

      {result?.kind === "outcome" && (
        <Notice title={result.outcome.text} testId="saved-notice">
          {result.outcome.changed.length > 0 && <>Changed: {result.outcome.changed.join(", ")}.</>}
        </Notice>
      )}
      {result?.kind === "reset" && <Notice title={RESET_NOTE} testId="reset-notice" />}
      {result?.kind === "problem" && (
        <div ref={problem} tabIndex={-1} className="outline-none" data-testid="save-problem" data-problem={result.problem}>
          <Alert>
            <strong className="block">{SAVE_PROBLEMS[result.problem].title}</strong>
            {SAVE_PROBLEMS[result.problem].text}
            {result.problem === "stale" && (
              <div className="mt-3">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    skipWarning.current = true;
                    window.location.reload();
                  }}
                  data-testid="reload"
                >
                  Reload the latest settings
                </Button>
              </div>
            )}
          </Alert>
        </div>
      )}
      {attempted && problems.length > 0 && (
        <div ref={summary} tabIndex={-1} aria-labelledby="summary-title" className="mb-5 rounded-[13px] border-2 border-danger bg-danger-soft p-4 text-danger-ink outline-none" data-testid="error-summary">
          <h2 id="summary-title" className="m-0 flex items-center gap-2 text-[16px] font-bold">
            <WarnIcon />
            {problems.length === 1 ? "There is 1 thing to fix before you can save" : `There are ${problems.length} things to fix before you can save`}
          </h2>
          <ul className="mt-2 mb-0 list-disc pl-6 text-[14px]">
            {problems.map((p) => (
              <li key={p.id}>
                <a
                  href={`#${p.id}`}
                  className={`${LINK} ${FOCUS}`}
                  onClick={(e) => {
                    e.preventDefault();
                    document.getElementById(p.id)?.focus();
                  }}
                >
                  {p.label}
                </a>
                : {p.message}
              </li>
            ))}
          </ul>
        </div>
      )}

      <Section id="sec-ack" title="When a lead texts you" hint="Every new lead gets this reply within seconds.">
        <TextAreaField
          id="field-ack"
          label="Instant reply"
          value={form.ack}
          onChange={(v) => edit({ ack: v })}
          onBlur={() => touch("ack")}
          error={shown.ack}
          counter={ackCounter([...form.ack.trim()].length)}
          example="This is the exact message a new lead receives."
          note="Plain text only. Names and other details can't be added to it yet."
        />
      </Section>

      <Section id="sec-timers" title="If nobody has replied" hint="Two reminders, counted from the moment the lead texts.">
        <NumberField
          id="field-holding"
          label="Send a holding message after"
          unit="minutes"
          value={form.holding}
          onChange={(v) => edit({ holding: v })}
          onBlur={() => touch("holding")}
          error={shown.holding}
          example={holdingExample(form.holding)}
        />
        <NumberField
          id="field-sla"
          label="Staff response target"
          unit="minutes"
          value={form.sla}
          onChange={(v) => edit({ sla: v })}
          onBlur={() => touch("sla")}
          error={shown.sla}
          example={slaExample(form.sla, form.role)}
          note="This must be longer than the holding message time."
        />
        <SelectField
          id="field-role"
          label="Who is told"
          value={form.role}
          onChange={(v) => edit({ role: v })}
          onBlur={() => touch("role")}
          error={shown.role}
          options={ROLE_CHOICES.map((r) => ({ value: r.value, label: r.label }))}
        />
      </Section>

      <Section id="sec-hours" title="Hours" hint={hoursExample(form.hours)}>
        <HoursEditor form={form} errors={shown} timezone={initial.timezone} onHours={editDay} onQuiet={(quiet) => edit({ quiet })} onTouch={touch} />
      </Section>

      <Section id="sec-ai" title="AI replies" tag>
        <AiSection />
      </Section>

      <SaveBar
        dirty={dirty}
        saving={saving}
        problems={attempted ? problems.length : 0}
        onSave={save}
        onDiscard={() => {
          setForm(original);
          setTouched(new Set());
          setAttempted(false);
          setResult(null);
        }}
      />

      {leaveTo && (
        <Dialog title="Leave without saving?" onClose={() => setLeaveTo(null)}>
          <p data-testid="leave-dialog" className="m-0 text-[15px]">
            You have changes that are not saved. If you leave now, they are lost.
          </p>
          <DialogActions>
            <Button type="button" variant="brand" onClick={() => setLeaveTo(null)} data-testid="stay">
              Stay on this page
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                const to = leaveTo;
                setLeaveTo(null);
                router.push(to);
              }}
              data-testid="leave"
            >
              Leave without saving
            </Button>
          </DialogActions>
        </Dialog>
      )}
    </div>
  );
}
