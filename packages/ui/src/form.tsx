import { useId, type ReactNode } from "react";
import type {
  InputHTMLAttributes,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";
import { cx } from "./cx";

const control =
  "border border-[#dedce5] text-ink focus:border-focus focus-ring";
const skin = "rounded-lg bg-white px-[13px] py-[11px] text-[14px]";
const codeSkin = "rounded-[9px] bg-[#f7f6fa] p-[15px] font-mono text-[13px]";

/** Controls fill their container; pass `inline` to size to their content instead. */
type Sizing = { inline?: boolean };

export function Input({
  className,
  inline,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & Sizing) {
  return (
    <input
      className={cx(control, skin, inline ? "w-auto" : "w-full", className)}
      {...props}
    />
  );
}

export function Textarea({
  className,
  inline,
  compact = false,
  code = false,
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement> &
  Sizing & { compact?: boolean; code?: boolean }) {
  return (
    <textarea
      className={cx(
        control,
        code ? codeSkin : skin,
        inline ? "w-auto" : "w-full",
        compact ? "min-h-[90px]" : "min-h-[170px]",
        "resize-y leading-[1.7]",
        className,
      )}
      {...props}
    />
  );
}

/** The browser's own select, styled to match the other controls. */
export function NativeSelect({
  className,
  inline,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement> & Sizing) {
  return (
    <select
      className={cx(control, skin, inline ? "w-auto" : "w-full", className)}
      {...props}
    />
  );
}

const labelStyles = "mb-2 block text-[14px] font-semibold";

type FieldProps = { label: string; hint?: ReactNode; flush?: boolean };

/** A labelled text input. `flush` drops the space below (for fields laid out in a grid row). */
export function TextField({
  label,
  hint,
  flush = false,
  className,
  ...props
}: FieldProps & InputHTMLAttributes<HTMLInputElement>) {
  const id = useId();
  return (
    <div data-field className={cx(!flush && "mb-[21px]")}>
      <label htmlFor={id} className={labelStyles}>
        {label}
      </label>
      <Input id={id} className={className} {...props} />
      {hint && (
        <small className="mt-[7px] block text-[12px] text-muted">{hint}</small>
      )}
    </div>
  );
}

/** A labelled multi-line input. `compact` makes it shorter. */
export function TextAreaField({
  label,
  hint,
  flush = false,
  compact = false,
  code = false,
  className,
  ...props
}: FieldProps & {
  compact?: boolean;
  code?: boolean;
} & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const id = useId();
  return (
    <div data-field className={cx(!flush && "mb-[21px]")}>
      <label htmlFor={id} className={labelStyles}>
        {label}
      </label>
      <Textarea
        id={id}
        compact={compact}
        code={code}
        className={className}
        {...props}
      />
      {hint && (
        <small className="mt-[7px] block text-[12px] text-muted">{hint}</small>
      )}
    </div>
  );
}

/** A setting you turn on or off: the name and an explanation on the left, a checkbox on the right. */
export function SwitchRow({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description: ReactNode;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  const id = useId();
  return (
    <div className="flex items-center justify-between border-b border-line py-4 text-[14px]">
      <label htmlFor={id} className="cursor-pointer">
        <strong>{label}</strong>
        <p className="my-[7px] text-[14px] text-muted">{description}</p>
      </label>
      <input
        id={id}
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="focus-ring size-[18px] shrink-0 accent-brand"
      />
    </div>
  );
}

/** A checkbox with its text beside it, for use inside a form. Controlled with `checked`, or a plain form field with `name`. */
export function CheckboxField({
  label,
  checked,
  defaultChecked,
  name,
  onChange,
}: {
  label: ReactNode;
  checked?: boolean;
  defaultChecked?: boolean;
  name?: string;
  onChange?: (checked: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-center gap-2.5 text-[14px]">
      <input
        type="checkbox"
        name={name}
        checked={checked}
        defaultChecked={defaultChecked}
        onChange={(event) => onChange?.(event.target.checked)}
        className="focus-ring size-4 shrink-0 accent-brand"
      />
      {label}
    </label>
  );
}
