"use client";
import type { RefObject } from "react";

import type { ListState, SortKey } from "../lib/patient-list";

const SORT_LABEL: Record<SortKey, string> = {
  likelihood: "Likelihood to come back",
  value: "Could be worth",
  overdue: "How overdue",
};

export function PatientControls({
  state,
  search,
  onSearch,
  onChange,
  showStatus,
  searchRef,
}: {
  state: ListState;
  /** The text in the box right now; the list uses it after a short pause. */
  search: string;
  onSearch: (text: string) => void;
  onChange: (patch: Partial<ListState>) => void;
  showStatus: boolean;
  searchRef: RefObject<HTMLInputElement | null>;
}) {
  return (
    <form className="dp-controls" role="search" aria-label="Find patients" onSubmit={(e) => e.preventDefault()}>
      <label className="dp-field dp-field-search">
        <span>Search by name or id</span>
        <input
          ref={searchRef}
          type="search"
          value={search}
          maxLength={100}
          autoComplete="off"
          onChange={(e) => onSearch(e.target.value)}
          data-testid="patient-search"
        />
      </label>
      {showStatus && (
        <label className="dp-field">
          <span>Status</span>
          <select
            value={state.status}
            onChange={(e) => onChange({ status: e.target.value as ListState["status"] })}
            data-testid="status-filter"
          >
            <option value="dormant">Dormant</option>
            <option value="at_risk">At risk</option>
            <option value="all">Dormant and at risk</option>
          </select>
        </label>
      )}
      <label className="dp-field">
        <span>Sort by</span>
        <select
          value={state.sort}
          onChange={(e) => onChange({ sort: e.target.value as SortKey, dir: "desc" })}
          data-testid="sort-select"
        >
          {(Object.keys(SORT_LABEL) as SortKey[]).map((k) => (
            <option key={k} value={k}>
              {SORT_LABEL[k]}
            </option>
          ))}
        </select>
      </label>
      <button
        type="button"
        className="dp-toggle"
        aria-pressed={state.dir === "asc"}
        onClick={() => onChange({ dir: state.dir === "desc" ? "asc" : "desc" })}
        data-testid="sort-direction"
      >
        {state.dir === "desc" ? "Highest first" : "Lowest first"}
      </button>
      <label className="dp-check">
        <input
          type="checkbox"
          checked={state.reachable}
          onChange={(e) => onChange({ reachable: e.target.checked })}
          data-testid="reachable-only"
        />
        <span>Reachable only</span>
      </label>
    </form>
  );
}
