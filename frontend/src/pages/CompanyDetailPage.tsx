/**
 * A company: profile and custom attributes, with its tickets and people.
 */

import { useId, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import toast from "react-hot-toast";
import { COMPANY_CONTACTS_LIMIT, type CompanyWrite } from "@/api/companies";
import { TIMELINE_TICKETS_LIMIT } from "@/api/contacts";
import { parseApiError } from "@/api/errors";
import { AttributeEditor } from "@/components/contacts/AttributeEditor";
import {
  BackLink,
  CARD_CLASS,
  DANGER_BUTTON_CLASS,
  DetailNotFound,
  Fact,
  SectionHeading,
} from "@/components/contacts/DetailParts";
import { FormModal } from "@/components/contacts/FormModal";
import { formatDateTime, formatMrr, NO_VALUE } from "@/components/contacts/format";
import {
  attributeErrors,
  fieldErrors,
  NO_ERRORS,
} from "@/components/contacts/formErrors";
import { InlineField } from "@/components/contacts/InlineField";
import {
  Avatar,
  ListEmpty,
  ListError,
  ListLoading,
  TH_CLASS,
} from "@/components/contacts/ListParts";
import { safeHttpUrl } from "@/components/contacts/safeUrl";
import { TicketLine } from "@/components/contacts/TicketLine";
import { UnverifiedBadge } from "@/components/contacts/UnverifiedBadge";
import { useCurrentUser } from "@/hooks/useAuth";
import {
  useCompany,
  useCompanyContacts,
  useCompanyTickets,
  useDeleteCompany,
  useUpdateCompany,
} from "@/hooks/useCompanies";
import type { Company } from "@/types";

const TABS = ["Tickets", "People"] as const;
type Tab = (typeof TABS)[number];

export function CompanyDetailPage() {
  const { id = "" } = useParams<{ id: string }>();
  const { data: company, isLoading, error, isFetching, refetch } = useCompany(id);

  if (isLoading) return <ListLoading label="Loading company" />;
  if (parseApiError(error).status === 404) {
    return (
      <DetailNotFound
        message="Company not found."
        backTo="/companies"
        backLabel="Back to companies"
      />
    );
  }
  if (!company) {
    return (
      <ListError
        message="Could not load this company."
        onRetry={() => void refetch()}
        isRetrying={isFetching}
      />
    );
  }
  return <CompanyDetail key={company.id} company={company} />;
}

function CompanyDetail({ company }: { company: Company }) {
  const { data: currentUser } = useCurrentUser();
  const isAdmin = currentUser?.role === "admin";
  const updateCompany = useUpdateCompany();
  const [showDelete, setShowDelete] = useState(false);

  // mutateAsync: fields save independently, and mutate() only tells the latest how it went.
  const save = async (
    data: CompanyWrite,
    errorsOf: (error: unknown) => string[],
  ): Promise<string[]> => {
    try {
      await updateCompany.mutateAsync({ id: company.id, ...data });
      return [];
    } catch (error) {
      return errorsOf(error);
    }
  };

  const saveField = (field: "name" | "domain" | "website" | "plan") => (value: string) =>
    save({ [field]: value }, (error) => fieldErrors(error, field));

  const website = safeHttpUrl(company.website);

  return (
    <div className="p-6">
      <div className="mb-4">
        <BackLink to="/companies" label="Back to companies" />
      </div>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-4">
        <div className="space-y-4">
          <section aria-label="Profile" className={`${CARD_CLASS} space-y-3`}>
            <div className="flex items-center gap-3">
              <Avatar url={company.logo_url} name={company.name} square />
              <div className="min-w-0 flex-1">
                <InlineField label="Name" value={company.name} onSave={saveField("name")}>
                  <h1 className="text-lg font-bold text-gray-900">{company.name}</h1>
                </InlineField>
              </div>
            </div>
            <InlineField label="Domain" value={company.domain} onSave={saveField("domain")} />
            <InlineField
              label="Website"
              type="url"
              value={company.website}
              onSave={saveField("website")}
            >
              {website ? (
                <a
                  href={website}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary-700 hover:underline"
                >
                  {company.website}
                </a>
              ) : undefined}
            </InlineField>
            <InlineField label="Plan" value={company.plan} onSave={saveField("plan")} />
            <Fact label="MRR">{formatMrr(company.mrr_cents)}</Fact>
            <Fact label="Health score">{company.health_score ?? NO_VALUE}</Fact>
            <Fact label="Contacts">{company.contacts_count}</Fact>
            <Fact label="Open tickets">{company.open_tickets_count}</Fact>
            {company.external_id && (
              <Fact label="External ID">
                <code className="break-all font-mono text-xs">{company.external_id}</code>
              </Fact>
            )}
          </section>

          <section aria-label="Attributes" className={CARD_CLASS}>
            <SectionHeading>Attributes</SectionHeading>
            <AttributeEditor
              entity="company"
              values={company.attributes}
              onSave={(key, value) =>
                save({ attributes: { [key]: value } }, (error) => attributeErrors(error, key))
              }
            />
          </section>

          {isAdmin && (
            <section aria-label="Admin actions" className={CARD_CLASS}>
              <button
                type="button"
                onClick={() => setShowDelete(true)}
                className={DANGER_BUTTON_CLASS}
              >
                Delete
              </button>
              {showDelete && (
                <DeleteModal company={company} onClose={() => setShowDelete(false)} />
              )}
            </section>
          )}
        </div>

        <div className="lg:col-span-3">
          <CompanyActivity companyId={company.id} />
        </div>
      </div>
    </div>
  );
}

function CompanyActivity({ companyId }: { companyId: string }) {
  const baseId = useId();
  const [tab, setTab] = useState<Tab>("Tickets");

  return (
    <section aria-label="Activity">
      <div role="tablist" aria-label="Company activity" className="mb-4 flex gap-1 border-b border-gray-200">
        {TABS.map((option) => (
          <button
            key={option}
            type="button"
            role="tab"
            id={`${baseId}-${option}`}
            aria-selected={tab === option}
            aria-controls={`${baseId}-panel`}
            onClick={() => setTab(option)}
            className={clsx(
              "rounded-t-lg px-4 py-2 text-sm font-medium transition-colors",
              tab === option
                ? "border-b-2 border-primary-500 text-primary-700"
                : "text-gray-500 hover:text-gray-700",
            )}
          >
            {option}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`${baseId}-panel`} aria-labelledby={`${baseId}-${tab}`}>
        {tab === "Tickets" ? (
          <TicketsTab companyId={companyId} />
        ) : (
          <PeopleTab companyId={companyId} />
        )}
      </div>
    </section>
  );
}

function TicketsTab({ companyId }: { companyId: string }) {
  const { data, isLoading, isFetching, refetch } = useCompanyTickets(companyId);

  if (isLoading) return <ListLoading label="Loading tickets" />;
  if (!data) {
    return (
      <ListError
        message="Could not load tickets."
        onRetry={() => void refetch()}
        isRetrying={isFetching}
      />
    );
  }
  if (data.length === 0) return <ListEmpty message="No tickets yet." />;
  return (
    <>
      <ul className="space-y-3">
        {data.map((ticket) => (
          <li key={ticket.id} className="rounded-lg border border-gray-200 bg-white p-4">
            <TicketLine ticket={ticket} />
          </li>
        ))}
      </ul>
      {data.length === TIMELINE_TICKETS_LIMIT && (
        <p className="mt-3 text-center text-xs text-gray-500">
          Showing the latest {TIMELINE_TICKETS_LIMIT}
        </p>
      )}
    </>
  );
}

function PeopleTab({ companyId }: { companyId: string }) {
  const { data, isLoading, isFetching, refetch } = useCompanyContacts(companyId);

  if (isLoading) return <ListLoading label="Loading people" />;
  if (!data) {
    return (
      <ListError
        message="Could not load people."
        onRetry={() => void refetch()}
        isRetrying={isFetching}
      />
    );
  }
  if (data.length === 0) return <ListEmpty message="No people yet." />;
  return (
    <>
      <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th scope="col" className={TH_CLASS}>Name</th>
              <th scope="col" className={TH_CLASS}>Email</th>
              <th scope="col" className={TH_CLASS}>Last seen</th>
              <th scope="col" className={TH_CLASS}>Open tickets</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {data.map((person) => (
              <tr key={person.id}>
                <td className="whitespace-nowrap px-6 py-4">
                  <div className="flex items-center gap-3">
                    <Avatar url={person.avatar_url} name={person.display_name} />
                    <Link
                      to={`/contacts/${person.id}`}
                      className="text-sm font-medium text-gray-900 hover:text-primary-700"
                    >
                      {person.display_name}
                    </Link>
                  </div>
                </td>
                <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-500">
                  {person.email && (
                    <div className="flex items-center gap-2">
                      <span>{person.email}</span>
                      {!person.email_verified && <UnverifiedBadge />}
                    </div>
                  )}
                </td>
                <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-500">
                  {formatDateTime(person.last_seen_at)}
                </td>
                <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-500">
                  {person.open_tickets_count}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {/* By name, unlike tickets: what's cut off isn't the oldest. */}
      {data.length === COMPANY_CONTACTS_LIMIT && (
        <p className="mt-3 text-center text-xs text-gray-500">
          Showing the first {COMPANY_CONTACTS_LIMIT}
        </p>
      )}
    </>
  );
}

function DeleteModal({ company, onClose }: { company: Company; onClose: () => void }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const deleteCompany = useDeleteCompany();

  const handleSubmit = async () => {
    try {
      await deleteCompany.mutateAsync(company.id);
      toast.success("Company deleted.");
      void navigate("/companies");
    } catch (error) {
      const { status, message } = parseApiError(error);
      if (status === 409) {
        toast.error(message ?? "This company could not be deleted. Try again.");
        void queryClient.invalidateQueries({ queryKey: ["company", company.id] });
        onClose();
      } else {
        toast.error("Failed to delete company.");
      }
    }
  };

  return (
    <FormModal
      title="Delete company"
      submitLabel="Delete"
      danger
      errors={NO_ERRORS}
      isSubmitting={deleteCompany.isPending}
      onClose={() => {
        if (!deleteCompany.isPending) onClose();
      }}
      onSubmit={() => void handleSubmit()}
    >
      <p className="text-sm text-gray-700">
        Delete <strong className="break-all">{company.name}</strong>?{" "}
        {company.contacts_count === 1
          ? "Its 1 contact stays, without a company."
          : `Its ${company.contacts_count} contacts stay, without a company.`}{" "}
        This can't be undone.
      </p>
    </FormModal>
  );
}
