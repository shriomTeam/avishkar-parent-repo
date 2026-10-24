"use client";
import { useEffect, useMemo, useState } from "react";
import { useAuth } from "@clinic/core/web/auth/provider";

import { browserClient } from "../lib/client";
import {
  applyForm,
  FIELD_BY_KEY,
  formFromConfig,
  GROUPS,
  isStandard,
  parseValue,
  sameForm,
  validate,
  type Config,
  type FieldKey,
  type FormState,
} from "../lib/settings";
import { Button, ButtonLink, Card, Icon, Notice, PageHead } from "./kit";
import { ROOT } from "./shell-nav";

export type SavedSettings = { version: number; config: Config; defaults: Config };

type Result = { kind: "saved" } | { kind: "stale" } | { kind: "invalid" } | { kind: "forbidden" } | { kind: "failed" };

const SECTIONS: { title: string; hint: string; keys: FieldKey[] }[] = [
  {
    title: "When a patient counts as dormant",
    hint: "These timelines decide who is overdue to come back.",
    keys: ["dormantDays", "intervalDays", "oneAndDoneDays"],
  },
  {
    title: "Top spenders",
    hint: "Top spenders who are well past their usual return time are the first group the analysis looks at.",
    keys: ["topPercent", "topDollars"],
  },
  {
    title: "What dormant patients could be worth",
    hint: "These feed the revenue ranges on the Overview. They are estimates, not promises.",
    keys: ["churnMonths", "rateLow", "rateHigh"],
  },
];

export function SettingsForm({ initial }: { initial: SavedSettings }) {
  const { auth } = useAuth();
  const client = useMemo(() => browserClient(auth.csrf_token, auth.workspace?.id), [auth.csrf_token, auth.workspace?.id]);
  const [saved, setSaved] = useState(initial);
  const [form, setForm] = useState<FormState>(() => formFromConfig(initial.config));
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<Result | null>(null);

  const original = useMemo(() => formFromConfig(saved.config), [saved]);
  const dirty = !sameForm(form, original);
  const errors = validate(form, saved.config);
  const hasErrors = Object.keys(errors).length > 0;
  const standard = isStandard(form, saved.defaults);

  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  function setValue(key: FieldKey, value: string) {
    setResult(null);
    setForm((f) => ({ ...f, values: { ...f.values, [key]: value } }));
  }

  async function save() {
    if (saving || !dirty || hasErrors) return;
    setSaving(true);
    setResult(null);
    try {
      const { data, response } = await client.PUT("/features/reactivation/settings", {
        params: { header: { "if-match": String(saved.version) } },
        body: applyForm(saved.config, form),
      });
      if (data) {
        const next = { version: data.version, config: data.config as Config, defaults: data.defaults as Config };
        setSaved(next);
        setForm(formFromConfig(next.config));
        setResult({ kind: "saved" });
      } else if (response.status === 412) setResult({ kind: "stale" });
      else if (response.status === 422) setResult({ kind: "invalid" });
      else if (response.status === 403) setResult({ kind: "forbidden" });
      else setResult({ kind: "failed" });
    } catch {
      setResult({ kind: "failed" });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="dp-stack" data-testid="settings-form">
      <PageHead
        title="Settings"
        description="How patients are judged dormant and what they could be worth."
        actions={
          <Button
            variant="secondary"
            onClick={() => {
              setResult(null);
              setForm(formFromConfig(saved.defaults));
            }}
            disabled={standard || saving}
            data-testid="settings-reset"
          >
            Reset to defaults
          </Button>
        }
      />
      <p className="dp-small" data-testid="settings-status">
        {saved.version === 0 ? "Using the standard settings." : `Using your saved settings (version ${saved.version}).`} A change
        applies to the next analysis. Results you already have don&apos;t change.
      </p>

      {result?.kind === "saved" && (
        <Notice
          tone="info"
          title="Saved."
          action={
            <ButtonLink variant="secondary" href={ROOT} data-testid="settings-to-overview">
              Go to the Overview
            </ButtonLink>
          }
        >
          Your next analysis will use these settings.
        </Notice>
      )}
      {result?.kind === "stale" && (
        <Notice
          tone="error"
          title="These settings changed while you were editing."
          action={
            <Button variant="secondary" onClick={() => window.location.reload()}>
              Load the latest
            </Button>
          }
        >
          Someone else saved a change. Load the latest settings, then make your changes again.
        </Notice>
      )}
      {result?.kind === "invalid" && (
        <Notice tone="error">One of the values isn&apos;t allowed. Check the numbers and try again.</Notice>
      )}
      {result?.kind === "forbidden" && (
        <Notice tone="error">Only the clinic owner or office manager can change these settings.</Notice>
      )}
      {result?.kind === "failed" && <Notice tone="error">We couldn&apos;t save. Please try again in a moment.</Notice>}

      {SECTIONS.map((section) => (
        <Card key={section.title} title={section.title}>
          <p className="dp-sub dp-settings-hint">{section.hint}</p>
          <div className="dp-settings-grid">
            {section.keys.map((key) => {
              const def = FIELD_BY_KEY[key];
              const raw = form.values[key];
              const error = errors[key];
              const n = parseValue(raw);
              const shown = error ? "" : def.example(n !== null && Number.isNaN(n) ? null : n);
              return (
                <div className="dp-setting" key={key}>
                  <label className="dp-field" htmlFor={`setting-${key}`}>
                    <span>{def.label}</span>
                    <span className="dp-setting-box">
                      {def.prefix && <span className="dp-setting-unit">{def.prefix}</span>}
                      <input
                        id={`setting-${key}`}
                        type="text"
                        inputMode="numeric"
                        autoComplete="off"
                        value={raw}
                        maxLength={9}
                        aria-invalid={error ? true : undefined}
                        aria-describedby={`setting-${key}-help`}
                        onChange={(e) => setValue(key, e.target.value)}
                        data-testid={`setting-${key}`}
                      />
                      <span className="dp-setting-unit">{def.unit}</span>
                    </span>
                  </label>
                  <p id={`setting-${key}-help`} className="dp-setting-help">
                    {error ? (
                      <span className="dp-setting-error" data-testid={`setting-${key}-error`}>
                        {error}
                      </span>
                    ) : (
                      <>
                        {shown} {def.note}
                      </>
                    )}
                  </p>
                </div>
              );
            })}
          </div>
        </Card>
      ))}

      <Card title="Patient types to look for">
        <p className="dp-sub dp-settings-hint">Switch off any type you don&apos;t want in the analysis.</p>
        <div className="dp-settings-switches">
          {GROUPS.map((g) => (
            <label className="dp-check" key={g.key}>
              <input
                type="checkbox"
                checked={form.switches[g.key]}
                onChange={(e) => {
                  setResult(null);
                  setForm((f) => ({ ...f, switches: { ...f.switches, [g.key]: e.target.checked } }));
                }}
                data-testid={`setting-switch-${g.key}`}
              />
              <span>{g.label}</span>
            </label>
          ))}
        </div>
      </Card>

      <div className="dp-savebar" data-dirty={dirty || undefined} data-testid="settings-savebar">
        <span className="dp-savebar-text" role="status">
          {dirty ? (
            <>
              <Icon name="warn" size={16} /> {hasErrors ? "Fix the highlighted boxes to save." : "You have unsaved changes."}
            </>
          ) : (
            "No unsaved changes."
          )}
        </span>
        <span className="dp-savebar-actions">
          <Button
            variant="secondary"
            onClick={() => {
              setResult(null);
              setForm(original);
            }}
            disabled={!dirty || saving}
            data-testid="settings-discard"
          >
            Discard changes
          </Button>
          <Button onClick={save} disabled={!dirty || hasErrors || saving} aria-busy={saving || undefined} data-testid="settings-save">
            {saving ? "Saving…" : "Save settings"}
          </Button>
        </span>
      </div>
    </div>
  );
}
