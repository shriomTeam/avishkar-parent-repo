import { Button } from "@clinic/ui";

import { WarnIcon } from "./fields";

export function SaveBar({
  dirty,
  saving,
  problems,
  onSave,
  onDiscard,
}: {
  dirty: boolean;
  saving: boolean;
  problems: number;
  onSave: () => void;
  onDiscard: () => void;
}) {
  const text = saving
    ? "Saving…"
    : problems > 0
      ? `Fix ${problems} ${problems === 1 ? "thing" : "things"} before saving.`
      : dirty
        ? "You have unsaved changes."
        : "No unsaved changes.";
  return (
    <div
      data-testid="save-bar"
      data-dirty={dirty || undefined}
      className="border-line sticky bottom-0 z-10 -mx-6 mt-6 flex flex-wrap items-center justify-between gap-3 border-t bg-white px-6 py-3 data-[dirty]:bg-warn-soft max-app:-mx-4 max-app:px-4"
    >
      <span role="status" className="flex items-center gap-2 text-[14px] font-medium text-ink data-[dirty]:text-warn-ink" data-dirty={dirty || undefined} data-testid="save-status">
        {dirty && <WarnIcon />}
        {text}
      </span>
      <span className="flex gap-2.5">
        <Button type="button" variant="outline" onClick={onDiscard} disabled={!dirty || saving} data-testid="discard">
          Discard changes
        </Button>
        <Button type="button" variant="brand" onClick={onSave} disabled={!dirty || saving} aria-busy={saving || undefined} data-testid="save">
          {saving ? "Saving…" : "Save settings"}
        </Button>
      </span>
    </div>
  );
}
