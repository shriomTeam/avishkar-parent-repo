"use client";
import { Check, ChevronDown } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { cx } from "./cx";

export type DropdownOption = {
  value: string;
  label: string;
  hint?: string; // small note after the label, such as "already added"
  disabled?: boolean;
};

/**
 * A select in the app's own style, in place of the browser's menu (which ignores the design). Follows the
 * select-only combobox pattern: focus stays on the button; arrows move, Enter chooses, Escape closes.
 *
 * Controlled with `value` and `onChange`, or uncontrolled with `defaultValue`. With `name` it also works in a
 * plain form, through a hidden input. `hideLabel` keeps the label for screen readers only (for filters);
 * `inline` sizes to the content instead of filling the row; `flush` drops the space below.
 */
export function Dropdown({
  label,
  options,
  value,
  defaultValue,
  onChange,
  name,
  disabled = false,
  hideLabel = false,
  inline = false,
  flush = false,
  className,
}: {
  label: string;
  options: DropdownOption[];
  value?: string;
  defaultValue?: string;
  onChange?: (value: string) => void;
  name?: string;
  disabled?: boolean;
  hideLabel?: boolean;
  inline?: boolean;
  flush?: boolean;
  className?: string;
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [own, setOwn] = useState(defaultValue ?? options[0]?.value ?? "");
  const current = value ?? own;
  const root = useRef<HTMLDivElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const selected = options.findIndex((o) => o.value === current);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  useEffect(() => {
    if (open && active >= 0)
      list.current?.children[active]?.scrollIntoView?.({ block: "nearest" });
  }, [open, active]);

  const enabled = (index: number) => !options[index]?.disabled;
  const step = (from: number, direction: 1 | -1) => {
    for (let i = from + direction; i >= 0 && i < options.length; i += direction)
      if (enabled(i)) return i;
    return from;
  };
  const show = () => {
    setActive(selected >= 0 && enabled(selected) ? selected : step(-1, 1));
    setOpen(true);
  };
  const choose = (index: number) => {
    const option = options[index];
    if (!option || option.disabled) return;
    setOwn(option.value);
    onChange?.(option.value);
    setOpen(false);
  };

  return (
    <div
      data-field={inline ? undefined : ""}
      className={cx(
        "relative",
        inline ? "inline-block" : !flush && "mb-[21px]",
        className,
      )}
      ref={root}
    >
      <label
        id={`${id}-label`}
        htmlFor={`${id}-button`}
        className={cx(
          hideLabel ? "sr-only" : "mb-2 block text-[14px] font-semibold",
        )}
      >
        {label}
      </label>
      {name && <input type="hidden" name={name} value={current} />}
      <button
        id={`${id}-button`}
        type="button"
        role="combobox"
        className={cx(
          "focus-ring flex cursor-pointer items-center justify-between gap-2.5 rounded-lg border border-[#dedce5] bg-white px-[13px] py-[11px] text-left text-[14px] font-normal text-ink hover:border-[#c9c6d2] aria-expanded:border-focus disabled:cursor-not-allowed disabled:opacity-50",
          inline ? "w-auto" : "w-full",
        )}
        aria-labelledby={`${id}-label`}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={`${id}-list`}
        aria-activedescendant={
          open && active >= 0 ? `${id}-option-${active}` : undefined
        }
        disabled={disabled}
        onClick={() => (open ? setOpen(false) : show())}
        onKeyDown={(event) => {
          if (!open) {
            if (["ArrowDown", "ArrowUp", "Enter", " "].includes(event.key)) {
              event.preventDefault();
              show();
            }
            return;
          }
          switch (event.key) {
            case "ArrowDown":
              event.preventDefault();
              setActive((i) => step(i, 1));
              break;
            case "ArrowUp":
              event.preventDefault();
              setActive((i) => step(i, -1));
              break;
            case "Home":
              event.preventDefault();
              setActive(step(-1, 1));
              break;
            case "End":
              event.preventDefault();
              setActive(step(options.length, -1));
              break;
            case "Enter":
            case " ":
              event.preventDefault();
              choose(active);
              break;
            case "Escape":
              // Close only the list, not the dialog around it.
              event.preventDefault();
              event.stopPropagation();
              setOpen(false);
              break;
            case "Tab":
              setOpen(false);
              break;
          }
        }}
      >
        <span>{options[selected]?.label ?? "Choose…"}</span>
        <ChevronDown
          size={16}
          aria-hidden="true"
          className="shrink-0 text-muted"
        />
      </button>
      {open && (
        <ul
          ref={list}
          id={`${id}-list`}
          role="listbox"
          aria-labelledby={`${id}-label`}
          className={cx(
            "absolute left-0 z-20 mt-1.5 max-h-60 overflow-y-auto rounded-[10px] border border-line bg-white p-1.5 shadow-[0_12px_32px_#201d1d1f]",
            inline ? "w-max min-w-full" : "right-0",
          )}
        >
          {options.map((option, index) => (
            <li
              key={option.value}
              id={`${id}-option-${index}`}
              role="option"
              aria-selected={index === selected}
              aria-disabled={option.disabled || undefined}
              className={cx(
                "flex items-center justify-between gap-2.5 rounded-lg px-3 py-2.5 text-[14px]",
                option.disabled
                  ? "cursor-not-allowed text-muted"
                  : "cursor-pointer",
                index === active && !option.disabled && "bg-brand-soft",
                index === selected && "font-semibold text-brand-ink",
              )}
              onMouseDown={(event) => event.preventDefault()} // keep focus on the button
              onMouseMove={() => option.disabled || setActive(index)}
              onClick={() => choose(index)}
            >
              <span>
                {option.label}
                {option.hint && (
                  <small className="ml-2 block text-[12px] font-normal text-muted">
                    {option.hint}
                  </small>
                )}
              </span>
              {index === selected && <Check size={16} aria-hidden="true" />}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
