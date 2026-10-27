"use client";
import { X } from "lucide-react";
import {
  useEffect,
  useId,
  useRef,
  type HTMLAttributes,
  type ReactNode,
} from "react";
import { cx } from "./cx";

/**
 * A modal dialog on the browser's own <dialog>: Escape closes it, focus returns to what opened it, and a click
 * on the backdrop closes it. Fields inside get even spacing.
 */
export function Dialog({
  title,
  children,
  onClose,
  placement = "center",
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  placement?: "center" | "right";
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
      // Tailwind's reset zeroes margins, which removes the browser's centring of modal dialogs: m-auto restores it.
      className={cx(
        "overflow-auto border border-line bg-white p-7 text-ink shadow-[0_20px_80px_#201d1d25] backdrop:bg-[#201d1d60] [&_[data-field]]:my-[15px]",
        placement === "right"
          ? "fixed inset-y-0 right-0 left-auto m-0 h-dvh max-h-dvh w-[min(440px,100vw)] max-w-full"
          : "m-auto max-h-[85vh] w-[min(520px,90vw)] rounded-2xl",
      )}
    >
      <div className="mb-[15px] flex items-center justify-between gap-[18px]">
        <h2
          id={titleId}
          className="m-0 text-[18px] font-bold tracking-[-0.4px]"
        >
          {title}
        </h2>
        <button
          type="button"
          aria-label="Close dialog"
          onClick={onClose}
          className="focus-ring cursor-pointer rounded-[9px] border-0 bg-white p-[7px] text-ink"
        >
          <X size={18} />
        </button>
      </div>
      {children}
    </dialog>
  );
}

/** The buttons at the bottom of a dialog, aligned right. */
export function DialogActions({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cx(
        "mt-[22px] flex items-center justify-end gap-2.5",
        className,
      )}
      {...props}
    />
  );
}
