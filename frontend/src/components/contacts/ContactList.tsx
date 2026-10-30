/**
 * The contacts of the organization: filters, table, pagination and "Add contact".
 */

import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { formatDistanceToNow } from "date-fns";
import toast from "react-hot-toast";
import { parseApiError } from "@/api/errors";
import { useAttributeDefs } from "@/hooks/useAttributeDefs";
import { useCompanies } from "@/hooks/useCompanies";
import { useContacts, useCreateContact } from "@/hooks/useContacts";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useFilterPage } from "@/hooks/useFilterPage";
import type { AttributeDef, Contact } from "@/types";
import { FormField, FormModal } from "./FormModal";
import { NO_ERRORS, readFormErrors, type FormErrors } from "./formErrors";
import {
  Avatar,
  FILTER_SELECT_CLASS,
  ListEmpty,
  ListError,
  ListHeader,
  ListLoading,
  Pagination,
  SearchInput,
  TH_CLASS,
} from "./ListParts";
import { UnverifiedBadge } from "./UnverifiedBadge";

const SEARCH_DEBOUNCE_MS = 300;
const FORM_FIELDS = ["name", "email", "phone"] as const;

export function ContactList() {
  const [searchInput, setSearchInput] = useState("");
  const search = useDebouncedValue(searchInput.trim(), SEARCH_DEBOUNCE_MS);
  const [company, setCompany] = useState("");
  const [verifiedOnly, setVerifiedOnly] = useState(false);
  const [attrs, setAttrs] = useState<Record<string, string>>({});
  const [pageSize, setPageSize] = useState(25);
  const [page, setPage] = useFilterPage(
    JSON.stringify({ search, company, verifiedOnly, attrs, pageSize }),
  );
  const [showAdd, setShowAdd] = useState(false);

  const { data: companies } = useCompanies({ page_size: 100 });
  const { data: attributeDefs } = useAttributeDefs("contact");
  const filterDefs = (attributeDefs ?? []).filter(
    (def) => !def.is_archived && (def.type === "enum" || def.type === "boolean"),
  );

  const { data, isLoading, isError, error, isFetching, refetch } = useContacts({
    search: search || undefined,
    company: company || undefined,
    email_verified: verifiedOnly || undefined,
    attrs,
    page,
    page_size: pageSize,
  });

  // The list shrank since: that page is a 404 now, and asking for it again won't help.
  if (isError && page > 1 && parseApiError(error).status === 404) {
    setPage(1);
  }

  const setAttr = (key: string, value: string) => {
    const next = { ...attrs, [key]: value };
    if (!value) delete next[key];
    setAttrs(next);
  };

  return (
    <div className="flex h-full flex-col">
      <ListHeader
        title="Contacts"
        countLabel={data ? `${data.count} ${data.count === 1 ? "contact" : "contacts"}` : null}
        addLabel="Add contact"
        onAdd={() => setShowAdd(true)}
      >
        <SearchInput label="Search contacts" value={searchInput} onChange={setSearchInput} />
        <select
          aria-label="Company"
          value={company}
          onChange={(e) => setCompany(e.target.value)}
          className={FILTER_SELECT_CLASS}
        >
          <option value="">All Companies</option>
          {companies?.results.map((option) => (
            <option key={option.id} value={option.id}>
              {option.name}
            </option>
          ))}
        </select>
        {filterDefs.map((def) => (
          <AttributeFilter
            key={def.id}
            def={def}
            value={attrs[def.key] ?? ""}
            onChange={(value) => setAttr(def.key, value)}
          />
        ))}
        <label className="flex items-center gap-2 text-sm text-gray-600">
          <input
            type="checkbox"
            checked={verifiedOnly}
            onChange={(e) => setVerifiedOnly(e.target.checked)}
            className="rounded-sm border-gray-300"
          />
          Verified email only
        </label>
      </ListHeader>

      <div className="flex-1 overflow-auto bg-white">
        {isLoading ? (
          <ListLoading label="Loading contacts" />
        ) : isError ? (
          <ListError
            message="Could not load contacts."
            onRetry={() => void refetch()}
            isRetrying={isFetching}
          />
        ) : !data || data.results.length === 0 ? (
          <ListEmpty message="No contacts found." />
        ) : (
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th scope="col" className={TH_CLASS}>Name</th>
                <th scope="col" className={TH_CLASS}>Email</th>
                <th scope="col" className={TH_CLASS}>Company</th>
                <th scope="col" className={TH_CLASS}>Last seen</th>
                <th scope="col" className={TH_CLASS}>Open tickets</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {data.results.map((contact) => (
                <ContactRow key={contact.id} contact={contact} />
              ))}
            </tbody>
          </table>
        )}
      </div>

      {data && data.count > 0 && !isLoading && !isError && (
        <Pagination
          count={data.count}
          page={page}
          pageSize={pageSize}
          onPageChange={setPage}
          onPageSizeChange={setPageSize}
        />
      )}

      {showAdd && <AddContactModal onClose={() => setShowAdd(false)} />}
    </div>
  );
}

function AttributeFilter({
  def,
  value,
  onChange,
}: {
  def: AttributeDef;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <select
      aria-label={def.label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={FILTER_SELECT_CLASS}
    >
      <option value="">Any {def.label}</option>
      {def.type === "boolean" ? (
        <>
          <option value="true">Yes</option>
          <option value="false">No</option>
        </>
      ) : (
        def.options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))
      )}
    </select>
  );
}

function ContactRow({ contact }: { contact: Contact }) {
  const navigate = useNavigate();
  const anonymized = contact.is_anonymized;
  const hasProvenEmail = Boolean(contact.email && contact.email_verified);
  const declaredEmail =
    !hasProvenEmail && contact.declared_email !== contact.email
      ? contact.declared_email
      : "";

  return (
    <tr
      aria-disabled={anonymized || undefined}
      className={anonymized ? "bg-gray-50" : "cursor-pointer hover:bg-gray-50"}
      onClick={anonymized ? undefined : () => navigate(`/contacts/${contact.id}`)}
    >
      <td className="whitespace-nowrap px-6 py-4">
        <div className="flex items-center gap-3">
          <Avatar url={contact.avatar_url} name={contact.display_name} />
          {anonymized ? (
            <>
              <span className="text-sm font-medium text-gray-500">{contact.display_name}</span>
              <span className="inline-flex items-center rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
                Anonymized
              </span>
            </>
          ) : (
            <Link
              to={`/contacts/${contact.id}`}
              onClick={(e) => e.stopPropagation()}
              className="text-sm font-medium text-gray-900 hover:text-primary-700"
            >
              {contact.display_name}
            </Link>
          )}
        </div>
      </td>
      <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-500">
        {contact.email && (
          <div className="flex items-center gap-2">
            <span>{contact.email}</span>
            {!contact.email_verified && <UnverifiedBadge />}
          </div>
        )}
        {declaredEmail && (
          <div className="flex items-center gap-2">
            <span>{declaredEmail}</span>
            <UnverifiedBadge />
          </div>
        )}
      </td>
      <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-500">
        {contact.company_detail?.name}
      </td>
      <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-500">
        {contact.last_seen_at &&
          formatDistanceToNow(new Date(contact.last_seen_at), { addSuffix: true })}
      </td>
      <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-500">
        {contact.open_tickets_count}
      </td>
    </tr>
  );
}

function AddContactModal({ onClose }: { onClose: () => void }) {
  const createContact = useCreateContact();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS);

  const handleSubmit = () => {
    const values = { name: name.trim(), email: email.trim(), phone: phone.trim() };
    if (!values.name && !values.email && !values.phone) {
      setErrors({
        fields: {},
        general: ["A contact needs a name, an email or a phone number."],
      });
      return;
    }
    setErrors(NO_ERRORS);
    createContact.mutate(
      Object.fromEntries(Object.entries(values).filter(([, value]) => value)),
      {
        onSuccess: () => {
          toast.success("Contact added.");
          onClose();
        },
        onError: (error) => {
          const shown = readFormErrors(error, FORM_FIELDS);
          if (shown) setErrors(shown);
          else toast.error("Failed to add contact.");
        },
      },
    );
  };

  return (
    <FormModal
      title="Add contact"
      errors={errors}
      isSubmitting={createContact.isPending}
      onClose={onClose}
      onSubmit={handleSubmit}
    >
      <FormField label="Name" value={name} onChange={setName} errors={errors.fields.name} autoFocus />
      <FormField label="Email" type="email" value={email} onChange={setEmail} errors={errors.fields.email} />
      <FormField label="Phone" type="tel" value={phone} onChange={setPhone} errors={errors.fields.phone} />
    </FormModal>
  );
}
