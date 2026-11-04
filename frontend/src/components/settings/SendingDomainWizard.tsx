/**
 * Sending replies from a mailbox's public address (design §7), in three steps:
 * 1. the address, and its domain proven to be the organization's (DNS TXT or admin email);
 * 2. the DNS records the sending provider asks for;
 * 3. where the provider stands, checked again on request.
 *
 * The current step follows from the domain's row and the mailbox, never stored: the
 * wizard can be closed and opened again anywhere. Admins only, with a sending provider.
 */

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { clsx } from "clsx";
import { formatDistanceToNow } from "date-fns";
import toast from "react-hot-toast";
import { parseApiError } from "@/api/errors";
import { FormField } from "@/components/contacts/FormModal";
import { fieldErrors } from "@/components/contacts/formErrors";
import { useCurrentUser } from "@/hooks/useAuth";
import { useUpdateMailbox } from "@/hooks/useMailboxes";
import {
  useCheckSending,
  useCreateOrganizationDomain,
  useDisableSending,
  useEnableSending,
  useOrganizationDomains,
  useRegenerateDomainToken,
  useVerifyOrganizationDomain,
} from "@/hooks/useOrganizationDomains";
import type {
  DomainVerificationMethod,
  Mailbox,
  OrganizationDomain,
  SendingRecord,
  SendingStatus,
} from "@/types";

const PRIMARY_BUTTON_CLASS =
  "rounded-lg bg-primary-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-primary-600 disabled:opacity-50";
const SECONDARY_BUTTON_CLASS =
  "rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50";
const COPY_BUTTON_CLASS =
  "shrink-0 rounded-sm border border-gray-200 bg-white px-2 py-0.5 text-xs text-gray-600 hover:bg-gray-50";

/** The domain of an address, lowercased; "" while it isn't one. */
function domainOf(address: string): string {
  const trimmed = address.trim();
  const at = trimmed.lastIndexOf("@");
  if (at < 1) return "";
  const domain = trimmed.slice(at + 1).toLowerCase();
  return domain.includes(".") && !domain.endsWith(".") ? domain : "";
}

/** What the API said when it refused, or `fallback`. */
function refusalMessage(error: unknown, fallback: string): string {
  const { message, fields } = parseApiError(error);
  return message ?? Object.values(fields).flat()[0] ?? fallback;
}

function ago(date: string): string {
  return formatDistanceToNow(new Date(date), { addSuffix: true });
}

export function SendingDomainWizard({
  id,
  mailbox,
  onClose,
}: {
  /** For the button that opens it (`aria-controls`). */
  id?: string;
  mailbox: Mailbox;
  onClose: () => void;
}) {
  const headingId = useId();
  const { data: domains, isLoading, isError } = useOrganizationDomains();
  const [address, setAddress] = useState(mailbox.public_address);
  const domain = domainOf(address);
  const row = domains?.find((candidate) => candidate.domain === domain) ?? null;
  const addressSaved =
    address.trim().toLowerCase() === mailbox.public_address.toLowerCase();
  const ownedRow = row?.status === "verified" && addressSaved ? row : null;
  const step = !ownedRow ? 1 : ownedRow.sending_status === "" ? 2 : 3;

  let body: ReactNode;
  if (isLoading) {
    body = <p className="text-sm text-gray-500">Loading…</p>;
  } else if (isError || !domains) {
    body = (
      <p role="alert" className="text-sm text-red-600">
        Could not load your domains.
      </p>
    );
  } else {
    body = (
      <ol className="space-y-3">
        <Step number={1} title="Address and ownership" current={step === 1} done={step > 1}>
          <OwnershipStep
            mailbox={mailbox}
            address={address}
            onAddressChange={setAddress}
            domain={domain}
            row={row}
            addressSaved={addressSaved}
          />
        </Step>
        <Step number={2} title="DNS records" current={step === 2} done={step > 2}>
          {ownedRow ? (
            <RecordsStep row={ownedRow} />
          ) : (
            <p className="text-sm text-gray-500">
              {row?.status === "verified"
                ? "Once the address is saved."
                : "Once the address's domain is verified."}
            </p>
          )}
        </Step>
        <Step number={3} title="Status" current={step === 3} done={false}>
          {ownedRow && step === 3 ? (
            <StatusStep row={ownedRow} mailbox={mailbox} />
          ) : (
            <p className="text-sm text-gray-500">Once you have the DNS records.</p>
          )}
        </Step>
      </ol>
    );
  }

  return (
    <section
      id={id}
      aria-labelledby={headingId}
      className="mt-4 rounded-lg border border-gray-200 bg-gray-50 p-4"
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <h4 id={headingId} className="text-sm font-semibold text-gray-900">
            Send from your domain
          </h4>
          <p className="mt-1 text-sm text-gray-500">
            Replies go out from your public address once its domain is verified for your
            organization and its DNS records are published. Until then, they go out from the
            inbound address.
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close send from your domain"
          className="shrink-0 rounded-sm px-2 py-1 text-xs text-gray-500 hover:bg-gray-100 hover:text-gray-700"
        >
          Close
        </button>
      </div>
      <div className="mt-4">{body}</div>
    </section>
  );
}

function Step({
  number,
  title,
  current,
  done,
  children,
}: {
  number: number;
  title: string;
  current: boolean;
  done: boolean;
  children: ReactNode;
}) {
  const headingId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const wasCurrent = useRef(current);

  // Where the wizard moved to, for keyboard and screen reader users; not when it opens.
  useEffect(() => {
    if (current && !wasCurrent.current) headingRef.current?.focus();
    wasCurrent.current = current;
  }, [current]);

  return (
    <li>
      <section
        aria-labelledby={headingId}
        aria-current={current ? "step" : undefined}
        className={clsx(
          "rounded-lg border bg-white p-4",
          current ? "border-primary-300" : "border-gray-200",
        )}
      >
        <h5
          ref={headingRef}
          tabIndex={-1}
          className="flex items-center gap-2 text-sm font-semibold text-gray-900 outline-none"
        >
          <span id={headingId}>
            {number}. {title}
          </span>
          {done && (
            <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
              Done
            </span>
          )}
        </h5>
        <div className="mt-3 space-y-3">{children}</div>
      </section>
    </li>
  );
}

function ErrorMessage({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
      {message}
    </p>
  );
}

function CopyButton({ value, label }: { value: string; label: string }) {
  const copy = () => {
    void navigator.clipboard.writeText(value).then(() => {
      toast.success("Copied.");
    });
  };

  return (
    <button type="button" onClick={copy} aria-label={label} className={COPY_BUTTON_CLASS}>
      Copy
    </button>
  );
}

// ─── Step 1 ─────────────────────────────────────────────────────────────

function OwnershipStep({
  mailbox,
  address,
  onAddressChange,
  domain,
  row,
  addressSaved,
}: {
  mailbox: Mailbox;
  address: string;
  onAddressChange: (address: string) => void;
  domain: string;
  row: OrganizationDomain | null;
  addressSaved: boolean;
}) {
  const { data: currentUser } = useCurrentUser();
  const create = useCreateOrganizationDomain();
  const verify = useVerifyOrganizationDomain();
  const regenerate = useRegenerateDomainToken();
  const updateMailbox = useUpdateMailbox();
  const [error, setError] = useState<string | null>(null);
  const [addressErrors, setAddressErrors] = useState<string[]>([]);
  // From "Use this address" until the mailbox reloaded with it, or the API refused it.
  const [saving, setSaving] = useState(false);
  const [seen, setSeen] = useState({ addressSaved, status: row?.status });
  if (seen.addressSaved !== addressSaved || seen.status !== row?.status) {
    setSeen({ addressSaved, status: row?.status });
    if (seen.addressSaved !== addressSaved) setSaving(false);
    // What the error was about has changed.
    if (seen.status !== row?.status) setError(null);
  }
  const isPending =
    create.isPending ||
    verify.isPending ||
    regenerate.isPending ||
    updateMailbox.isPending ||
    saving;
  const canUseMyEmail = Boolean(domain) && domainOf(currentUser?.email ?? "") === domain;

  const changeAddress = (value: string) => {
    setError(null);
    setAddressErrors([]);
    onAddressChange(value);
  };

  const failed = (fallback: string) => (err: unknown) => {
    setError(refusalMessage(err, fallback));
  };

  const createRow = (method: DomainVerificationMethod) => {
    setError(null);
    create.mutate(
      {
        domain,
        is_sending: true,
        is_branding: false,
        is_email_routing: false,
        verification_method: method,
      },
      {
        onSuccess: (created) => {
          if (created.status === "verified") toast.success(`${created.domain} is verified.`);
        },
        onError: failed(`Could not add ${domain}.`),
      },
    );
  };

  const checkNow = (id: string) => {
    setError(null);
    verify.mutate(id, {
      onSuccess: ({ verified }) => {
        if (verified) toast.success(`${domain} is verified.`);
        else setError("TXT record not found yet. DNS can take a few minutes to propagate.");
      },
      onError: failed("The verification check failed."),
    });
  };

  const newToken = (id: string) => {
    setError(null);
    regenerate.mutate(id, { onError: failed("Could not create a new token.") });
  };

  const saveAddress = () => {
    if (
      mailbox.sends_from_public_address &&
      !window.confirm(
        `Replies go out from ${mailbox.public_address} now. Until ${domain} is set up for sending, they will go out from ${mailbox.inbound_address} instead. Use ${address.trim()}?`,
      )
    ) {
      return;
    }
    setAddressErrors([]);
    setSaving(true);
    updateMailbox.mutate(
      { id: mailbox.id, public_address: address.trim() },
      {
        onSuccess: () => toast.success("Public address saved."),
        onError: (err) => {
          setSaving(false);
          setAddressErrors(fieldErrors(err, "public_address"));
        },
      },
    );
  };

  const myEmailButton = canUseMyEmail && (
    <button
      type="button"
      onClick={() => createRow("admin_email")}
      disabled={isPending}
      className={SECONDARY_BUTTON_CLASS}
    >
      Verify with my email
    </button>
  );

  let ownership: ReactNode;
  if (!domain) {
    ownership = (
      <p className="text-sm text-gray-500">
        The address your customers write to, e.g. support@yourcompany.com.
      </p>
    );
  } else if (row?.status === "verified") {
    ownership = (
      <>
        <p className="text-sm text-green-700">{domain} is verified for your organization.</p>
        {!addressSaved && (
          <button
            type="button"
            onClick={saveAddress}
            disabled={isPending}
            className={PRIMARY_BUTTON_CLASS}
          >
            Use this address
          </button>
        )}
      </>
    );
  } else if (row?.status === "pending" && row.verification_method === "dns_txt") {
    ownership = (
      <>
        <p className="text-sm text-gray-700">
          Add this TXT record to {domain}'s DNS to prove it is your organization's, then check
          it. We also check it every 15 minutes for 7 days.
        </p>
        <p className="text-sm text-gray-500">
          You can close this and come back: DNS changes can take a while.
        </p>
        <dl className="space-y-2 text-sm">
          <RecordField label="Name" value={row.txt_record_name} copyLabel="Copy the TXT record name" />
          <RecordField
            label="Value"
            value={row.txt_record_value}
            copyLabel="Copy the TXT record value"
          />
        </dl>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => checkNow(row.id)}
            disabled={isPending}
            className={PRIMARY_BUTTON_CLASS}
          >
            {verify.isPending ? "Checking…" : "Check now"}
          </button>
          <button
            type="button"
            onClick={() => newToken(row.id)}
            disabled={isPending}
            className={SECONDARY_BUTTON_CLASS}
          >
            New token
          </button>
          {myEmailButton}
        </div>
      </>
    );
  } else {
    // No row yet, a failed one, or a pending one without a DNS challenge.
    ownership = (
      <>
        {row?.status === "failed" ? (
          <p className="text-sm text-red-700">
            The verification of {domain} failed: another organization may have verified it,
            or the TXT record was removed.
          </p>
        ) : (
          <p className="text-sm text-gray-700">
            Prove that {domain} is your organization's, with a DNS TXT record
            {canUseMyEmail ? " or with your own address on it" : ""}.
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => (row ? newToken(row.id) : createRow("dns_txt"))}
            disabled={isPending}
            className={PRIMARY_BUTTON_CLASS}
          >
            Verify with DNS
          </button>
          {myEmailButton}
        </div>
      </>
    );
  }

  return (
    <>
      <div className="max-w-md">
        <FormField
          label="Address to send from"
          type="email"
          value={address}
          errors={addressErrors}
          onChange={changeAddress}
        />
      </div>
      {ownership}
      <ErrorMessage message={error} />
    </>
  );
}

function RecordField({
  label,
  value,
  copyLabel,
}: {
  label: string;
  value: string;
  copyLabel: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <dt className="w-14 shrink-0 text-xs font-medium uppercase text-gray-500">{label}</dt>
      <dd className="flex min-w-0 flex-1 items-center gap-2">
        <code className="min-w-0 flex-1 break-all rounded-sm border border-gray-200 bg-gray-50 px-2 py-1 font-mono text-xs text-gray-800">
          {value}
        </code>
        <CopyButton value={value} label={copyLabel} />
      </dd>
    </div>
  );
}

// ─── Step 2 ─────────────────────────────────────────────────────────────

function RecordsStep({ row }: { row: OrganizationDomain }) {
  const enable = useEnableSending();
  const [error, setError] = useState<string | null>(null);

  const getRecords = () => {
    setError(null);
    enable.mutate(row.id, {
      onError: (err) => setError(refusalMessage(err, "Could not get the records.")),
    });
  };

  if (row.sending_status === "") {
    return (
      <>
        <p className="text-sm text-gray-700">
          Mail sent from {row.domain} must be authorized in its DNS. Get the records to
          publish.
        </p>
        <div>
          <button
            type="button"
            onClick={getRecords}
            disabled={enable.isPending}
            className={PRIMARY_BUTTON_CLASS}
          >
            {enable.isPending ? "Getting the records…" : "Get the records"}
          </button>
        </div>
        <ErrorMessage message={error} />
      </>
    );
  }

  return (
    <>
      <p className="text-sm text-gray-700">
        Publish these records where {row.domain}'s DNS is managed.
      </p>
      {row.sending_dns_records.length > 0 ? (
        <RecordsTable records={row.sending_dns_records} />
      ) : (
        <p className="text-sm text-gray-500">
          The sending service returned no records yet. Check again in a minute.
        </p>
      )}
    </>
  );
}

/** How to publish a record that may already exist: SPF and DMARC are TXT records. */
function mergeNote(record: SendingRecord): string {
  const value = record.value.trim().toLowerCase();
  if (value.startsWith("v=spf1")) {
    return `Already have an SPF record at ${record.name}? Add the include: part to it rather than adding a second record.`;
  }
  if (value.startsWith("v=dmarc1")) {
    return `Already have a DMARC record at ${record.name}? Keep a single one.`;
  }
  const article = /^[aefhilmnorsx]/i.test(record.type) ? "an" : "a";
  return `Already have ${article} ${record.type} record at ${record.name}? Merge this into it rather than adding a second record.`;
}

function RecordsTable({ records }: { records: SendingRecord[] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-gray-200">
      <table className="min-w-full divide-y divide-gray-200 text-sm">
        <thead className="bg-gray-50">
          <tr>
            <th scope="col" className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">
              Type
            </th>
            <th scope="col" className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">
              Name
            </th>
            <th scope="col" className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">
              Value
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {records.map((record) => (
            <tr key={`${record.type} ${record.name}`} className="align-top">
              <td className="whitespace-nowrap px-3 py-2 font-mono text-xs text-gray-800">
                {record.type}
              </td>
              <td className="px-3 py-2">
                <div className="flex items-start gap-2">
                  <code className="break-all font-mono text-xs text-gray-800">{record.name}</code>
                  <CopyButton
                    value={record.name}
                    label={`Copy the name of the ${record.type} record ${record.name}`}
                  />
                </div>
              </td>
              <td className="px-3 py-2">
                <div className="flex items-start gap-2">
                  <code className="break-all font-mono text-xs text-gray-800">{record.value}</code>
                  <CopyButton
                    value={record.value}
                    label={`Copy the value of the ${record.type} record ${record.name}`}
                  />
                </div>
                {record.merge && (
                  <p className="mt-1 text-xs text-amber-700">{mergeNote(record)}</p>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Step 3 ─────────────────────────────────────────────────────────────

const SENDING_STATUSES: Record<Exclude<SendingStatus, "">, { label: string; cls: string }> = {
  pending: { label: "Pending", cls: "bg-amber-50 text-amber-700 ring-amber-200" },
  verified: { label: "Verified", cls: "bg-green-50 text-green-700 ring-green-200" },
  failed: { label: "Failed", cls: "bg-red-50 text-red-700 ring-red-200" },
};

/** Where the sending provider stands on a domain; nothing while it isn't registered. */
export function SendingStatusBadge({
  status,
  prefix = "",
}: {
  status: SendingStatus;
  /** Before the status, e.g. "Sending: ". */
  prefix?: string;
}) {
  if (status === "") return null;
  const { label, cls } = SENDING_STATUSES[status];
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        cls,
      )}
    >
      {prefix}
      {label}
    </span>
  );
}

function StatusStep({ row, mailbox }: { row: OrganizationDomain; mailbox: Mailbox }) {
  const check = useCheckSending();
  const enable = useEnableSending();
  const disable = useDisableSending();
  const [error, setError] = useState<string | null>(null);
  const isPending = check.isPending || enable.isPending || disable.isPending;

  const failed = (fallback: string) => (err: unknown) => {
    setError(refusalMessage(err, fallback));
  };

  const checkNow = () => {
    setError(null);
    check.mutate(row.id, { onError: failed("The check failed.") });
  };

  const setUpAgain = () => {
    setError(null);
    enable.mutate(row.id, { onError: failed("Could not set sending up again.") });
  };

  const stop = () => {
    if (
      !window.confirm(
        `Stop sending from ${row.domain}? Replies will go out from the inbound address again.`,
      )
    ) {
      return;
    }
    setError(null);
    disable.mutate(row.id, {
      onSuccess: () => toast.success(`Replies no longer go out from ${row.domain}.`),
      onError: failed("Could not stop sending from this domain."),
    });
  };

  return (
    <>
      <p role="status" className="flex items-center gap-2 text-sm text-gray-700">
        Sending from {row.domain}: <SendingStatusBadge status={row.sending_status} />
      </p>
      {row.sending_status === "pending" && (
        <p className="text-sm text-gray-700">
          We check the records regularly for 72 hours. Until they are found, replies go out
          from {mailbox.inbound_address}.
        </p>
      )}
      {row.sending_status === "verified" && (
        <p className="text-sm text-gray-700">
          Replies go out from{" "}
          {mailbox.sends_from_public_address ? mailbox.public_address : mailbox.inbound_address}.
        </p>
      )}
      {row.sending_status === "failed" && (
        <p className="text-sm text-gray-700">
          The records could not be verified. Fix them, then set sending up again: replies go
          out from {mailbox.inbound_address} until then.
        </p>
      )}
      <p className="text-xs text-gray-500">
        {row.sending_last_checked_at
          ? `Last checked ${ago(row.sending_last_checked_at)}.`
          : "Not checked yet."}
      </p>
      {row.sending_last_error && (
        <p className="text-xs text-red-700">Last error: {row.sending_last_error}</p>
      )}
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={checkNow} disabled={isPending} className={PRIMARY_BUTTON_CLASS}>
          {check.isPending ? "Checking…" : "Check now"}
        </button>
        {row.sending_status === "failed" && (
          <button
            type="button"
            onClick={setUpAgain}
            disabled={isPending}
            className={SECONDARY_BUTTON_CLASS}
          >
            Set up again
          </button>
        )}
        <button
          type="button"
          onClick={stop}
          disabled={isPending}
          className="rounded-lg px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 disabled:opacity-50"
        >
          Stop sending from this domain
        </button>
      </div>
      <ErrorMessage message={error} />
    </>
  );
}
