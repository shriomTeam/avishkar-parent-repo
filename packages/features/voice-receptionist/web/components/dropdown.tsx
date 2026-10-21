"use client";
import { Check, ChevronDown } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

export type DropdownOption = {
  value: string;
  label: string;
  hint?: string; // small note after the label, such as "already added"
  disabled?: boolean;
};

/**
 * A select in the app's own style, in place of the browser's menu (which ignores the design). Follows the
 * select-only combobox pattern: focus stays on the button; arrows move, Enter chooses, Escape closes.
 * With ``name`` it works inside a plain form, through a hidden input.
 */
export function Dropdown({
  label,
  value,
  options,
  onChange,
  name,
  disabled = false,
}: {
  label: string;
  value: string;
  options: DropdownOption[];
  onChange: (value: string) => void;
  name?: string;
  disabled?: boolean;
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const root = useRef<HTMLDivElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const selected = options.findIndex((o) => o.value === value);

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
    onChange(option.value);
    setOpen(false);
  };

  return (
    <div className="field dropdown" ref={root}>
      <label id={`${id}-label`} htmlFor={`${id}-button`}>
        {label}
      </label>
      {name && <input type="hidden" name={name} value={value} />}
      <button
        id={`${id}-button`}
        type="button"
        role="combobox"
        className="dropdown-button"
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
        <ChevronDown size={16} aria-hidden="true" />
      </button>
      {open && (
        <ul
          ref={list}
          id={`${id}-list`}
          role="listbox"
          aria-labelledby={`${id}-label`}
          className="dropdown-list"
        >
          {options.map((option, index) => (
            <li
              key={option.value}
              id={`${id}-option-${index}`}
              role="option"
              aria-selected={index === selected}
              aria-disabled={option.disabled || undefined}
              className={`dropdown-option${index === active ? " active" : ""}${option.disabled ? " disabled" : ""}`}
              onMouseDown={(event) => event.preventDefault()} // keep focus on the button
              onMouseMove={() => option.disabled || setActive(index)}
              onClick={() => choose(index)}
            >
              <span>
                {option.label}
                {option.hint && <small>{option.hint}</small>}
              </span>
              {index === selected && <Check size={16} aria-hidden="true" />}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
