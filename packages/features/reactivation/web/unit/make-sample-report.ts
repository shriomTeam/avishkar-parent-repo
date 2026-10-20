// Writes a sample report to the path given, for tests/test_report_xlsx.py, which opens it with openpyxl.
import { writeFileSync } from "node:fs";

import { buildReport, type ReportRow } from "../lib/report.ts";

const row = (over: Partial<ReportRow>): ReportRow => ({
  id: "p1",
  name: "Maya Rao",
  status: "dormant",
  usualService: "Botox",
  lastVisitDay: "2026-01-02",
  daysSince: 291,
  likelihood: "High",
  score: 70,
  basisCents: 25050,
  lowCents: 2004,
  highCents: 3758,
  offerService: "Facial",
  reasons: ["One visit", "No return"],
  ...over,
});

const longName = "A very long patient group name that Excel would refuse";
const bytes = buildReport(
  {
    clinic: "Riverside & Sons <Skin> \"Clinic\"",
    generatedOn: "2026-10-20",
    source: "File march-export.csv, not saved",
    totals: { dormant: 3, patients: 12, lowCents: 123456, highCents: 234567 },
    types: [
      { key: "a", label: "One-and-done", description: "Visited once and has not come back.", available: true, patients: 2, lowCents: 3000, highCents: 5000, topService: "Botox" },
      { key: "b", label: longName, description: "x", available: true, patients: 1, lowCents: null, highCents: null, topService: null },
      { key: "c", label: "Churned member", description: "y", available: false, patients: null, lowCents: null, highCents: null, topService: null },
    ],
    rows: new Map([
      ["a", [row({}), row({ id: "p2", name: "Zoë ☃ O'Brien", reasons: ["a & b", "<c>"] })]],
      ["b", [row({ id: "p3", name: "=HYPERLINK(\"http://x\")\u0001", lowCents: null, highCents: null, usualService: null, lastVisitDay: null, daysSince: null, likelihood: "", score: null })]],
    ]),
  },
  new Date(2026, 9, 20, 12, 0, 0),
);
writeFileSync(process.argv[2]!, bytes);
