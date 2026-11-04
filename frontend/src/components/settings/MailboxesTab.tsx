/**
 * Settings tab for the email channel: the organization's mailboxes, how to forward mail
 * to them, and the mail they received that didn't become a message.
 * Admins manage them, agents read them.
 */

import { useId, useRef, useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { formatDistanceToNow } from "date-fns";
import toast from "react-hot-toast";
import type { MailboxUpdate } from "@/api/mailboxes";
import { fetchOrganization, fetchTeams } from "@/api/users";
import { FormField } from "@/components/contacts/FormModal";
import {
  fieldErrors,
  NO_ERRORS,
  readFormErrors,
  type FormErrors,
} from "@/components/contacts/formErrors";
import { TH_CLASS } from "@/components/contacts/ListParts";
import {
  useCreateMailbox,
  useMailboxes,
  useMailboxInbound,
  useRegenerateMailboxAddress,
  useReplayInboundEmail,
  useUpdateMailbox,
} from "@/hooks/useMailboxes";
import type { ForwardingConfirmation, Mailbox, Team } from "@/types";
import { safeConfirmationUrl } from "./forwarding";
import { SendingDomainWizard } from "./SendingDomainWizard";

const FORM_FIELDS = ["name", "public_address", "default_team"];
const CONTROL_CLASS =
  "w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-hidden focus:ring-1 focus:ring-primary-500";
const SMALL_BUTTON_CLASS =
  "rounded-sm px-2 py-1 text-xs text-gray-500 hover:bg-gray-100 hover:text-gray-700 disabled:opacity-50";

const REASONS: Record<string, string> = {
  auto_reply: "Automatic reply",
  bulk: "Bulk or mailing list",
  bounce: "Bounce",
  loop: "Mail loop",
  spam: "Spam",
  duplicate: "Duplicate",
  rate_limited: "Too many from this sender",
  mailbox_rate_limited: "Too many for this mailbox",
  forwarding_confirmation: "Gmail forwarding confirmation",
  inactive_organization: "Organization inactive",
  unknown_recipient: "Unknown recipient",
  unparseable: "Unreadable mail",
  raw_missing: "Mail no longer stored",
  exception: "Processing error",
};

const STATUSES: Record<string, string> = {
  ignored: "Ignored",
  rejected: "Rejected",
  failed: "Failed",
  pending: "Pending",
  processed: "Processed",
};

/** What the form is open on, null when it's closed. */
type FormTarget = { mode: "create" } | { mode: "edit"; mailbox: Mailbox } | null;

export function MailboxesTab({ isAdmin }: { isAdmin: boolean }) {
  const { data: mailboxes, isLoading, isError } = useMailboxes();
  const { data: teams = [] } = useQuery({ queryKey: ["teams"], queryFn: fetchTeams });
  // The app's organization query: whether mail can go out from the org's own domains.
  const { data: organization } = useQuery({
    queryKey: ["organization"],
    queryFn: fetchOrganization,
  });
  const canSendFromDomain = isAdmin && organization?.sending_domains_enabled === true;
  const [formTarget, setFormTarget] = useState<FormTarget>(null);

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary-500 border-t-transparent" />
      </div>
    );
  }
  if (isError || !mailboxes) {
    return (
      <div role="alert" className="mx-auto max-w-5xl text-center text-sm text-red-600">
        Could not load the mailboxes.
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Email</h2>
          <p className="mt-1 text-sm text-gray-500">
            Forward your support address to a mailbox's inbound address: every mail opens or
            continues a ticket.
          </p>
        </div>
        {isAdmin && (
          <button
            type="button"
            onClick={() => setFormTarget({ mode: "create" })}
            className="shrink-0 rounded-lg bg-primary-500 px-4 py-2 text-sm font-medium text-white hover:bg-primary-600"
          >
            + New mailbox
          </button>
        )}
      </div>

      {isAdmin && formTarget && (
        <MailboxForm
          key={formTarget.mode === "edit" ? formTarget.mailbox.id : "create"}
          mailbox={formTarget.mode === "edit" ? formTarget.mailbox : null}
          teams={teams}
          onClose={() => setFormTarget(null)}
        />
      )}

      {mailboxes.length === 0 ? (
        <div className="rounded-xl border border-gray-200 bg-white px-6 py-12 text-center text-gray-500">
          No mailboxes yet.
        </div>
      ) : (
        mailboxes.map((mailbox) => (
          <MailboxCard
            key={mailbox.id}
            mailbox={mailbox}
            teamName={teams.find((team) => team.id === mailbox.default_team)?.name ?? ""}
            isAdmin={isAdmin}
            canSendFromDomain={canSendFromDomain}
            onEdit={() => setFormTarget({ mode: "edit", mailbox })}
          />
        ))
      )}

      <ForwardingHelp />
    </div>
  );
}

function MailboxCard({
  mailbox,
  teamName,
  isAdmin,
  canSendFromDomain,
  onEdit,
}: {
  mailbox: Mailbox;
  teamName: string;
  isAdmin: boolean;
  /** An admin, on a server with a sending provider. */
  canSendFromDomain: boolean;
  onEdit: () => void;
}) {
  const update = useUpdateMailbox();
  const regenerate = useRegenerateMailboxAddress();
  const [showLog, setShowLog] = useState(false);
  const [showWizard, setShowWizard] = useState(false);
  const wizardId = useId();
  const wizardToggle = useRef<HTMLButtonElement>(null);
  const confirmation = mailbox.forwarding_confirmation;

  const copyAddress = () => {
    void navigator.clipboard.writeText(mailbox.inbound_address).then(() => {
      toast.success("Inbound address copied.");
    });
  };

  const setActive = (isActive: boolean) => {
    update.mutate(
      { id: mailbox.id, is_active: isActive },
      { onError: (error) => toast.error(fieldErrors(error, "is_active").join(" ")) },
    );
  };

  const regenerateAddress = () => {
    if (
      !window.confirm(
        "Give this mailbox a new inbound address? Mail forwarded to the current one will be refused: update your forwarding first.",
      )
    ) {
      return;
    }
    regenerate.mutate(mailbox.id, {
      onSuccess: () => toast.success("New inbound address created."),
      onError: () => toast.error("Could not create a new address."),
    });
  };

  return (
    <section
      aria-label={mailbox.name}
      className={clsx(
        "rounded-xl border border-gray-200 bg-white p-6",
        !mailbox.is_active && "bg-gray-50",
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="flex items-baseline gap-3">
          <h3 className="text-base font-semibold text-gray-900">{mailbox.name}</h3>
          <span
            className={clsx(
              "rounded-full px-2 py-0.5 text-xs font-medium",
              mailbox.is_active ? "bg-green-100 text-green-700" : "bg-gray-200 text-gray-600",
            )}
          >
            {mailbox.is_active ? "Active" : "Inactive"}
          </span>
        </div>
        {isAdmin && (
          <div className="flex min-w-0 flex-wrap justify-end gap-1">
            <button type="button" onClick={onEdit} className={SMALL_BUTTON_CLASS}>
              Edit
            </button>
            <button
              type="button"
              onClick={() => setActive(!mailbox.is_active)}
              disabled={update.isPending}
              className={SMALL_BUTTON_CLASS}
            >
              {mailbox.is_active ? "Deactivate" : "Activate"}
            </button>
            <button
              type="button"
              onClick={regenerateAddress}
              disabled={regenerate.isPending}
              className={SMALL_BUTTON_CLASS}
            >
              New inbound address
            </button>
            {canSendFromDomain && (
              <button
                type="button"
                ref={wizardToggle}
                onClick={() => setShowWizard(!showWizard)}
                aria-expanded={showWizard}
                aria-controls={wizardId}
                className={SMALL_BUTTON_CLASS}
              >
                Send from your domain
              </button>
            )}
          </div>
        )}
      </div>

      <dl className="mt-4 grid gap-4 text-sm sm:grid-cols-3">
        <div>
          <dt className="text-xs font-medium uppercase text-gray-500">Inbound address</dt>
          <dd className="mt-1 flex items-center gap-2">
            <code className="break-all font-mono text-xs text-gray-800">
              {mailbox.inbound_address}
            </code>
            <button
              type="button"
              onClick={copyAddress}
              aria-label="Copy inbound address"
              className="shrink-0 rounded-sm border border-gray-200 px-2 py-0.5 text-xs text-gray-600 hover:bg-gray-50"
            >
              Copy
            </button>
          </dd>
        </div>
        <div>
          <dt className="text-xs font-medium uppercase text-gray-500">Public address</dt>
          <dd className="mt-1 text-gray-800">{mailbox.public_address || "—"}</dd>
        </div>
        <div>
          <dt className="text-xs font-medium uppercase text-gray-500">Default team</dt>
          <dd className="mt-1 text-gray-800">{teamName || "None"}</dd>
        </div>
      </dl>

      {(mailbox.sends_from_public_address || mailbox.inbound_address) && (
        <p className="mt-4 text-sm text-gray-600">
          Replies are sent from{" "}
          <span className="font-medium text-gray-800">
            {mailbox.sends_from_public_address ? mailbox.public_address : mailbox.inbound_address}
          </span>
        </p>
      )}

      {canSendFromDomain && showWizard && (
        <SendingDomainWizard
          id={wizardId}
          mailbox={mailbox}
          onClose={() => {
            setShowWizard(false);
            wizardToggle.current?.focus();
          }}
        />
      )}

      {(confirmation?.code || confirmation?.url) && (
        <GmailConfirmation confirmation={confirmation} />
      )}

      <div className="mt-4">
        <button
          type="button"
          onClick={() => setShowLog(!showLog)}
          className="text-sm font-medium text-primary-600 hover:text-primary-700"
        >
          {showLog ? "Hide received mail log" : "Show received mail log"}
        </button>
        {showLog && <InboundLog mailboxId={mailbox.id} isAdmin={isAdmin} />}
      </div>
    </section>
  );
}

/** The code and link of a Gmail confirmation. Linked only to Google's own hosts. */
function GmailConfirmation({
  confirmation,
}: {
  confirmation: Partial<ForwardingConfirmation>;
}) {
  const url = safeConfirmationUrl(confirmation.url ?? "");

  return (
    <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
      <p className="font-medium">
        Gmail asked to confirm forwarding
        {confirmation.detected_at &&
          ` (${formatDistanceToNow(new Date(confirmation.detected_at), { addSuffix: true })})`}
        .
      </p>
      <p className="mt-1">
        Only confirm if you have just set up forwarding to this mailbox: anyone can send a
        mail that looks like Gmail's.
      </p>
      {confirmation.code && (
        <p className="mt-2">
          Confirmation code: <code className="font-mono font-semibold">{confirmation.code}</code>
        </p>
      )}
      {url && (
        <p className="mt-2 break-all">
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="font-medium underline"
          >
            Confirm forwarding in Gmail
          </a>
          <span className="mt-1 block font-mono text-xs text-amber-800">{url}</span>
        </p>
      )}
    </div>
  );
}

function InboundLog({ mailboxId, isAdmin }: { mailboxId: string; isAdmin: boolean }) {
  const [page, setPage] = useState(1);
  const { data, isLoading, isError } = useMailboxInbound(mailboxId, page);
  const replay = useReplayInboundEmail(mailboxId);

  if (isLoading) {
    return <p className="mt-3 text-sm text-gray-500">Loading…</p>;
  }
  if (isError || !data) {
    // With the pager: a page emptied meanwhile is a 404, and the previous one isn't.
    return (
      <div className="mt-3">
        <p role="alert" className="text-sm text-red-600">
          Could not load the received mail log.
        </p>
        {page > 1 && <LogPager page={page} hasNewer hasOlder={false} onPage={setPage} />}
      </div>
    );
  }
  if (data.results.length === 0) {
    return (
      <p className="mt-3 text-sm text-gray-500">
        No ignored, rejected or failed mail. Mail that became a message is on its ticket.
      </p>
    );
  }

  const replayMail = (id: string) => {
    // The replayed mail leaves the log: alone on its page, the page goes with it.
    const emptiesPage = page > 1 && data.results.length === 1;
    replay.mutate(id, {
      onSuccess: () => {
        if (emptiesPage) setPage(page - 1);
        toast.success("The mail will be processed again.");
      },
      onError: () => toast.error("Could not replay this mail."),
    });
  };

  return (
    <div className="mt-3">
      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th scope="col" className={TH_CLASS}>Received</th>
              <th scope="col" className={TH_CLASS}>From</th>
              <th scope="col" className={TH_CLASS}>Subject</th>
              <th scope="col" className={TH_CLASS}>Outcome</th>
              {isAdmin && (
                <th scope="col" className={TH_CLASS}>
                  <span className="sr-only">Actions</span>
                </th>
              )}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {data.results.map((entry) => (
              <tr key={entry.id}>
                <td className="whitespace-nowrap px-6 py-2 text-xs text-gray-500">
                  {new Date(entry.received_at).toLocaleString()}
                </td>
                <td className="px-6 py-2 text-sm text-gray-700">{entry.sender}</td>
                <td className="px-6 py-2 text-sm text-gray-700">{entry.subject}</td>
                <td className="px-6 py-2 text-sm text-gray-600">
                  {STATUSES[entry.status] ?? entry.status}
                  {entry.reason && `: ${REASONS[entry.reason] ?? entry.reason}`}
                </td>
                {isAdmin && (
                  <td className="whitespace-nowrap px-6 py-2 text-right">
                    {entry.status === "failed" && (
                      <button
                        type="button"
                        onClick={() => replayMail(entry.id)}
                        disabled={replay.isPending}
                        className={SMALL_BUTTON_CLASS}
                      >
                        Replay
                      </button>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {(data.previous || data.next) && (
        <LogPager
          page={page}
          hasNewer={Boolean(data.previous)}
          hasOlder={Boolean(data.next)}
          onPage={setPage}
        />
      )}
    </div>
  );
}

function LogPager({
  page,
  hasNewer,
  hasOlder,
  onPage,
}: {
  page: number;
  hasNewer: boolean;
  hasOlder: boolean;
  onPage: (page: number) => void;
}) {
  return (
    <div className="mt-2 flex justify-end gap-2">
      <button
        type="button"
        onClick={() => onPage(page - 1)}
        disabled={!hasNewer}
        className={SMALL_BUTTON_CLASS}
      >
        Newer
      </button>
      <button
        type="button"
        onClick={() => onPage(page + 1)}
        disabled={!hasOlder}
        className={SMALL_BUTTON_CLASS}
      >
        Older
      </button>
    </div>
  );
}

/** Creates a mailbox, or edits `mailbox`, whose inbound address only changes on request. */
function MailboxForm({
  mailbox,
  teams,
  onClose,
}: {
  mailbox: Mailbox | null;
  teams: Team[];
  onClose: () => void;
}) {
  const create = useCreateMailbox();
  const update = useUpdateMailbox();
  const [name, setName] = useState(mailbox?.name ?? "");
  const [publicAddress, setPublicAddress] = useState(mailbox?.public_address ?? "");
  const [team, setTeam] = useState(mailbox?.default_team ?? "");
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS);
  const teamId = useId();
  const isPending = create.isPending || update.isPending;

  const refused = (error: unknown) => {
    const formErrors = readFormErrors(error, FORM_FIELDS);
    if (formErrors) setErrors(formErrors);
    else toast.error("Could not save this mailbox.");
  };

  const saved = (message: string) => () => {
    toast.success(message);
    onClose();
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (isPending) return;
    if (!name.trim()) {
      setErrors({ fields: { name: ["A name is required."] }, general: [] });
      return;
    }
    setErrors(NO_ERRORS);
    const values = {
      name: name.trim(),
      public_address: publicAddress.trim(),
      default_team: team || null,
    };
    if (!mailbox) {
      create.mutate(values, { onSuccess: saved("Mailbox created."), onError: refused });
      return;
    }
    // Only what changed.
    const changes: MailboxUpdate = {};
    if (values.name !== mailbox.name) changes.name = values.name;
    if (values.public_address !== mailbox.public_address) {
      changes.public_address = values.public_address;
    }
    if (values.default_team !== mailbox.default_team) changes.default_team = values.default_team;
    if (Object.keys(changes).length === 0) {
      onClose();
      return;
    }
    update.mutate(
      { id: mailbox.id, ...changes },
      { onSuccess: saved("Mailbox updated."), onError: refused },
    );
  };

  return (
    <form
      noValidate
      onSubmit={handleSubmit}
      aria-label={mailbox ? "Edit mailbox" : "New mailbox"}
      className="rounded-xl border border-gray-200 bg-white p-4"
    >
      <fieldset disabled={isPending} className="space-y-4">
        {errors.general.length > 0 && (
          <div role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
            {errors.general.map((message) => (
              <p key={message}>{message}</p>
            ))}
          </div>
        )}

        <div className="grid gap-4 sm:grid-cols-3">
          <FormField
            label="Name"
            value={name}
            errors={errors.fields.name}
            autoFocus
            onChange={setName}
          />
          <FormField
            label="Public address"
            type="email"
            value={publicAddress}
            errors={errors.fields.public_address}
            onChange={setPublicAddress}
          />
          <div>
            <label htmlFor={teamId} className="mb-1 block text-sm font-medium text-gray-700">
              Default team
            </label>
            <select
              id={teamId}
              value={team}
              onChange={(e) => setTeam(e.target.value)}
              className={CONTROL_CLASS}
            >
              <option value="">No team</option>
              {teams.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.name}
                </option>
              ))}
            </select>
            {errors.fields.default_team && (
              <p className="mt-1 text-xs text-red-600">{errors.fields.default_team.join(" ")}</p>
            )}
          </div>
        </div>
        <p className="text-xs text-gray-500">
          The public address is the one your customers write to, e.g. support@yourcompany.com.
        </p>

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg px-4 py-2 text-sm text-gray-600 hover:bg-gray-100"
          >
            Cancel
          </button>
          <button
            type="submit"
            className="rounded-lg bg-primary-500 px-4 py-2 text-sm font-medium text-white hover:bg-primary-600 disabled:opacity-50"
          >
            {mailbox ? "Save" : "Create"}
          </button>
        </div>
      </fieldset>
    </form>
  );
}

/** How to forward a support address to an inbound address (design §7.4). */
function ForwardingHelp() {
  return (
    <section className="rounded-xl border border-gray-200 bg-white p-6 text-sm text-gray-700">
      <h3 className="text-base font-semibold text-gray-900">Forwarding your support address</h3>
      <p className="mt-1 text-gray-500">
        Keep your address and your mail provider: forward its mail to the mailbox's inbound
        address.
      </p>

      <h4 className="mt-4 font-medium text-gray-900">Google Workspace or Gmail</h4>
      <ol className="mt-1 list-decimal space-y-1 pl-5">
        <li>
          In the support mailbox's Gmail, open Settings, then "Forwarding and POP/IMAP", and
          add the inbound address as a forwarding address.
        </li>
        <li>
          Gmail sends a confirmation mail to the inbound address. Its code and link appear on
          the mailbox above within a minute; confirm it in Gmail.
        </li>
        <li>Choose "Forward a copy of incoming mail to" the inbound address, and save.</li>
        <li>
          For a group or an alias, an administrator can instead add the inbound address as a
          recipient in the Admin console (Gmail routing).
        </li>
      </ol>

      <h4 className="mt-4 font-medium text-gray-900">Microsoft 365</h4>
      <ol className="mt-1 list-decimal space-y-1 pl-5">
        <li>
          Microsoft 365 blocks forwarding to outside addresses by default. In the Microsoft
          Defender portal, edit the outbound anti-spam policy that applies to the support
          mailbox, and set automatic forwarding to "On".
        </li>
        <li>
          In the Exchange admin center, open the support mailbox, then "Manage mail flow
          settings", turn on forwarding to the inbound address, and keep a copy in the
          mailbox if you wish.
        </li>
      </ol>

      <h4 className="mt-4 font-medium text-gray-900">Other providers</h4>
      <p className="mt-1">
        Any provider able to forward or redirect mail works: forward to the inbound address.
      </p>
    </section>
  );
}
