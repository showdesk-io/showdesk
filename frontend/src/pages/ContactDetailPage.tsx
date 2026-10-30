/**
 * A contact: profile and custom attributes, timeline, and what's known around them.
 *
 * Anonymized contacts open read-only. The API refuses their writes with a 409, which also
 * covers a contact anonymized while its page was open.
 */

import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import toast from "react-hot-toast";
import { parseApiError } from "@/api/errors";
import type { ContactWrite } from "@/api/contacts";
import { AttributeEditor } from "@/components/contacts/AttributeEditor";
import { ContactTimeline } from "@/components/contacts/ContactTimeline";
import {
  ACTION_BUTTON_CLASS,
  BackLink,
  CARD_CLASS,
  DANGER_BUTTON_CLASS,
  DetailNotFound,
  Fact,
  SectionHeading,
} from "@/components/contacts/DetailParts";
import { FormField, FormModal } from "@/components/contacts/FormModal";
import { formatDateTime, formatMrr, NO_VALUE } from "@/components/contacts/format";
import {
  attributeErrors,
  fieldErrors,
  NO_ERRORS,
  readFormErrors,
  type FormErrors,
} from "@/components/contacts/formErrors";
import { InlineField } from "@/components/contacts/InlineField";
import { Avatar, ListError, ListLoading } from "@/components/contacts/ListParts";
import {
  AnonymizedBadge,
  UnverifiedBadge,
  VerifiedBadge,
} from "@/components/contacts/UnverifiedBadge";
import { useContactConflict } from "@/components/contacts/useContactConflict";
import { useCurrentUser } from "@/hooks/useAuth";
import { useCompany } from "@/hooks/useCompanies";
import {
  useAnonymizeContact,
  useContact,
  useDeleteContact,
  useExportContact,
  useUpdateContact,
} from "@/hooks/useContacts";
import type { CompanySummary, Contact } from "@/types";

export function ContactDetailPage() {
  const { id = "" } = useParams<{ id: string }>();
  const { data: contact, isLoading, error, isFetching, refetch } = useContact(id);

  if (isLoading) return <ListLoading label="Loading contact" />;
  if (parseApiError(error).status === 404) {
    return (
      <DetailNotFound
        message="Contact not found."
        backTo="/contacts"
        backLabel="Back to contacts"
      />
    );
  }
  if (!contact) {
    return (
      <ListError
        message="Could not load this contact."
        onRetry={() => void refetch()}
        isRetrying={isFetching}
      />
    );
  }
  return <ContactDetail key={contact.id} contact={contact} />;
}

function ContactDetail({ contact }: { contact: Contact }) {
  const { data: currentUser } = useCurrentUser();
  const isAdmin = currentUser?.role === "admin";
  const readOnly = contact.is_anonymized;
  const updateContact = useUpdateContact();
  const handleConflict = useContactConflict(contact.id);

  // mutateAsync: fields save independently, and mutate() only tells the latest how it went.
  const save = async (
    data: ContactWrite,
    errorsOf: (error: unknown) => string[],
  ): Promise<string[]> => {
    try {
      await updateContact.mutateAsync({ id: contact.id, ...data });
      return [];
    } catch (error) {
      return handleConflict(error) ? [] : errorsOf(error);
    }
  };

  const saveField = (field: "name" | "email" | "phone") => (value: string) =>
    save({ [field]: value }, (error) => fieldErrors(error, field));

  return (
    <div className="p-6">
      <div className="mb-4">
        <BackLink to="/contacts" label="Back to contacts" />
      </div>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-4">
        <div className="space-y-4">
          <section aria-label="Profile" className={`${CARD_CLASS} space-y-3`}>
            <div className="flex items-center gap-3">
              <Avatar url={contact.avatar_url} name={contact.display_name} />
              <div className="min-w-0 flex-1">
                <InlineField
                  label="Name"
                  value={contact.name}
                  readOnly={readOnly}
                  onSave={saveField("name")}
                >
                  <h1 className="text-lg font-bold text-gray-900">{contact.display_name}</h1>
                </InlineField>
              </div>
            </div>

            {readOnly ? (
              <div
                role="status"
                aria-label="Anonymized"
                className="rounded-lg bg-gray-100 px-3 py-2 text-sm text-gray-600"
              >
                <AnonymizedBadge />
                <p className="mt-1">
                  This contact's personal data was removed. This page is read-only.
                </p>
              </div>
            ) : (
              <>
                <InlineField
                  label="Email"
                  type="email"
                  value={contact.email}
                  onSave={saveField("email")}
                >
                  {contact.email ? (
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="break-all">{contact.email}</span>
                      {contact.email_verified ? <VerifiedBadge /> : <UnverifiedBadge />}
                    </span>
                  ) : undefined}
                </InlineField>
                {contact.declared_email && contact.declared_email !== contact.email && (
                  <Fact label="Declared (unverified)">
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="break-all">{contact.declared_email}</span>
                      <UnverifiedBadge />
                    </span>
                  </Fact>
                )}
                <InlineField
                  label="Phone"
                  type="tel"
                  value={contact.phone}
                  onSave={saveField("phone")}
                />
              </>
            )}

            {contact.company_detail && (
              <Fact label="Company">
                <CompanyLink company={contact.company_detail} />
              </Fact>
            )}
            {contact.external_id && (
              <Fact label="External ID">
                <code className="break-all font-mono text-xs">{contact.external_id}</code>
              </Fact>
            )}
          </section>

          <section aria-label="Attributes" className={CARD_CLASS}>
            <SectionHeading>Attributes</SectionHeading>
            <AttributeEditor
              entity="contact"
              values={contact.attributes}
              readOnly={readOnly}
              onSave={(key, value) =>
                save({ attributes: { [key]: value } }, (error) => attributeErrors(error, key))
              }
            />
          </section>

          {isAdmin && !readOnly && <AdminActions contact={contact} />}
        </div>

        <div className="lg:col-span-2">
          <ContactTimeline contactId={contact.id} readOnly={readOnly} />
        </div>

        <Overview contact={contact} />
      </div>
    </div>
  );
}

function CompanyLink({ company }: { company: CompanySummary }) {
  return (
    <Link to={`/companies/${company.id}`} className="text-primary-700 hover:underline">
      {company.name}
    </Link>
  );
}

function Overview({ contact }: { contact: Contact }) {
  // A contact only embeds a summary of its company, without the MRR.
  const { data: company } = useCompany(contact.company ?? "");

  return (
    <section aria-label="Overview" className={`${CARD_CLASS} h-fit space-y-3`}>
      <SectionHeading>Overview</SectionHeading>
      <Fact label="Total tickets">{contact.tickets_count}</Fact>
      <Fact label="Open tickets">{contact.open_tickets_count}</Fact>
      <Fact label="First seen">{formatDateTime(contact.first_seen_at)}</Fact>
      <Fact label="Last seen">{formatDateTime(contact.last_seen_at)}</Fact>
      {contact.company_detail && (
        <>
          <Fact label="Company">
            <CompanyLink company={contact.company_detail} />
          </Fact>
          <Fact label="Plan">{contact.company_detail.plan || NO_VALUE}</Fact>
          <Fact label="MRR">{formatMrr(company?.mrr_cents)}</Fact>
        </>
      )}
    </section>
  );
}

function AdminActions({ contact }: { contact: Contact }) {
  const exportContact = useExportContact();
  const handleConflict = useContactConflict(contact.id);
  const [modal, setModal] = useState<"anonymize" | "delete" | null>(null);

  const handleExport = () => {
    exportContact.mutate(contact.id, {
      onSuccess: () => toast.success("Export queued — you will receive it by email"),
      onError: (error) => {
        if (!handleConflict(error)) toast.error("Failed to queue the export.");
      },
    });
  };

  return (
    <section aria-label="Admin actions" className={`${CARD_CLASS} space-y-2`}>
      <button
        type="button"
        disabled={exportContact.isPending}
        onClick={handleExport}
        className={ACTION_BUTTON_CLASS}
      >
        Export data
      </button>
      <button type="button" onClick={() => setModal("anonymize")} className={DANGER_BUTTON_CLASS}>
        Anonymize
      </button>
      <button type="button" onClick={() => setModal("delete")} className={DANGER_BUTTON_CLASS}>
        Delete
      </button>
      {modal === "anonymize" && (
        <AnonymizeModal contact={contact} onClose={() => setModal(null)} />
      )}
      {modal === "delete" && <DeleteModal contact={contact} onClose={() => setModal(null)} />}
    </section>
  );
}

function AnonymizeModal({ contact, onClose }: { contact: Contact; onClose: () => void }) {
  const anonymize = useAnonymizeContact();
  const handleConflict = useContactConflict(contact.id);
  const [typed, setTyped] = useState("");
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS);
  const expected = contact.email || contact.display_name;
  const matches = typed.trim() === expected;

  // mutateAsync: success takes this modal off the page, and mutate() wouldn't tell it then.
  const handleSubmit = async () => {
    if (!matches || anonymize.isPending) return;
    setErrors(NO_ERRORS);
    try {
      await anonymize.mutateAsync(contact.id);
      toast.success("Contact anonymized.");
      onClose();
    } catch (error) {
      if (handleConflict(error)) {
        onClose();
        return;
      }
      const shown = readFormErrors(error, []);
      if (shown) setErrors(shown);
      else toast.error("Failed to anonymize contact.");
    }
  };

  return (
    <FormModal
      title="Anonymize contact"
      submitLabel="Anonymize"
      danger
      errors={errors}
      isSubmitting={anonymize.isPending}
      canSubmit={matches}
      onClose={() => {
        if (!anonymize.isPending) onClose();
      }}
      onSubmit={() => void handleSubmit()}
    >
      <div className="space-y-2 text-sm text-gray-700">
        <p className="font-semibold text-red-700">This is irreversible.</p>
        <p>
          It removes this contact's personal data and permanently deletes notes, attachments and
          recordings from this contact. Tickets stay, with the contact's messages removed.
        </p>
        <p>
          To confirm, type <strong className="break-all">{expected}</strong>
        </p>
      </div>
      <FormField
        label={contact.email ? "Type the email to confirm" : "Type the name to confirm"}
        value={typed}
        onChange={setTyped}
        autoFocus
      />
    </FormModal>
  );
}

function DeleteModal({ contact, onClose }: { contact: Contact; onClose: () => void }) {
  const navigate = useNavigate();
  const deleteContact = useDeleteContact();
  const handleConflict = useContactConflict(contact.id);

  const handleSubmit = async () => {
    try {
      await deleteContact.mutateAsync(contact.id);
      toast.success("Contact deleted.");
      void navigate("/contacts");
    } catch (error) {
      if (handleConflict(error)) onClose();
      else toast.error("Failed to delete contact.");
    }
  };

  return (
    <FormModal
      title="Delete contact"
      submitLabel="Delete"
      danger
      errors={NO_ERRORS}
      isSubmitting={deleteContact.isPending}
      onClose={() => {
        if (!deleteContact.isPending) onClose();
      }}
      onSubmit={() => void handleSubmit()}
    >
      <p className="text-sm text-gray-700">
        Delete <strong className="break-all">{contact.display_name}</strong> and their notes? Their
        tickets stay, no longer linked to a contact. This can't be undone.
      </p>
    </FormModal>
  );
}
