/**
 * What the frame says about the data on screen: the header badge, the sidebar card and the footer line. Free of React
 * so it can be unit-tested.
 *
 * Three things can be true: a saved analysis exists, the page is showing results from a file imported in this tab
 * (never saved), or there is nothing yet. A fourth, "unknown", covers a failed check; it claims nothing.
 */
// The same paths as in shell-nav.ts, written out because the web app's TypeScript settings do not allow the ".ts"
// import that Node's test runner needs. shell-status.test.ts checks they match.
export const PATHS = { root: "/reactivation", file: "/reactivation/file", import: "/reactivation/import" } as const;

export type Saved = "saved" | "none" | "unknown";
export type Tone = "saved" | "file" | "none" | "unknown";

export type Status = {
  tone: Tone;
  badge: string;
  title: string;
  text: string;
  footer: string;
};

/**
 * Whether the page is showing the file's results (true) or the saved ones. File results are open in this tab
 * (`hasFile`), but a page only shows them where it says so: the Overview unless it was opened with ?view=saved, a
 * type page with ?source=file, and the file pages. Runs and Settings are about saved data.
 */
export function showingFile(path: string, view: string | null, source: string | null, hasFile: boolean): boolean {
  if (!hasFile) return false;
  if (path === PATHS.root) return view !== "saved";
  if (path.startsWith(`${PATHS.root}/types`)) return source === "file";
  return path === PATHS.file || path === PATHS.import;
}

export function statusOf(saved: Saved, file: boolean): Status {
  if (file)
    return {
      tone: "file",
      badge: "From file",
      title: "File results",
      text: "Analysed from your file in this browser. Not saved. Refreshing the page clears them.",
      footer: "Showing results from a file, not saved",
    };
  if (saved === "saved")
    return {
      tone: "saved",
      badge: "Saved data",
      title: "Saved analysis",
      text: "These figures come from your clinic's last saved analysis.",
      footer: "Showing your last saved analysis",
    };
  if (saved === "none")
    return {
      tone: "none",
      badge: "No saved data",
      title: "No analysis yet",
      text: "Nothing has been analysed yet. Run an analysis or import a CSV file to see your dormant patients.",
      footer: "No analysis yet",
    };
  return {
    tone: "unknown",
    badge: "No saved data",
    title: "Dormant patients",
    text: "Open the Overview to see the current results.",
    footer: "Results show on the Overview",
  };
}
