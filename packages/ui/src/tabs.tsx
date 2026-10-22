"use client";
import { useId, useRef } from "react";
import { cx } from "./cx";

/** An accessible tab list: arrow keys, Home and End move between tabs. The caller renders the panel. */
export function Tabs({
  tabs,
  value,
  onChange,
  label = "Section tabs",
}: {
  tabs: string[];
  value: string;
  onChange: (tab: string) => void;
  label?: string;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const id = useId();
  return (
    <div
      className="mb-[25px] flex gap-[23px] overflow-auto border-b border-line max-app:gap-[18px]"
      role="tablist"
      aria-label={label}
    >
      {tabs.map((tab, index) => {
        const selected = value === tab;
        return (
          <button
            key={tab}
            id={`${id}-${index}`}
            ref={(node) => {
              refs.current[index] = node;
            }}
            role="tab"
            aria-selected={selected}
            tabIndex={selected ? 0 : -1}
            className={cx(
              "focus-ring cursor-pointer whitespace-nowrap rounded-none border-0 bg-transparent px-0 py-[13px] text-[14px] font-semibold",
              selected
                ? "border-b-2 border-brand text-brand-ink"
                : "text-muted hover:text-ink",
            )}
            onClick={() => onChange(tab)}
            onKeyDown={(event) => {
              let target: number | undefined;
              if (event.key === "ArrowRight")
                target = (index + 1) % tabs.length;
              if (event.key === "ArrowLeft")
                target = (index - 1 + tabs.length) % tabs.length;
              if (event.key === "Home") target = 0;
              if (event.key === "End") target = tabs.length - 1;
              if (target !== undefined) {
                event.preventDefault();
                const next = tabs[target];
                if (next !== undefined) onChange(next);
                refs.current[target]?.focus();
              }
            }}
          >
            {tab}
          </button>
        );
      })}
    </div>
  );
}
