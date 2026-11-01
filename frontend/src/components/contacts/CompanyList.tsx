/**
 * The companies of the organization: search, table, pagination and "Add company".
 */

import { useState } from "react";
import { Link, useNavigate } from "react-router";
import toast from "react-hot-toast";
import { parseApiError } from "@/api/errors";
import { useCompanies, useCreateCompany } from "@/hooks/useCompanies";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useFilterPage } from "@/hooks/useFilterPage";
import type { Company } from "@/types";
import { FormField, FormModal } from "./FormModal";
import { NO_ERRORS, readFormErrors, type FormErrors } from "./formErrors";
import {
  Avatar,
  ListEmpty,
  ListError,
  ListHeader,
  ListLoading,
  Pagination,
  SearchInput,
  TH_CLASS,
} from "./ListParts";

const SEARCH_DEBOUNCE_MS = 300;
const FORM_FIELDS = ["name", "domain", "plan"] as const;

export function CompanyList() {
  const [searchInput, setSearchInput] = useState("");
  const search = useDebouncedValue(searchInput.trim(), SEARCH_DEBOUNCE_MS);
  const [pageSize, setPageSize] = useState(25);
  const [page, setPage] = useFilterPage(JSON.stringify({ search, pageSize }));
  const [showAdd, setShowAdd] = useState(false);

  const { data, isLoading, isError, error, isFetching, refetch } = useCompanies({
    search: search || undefined,
    page,
    page_size: pageSize,
  });

  // The list shrank since: that page is a 404 now, and asking for it again won't help.
  if (isError && page > 1 && parseApiError(error).status === 404) {
    setPage(1);
  }

  return (
    <div className="flex h-full flex-col">
      <ListHeader
        title="Companies"
        countLabel={data ? `${data.count} ${data.count === 1 ? "company" : "companies"}` : null}
        addLabel="Add company"
        onAdd={() => setShowAdd(true)}
      >
        <SearchInput label="Search companies" value={searchInput} onChange={setSearchInput} />
      </ListHeader>

      <div className="flex-1 overflow-auto bg-white">
        {isLoading ? (
          <ListLoading label="Loading companies" />
        ) : isError ? (
          <ListError
            message="Could not load companies."
            onRetry={() => void refetch()}
            isRetrying={isFetching}
          />
        ) : !data || data.results.length === 0 ? (
          <ListEmpty message="No companies found." />
        ) : (
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th scope="col" className={TH_CLASS}>Name</th>
                <th scope="col" className={TH_CLASS}>Domain</th>
                <th scope="col" className={TH_CLASS}>Contacts</th>
                <th scope="col" className={TH_CLASS}>Open tickets</th>
                <th scope="col" className={TH_CLASS}>Plan</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {data.results.map((company) => (
                <CompanyRow key={company.id} company={company} />
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

      {showAdd && <AddCompanyModal onClose={() => setShowAdd(false)} />}
    </div>
  );
}

function CompanyRow({ company }: { company: Company }) {
  const navigate = useNavigate();

  return (
    <tr
      className="cursor-pointer hover:bg-gray-50"
      onClick={() => navigate(`/companies/${company.id}`)}
    >
      <td className="whitespace-nowrap px-6 py-4">
        <div className="flex items-center gap-3">
          <Avatar url={company.logo_url} name={company.name} square />
          <Link
            to={`/companies/${company.id}`}
            onClick={(e) => e.stopPropagation()}
            className="text-sm font-medium text-gray-900 hover:text-primary-700"
          >
            {company.name}
          </Link>
        </div>
      </td>
      <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-500">{company.domain}</td>
      <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-500">{company.contacts_count}</td>
      <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-500">{company.open_tickets_count}</td>
      <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-500">{company.plan}</td>
    </tr>
  );
}

function AddCompanyModal({ onClose }: { onClose: () => void }) {
  const createCompany = useCreateCompany();
  const [name, setName] = useState("");
  const [domain, setDomain] = useState("");
  const [plan, setPlan] = useState("");
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS);

  const handleSubmit = () => {
    if (!name.trim()) {
      setErrors({ fields: {}, general: ["A company needs a name."] });
      return;
    }
    setErrors(NO_ERRORS);
    const optional = { domain: domain.trim(), plan: plan.trim() };
    createCompany.mutate(
      {
        name: name.trim(),
        ...Object.fromEntries(Object.entries(optional).filter(([, value]) => value)),
      },
      {
        onSuccess: () => {
          toast.success("Company added.");
          onClose();
        },
        onError: (error) => {
          const shown = readFormErrors(error, FORM_FIELDS);
          if (shown) setErrors(shown);
          else toast.error("Failed to add company.");
        },
      },
    );
  };

  return (
    <FormModal
      title="Add company"
      errors={errors}
      isSubmitting={createCompany.isPending}
      onClose={onClose}
      onSubmit={handleSubmit}
    >
      <FormField label="Name" value={name} onChange={setName} errors={errors.fields.name} autoFocus />
      <FormField label="Domain" value={domain} onChange={setDomain} errors={errors.fields.domain} />
      <FormField label="Plan" value={plan} onChange={setPlan} errors={errors.fields.plan} />
    </FormModal>
  );
}
