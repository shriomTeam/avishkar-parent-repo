import type { CsvAnalysis } from "./api-types";

export const CSV_PATH = "/api/platform/features/reactivation/csv-analysis";

export type CsvRowError = { row: number; column: string; reason: string };
export type CsvFailure = {
  status: number;
  code: string;
  message: string;
  total: number;
  errors: CsvRowError[];
};
export type UploadOutcome =
  | { ok: true; data: CsvAnalysis }
  | { ok: false; cancelled: true }
  | { ok: false; cancelled?: false; failure: CsvFailure };

function failure(status: number, body: unknown): CsvFailure {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (detail && typeof detail === "object") {
    const d = detail as Partial<CsvFailure> & {
      total_errors?: number;
      errors?: CsvRowError[];
    };
    return {
      status,
      code: d.code ?? "unknown",
      message: d.message ?? generic(status),
      total: d.total_errors ?? 0,
      errors: Array.isArray(d.errors) ? d.errors : [],
    };
  }
  return { status, code: "unknown", message: generic(status), total: 0, errors: [] };
}

function generic(status: number) {
  if (status === 401) return "Your session has ended. Please sign in again.";
  if (status === 403)
    return "Your role can't import files. Ask the clinic owner or office manager.";
  if (status === 413 || status === 502 || status === 500)
    return "We couldn't analyse this file. Please try again, or try a smaller file.";
  return "We couldn't analyse this file. Please try again in a moment.";
}

/**
 * Sends the file as the raw request body (XHR, so the browser reports upload progress) and keeps the result in
 * memory only. Nothing about the file is written to storage by this code.
 */
export function uploadCsv(
  file: File,
  opts: {
    csrfToken: string;
    tenantId: string | undefined;
    onProgress: (pct: number) => void;
    onUploaded: () => void;
    signal: AbortSignal;
  },
): Promise<UploadOutcome> {
  return new Promise((resolve) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", CSV_PATH);
    xhr.responseType = "json";
    xhr.setRequestHeader("Content-Type", "text/csv");
    xhr.setRequestHeader("X-CSRF-Token", opts.csrfToken);
    if (opts.tenantId) xhr.setRequestHeader("X-Tenant-Id", opts.tenantId);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) opts.onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.upload.onload = () => opts.onUploaded();
    xhr.onload = () =>
      resolve(
        xhr.status === 200 && xhr.response
          ? { ok: true, data: xhr.response as CsvAnalysis }
          : { ok: false, failure: failure(xhr.status, xhr.response) },
      );
    xhr.onerror = () =>
      resolve({
        ok: false,
        failure: {
          status: 0,
          code: "network",
          message: "We couldn't reach the server. Check your connection and try again.",
          total: 0,
          errors: [],
        },
      });
    xhr.onabort = () => resolve({ ok: false, cancelled: true });
    opts.signal.addEventListener("abort", () => xhr.abort(), { once: true });
    if (opts.signal.aborted) return xhr.abort();
    xhr.send(file);
  });
}
