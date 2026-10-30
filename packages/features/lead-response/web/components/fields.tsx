"use client";
/** The form's building blocks: a label, the control, a live example sentence and a friendly error, all tied together. */
import type { ReactNode } from "react";

import { CONTROL } from "../lib/look";

/** A small warning mark. The error text always comes with it, so colour is never the only signal. */
export function WarnIcon() {
  return (
    <svg aria-hidden width="16" height="16" viewBox="0 0 16 16" className="mt-0.5 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path d="M8 1.8 14.6 13.4H1.4L8 1.8Z" strokeLinejoin="round" />
      <path d="M8 6.2v3.4M8 11.4v.2" strokeLinecap="round" />
    </svg>
  );
}

export function FieldError({ id, children }: { id: string; children: ReactNode }) {
  return (
    <p id={id} data-testid={id} className="mt-2 flex gap-1.5 text-[14px] font-medium text-danger-ink">
      <WarnIcon />
      <span>{children}</span>
    </p>
  );
}

type Common = {
  id: string; // the control's id; the summary links to it
  label: string;
  value: string;
  onChange: (value: string) => void;
  onBlur?: () => void;
  error?: string;
  example?: string;
  note?: string;
};

function Wrap({ id, label, error, example, note, extra, children }: Pick<Common, "id" | "label" | "error" | "example" | "note"> & { extra?: ReactNode; children: ReactNode }) {
  return (
    <div className="mb-6 last:mb-0">
      <label htmlFor={id} className="mb-1.5 block text-[15px] font-semibold">
        {label}
      </label>
      {children}
      {extra}
      {error && <FieldError id={`${id}-error`}>{error}</FieldError>}
      {(example || note) && (
        <p id={`${id}-help`} className="mt-2 text-[14px] text-muted" data-testid={`${id}-help`}>
          {!error && example} {note}
        </p>
      )}
    </div>
  );
}

const describedBy = (id: string, error?: string, hasHelp?: boolean) =>
  [error ? `${id}-error` : null, hasHelp ? `${id}-help` : null].filter(Boolean).join(" ") || undefined;

export function NumberField({ unit, ...c }: Common & { unit: string }) {
  return (
    <Wrap {...c}>
      <span className="flex items-center gap-2.5">
        <input
          id={c.id}
          type="text"
          inputMode="numeric"
          autoComplete="off"
          maxLength={4}
          value={c.value}
          onChange={(e) => c.onChange(e.target.value)}
          onBlur={c.onBlur}
          aria-invalid={c.error ? true : undefined}
          aria-describedby={describedBy(c.id, c.error, !!(c.example || c.note))}
          className={`${CONTROL} w-24`}
          data-testid={c.id}
        />
        <span className="text-[15px]">{unit}</span>
      </span>
    </Wrap>
  );
}

export function TextAreaField({ counter, ...c }: Common & { counter: string }) {
  return (
    <Wrap {...c} extra={<p className="mt-1.5 text-right text-[13px] text-muted" data-testid={`${c.id}-count`}>{counter}</p>}>
      <textarea
        id={c.id}
        rows={4}
        value={c.value}
        onChange={(e) => c.onChange(e.target.value)}
        onBlur={c.onBlur}
        aria-invalid={c.error ? true : undefined}
        aria-describedby={describedBy(c.id, c.error, !!(c.example || c.note)) }
        className={`${CONTROL} w-full leading-[1.6]`}
        data-testid={c.id}
      />
    </Wrap>
  );
}

export function SelectField({ options, ...c }: Common & { options: { value: string; label: string }[] }) {
  return (
    <Wrap {...c}>
      <select
        id={c.id}
        value={c.value}
        onChange={(e) => c.onChange(e.target.value)}
        onBlur={c.onBlur}
        aria-invalid={c.error ? true : undefined}
        aria-describedby={describedBy(c.id, c.error, !!(c.example || c.note))}
        className={`${CONTROL} min-w-52`}
        data-testid={c.id}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </Wrap>
  );
}
