"use client";
/** Business hours (up to three time ranges a day) and quiet hours. Native time boxes, so the keyboard and phone pickers work. */
import { Button } from "@clinic/ui";

import { CHECK, CONTROL } from "../lib/look";
import { daySummary, quietExample } from "../lib/messages";
import { DAYS, DAY_LABELS, LIMITS, NEW_WINDOW, type Day, type Errors, type FormState, type WindowForm } from "../lib/settings";
import { FieldError } from "./fields";

type Props = {
  form: FormState;
  errors: Errors;
  timezone: string;
  onHours: (day: Day, windows: WindowForm[]) => void;
  onQuiet: (quiet: FormState["quiet"]) => void;
  onTouch: (key: string) => void;
};

function TimeBox({ label, value, onChange, onBlur, invalid, testId }: { label: string; value: string; onChange: (v: string) => void; onBlur: () => void; invalid: boolean; testId: string }) {
  return (
    <input
      type="time"
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onBlur={onBlur}
      aria-invalid={invalid ? true : undefined}
      className={`${CONTROL} w-36`}
      data-testid={testId}
    />
  );
}

export function HoursEditor({ form, errors, timezone, onHours, onQuiet, onTouch }: Props) {
  return (
    <div>
      <div className="mb-3 text-[15px] font-semibold" id="business-hours-title">
        Business hours
      </div>
      <p className="mb-4 text-[14px] text-muted">
        Times are in your clinic&apos;s time zone: <strong className="text-ink" data-testid="timezone">{timezone}</strong>. To change the time zone, use the workspace settings.
      </p>
      <div role="group" aria-labelledby="business-hours-title">
        {DAYS.map((day) => {
          const windows = form.hours[day];
          const error = errors.hours?.[day];
          const open = windows.length > 0;
          return (
            <fieldset key={day} className="border-line mb-3 rounded-[13px] border p-3.5" data-testid={`hours-${day}`}>
              <legend className="px-1 text-[15px] font-semibold">{DAY_LABELS[day]}</legend>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                <label className="flex cursor-pointer items-center gap-2.5 text-[15px]">
                  <input
                    id={`field-hours-${day}`}
                    type="checkbox"
                    checked={open}
                    onChange={(e) => {
                      onHours(day, e.target.checked ? [{ ...NEW_WINDOW }] : []);
                      onTouch(`hours-${day}`);
                    }}
                    aria-describedby={error ? `field-hours-${day}-error` : undefined}
                    className={CHECK}
                    data-testid={`open-${day}`}
                  />
                  Open
                </label>
                <span className="text-[14px] text-muted" data-testid={`summary-${day}`}>
                  {error ? "" : daySummary(windows)}
                </span>
              </div>
              {windows.map((w, i) => (
                <div key={i} className="mt-3 flex flex-wrap items-center gap-2.5" data-testid={`window-${day}-${i}`}>
                  <TimeBox
                    label={`${DAY_LABELS[day]}, range ${i + 1}, opens at`}
                    value={w.start}
                    onChange={(v) => onHours(day, windows.map((x, j) => (j === i ? { ...x, start: v } : x)))}
                    onBlur={() => onTouch(`hours-${day}`)}
                    invalid={!!error}
                    testId={`start-${day}-${i}`}
                  />
                  <span aria-hidden>to</span>
                  <TimeBox
                    label={`${DAY_LABELS[day]}, range ${i + 1}, closes at`}
                    value={w.end}
                    onChange={(v) => onHours(day, windows.map((x, j) => (j === i ? { ...x, end: v } : x)))}
                    onBlur={() => onTouch(`hours-${day}`)}
                    invalid={!!error}
                    testId={`end-${day}-${i}`}
                  />
                  <Button
                    type="button"
                    variant="outline"
                    aria-label={`Remove range ${i + 1} for ${DAY_LABELS[day]}`}
                    onClick={() => {
                      onHours(day, windows.filter((_, j) => j !== i));
                      onTouch(`hours-${day}`);
                    }}
                    data-testid={`remove-${day}-${i}`}
                  >
                    Remove
                  </Button>
                </div>
              ))}
              {open && windows.length < LIMITS.windows_per_day && (
                <div className="mt-3">
                  <Button
                    type="button"
                    variant="outline"
                    aria-label={`Add another time range for ${DAY_LABELS[day]}`}
                    onClick={() => onHours(day, [...windows, { start: "", end: "" }])}
                    data-testid={`add-${day}`}
                  >
                    Add another range
                  </Button>
                </div>
              )}
              {error && <FieldError id={`field-hours-${day}-error`}>{error}</FieldError>}
            </fieldset>
          );
        })}
      </div>

      <fieldset className="border-line mt-6 rounded-[13px] border p-3.5" data-testid="quiet-hours">
        <legend className="px-1 text-[15px] font-semibold">Quiet hours</legend>
        <label className="flex cursor-pointer items-center gap-2.5 text-[15px]">
          <input
            id="field-quiet"
            type="checkbox"
            checked={form.quiet.on}
            onChange={(e) => {
              onQuiet({ ...form.quiet, on: e.target.checked });
              onTouch("quiet");
            }}
            aria-describedby={errors.quiet ? "field-quiet-error" : undefined}
            className={CHECK}
            data-testid="quiet-on"
          />
          Use quiet hours
        </label>
        {form.quiet.on && (
          <div className="mt-3 flex flex-wrap items-center gap-2.5">
            <TimeBox
              label="Quiet hours start at"
              value={form.quiet.start}
              onChange={(v) => onQuiet({ ...form.quiet, start: v })}
              onBlur={() => onTouch("quiet")}
              invalid={!!errors.quiet}
              testId="quiet-start"
            />
            <span aria-hidden>to</span>
            <TimeBox
              label="Quiet hours end at"
              value={form.quiet.end}
              onChange={(v) => onQuiet({ ...form.quiet, end: v })}
              onBlur={() => onTouch("quiet")}
              invalid={!!errors.quiet}
              testId="quiet-end"
            />
          </div>
        )}
        {errors.quiet && <FieldError id="field-quiet-error">{errors.quiet}</FieldError>}
        <p className="mt-3 text-[14px] text-muted" data-testid="quiet-example">
          {quietExample(form.quiet, timezone)}
        </p>
      </fieldset>
    </div>
  );
}
