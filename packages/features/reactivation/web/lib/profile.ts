/** What the sidebar shows for the clinic and the signed-in person, with a plain fallback for every missing field. */

export const FALLBACK_CLINIC = "Your clinic";
export const FALLBACK_CLINIC_LETTER = "D";

export function clinicOf(name: string | null | undefined): { name: string; letter: string } {
  const clean = (name ?? "").trim();
  return clean ? { name: clean, letter: clean[0]!.toUpperCase() } : { name: FALLBACK_CLINIC, letter: FALLBACK_CLINIC_LETTER };
}

/** Initials of a name (two at most), or the first letter of an email. */
export function initialsOf(label: string): string {
  const words = label.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "";
  if (words.length === 1 && words[0]!.includes("@")) return words[0]![0]!.toUpperCase();
  return words
    .slice(0, 2)
    .map((w) => w[0]!)
    .join("")
    .toUpperCase();
}

/** The name, else the email, else "Signed in". */
export function personOf(user: { display_name?: string | null; email?: string | null } | null | undefined): {
  name: string;
  initials: string;
} {
  const name = (user?.display_name ?? "").trim() || (user?.email ?? "").trim() || "Signed in";
  return { name, initials: initialsOf(name) };
}

/** "office_manager" reads as "office manager"; a missing role gives null so the line is left out. */
export function roleLabel(role: string | null | undefined): string | null {
  const clean = (role ?? "").trim();
  return clean ? clean.replaceAll("_", " ") : null;
}
