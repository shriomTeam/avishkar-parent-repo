/**
 * The patient list's logic, kept free of React and of imports so it can be unit tested with `node --test`
 * (see web/unit). Everything here works on plain data and never touches storage, the network or the console.
 */

export const PAGE_SIZE = 25;

/** Scores are out of 100. The bands are a plain-words reading of the number, not a probability. */
export const LIKELIHOOD_BANDS = { high: 65, medium: 45 } as const;
export type Band = "high" | "medium" | "low";

export function likelihoodBand(score: number | null | undefined): Band | null {
  if (score === null || score === undefined) return null;
  if (score >= LIKELIHOOD_BANDS.high) return "high";
  if (score >= LIKELIHOOD_BANDS.medium) return "medium";
  return "low";
}

export const BAND_LABEL: Record<Band, string> = { high: "High", medium: "Medium", low: "Low" };

export type Reach = "both" | "email" | "text" | "none" | "unknown";
export const REACH_LABEL: Record<Reach, string> = {
  both: "By email and text",
  email: "By email",
  text: "By text",
  none: "Not reachable",
  unknown: "Unknown",
};

/** From points.reachable ({email, sms, either}). Absent when that point is switched off in settings. */
export function reachFromPoints(points: Record<string, unknown> | null | undefined): Reach {
  const r = points?.reachable;
  if (!r || typeof r !== "object") return "unknown";
  const { email, sms } = r as { email?: unknown; sms?: unknown };
  if (typeof email !== "boolean" || typeof sms !== "boolean") return "unknown";
  if (email && sms) return "both";
  if (email) return "email";
  if (sms) return "text";
  return "none";
}

// --- one row, whatever the source ----------------------------------------------------------------------------------

export type PatientRow = {
  key: string;
  name: string;
  hasName: boolean;
  status: string;
  primaryType: string | null;
  lastVisitDay: string | null;
  daysSince: number | null;
  usualService: string | null;
  overdueRatio: number | null;
  score: number | null;
  basisCents: number;
  low: number | null;
  high: number | null;
  kind: string | null;
  reach: Reach;
  reasons: string[];
  offerService: string | null;
  points: Record<string, unknown>;
  /** Lower-cased name and id, for the in-browser search of file results. */
  searchName: string;
  searchId: string;
};

type Common = {
  status: string;
  primary_type: string | null;
  reasons: string[];
  usual_service_name: string | null;
  days_since_last_visit: number | null;
  likelihood_score: number | null;
  revenue_basis_cents: number;
  overdue_ratio: number | null;
  revenue_kind: string | null;
  revenue_low_cents: number | null;
  revenue_high_cents: number | null;
  offer_service_name: string | null;
  points: Record<string, unknown>;
};
export type SavedPatientInput = Common & {
  patient_id: string;
  display_name: string | null;
  last_visit_at: string | null;
};
export type FilePatientInput = Common & {
  patient_id: string;
  external_id: string;
  display_name: string | null;
  last_visit_day: string | null;
};

/** The calendar day of an instant in the clinic's timezone, as "2026-03-14". */
export function localDay(iso: string, timeZone: string): string | null {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  try {
    return new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).format(d);
  } catch {
    return d.toISOString().slice(0, 10);
  }
}

function build(
  common: Common,
  key: string,
  shownId: string,
  searchId: string,
  displayName: string | null,
  lastDay: string | null,
): PatientRow {
  const named = !!displayName && displayName.trim() !== "";
  const name = named ? displayName!.trim() : `Patient ${shownId}`;
  return {
    key,
    name,
    hasName: named,
    status: common.status,
    primaryType: common.primary_type,
    lastVisitDay: lastDay,
    daysSince: common.days_since_last_visit,
    usualService: common.usual_service_name,
    overdueRatio: common.overdue_ratio,
    score: common.likelihood_score,
    basisCents: common.revenue_basis_cents,
    low: common.revenue_low_cents,
    high: common.revenue_high_cents,
    kind: common.revenue_kind,
    reach: reachFromPoints(common.points),
    reasons: common.reasons,
    offerService: common.offer_service_name,
    points: common.points,
    searchName: (named ? name : "").toLowerCase(),
    searchId: searchId.toLowerCase(),
  };
}

export function rowFromSaved(p: SavedPatientInput, timeZone: string): PatientRow {
  const day = p.last_visit_at ? localDay(p.last_visit_at, timeZone) : null;
  return build(p, p.patient_id, p.patient_id.slice(0, 8), p.patient_id, p.display_name, day);
}

export function rowFromFile(p: FilePatientInput): PatientRow {
  return build(p, p.patient_id, p.external_id, p.external_id, p.display_name, p.last_visit_day);
}

// --- the controls ---------------------------------------------------------------------------------------------------

export type SortKey = "likelihood" | "value" | "overdue";
export type Dir = "asc" | "desc";
export type StatusFilter = "dormant" | "at_risk" | "all";

export type ListState = {
  q: string;
  status: StatusFilter;
  reachable: boolean;
  sort: SortKey;
  dir: Dir;
  page: number;
};

export const SORT_KEYS: readonly SortKey[] = ["likelihood", "value", "overdue"];

export const DEFAULT_STATE: ListState = {
  q: "",
  status: "dormant",
  reachable: false,
  sort: "likelihood",
  dir: "desc",
  page: 1,
};

/** Only the Unclassified page can hold both statuses, so it is the only page with a status filter. */
export const hasStatusFilter = (typeKey: string) => typeKey === "unclassified";

/**
 * The controls kept in the page URL. The search text is deliberately not one of them: names must not end up in
 * the address bar, browser history or a shared link.
 */
export function parseUrlState(params: URLSearchParams): ListState {
  const sort = params.get("sort");
  const status = params.get("status");
  const page = Number.parseInt(params.get("page") ?? "1", 10);
  return {
    q: "",
    status: status === "at_risk" || status === "all" ? status : "dormant",
    reachable: params.get("reachable") === "1",
    sort: SORT_KEYS.includes(sort as SortKey) ? (sort as SortKey) : "likelihood",
    dir: params.get("dir") === "asc" ? "asc" : "desc",
    page: Number.isFinite(page) && page >= 1 ? page : 1,
  };
}

/** The query string for a state, leaving out every default, so a plain page has a plain URL. */
export function serializeUrlState(state: ListState): string {
  const p = new URLSearchParams();
  if (state.status !== "dormant") p.set("status", state.status);
  if (state.reachable) p.set("reachable", "1");
  if (state.sort !== "likelihood") p.set("sort", state.sort);
  if (state.dir !== "desc") p.set("dir", state.dir);
  if (state.page > 1) p.set("page", String(state.page));
  const text = p.toString();
  return text ? `?${text}` : "";
}

/** Query parameters for GET /runs/{id}/patients. The type's own page never filters by status unless asked. */
export function apiParams(typeKey: string, state: ListState): Record<string, string | number | boolean> {
  const out: Record<string, string | number | boolean> = {
    type: typeKey,
    sort: state.sort,
    dir: state.dir,
    limit: PAGE_SIZE,
    offset: (state.page - 1) * PAGE_SIZE,
  };
  if (hasStatusFilter(typeKey) && state.status !== "all") out.status = state.status;
  if (state.reachable) out.reachable = true;
  const q = state.q.trim();
  if (q) out.q = q;
  return out;
}

export const pageCount = (total: number) => Math.max(1, Math.ceil(total / PAGE_SIZE));
export const clampPage = (page: number, total: number) => Math.min(Math.max(1, page), pageCount(total));

export const isFiltered = (state: ListState, typeKey: string) =>
  state.q.trim() !== "" || state.reachable || (hasStatusFilter(typeKey) && state.status !== "dormant");

export function clearFilters(state: ListState): ListState {
  return { ...state, q: "", status: "dormant", reachable: false, page: 1 };
}

// --- file results: filter, sort and page in the browser --------------------------------------------------------------

const sortValue = (row: PatientRow, sort: SortKey): number | null =>
  sort === "likelihood" ? row.score : sort === "value" ? row.basisCents : row.overdueRatio;

/**
 * The same filters, sort and paging as the API, over rows already in memory. The rows arrive in the engine's
 * order (score, spend, id) and the sort is stable, so ties keep that order, as they do on the API side.
 */
export function applyList(rows: PatientRow[], typeKey: string, state: ListState) {
  const q = state.q.trim().toLowerCase();
  let kept = rows.filter((r) =>
    typeKey === "unclassified" ? r.primaryType === null : r.primaryType === typeKey,
  );
  if (hasStatusFilter(typeKey) && state.status !== "all") kept = kept.filter((r) => r.status === state.status);
  if (state.reachable) kept = kept.filter((r) => r.reach === "both" || r.reach === "email" || r.reach === "text");
  if (q) kept = kept.filter((r) => r.searchName.includes(q) || r.searchId.startsWith(q));
  const sign = state.dir === "asc" ? 1 : -1;
  const sorted = [...kept].sort((a, b) => {
    const x = sortValue(a, state.sort);
    const y = sortValue(b, state.sort);
    if (x === null && y === null) return 0;
    if (x === null) return 1; // missing values sort last in both directions, like the API
    if (y === null) return -1;
    return x === y ? 0 : x < y ? -sign : sign;
  });
  const page = clampPage(state.page, sorted.length);
  const start = (page - 1) * PAGE_SIZE;
  return { items: sorted.slice(start, start + PAGE_SIZE), total: sorted.length, page };
}

/** Overview links to a type's page; a file analysis marks its links so the page opens in file mode. */
export const typeHref = (typeKey: string, fromFile: boolean) =>
  `/reactivation/types/${typeKey}${fromFile ? "?source=file" : ""}`;
