"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { MessageCircle } from "lucide-react";
import {
  Button,
  buttonStyles,
  DataTable,
  DialogActions,
  H2,
  Muted,
  Note,
  Panel,
  SidebarLayout,
  Td,
  Th,
  Tr,
} from "@clinic/ui";
import { useAuth } from "@clinic/core/web/auth/provider";
import { useDemo } from "../lib/demo/provider";
import { useVoice } from "../lib/voice/provider";
import {
  ApiError,
  type WhatsAppAccountInput,
  type WhatsAppConversation,
  type WhatsAppConversationDetail,
  type WhatsAppState,
} from "../lib/inbound/api";
import { dateLabel } from "../lib/format";
import {
  Badge,
  Dialog,
  Empty,
  Field,
  FormError,
  Heading,
  Switch,
  Textarea,
} from "./ui";
import { VoiceBoundary } from "./voice-boundary";
import {
  LinesSkeleton,
  TableLoading,
  WhatsAppChatsSkeleton,
  WhatsAppSettingsSkeleton,
} from "./skeletons";

const SETTINGS = "/voice-receptionist/whatsapp/settings";

function failure(e: unknown, fallback: string) {
  return e instanceof ApiError ? e.message : fallback;
}

/** The person's name when WhatsApp gave one, else their number. */
const who = (c: { contact_name: string | null; contact_number: string }) =>
  c.contact_name || `+${c.contact_number}`;

// ---- Conversations -------------------------------------------------------------------------------------------------

export function WhatsAppConversations() {
  return (
    <VoiceBoundary fallback={<WhatsAppChatsSkeleton />}>
      <Conversations />
    </VoiceBoundary>
  );
}

function Conversations() {
  const { api } = useVoice();
  const { state } = useDemo();
  const timezone = state?.workspace.timezone || "UTC";
  const [chats, setChats] = useState<WhatsAppConversation[] | null>(null);
  const [error, setError] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const { auth } = useAuth();
  const role = auth.memberships.find(
    (m) => m.workspace_id === auth.workspace?.id,
  )?.role;
  const manager = role === "owner" || role === "office_manager";

  const refresh = useCallback(async () => {
    try {
      setChats(await api.listWhatsAppConversations());
      setError("");
    } catch (e) {
      setError(failure(e, "Could not load the WhatsApp conversations."));
    }
  }, [api]);
  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <>
      <Heading
        title="WhatsApp conversations"
        description="Who wrote to your clinic on WhatsApp and what the agent answered."
        actions={
          <>
            <Button variant="outline" onClick={() => void refresh()}>
              Refresh
            </Button>
            <Link className={buttonStyles("outline")} href={SETTINGS}>
              Configuration
            </Link>
          </>
        }
      />
      <FormError message={error} />
      <Note className="mb-[18px]" role="note">
        <strong>Messages are encrypted.</strong> Each message, name and number
        is stored encrypted with a key that belongs to your clinic. Opening a
        conversation is recorded in the audit log.
      </Note>
      <SidebarLayout>
        <Panel>
          {!chats ? (
            <TableLoading columns={[150, 220, 90]} rows={3} />
          ) : chats.length === 0 ? (
            <Empty
              title="No conversations yet"
              description="They appear here when someone writes to your WhatsApp number. Connect the number in Configuration first."
            />
          ) : (
            <DataTable>
              <thead>
                <tr>
                  <Th>Contact</Th>
                  <Th>Last message</Th>
                  <Th className="max-app:hidden">Last activity</Th>
                  <Th>Actions</Th>
                </tr>
              </thead>
              <tbody>
                {chats.map((c) => (
                  <Tr key={c.id}>
                    <Td>
                      <strong>{who(c)}</strong>
                      {c.contact_name && <Muted>+{c.contact_number}</Muted>}
                      {c.agent_paused && (
                        <span className="mt-1 flex gap-1.5">
                          <Badge>Agent paused</Badge>
                          {c.last_direction === "inbound" && (
                            <Badge>Needs reply</Badge>
                          )}
                        </span>
                      )}
                    </Td>
                    {/* w-full max-w-0 lets this column take the leftover width and cut a long message with "…",
                        so the Open button is always on screen and the table never scrolls sideways. */}
                    <Td className="w-full max-w-0 truncate">
                      {c.last_direction === "outbound" ? "Agent: " : ""}
                      {c.last_message}
                    </Td>
                    <Td className="max-app:hidden">
                      {dateLabel(c.last_message_at, timezone)}
                    </Td>
                    <Td>
                      <Button
                        variant="outline"
                        aria-label={`Open the conversation with ${who(c)}`}
                        onClick={() => setOpenId(c.id)}
                      >
                        Open
                      </Button>
                    </Td>
                  </Tr>
                ))}
              </tbody>
            </DataTable>
          )}
        </Panel>
        <Panel>
          <H2>How it works</H2>
          <Muted>
            Patient writes on WhatsApp → the agent answers using your prompt →
            both messages are saved here. Owners and office managers can reply
            themselves. A reply pauses the agent for that chat until you press
            Resume agent.
          </Muted>
          <Muted className="mt-3">
            {chats ? `${chats.length} conversation(s) shown.` : " "}
          </Muted>
        </Panel>
      </SidebarLayout>
      {openId && (
        <ConversationDialog
          key={openId}
          id={openId}
          timezone={timezone}
          manager={manager}
          onClose={() => {
            setOpenId(null);
            void refresh(); // the list shows what arrived while the chat was open
          }}
          onChanged={() => void refresh()}
        />
      )}
    </>
  );
}

// ---- One conversation: the thread, the pause button and the reply box ----------------------------------------------

const WINDOW_MS = 24 * 60 * 60 * 1000; // WhatsApp allows a free message only this long after the person's last one
const POLL_MS = 10_000;

function ConversationDialog({
  id,
  timezone,
  manager,
  onClose,
  onChanged,
}: {
  id: string;
  timezone: string;
  manager: boolean;
  onClose: () => void;
  onChanged: () => void;
}) {
  const { api } = useVoice();
  const [detail, setDetail] = useState<WhatsAppConversationDetail | null>(null);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const endRef = useRef<HTMLLIElement | null>(null);

  const load = useCallback(
    async (first: boolean) => {
      try {
        setDetail(await api.getWhatsAppConversation(id));
        if (first) setError("");
      } catch (e) {
        if (first) setError(failure(e, "Could not load this conversation."));
      }
    },
    [api, id],
  );
  useEffect(() => {
    void load(true);
    // New patient messages appear without a reload. A hidden tab, or a send in progress, does not ask.
    const timer = setInterval(() => {
      if (!document.hidden && !busyRef.current) void load(false);
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [load]);
  const count = detail?.messages.length ?? 0;
  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [count]);

  async function run(action: () => Promise<unknown>, failed: string) {
    busyRef.current = true;
    setBusy(true);
    setError("");
    try {
      await action();
      await load(false);
      onChanged();
      return true;
    } catch (e) {
      setError(failure(e, failed));
      return false;
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  const paused = detail?.conversation.agent_paused ?? false;
  const lastPatient = detail?.messages
    .filter((m) => m.direction === "inbound")
    .at(-1);
  const windowOpen =
    !!lastPatient &&
    Date.now() - new Date(lastPatient.created_at).getTime() < WINDOW_MS;

  return (
    <Dialog
      title={detail ? who(detail.conversation) : "Conversation"}
      onClose={onClose}
    >
      <FormError message={error} />
      {!detail && !error && <Muted role="status">Loading…</Muted>}
      {detail && (
        <>
          <ol
            aria-label="Messages"
            data-testid="whatsapp-thread"
            className="m-0 grid max-h-[50vh] list-none gap-2 overflow-auto p-0"
          >
            {detail.messages.map((m) => (
              <li
                key={m.id}
                data-direction={m.direction}
                data-sender={
                  m.direction === "inbound"
                    ? "patient"
                    : m.from_staff
                      ? "staff"
                      : "agent"
                }
                className={`max-w-[85%] rounded-xl px-3 py-2 text-[14px] [overflow-wrap:anywhere] ${m.direction === "outbound" ? (m.from_staff ? "justify-self-end bg-[#eef3ff]" : "justify-self-end bg-brand-soft") : "justify-self-start border border-line bg-white"}`}
              >
                <small className="block text-[12px] text-muted">
                  {m.direction === "inbound"
                    ? who(detail.conversation)
                    : m.from_staff
                      ? `${m.sent_by ?? "Staff"} (staff)`
                      : "Agent"}{" "}
                  · {dateLabel(m.created_at, timezone)}
                  {m.status === "failed" ? " · not delivered" : ""}
                </small>
                <span className="whitespace-pre-wrap">{m.text}</span>
              </li>
            ))}
            <li ref={endRef} aria-hidden="true" />
          </ol>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
            <span data-testid="whatsapp-agent-state">
              <Badge>{paused ? "Agent paused" : "Agent on"}</Badge>
            </span>
            {manager && (
              <Button
                variant="outline"
                disabled={busy}
                onClick={() =>
                  void run(
                    () =>
                      paused
                        ? api.resumeWhatsAppAgent(id)
                        : api.pauseWhatsAppAgent(id),
                    "Could not change the agent for this chat.",
                  )
                }
              >
                {paused ? "Resume agent" : "Pause agent"}
              </Button>
            )}
          </div>
          {paused && (
            <Muted className="mt-2">
              The agent is paused for this chat. It saves new messages but does
              not answer them. Press Resume agent to let it answer again.
            </Muted>
          )}
          {manager ? (
            <form
              aria-label="Reply to this person"
              className="mt-4"
              onSubmit={async (event) => {
                event.preventDefault();
                const text = draft.trim();
                if (!text) return;
                if (
                  await run(
                    () => api.sendWhatsAppReply(id, text),
                    "Could not send the reply.",
                  )
                )
                  setDraft("");
              }}
            >
              <Textarea
                label="Reply"
                name="reply"
                compact
                maxLength={4096}
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                disabled={busy || !windowOpen}
                hint={
                  windowOpen
                    ? paused
                      ? "You are the one answering this chat."
                      : "Sending a reply pauses the agent for this chat."
                    : "The 24-hour reply window is closed. WhatsApp allows a free message only within 24 hours of the person's last message."
                }
              />
              <DialogActions>
                <Button variant="outline" type="button" onClick={onClose}>
                  Close
                </Button>
                <Button
                  type="submit"
                  variant="brand"
                  disabled={busy || !windowOpen || !draft.trim()}
                >
                  {busy ? "Sending…" : "Send"}
                </Button>
              </DialogActions>
            </form>
          ) : (
            <>
              <Muted className="mt-3">
                Only owners and office managers can reply to this chat.
              </Muted>
              <DialogActions>
                <Button variant="outline" onClick={onClose}>
                  Close
                </Button>
              </DialogActions>
            </>
          )}
        </>
      )}
      {!detail && (
        <DialogActions>
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
        </DialogActions>
      )}
    </Dialog>
  );
}

// ---- Configuration -------------------------------------------------------------------------------------------------

export function WhatsAppSettings() {
  return (
    <VoiceBoundary fallback={<WhatsAppSettingsSkeleton />}>
      <Settings />
    </VoiceBoundary>
  );
}

function Settings() {
  const { api } = useVoice();
  const { notify } = useDemo();
  const [data, setData] = useState<WhatsAppState | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [active, setActive] = useState(true);
  const [useKnowledge, setUseKnowledge] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);

  const load = useCallback(async () => {
    try {
      const state = await api.getWhatsAppAccount();
      setData(state);
      setActive(state.account?.is_active ?? true);
      setUseKnowledge(state.account?.use_knowledge ?? false);
    } catch (e) {
      setError(failure(e, "Could not load the WhatsApp settings."));
    }
  }, [api]);
  useEffect(() => {
    void load();
  }, [load]);

  async function save(form: FormData) {
    const token = String(form.get("access_token") ?? "").trim();
    const body: WhatsAppAccountInput = {
      phone_number_id: String(form.get("phone_number_id") ?? "").trim(),
      access_token: token || null,
      agent_name: String(form.get("agent_name") ?? "").trim(),
      prompt: String(form.get("prompt") ?? "").trim(),
      greeting: String(form.get("greeting") ?? "").trim() || null,
      is_active: active,
      use_knowledge: useKnowledge,
    };
    setBusy(true);
    setError("");
    try {
      await api.saveWhatsAppAccount(body);
      await load();
      notify("WhatsApp settings saved");
    } catch (e) {
      setError(failure(e, "Could not save the WhatsApp settings."));
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    setBusy(true);
    try {
      await api.disconnectWhatsApp();
      setDisconnecting(false);
      await load();
      notify("WhatsApp number disconnected");
    } catch (e) {
      setError(failure(e, "Could not disconnect the number."));
      setDisconnecting(false);
    } finally {
      setBusy(false);
    }
  }

  const account = data?.account ?? null;
  return (
    <>
      <Heading
        title="WhatsApp configuration"
        description="Connect your clinic's WhatsApp Business number and set how the agent answers."
        actions={
          <Link
            className={buttonStyles("outline")}
            href="/voice-receptionist/whatsapp"
          >
            <MessageCircle size={15} />
            Conversations
          </Link>
        }
      />
      <FormError message={error} />
      {data && !data.ready && (
        <Note className="mb-[18px]" role="note">
          <strong>WhatsApp is not set up on this server yet.</strong> You can
          save the settings, but messages will not arrive until the address of
          the WhatsApp service is added to the server.
        </Note>
      )}
      {!data ? (
        <Panel>
          <LinesSkeleton lines={4} />
        </Panel>
      ) : (
        <SidebarLayout>
          <Panel>
            <form
              aria-label="WhatsApp settings"
              onSubmit={async (event) => {
                event.preventDefault();
                await save(new FormData(event.currentTarget));
              }}
            >
              <Field
                label="Phone number ID"
                name="phone_number_id"
                required
                inputMode="numeric"
                pattern="\d+"
                maxLength={64}
                defaultValue={account?.phone_number_id ?? ""}
                hint="From Meta: WhatsApp → API setup → Phone number ID. It is not the phone number itself."
              />
              <Field
                label="Access token"
                name="access_token"
                type="password"
                autoComplete="off"
                required={!account}
                placeholder={account ? "Saved. Leave blank to keep it." : ""}
                hint="From Meta. It is stored encrypted and is never shown again."
              />
              <Field
                label="Agent name"
                name="agent_name"
                required
                maxLength={200}
                defaultValue={account?.agent_name ?? "WhatsApp assistant"}
              />
              <Textarea
                label="Instructions for the agent"
                name="prompt"
                required
                maxLength={8000}
                defaultValue={account?.prompt ?? data.default_prompt}
                hint="Tell the agent who it is and what it may talk about. Opening hours and services go here."
              />
              <Textarea
                label="Greeting"
                name="greeting"
                compact
                maxLength={1000}
                defaultValue={account?.greeting ?? ""}
                hint="Optional. The agent opens its first reply to a new person with this."
              />
              <Switch
                label="Search the knowledge base"
                description={
                  <>
                    The agent looks answers up in the documents you uploaded
                    (prices, treatments, opening hours, policies) before it
                    replies, and does not guess. Upload them in the{" "}
                    <Link
                      className="focus-ring text-[#38691d] underline"
                      href="/voice-receptionist/knowledge"
                    >
                      Knowledge base
                    </Link>
                    .
                  </>
                }
                checked={useKnowledge}
                onChange={setUseKnowledge}
              />
              <Switch
                label="Agent is on"
                description="When it is off, messages are not answered or saved."
                checked={active}
                onChange={setActive}
              />
              <DialogActions>
                {account && (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => setDisconnecting(true)}
                  >
                    Disconnect number
                  </Button>
                )}
                <Button type="submit" variant="brand" disabled={busy}>
                  {busy
                    ? "Saving…"
                    : account
                      ? "Save changes"
                      : "Connect number"}
                </Button>
              </DialogActions>
            </form>
          </Panel>
          <Panel>
            <H2>Connect to Meta</H2>
            {account && (
              <p className="my-2 text-[14px]">
                <Badge>{account.is_active ? "Agent on" : "Agent off"}</Badge>{" "}
                {account.display_number}
              </p>
            )}
            <Muted>
              In the Meta developer console, open WhatsApp → Configuration and
              set the callback URL to the address below. Use the verify token
              your administrator set on the server, and subscribe to “messages”.
            </Muted>
            <p
              data-testid="whatsapp-webhook-url"
              className="my-3 text-[13px] [overflow-wrap:anywhere]"
            >
              <code>
                {data.webhook_url ??
                  "The server has no public WhatsApp address yet."}
              </code>
            </p>
          </Panel>
        </SidebarLayout>
      )}
      {disconnecting && (
        <Dialog
          title="Disconnect this WhatsApp number?"
          onClose={() => setDisconnecting(false)}
        >
          <Muted>
            The agent stops answering. All saved WhatsApp conversations for your
            clinic are deleted. This cannot be undone.
          </Muted>
          <DialogActions>
            <Button variant="outline" onClick={() => setDisconnecting(false)}>
              Cancel
            </Button>
            <Button
              variant="brand"
              disabled={busy}
              onClick={() => void disconnect()}
            >
              Disconnect
            </Button>
          </DialogActions>
        </Dialog>
      )}
    </>
  );
}
