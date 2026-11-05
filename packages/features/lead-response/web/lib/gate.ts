/**
 * What the answer to the first settings read means for the page. The API is the gate, not the platform's feature
 * check (`requireFeature`), on purpose: that check answers 404 to a role the platform does not grant, and this page
 * shows such a role an explanation instead. Only a plain "feature not enabled" is a 404. A role refusal shows the role
 * view, and everything else is an error the person can retry, never a 404.
 */
export type Gate = "ok" | "not_found" | "role" | "error";

const NOT_ENABLED = /^Feature '.+' is not enabled$/;

export function classifyGate(status: number, detail: unknown): Gate {
  if (status >= 200 && status < 300) return "ok";
  if (status === 403 && typeof detail === "string") {
    if (NOT_ENABLED.test(detail)) return "not_found";
    if (detail === "feature_access_denied" || detail === "Not allowed for your role") return "role";
  }
  return "error";
}
