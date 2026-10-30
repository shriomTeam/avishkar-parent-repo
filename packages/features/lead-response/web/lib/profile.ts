/** What the sidebar shows for the clinic and the signed-in person, with a plain fallback for every missing field. */

export function clinicOf(name: string | null | undefined): { name: string; letter: string } {
  const clean = (name ?? "").trim();
  return clean ? { name: clean, letter: clean[0]!.toUpperCase() } : { name: "Your clinic", letter: "C" };
}

/** The name, else the email, else "Signed in", with up to two initials. */
export function personOf(user: { display_name?: string | null; email?: string | null } | null | undefined): {
  name: string;
  initials: string;
} {
  const name = (user?.display_name ?? "").trim() || (user?.email ?? "").trim();
  if (!name) return { name: "Signed in", initials: "?" };
  const words = name.split(/\s+/).filter(Boolean);
  const initials = words.length === 1 && words[0]!.includes("@") ? words[0]![0]! : words.slice(0, 2).map((w) => w[0]!).join("");
  return { name, initials: initials.toUpperCase() };
}

/** "office_manager" reads as "office manager"; a missing role gives null so the line is left out. */
export function roleLabel(role: string | null | undefined): string | null {
  const clean = (role ?? "").trim();
  return clean ? clean.replaceAll("_", " ") : null;
}
