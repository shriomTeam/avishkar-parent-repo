"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Plus } from "lucide-react";
import {
  Button,
  buttonStyles,
  DataTable,
  DialogActions,
  FooterRow,
  H2,
  Muted,
  Note,
  Panel,
  Td,
  Th,
  Tr,
  WideSplit,
} from "@clinic/ui";
import { useDemo } from "../lib/demo/provider";
import { useVoice } from "../lib/voice/provider";
import {
  ApiError,
  type AvailableNumber,
  type PhoneNumber,
  type PhoneNumbers,
} from "../lib/inbound/api";
import { Heading, Badge, Dialog, Dropdown, Field, FormError } from "./ui";
import { VoiceBoundary } from "./voice-boundary";
import { NumbersSkeleton, TableLoading } from "./skeletons";

export function Numbers() {
  return (
    <VoiceBoundary fallback={<NumbersSkeleton />}>
      <NumberList />
    </VoiceBoundary>
  );
}

/** +14155550123 shown as +1 (415) 555-0123. Other shapes are shown as they are. */
function pretty(number: string) {
  const m = /^\+1(\d{3})(\d{3})(\d{4})$/.exec(number);
  return m ? `+1 (${m[1]}) ${m[2]}-${m[3]}` : number;
}

const UNASSIGNED = "";

function NumberList() {
  const { api, agents } = useVoice();
  const { notify } = useDemo();
  const [data, setData] = useState<PhoneNumbers | null>(null);
  const [error, setError] = useState("");
  const [buying, setBuying] = useState(false);
  const [managing, setManaging] = useState<PhoneNumber | null>(null);

  const refresh = useCallback(async () => {
    try {
      setData(await api.listNumbers());
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e.message
          : "Could not load your phone numbers.",
      );
    }
  }, [api]);
  useEffect(() => {
    void refresh();
  }, [refresh]);

  const numbers = data?.numbers ?? [];
  const full = !!data && numbers.length >= data.max_numbers;
  return (
    <>
      <Heading
        title="Phone numbers"
        description="Buy a phone number and choose which agent it belongs to."
        actions={
          <Button
            variant="brand"
            disabled={!data?.enabled || full}
            onClick={() => {
              setError("");
              setBuying(true);
            }}
          >
            <Plus size={16} />
            Buy a number
          </Button>
        }
      />
      <FormError message={error} />
      {data?.enabled === false && (
        <Note className="mb-[18px]" role="note">
          <strong>Phone numbers are not set up on this server yet.</strong> They
          can be bought once the Twilio account details are added.
        </Note>
      )}
      {data?.enabled && !data.calls_enabled && (
        <Note className="mb-[18px]" role="note">
          <strong>Calls are not connected on this server yet.</strong> You can
          buy a number and choose its agent, but calls to it will not be
          answered until this server has a public address for Twilio.
        </Note>
      )}
      {data?.enabled && data.calls_enabled && (
        <Note className="mb-[18px]" role="note">
          <strong>Calls are answered by the agent you assign.</strong> A number
          with no agent, or with an agent that is switched off, tells callers it
          is not in service.
        </Note>
      )}
      <Panel>
        {!data ? (
          <TableLoading columns={[150, 60, 130, 90, 90]} rows={2} />
        ) : numbers.length === 0 ? (
          <Muted role="status">
            No phone numbers yet. Buy one to get started.
          </Muted>
        ) : (
          <DataTable>
            <thead>
              <tr>
                <Th>Phone number</Th>
                <Th>Type</Th>
                <Th>Assigned agent</Th>
                <Th>Status</Th>
                <Th>Actions</Th>
              </tr>
            </thead>
            <tbody>
              {numbers.map((n) => (
                <Tr key={n.id}>
                  <Td>
                    <strong>{pretty(n.number)}</strong>
                  </Td>
                  <Td>{n.kind === "toll_free" ? "Toll-free" : "Local"}</Td>
                  <Td>
                    {agents.find((a) => a.id === n.agent_id)?.name ||
                      "Not assigned"}
                  </Td>
                  <Td>
                    <Badge>{n.agent_id ? "Connected" : "Unassigned"}</Badge>
                  </Td>
                  <Td>
                    <Button
                      variant="outline"
                      aria-label={`Manage ${n.number}`}
                      onClick={() => {
                        setError("");
                        setManaging(n);
                      }}
                    >
                      Manage
                    </Button>
                  </Td>
                </Tr>
              ))}
            </tbody>
          </DataTable>
        )}
        {data && (
          <Muted className="mt-3">
            {numbers.length} of {data.max_numbers} numbers used. Twilio bills a
            monthly fee for each number until you release it.
          </Muted>
        )}
      </Panel>
      <WideSplit className="mt-5">
        <Panel>
          <H2>How inbound routing works</H2>
          <Muted>Caller → phone number → the agent you assign</Muted>
          <FooterRow>
            <span>Default greeting</span>
            <strong>Agent greeting</strong>
          </FooterRow>
          <FooterRow>
            <span>Outside opening hours</span>
            <strong>Collect callback details</strong>
          </FooterRow>
        </Panel>
        <Panel>
          <H2>Before going live</H2>
          <Muted>
            Test your agent from the browser first, then confirm the greeting
            and consent message.
          </Muted>
          <Link
            className={buttonStyles("outline", { className: "mt-5" })}
            href="/voice-receptionist/test"
          >
            Open test studio
          </Link>
        </Panel>
      </WideSplit>
      {buying && (
        <BuyDialog
          onClose={() => setBuying(false)}
          onBought={async () => {
            setBuying(false);
            notify("Phone number bought");
            await refresh();
          }}
        />
      )}
      {managing && (
        <ManageDialog
          number={managing}
          onClose={() => setManaging(null)}
          onChanged={async (message) => {
            setManaging(null);
            notify(message);
            await refresh();
          }}
        />
      )}
    </>
  );
}

function BuyDialog({
  onClose,
  onBought,
}: {
  onClose: () => void;
  onBought: () => Promise<void>;
}) {
  const { api, agents } = useVoice();
  const [kind, setKind] = useState<"local" | "toll_free">("local");
  const [found, setFound] = useState<AvailableNumber[] | null>(null);
  const [picked, setPicked] = useState<string>("");
  const [agentId, setAgentId] = useState(UNASSIGNED);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const active = agents.filter((a) => a.is_active);

  async function search(form: FormData) {
    const areaCode = String(form.get("area_code") ?? "").trim();
    const contains = String(form.get("contains") ?? "").trim();
    if (kind === "local" && areaCode && !/^[2-9]\d{2}$/.test(areaCode))
      return setError("An area code is three digits, such as 415.");
    if (contains && !/^\d{1,7}$/.test(contains))
      return setError("Use up to seven digits to look for.");
    setBusy(true);
    setError("");
    setPicked("");
    try {
      setFound(await api.searchNumbers(kind, areaCode, contains));
    } catch (e) {
      setFound(null);
      setError(e instanceof ApiError ? e.message : "The search failed.");
    } finally {
      setBusy(false);
    }
  }

  async function buy() {
    setBusy(true);
    setError("");
    try {
      await api.buyNumber(picked, agentId || null);
      await onBought();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not buy the number.");
      setBusy(false);
    }
  }

  return (
    <Dialog title="Buy a phone number" onClose={onClose}>
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          await search(new FormData(event.currentTarget));
        }}
      >
        <Dropdown
          label="Type"
          value={kind}
          onChange={(value) => {
            setKind(value as "local" | "toll_free");
            setFound(null);
            setPicked("");
          }}
          options={[
            { value: "local", label: "Local (US)" },
            { value: "toll_free", label: "Toll-free (US)" },
          ]}
        />
        {kind === "local" && (
          <Field
            label="Area code (optional)"
            name="area_code"
            inputMode="numeric"
            maxLength={3}
            placeholder="415"
          />
        )}
        <Field
          label="Contains digits (optional)"
          name="contains"
          inputMode="numeric"
          maxLength={7}
          placeholder="555"
          hint="Searching is free. You are only charged when you buy."
        />
        <Button type="submit" variant="outline" disabled={busy}>
          Search numbers
        </Button>
      </form>
      <FormError message={error} />
      {found && found.length === 0 && (
        <Muted role="status">
          No numbers matched. Try a different area code or fewer digits.
        </Muted>
      )}
      {found && found.length > 0 && (
        <fieldset className="mt-4 border-0 p-0">
          <legend className="mb-2 text-[14px] font-semibold">
            Choose a number
          </legend>
          {found.map((n) => (
            <label
              key={n.number}
              className="mb-2 flex cursor-pointer items-center gap-3 rounded-lg border border-line px-3 py-2.5 text-[14px]"
            >
              <input
                type="radio"
                name="number"
                value={n.number}
                checked={picked === n.number}
                onChange={() => setPicked(n.number)}
              />
              <strong>{pretty(n.number)}</strong>
              <span className="text-muted">
                {[n.locality, n.region].filter(Boolean).join(", ")}
              </span>
            </label>
          ))}
        </fieldset>
      )}
      {picked && (
        <>
          <Dropdown
            label="Assigned agent"
            value={agentId}
            onChange={setAgentId}
            options={[
              { value: UNASSIGNED, label: "Choose later" },
              ...active.map((a) => ({ value: a.id, label: a.name })),
            ]}
          />
          <Note role="note">
            Buying <strong>{pretty(picked)}</strong> charges your Twilio account
            a monthly fee until you release the number.
          </Note>
        </>
      )}
      <DialogActions>
        <Button type="button" variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button
          type="button"
          variant="brand"
          disabled={!picked || busy}
          onClick={() => void buy()}
        >
          Buy number
        </Button>
      </DialogActions>
    </Dialog>
  );
}

function ManageDialog({
  number,
  onClose,
  onChanged,
}: {
  number: PhoneNumber;
  onClose: () => void;
  onChanged: (message: string) => Promise<void>;
}) {
  const { api, agents } = useVoice();
  const [agentId, setAgentId] = useState(number.agent_id ?? UNASSIGNED);
  const [confirmRelease, setConfirmRelease] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const active = agents.filter((a) => a.is_active || a.id === number.agent_id);

  async function run(work: () => Promise<unknown>, done: string) {
    setBusy(true);
    setError("");
    try {
      await work();
      await onChanged(done);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
      setBusy(false);
    }
  }

  if (confirmRelease)
    return (
      <Dialog
        title={`Release ${pretty(number.number)}?`}
        onClose={() => setConfirmRelease(false)}
      >
        <Muted>
          The number goes back to Twilio and stops being billed. You may not be
          able to get this exact number again.
        </Muted>
        <FormError message={error} />
        <DialogActions>
          <Button variant="outline" onClick={() => setConfirmRelease(false)}>
            Keep number
          </Button>
          <Button
            variant="brand"
            disabled={busy}
            onClick={() =>
              void run(
                () => api.releaseNumber(number.id),
                "Phone number released",
              )
            }
          >
            Release number
          </Button>
        </DialogActions>
      </Dialog>
    );

  return (
    <Dialog title={pretty(number.number)} onClose={onClose}>
      <Dropdown
        label="Assigned agent"
        value={agentId}
        onChange={setAgentId}
        options={[
          { value: UNASSIGNED, label: "Unassigned" },
          ...active.map((a) => ({ value: a.id, label: a.name })),
        ]}
      />
      <FormError message={error} />
      <DialogActions>
        <Button
          variant="outline"
          disabled={busy}
          onClick={() => setConfirmRelease(true)}
        >
          Release number
        </Button>
        <Button variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button
          variant="brand"
          disabled={busy}
          onClick={() =>
            void run(
              () => api.assignNumber(number.id, agentId || null),
              "Routing saved",
            )
          }
        >
          Save routing
        </Button>
      </DialogActions>
    </Dialog>
  );
}
