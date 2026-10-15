"use client";
import {
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
  type TextareaHTMLAttributes,
} from "react";
import { Brand as SharedBrand } from "@clinic/ui";
import { X } from "lucide-react";
import { useDemo } from "@/lib/voice/demo/provider";
export function Brand() {
  return <SharedBrand href="/voice-receptionist" />;
}
export { Field, Select, FormError } from "@clinic/ui";
export function Heading({
  title,
  description,
  actions,
}: {
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  return (
    <div className="heading">
      <div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {actions && <div className="actions">{actions}</div>}
    </div>
  );
}
export function Badge({ children }: { children: string }) {
  return (
    <span
      className={`badge ${["Draft", "Unassigned", "Disabled", "Archived"].includes(children) ? "neutral" : ["Failed", "Error"].includes(children) ? "bad" : "pale"}`}
    >
      {children}
    </span>
  );
}
export function Textarea({
  label,
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement> & { label: string }) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <textarea {...props} id={id} />
    </div>
  );
}
export function Tabs({
  tabs,
  value,
  onChange,
}: {
  tabs: string[];
  value: string;
  onChange: (tab: string) => void;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const id = useId();
  return (
    <div className="tabs" role="tablist" aria-label="Section tabs">
      {tabs.map((tab, index) => (
        <button
          key={tab}
          id={`${id}-${index}`}
          ref={(node) => {
            refs.current[index] = node;
          }}
          role="tab"
          aria-selected={value === tab}
          tabIndex={value === tab ? 0 : -1}
          className={value === tab ? "selected" : ""}
          onClick={() => onChange(tab)}
          onKeyDown={(event) => {
            let target: number | undefined;
            if (event.key === "ArrowRight") target = (index + 1) % tabs.length;
            if (event.key === "ArrowLeft")
              target = (index - 1 + tabs.length) % tabs.length;
            if (event.key === "Home") target = 0;
            if (event.key === "End") target = tabs.length - 1;
            if (target !== undefined) {
              event.preventDefault();
              const selected = tabs[target];
              if (selected !== undefined) onChange(selected);
              refs.current[target]?.focus();
            }
          }}
        >
          {tab}
        </button>
      ))}
    </div>
  );
}
export function Dialog({
  title,
  children,
  onClose,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const dialog = ref.current;
    dialog?.showModal();
    dialog?.querySelector<HTMLElement>("input, select, textarea")?.focus();
    return () => {
      dialog?.close();
      previous?.focus();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onCancel={onClose}
      onClick={(event) => {
        if (event.target === ref.current) {
          const rect = ref.current.getBoundingClientRect();
          if (
            event.clientX < rect.left ||
            event.clientX > rect.right ||
            event.clientY < rect.top ||
            event.clientY > rect.bottom
          )
            onClose();
        }
      }}
    >
      <div className="dialog-title">
        <h2 id={titleId}>{title}</h2>
        <button type="button" aria-label="Close dialog" onClick={onClose}>
          <X size={18} />
        </button>
      </div>
      {children}
    </dialog>
  );
}

export function Empty({
  title,
  description,
}: {
  title: string;
  description?: string;
}) {
  return (
    <div className="empty">
      <h2>{title}</h2>
      {description && <p>{description}</p>}
    </div>
  );
}
export function DemoBoundary({ children }: { children: ReactNode }) {
  const { state, error, retry } = useDemo();
  if (!state)
    return (
      <div className="panel">
        {error ? (
          <>
            <p role="alert">{error}</p>
            <button onClick={retry}>Retry</button>
          </>
        ) : (
          <p role="status">Loading demo workspace…</p>
        )}
      </div>
    );
  return (
    <>
      {error && (
        <div className="note error-note" role="alert">
          {error}
        </div>
      )}
      {children}
    </>
  );
}
export function Metric({
  label,
  value,
  sub,
  feature = false,
}: {
  label: string;
  value: string;
  sub: string;
  feature?: boolean;
}) {
  return (
    <div className={`card metric ${feature ? "feature" : ""}`}>
      <span className="metric-label">{label}</span>
      <div className="value">{value}</div>
      <small>{sub}</small>
    </div>
  );
}
export function Switch({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  const id = useId();
  return (
    <div className="checkrow">
      <label htmlFor={id}>
        <strong>{label}</strong>
        <p>{description}</p>
      </label>
      <input
        id={id}
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
    </div>
  );
}
export function ResetDemo() {
  const { run, busy } = useDemo();
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)}>Reset demo</button>
      {open && (
        <Dialog title="Reset sample workspace?" onClose={() => setOpen(false)}>
          <p>
            This clears changes made during this preview and restores the sample
            records.
          </p>
          <div className="actions dialog-actions">
            <button onClick={() => setOpen(false)}>Cancel</button>
            <button
              className="primary"
              disabled={busy}
              onClick={async () => {
                if (await run({ type: "reset" }, "Sample workspace restored"))
                  setOpen(false);
              }}
            >
              Reset demo
            </button>
          </div>
        </Dialog>
      )}
    </>
  );
}
