"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
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
  const [detail, setDetail] = useState<WhatsAppConversationDetail | null>(null);
  const [detailError, setDetailError] = useState("");

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

  useEffect(() => {
    if (!openId) return;
    let current = true;
    setDetail(null);
    setDetailError("");
    api
      .getWhatsAppConversation(openId)
      .then((d) => current && setDetail(d))
      .catch(
        (e) =>
          current &&
          setDetailError(failure(e, "Could not load this conversation.")),
      );
    return () => {
      current = false;
    };
  }, [api, openId]);

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
            both messages are saved here.
          </Muted>
          <Muted className="mt-3">
            {chats ? `${chats.length} conversation(s) shown.` : " "}
          </Muted>
        </Panel>
      </SidebarLayout>
      {openId && (
        <Dialog
          title={detail ? who(detail.conversation) : "Conversation"}
          onClose={() => setOpenId(null)}
        >
          <FormError message={detailError} />
          {!detail && !detailError && <Muted role="status">Loading…</Muted>}
          {detail && (
            <ol
              aria-label="Messages"
              data-testid="whatsapp-thread"
              className="m-0 grid max-h-[60vh] list-none gap-2 overflow-auto p-0"
            >
              {detail.messages.map((m) => (
                <li
                  key={m.id}
                  data-direction={m.direction}
                  className={`max-w-[85%] rounded-xl px-3 py-2 text-[14px] [overflow-wrap:anywhere] ${m.direction === "outbound" ? "justify-self-end bg-brand-soft" : "justify-self-start border border-line bg-white"}`}
                >
                  <small className="block text-[12px] text-muted">
                    {m.direction === "outbound"
                      ? "Agent"
                      : who(detail.conversation)}{" "}
                    · {dateLabel(m.created_at, timezone)}
                    {m.status === "failed" ? " · not delivered" : ""}
                  </small>
                  <span className="whitespace-pre-wrap">{m.text}</span>
                </li>
              ))}
            </ol>
          )}
          <DialogActions>
            <Button variant="outline" onClick={() => setOpenId(null)}>
              Close
            </Button>
          </DialogActions>
        </Dialog>
      )}
    </>
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
