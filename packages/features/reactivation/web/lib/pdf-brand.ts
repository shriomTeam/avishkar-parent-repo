/**
 * What is printed on every page of the summary report besides the figures.
 *
 * - The logo is in `pdf-logo.ts`, made from a PNG by `scripts/make_pdf_logo.py`. To change it, run that script on the
 *   new file (see its docstring); nothing else needs to change.
 * - The footer text is the one constant below. Replace the placeholder with the real words.
 */
export const REPORT_FOOTER_TEXT = "[FOOTER TEXT PLACEHOLDER]";

/** Printed next to the logo at the top of every page. */
export const REPORT_BRAND_NAME = "Always-On Clinic";

/** Says what the report holds and who it is for. Printed above the footer text on every page. */
export const REPORT_PRIVACY_LINE =
  "Summary totals only. This report has no patient names or contact details. It is meant for the clinic owner and office manager.";
