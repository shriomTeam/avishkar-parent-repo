/** The AI settings are stored but not part of this release, so they are plain rows with a tag, not controls. */
import { AI_INTRO, AI_ROWS, COMING_LATER } from "../lib/messages";

export function ComingLater() {
  return <span className="border-line inline-flex shrink-0 rounded-md border bg-neutral-soft px-2 py-1 text-[12px] font-semibold text-ink">{COMING_LATER}</span>;
}

export function AiSection() {
  return (
    <div data-testid="ai-section">
      <p className="mb-3 text-[14px] text-muted">{AI_INTRO}</p>
      <ul className="m-0 list-none p-0">
        {AI_ROWS.map((row) => (
          <li key={row} className="border-line flex items-center justify-between gap-3 border-b py-3 text-[15px] last:border-b-0" data-testid="ai-row">
            <span>{row}</span>
            <ComingLater />
          </li>
        ))}
      </ul>
    </div>
  );
}
