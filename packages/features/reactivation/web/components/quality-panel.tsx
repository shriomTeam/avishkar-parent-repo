import { qualityNotes, type Note } from "../lib/messages";
import { CollapsiblePanel } from "./kit";

export function QualityPanel({
  quality,
  source = "saved",
  extra = [],
}: {
  quality: Record<string, unknown> | null;
  source?: "saved" | "file";
  extra?: Note[];
}) {
  const notes = [...qualityNotes(quality, source), ...extra];
  return (
    <CollapsiblePanel
      title={
        notes.length
          ? `About this data (${notes.length} ${notes.length === 1 ? "note" : "notes"})`
          : "About this data"
      }
      testId="about-data"
    >
      {notes.length === 0 ? (
        <p className="dp-sub">
          Nothing unusual was found in your records for this analysis.
        </p>
      ) : (
        <ul className="dp-notes">
          {notes.map((n) => (
            <li key={n.text} data-tone={n.tone}>
              <b>{n.tone === "warn" ? "Heads up" : "For your info"}</b>
              <span>{n.text}</span>
            </li>
          ))}
        </ul>
      )}
    </CollapsiblePanel>
  );
}
