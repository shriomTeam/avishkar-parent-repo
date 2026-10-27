"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { Upload } from "lucide-react";
import {
  Button,
  DataTable,
  DialogActions,
  H2,
  Input,
  Muted,
  Note,
  Panel,
  StatusBadge,
  Td,
  Th,
  Tr,
} from "@clinic/ui";
import { useDemo } from "../lib/demo/provider";
import { useVoice } from "../lib/voice/provider";
import {
  ApiError,
  type Knowledge,
  type KnowledgeDocument,
  type SearchResult,
} from "../lib/inbound/api";
import { Dialog, Empty, FormError, Heading } from "./ui";
import { VoiceBoundary } from "./voice-boundary";
import { KnowledgeSkeleton, TableLoading } from "./skeletons";

const POLL_MS = 2500;
const LABELS: Record<
  string,
  { text: string; tone: "brand" | "muted" | "danger" | "warn" }
> = {
  uploaded: { text: "Waiting", tone: "muted" },
  processing: { text: "Processing", tone: "warn" },
  ready: { text: "Ready", tone: "brand" },
  failed: { text: "Failed", tone: "danger" },
  duplicate: { text: "Duplicate", tone: "muted" },
};

const inProgress = (d: KnowledgeDocument) =>
  d.status === "uploaded" || d.status === "processing";

function size(bytes: number) {
  return bytes < 1024 * 1024
    ? `${Math.max(1, Math.round(bytes / 1024))} KB`
    : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function KnowledgeBase() {
  return (
    <VoiceBoundary fallback={<KnowledgeSkeleton />}>
      <DocumentList />
    </VoiceBoundary>
  );
}

function DocumentList() {
  const { api } = useVoice();
  const { notify } = useDemo();
  const [data, setData] = useState<Knowledge | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState<KnowledgeDocument | null>(null);
  // A file whose name is already taken: waits here until the user picks replace or keep both.
  const [clash, setClash] = useState<File | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      setData(await api.listKnowledge());
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : "Could not load the documents.",
      );
    }
  }, [api]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // While any document is still being read, check again every few seconds.
  const working = data?.documents.some(inProgress) ?? false;
  useEffect(() => {
    if (!working) return;
    const timer = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(timer);
  }, [working, refresh]);

  async function upload(file: File, sameName?: "replace" | "keep") {
    setBusy(true);
    setError("");
    try {
      await api.uploadDocument(file, sameName);
      notify("Document uploaded. It is being read now.");
      setClash(null);
      await refresh();
    } catch (e) {
      if (e instanceof ApiError && e.code === "same_name") setClash(file);
      else
        setError(
          e instanceof ApiError ? e.message : "Could not upload the file.",
        );
    } finally {
      setBusy(false);
    }
  }

  async function act(run: () => Promise<unknown>, done: string) {
    setBusy(true);
    setError("");
    try {
      await run();
      notify(done);
      await refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
      setDeleting(null);
    }
  }

  const documents = data?.documents ?? [];
  return (
    <>
      <Heading
        title="Knowledge base"
        description="Files your agents can look things up in while they talk to callers, such as prices, policies and directions."
        actions={
          <>
            <input
              ref={input}
              type="file"
              hidden
              aria-label="Choose a file"
              accept=".pdf,.docx,.txt,.md"
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = "";
                if (file) void upload(file);
              }}
            />
            <Button
              variant="brand"
              disabled={busy || data?.enabled === false}
              onClick={() => input.current?.click()}
            >
              <Upload size={16} />
              Upload file
            </Button>
          </>
        }
      />
      <FormError message={error} />
      {data?.enabled === false && (
        <Note className="mb-[18px]" role="note">
          <strong>File storage is not set up on this server.</strong> Documents
          cannot be added until it is.
        </Note>
      )}
      <Panel>
        <H2>Your documents</H2>
        {!data ? (
          <TableLoading columns={[220, 56, 100, 80, 130]} />
        ) : documents.length === 0 ? (
          <Empty
            title="No documents yet"
            description={`Upload a PDF, Word, text or Markdown file (up to ${Math.round(data.max_file_bytes / (1024 * 1024))} MB, ${data.max_documents} files).`}
          />
        ) : (
          <DataTable>
            <thead>
              <tr>
                <Th>File</Th>
                <Th>Size</Th>
                <Th>Status</Th>
                <Th>Added</Th>
                <Th>Actions</Th>
              </tr>
            </thead>
            <tbody>
              {documents.map((d) => {
                const label = LABELS[d.status] ?? {
                  text: d.status,
                  tone: "muted" as const,
                };
                return (
                  <Tr key={d.id}>
                    <Td className="max-w-[320px] truncate">{d.filename}</Td>
                    <Td>{size(d.size_bytes)}</Td>
                    <Td>
                      <StatusBadge tone={label.tone}>{label.text}</StatusBadge>
                      {d.status === "ready" && (
                        <Muted>{d.chunk_count} sections</Muted>
                      )}
                      {d.error && <Muted>{d.error}</Muted>}
                    </Td>
                    <Td>{new Date(d.created_at).toLocaleDateString()}</Td>
                    <Td>
                      <div className="flex items-center gap-2.5">
                        {d.status === "failed" && (
                          <Button
                            variant="outline"
                            disabled={busy}
                            aria-label={`Try ${d.filename} again`}
                            onClick={() =>
                              void act(
                                () => api.retryDocument(d.id),
                                "Trying again",
                              )
                            }
                          >
                            Try again
                          </Button>
                        )}
                        <Button
                          variant="outline"
                          aria-label={`Delete ${d.filename}`}
                          onClick={() => setDeleting(d)}
                        >
                          Delete
                        </Button>
                      </div>
                    </Td>
                  </Tr>
                );
              })}
            </tbody>
          </DataTable>
        )}
      </Panel>
      {documents.some((d) => d.status === "ready") && (
        <TestSearch
          search={(query) => api.searchKnowledge(query).then((r) => r.results)}
        />
      )}
      <Note className="mt-5">
        <strong>How it works</strong>
        <p>
          Each file is read and split into sections. Deleting a file removes its
          sections too, so agents stop using it straight away. Do not upload
          patient records: this is for general information about your clinic.
        </p>
      </Note>
      {clash && (
        <Dialog
          title="A file with this name exists"
          onClose={() => setClash(null)}
        >
          <Muted>
            “{clash.name}” is already in your knowledge base, but its content is
            different. Replace it with this one, or keep both?
          </Muted>
          <DialogActions>
            <Button variant="outline" onClick={() => setClash(null)}>
              Cancel
            </Button>
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => void upload(clash, "keep")}
            >
              Keep both
            </Button>
            <Button
              variant="brand"
              disabled={busy}
              onClick={() => void upload(clash, "replace")}
            >
              Replace
            </Button>
          </DialogActions>
        </Dialog>
      )}
      {deleting && (
        <Dialog
          title={`Delete ${deleting.filename}?`}
          onClose={() => setDeleting(null)}
        >
          <Muted>
            The file and everything agents learned from it is removed. This
            cannot be undone.
          </Muted>
          <DialogActions>
            <Button variant="outline" onClick={() => setDeleting(null)}>
              Cancel
            </Button>
            <Button
              variant="brand"
              disabled={busy}
              onClick={() =>
                void act(
                  () => api.deleteDocument(deleting.id),
                  "Document deleted",
                )
              }
            >
              Delete document
            </Button>
          </DialogActions>
        </Dialog>
      )}
    </>
  );
}

/** Asks the same question an agent would, so staff can see what their documents answer before a caller does. */
function TestSearch({
  search,
}: {
  search: (query: string) => Promise<SearchResult[]>;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function run(event: React.FormEvent) {
    event.preventDefault();
    if (!query.trim()) return;
    setBusy(true);
    setError("");
    try {
      setResults(await search(query.trim()));
    } catch (e) {
      setResults(null);
      setError(e instanceof ApiError ? e.message : "The search failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel className="mt-5">
      <H2>Test search</H2>
      <Muted>
        Ask a question a caller might ask and see what an agent would find.
      </Muted>
      <form className="mt-3 flex gap-2.5" onSubmit={run}>
        <Input
          aria-label="Question"
          placeholder="How much does Botox cost?"
          maxLength={500}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <Button type="submit" variant="outline" disabled={busy}>
          Search
        </Button>
      </form>
      <FormError message={error} />
      {results && results.length === 0 && (
        <Muted role="status">
          Nothing in your documents answers that. An agent would say it does not
          know and offer to take a message.
        </Muted>
      )}
      {results?.map((r, i) => (
        <div
          key={`${r.document_id}-${i}`}
          className="mt-3 rounded-lg border border-line p-3"
          data-testid="search-result"
        >
          <div className="text-[13px] font-semibold">
            {r.filename}
            {r.heading ? ` · ${r.heading}` : ""}{" "}
            <span className="font-normal text-muted">
              ({Math.round(r.similarity * 100)}% match)
            </span>
          </div>
          <p className="mt-1.5 whitespace-pre-wrap text-[14px]">{r.text}</p>
        </div>
      ))}
    </Panel>
  );
}
