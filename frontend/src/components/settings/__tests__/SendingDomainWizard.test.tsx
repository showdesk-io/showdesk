/**
 * Tests for the send-from-your-domain wizard. Only the API client is mocked: each step
 * renders from the domain row the API answers.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AxiosError, type AxiosResponse } from "axios";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "@/api/client";
import { useAuthStore } from "@/store/authStore";
import { useMailboxes } from "@/hooks/useMailboxes";
import type { Mailbox, OrganizationDomain } from "@/types";
import { SendingDomainWizard } from "../SendingDomainWizard";

vi.mock("@/api/client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("react-hot-toast", () => ({
  default: { success: vi.fn(), error: vi.fn() },
}));

const client = vi.mocked(apiClient);

const MAILBOX: Mailbox = {
  id: "m1",
  name: "Support",
  local_part: "acme-x7k2m9abcd",
  inbound_address: "acme-x7k2m9abcd@in.example.com",
  public_address: "support@acme.com",
  sends_from_public_address: false,
  default_team: null,
  is_active: true,
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-01T00:00:00Z",
};

const RECORDS = [
  // The organization's own proof, first whatever the provider.
  { type: "TXT", name: "_showdesk.acme.com", value: "showdesk-verification=tok" },
  { type: "TXT", name: "acme.com", value: "v=spf1 include:_spf.example.net ~all", merge: true },
  {
    type: "CNAME",
    name: "sd._domainkey.acme.com",
    value: "sd._domainkey.in.example.com",
  },
];

function domain(overrides: Partial<OrganizationDomain> = {}): OrganizationDomain {
  return {
    id: "d1",
    domain: "acme.com",
    is_branding: false,
    is_email_routing: false,
    is_sending: true,
    status: "verified",
    verification_method: "dns_txt",
    verification_token: "tok",
    verified_at: "2026-11-02T00:00:00Z",
    last_check_at: "2026-11-02T00:00:00Z",
    txt_record_name: "_showdesk-verify.acme.com",
    txt_record_value: "showdesk-verify=tok",
    sending_status: "",
    sending_dns_records: [],
    sending_requested_at: null,
    sending_last_checked_at: null,
    sending_last_error: "",
    created_at: "2026-11-01T00:00:00Z",
    updated_at: "2026-11-01T00:00:00Z",
    ...overrides,
  };
}

function refusal(data: unknown, status = 400): AxiosError {
  return new AxiosError("Request failed", "ERR_BAD_REQUEST", undefined, undefined, {
    status,
    data,
  } as AxiosResponse);
}

let domains: OrganizationDomain[];
let mailboxes: Mailbox[];
let userEmail: string;

/** The wizard on the mailbox as the API lists it, as in the Email tab. */
function ListedMailboxWizard() {
  const { data } = useMailboxes();
  return data?.[0] ? <SendingDomainWizard mailbox={data[0]} onClose={() => {}} /> : null;
}

async function renderWizard(mailbox: Mailbox | "listed" = MAILBOX) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return renderWizardWith(queryClient, mailbox);
}

async function renderWizardWith(queryClient: QueryClient, mailbox: Mailbox | "listed") {
  render(
    <QueryClientProvider client={queryClient}>
      {mailbox === "listed" ? (
        <ListedMailboxWizard />
      ) : (
        <SendingDomainWizard mailbox={mailbox} onClose={() => {}} />
      )}
    </QueryClientProvider>,
  );
  await screen.findByRole("region", { name: "1. Address and ownership" });
  return userEvent.setup();
}

function currentStep(): HTMLElement {
  const step = document.querySelector<HTMLElement>('[aria-current="step"]');
  if (!step) throw new Error("no current step");
  return step;
}

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  useAuthStore.setState({ isAuthenticated: true });
  domains = [];
  mailboxes = [MAILBOX];
  userEmail = "ann@acme.com";
  client.get.mockImplementation((url: string) => {
    if (url === "/organization-domains/") return Promise.resolve({ data: { results: domains } });
    if (url === "/mailboxes/") return Promise.resolve({ data: mailboxes });
    if (url === "/users/me/") return Promise.resolve({ data: { id: "u1", email: userEmail } });
    return Promise.reject(new Error(`unexpected ${url}`));
  });
});

describe("SendingDomainWizard", () => {
  it("offers to verify an unknown domain by DNS, or by email to an admin on it", async () => {
    const user = await renderWizard();
    client.post.mockResolvedValueOnce({ data: domain({ status: "pending" }) });

    expect(currentStep()).toHaveAccessibleName("1. Address and ownership");
    await screen.findByRole("button", { name: "Verify with my email" });
    await user.click(screen.getByRole("button", { name: "Verify with DNS" }));

    expect(client.post).toHaveBeenCalledWith("/organization-domains/", {
      domain: "acme.com",
      is_sending: true,
      is_branding: false,
      is_email_routing: false,
      verification_method: "dns_txt",
    });
  });

  it("lands keyboard users in the wizard when it opens", async () => {
    await renderWizard();

    expect(screen.getByRole("heading", { name: "Send from your domain" })).toHaveFocus();
  });

  it("keeps the address typed until it is saved, when opened again", async () => {
    domains = [domain({ domain: "acme.org", id: "d2", status: "pending", verified_at: null })];
    const user = await renderWizard();
    const field = screen.getByLabelText("Address to send from");
    await user.clear(field);
    await user.type(field, "help@acme.org");
    cleanup();

    // Opened again: the typed address, and so the pending domain's TXT record.
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    await renderWizardWith(queryClient, "listed");
    expect(screen.getByLabelText("Address to send from")).toHaveValue("help@acme.org");
    expect(await screen.findByText("_showdesk-verify.acme.com")).toBeInTheDocument();
    cleanup();

    // Once the mailbox has it, it is the mailbox's address that opens.
    sessionStorage.setItem("showdesk:sending-address:m1", "help@acme.org");
    mailboxes = [{ ...MAILBOX, public_address: "help@acme.org" }];
    await renderWizardWith(
      new QueryClient({ defaultOptions: { queries: { retry: false } } }),
      "listed",
    );
    expect(screen.getByLabelText("Address to send from")).toHaveValue("help@acme.org");
    await waitFor(() =>
      expect(sessionStorage.getItem("showdesk:sending-address:m1")).toBeNull(),
    );
  });

  it("doesn't offer email verification to an admin whose address is elsewhere", async () => {
    userEmail = "ann@other.org";
    await renderWizard();

    await waitFor(() => expect(client.get).toHaveBeenCalledWith("/users/me/"));
    expect(screen.getByRole("button", { name: "Verify with DNS" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Verify with my email" })).not.toBeInTheDocument();
  });

  it.each([
    ["a failed domain", domain({ status: "failed", verified_at: null })],
    ["a pending domain without a DNS challenge", domain({ status: "pending", verification_method: null, verification_token: "" })],
    ["a pending challenge whose token was cleared", domain({ status: "pending", verified_at: null, verification_token: "" })],
  ])("restarts the DNS challenge of %s rather than adding it again", async (_, row) => {
    domains = [row];
    const user = await renderWizard();
    client.post.mockResolvedValueOnce({ data: domain({ status: "pending" }) });

    await user.click(screen.getByRole("button", { name: "Verify with DNS" }));

    expect(client.post).toHaveBeenCalledWith("/organization-domains/d1/regenerate-token/");
    expect(client.post).not.toHaveBeenCalledWith("/organization-domains/", expect.anything());
  });

  it("stays on step 1 while the TXT record isn't found", async () => {
    domains = [domain({ status: "pending", verified_at: null })];
    const user = await renderWizard();
    client.post.mockResolvedValueOnce({
      status: 202,
      data: { detail: "Still pending.", code: "still_pending", domain: domains[0] },
    });

    await user.click(screen.getByRole("button", { name: "Check now" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "TXT record not found yet. DNS can take a few minutes to propagate.",
    );
    expect(currentStep()).toHaveAccessibleName("1. Address and ownership");
  });

  it("shows a pending domain's TXT record, and moves on to step 2 once verified", async () => {
    domains = [domain({ status: "pending", verified_at: null })];
    const user = await renderWizard();
    const writeText = vi.spyOn(navigator.clipboard, "writeText");

    expect(screen.getByText("_showdesk-verify.acme.com")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Copy the TXT record value" }));
    expect(writeText).toHaveBeenCalledWith("showdesk-verify=tok");

    domains = [domain()];
    client.post.mockResolvedValueOnce({ status: 200, data: domains[0] });
    await user.click(screen.getByRole("button", { name: "Check now" }));

    expect(client.post).toHaveBeenCalledWith(
      "/organization-domains/d1/verify/",
      {},
      expect.anything(),
    );
    await waitFor(() => expect(currentStep()).toHaveAccessibleName("2. DNS records"));
    expect(within(currentStep()).getByRole("button", { name: "Get the records" })).toBeInTheDocument();
  });

  it("saves the address before step 2, and shows a refusal under the field", async () => {
    domains = [domain({ domain: "acme.org", id: "d2" })];
    const user = await renderWizard();
    client.patch.mockRejectedValueOnce(
      refusal({ public_address: ["Another mailbox already uses this address."] }),
    );

    const field = screen.getByLabelText("Address to send from");
    await user.clear(field);
    await user.type(field, "help@acme.org");
    await user.click(screen.getByRole("button", { name: "Use this address" }));

    expect(client.patch).toHaveBeenCalledWith("/mailboxes/m1/", {
      public_address: "help@acme.org",
    });
    expect(
      await screen.findByText("Another mailbox already uses this address."),
    ).toBeInTheDocument();
    expect(currentStep()).toHaveAccessibleName("1. Address and ownership");
  });

  it("saves the address, then moves on to step 2 once the mailbox has it", async () => {
    domains = [domain({ domain: "acme.org", id: "d2" })];
    const user = await renderWizard("listed");
    client.patch.mockImplementationOnce(() => {
      mailboxes = [{ ...MAILBOX, public_address: "help@acme.org" }];
      return Promise.resolve({ data: mailboxes[0] });
    });

    const field = screen.getByLabelText("Address to send from");
    await user.clear(field);
    await user.type(field, "help@acme.org");
    await user.click(screen.getByRole("button", { name: "Use this address" }));

    await waitFor(() => expect(currentStep()).toHaveAccessibleName("2. DNS records"));
    expect(client.patch).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("heading", { name: "2. DNS records" })).toHaveFocus();
    expect(screen.queryByRole("button", { name: "Use this address" })).not.toBeInTheDocument();
  });

  it("warns before moving replies off a public address they go out from", async () => {
    domains = [domain({ domain: "acme.org", id: "d2" })];
    const user = await renderWizard({ ...MAILBOX, sends_from_public_address: true });
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false);

    const field = screen.getByLabelText("Address to send from");
    await user.clear(field);
    await user.type(field, "help@acme.org");
    await user.click(screen.getByRole("button", { name: "Use this address" }));

    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("acme-x7k2m9abcd@in.example.com"));
    expect(client.patch).not.toHaveBeenCalled();
  });

  it("gets the records, with a note on the one to merge and copy buttons", async () => {
    domains = [domain()];
    const user = await renderWizard();
    const writeText = vi.spyOn(navigator.clipboard, "writeText");
    domains = [domain({ sending_status: "pending", sending_dns_records: RECORDS })];
    client.post.mockResolvedValueOnce({ data: domains[0] });

    await user.click(screen.getByRole("button", { name: "Get the records" }));

    expect(client.post).toHaveBeenCalledWith("/organization-domains/d1/sending/");
    expect(await screen.findByText("sd._domainkey.in.example.com")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Already have an SPF record at acme.com? Add the include: part to it rather than adding a second record.",
      ),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/^Already have/)).toHaveLength(1);
    expect(
      screen.getByText("The first record proves your organization controls the domain."),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", {
        name: "Copy the value of the TXT record _showdesk.acme.com",
      }),
    );
    expect(writeText).toHaveBeenCalledWith("showdesk-verification=tok");
    await user.click(
      screen.getByRole("button", {
        name: "Copy the value of the CNAME record sd._domainkey.acme.com",
      }),
    );
    expect(writeText).toHaveBeenCalledWith("sd._domainkey.in.example.com");
    expect(currentStep()).toHaveAccessibleName("3. Status");
    expect(screen.getByRole("status")).toHaveTextContent("Sending from acme.com: Pending");
  });

  it("says the service gave no records yet when only the ownership one is there", async () => {
    const ownership = {
      type: "TXT",
      name: "_showdesk-verify.acme.com",
      value: "showdesk-verify=tok",
    };
    domains = [domain({ sending_status: "pending", sending_dns_records: [ownership] })];
    await renderWizard();

    expect(await screen.findByText("showdesk-verify=tok")).toBeInTheDocument();
    expect(
      screen.getByText("The sending service returned no records yet. Check again in a minute."),
    ).toBeInTheDocument();
  });

  it("shows what the API says when it refuses", async () => {
    domains = [domain()];
    const user = await renderWizard();
    client.post.mockRejectedValueOnce(
      refusal(
        {
          detail: "acme.com's previous sending setup is still being removed.",
          code: "removal_pending",
        },
        409,
      ),
    );

    await user.click(screen.getByRole("button", { name: "Get the records" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "acme.com's previous sending setup is still being removed.",
    );
  });

  it.each([
    [
      "pending, without an error",
      domain({ sending_status: "pending", sending_dns_records: RECORDS }),
      "Checked: still pending. We couldn't reach the DNS or the sending service this time; we'll keep trying.",
    ],
    [
      "pending, with an error",
      domain({
        sending_status: "pending",
        sending_dns_records: RECORDS,
        sending_last_error: "DKIM record not found.",
      }),
      "Checked: still pending.",
    ],
    [
      "verified",
      domain({ sending_status: "verified", sending_dns_records: RECORDS }),
      "Checked: still verified.",
    ],
  ])("says what a check found when it changed nothing: %s", async (_, row, note) => {
    domains = [row];
    const user = await renderWizard();
    client.post.mockResolvedValueOnce({ data: row });

    await user.click(screen.getByRole("button", { name: "Check now" }));

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(note));
    if (note === "Checked: still pending.") {
      expect(screen.getByRole("status")).not.toHaveTextContent("couldn't reach");
    }
  });

  it("says nothing more when a check changed the status", async () => {
    domains = [domain({ sending_status: "pending", sending_dns_records: RECORDS })];
    const user = await renderWizard();
    domains = [domain({ sending_status: "verified", sending_dns_records: RECORDS })];
    client.post.mockResolvedValueOnce({ data: domains[0] });

    await user.click(screen.getByRole("button", { name: "Check now" }));

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Verified"));
    expect(screen.getByRole("status")).not.toHaveTextContent("Checked");
  });

  it("shows why sending failed, and sets it up again", async () => {
    domains = [
      domain({
        sending_status: "failed",
        sending_dns_records: RECORDS,
        sending_last_error: "DKIM record not found.",
      }),
    ];
    const user = await renderWizard();
    client.post.mockResolvedValueOnce({ data: domain({ sending_status: "pending" }) });

    expect(screen.getByText("Last error: DKIM record not found.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Set up again" }));

    expect(client.post).toHaveBeenCalledWith("/organization-domains/d1/sending/");
  });

  it("shows a verified domain's status, checks it, and stops sending once confirmed", async () => {
    domains = [
      domain({
        sending_status: "verified",
        sending_dns_records: RECORDS,
        sending_last_checked_at: "2026-11-03T00:00:00Z",
      }),
    ];
    const user = await renderWizard({ ...MAILBOX, sends_from_public_address: true });
    client.post.mockRejectedValueOnce(
      refusal({ detail: "This domain was checked a moment ago.", code: "too_soon" }, 429),
    );

    expect(screen.getByRole("status")).toHaveTextContent("Verified");
    expect(screen.getByText(/^Last checked/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Check now" }));
    expect(client.post).toHaveBeenCalledWith("/organization-domains/d1/sending/check/");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This domain was checked a moment ago.",
    );

    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false);
    await user.click(screen.getByRole("button", { name: "Stop sending from this domain" }));
    expect(client.delete).not.toHaveBeenCalled();

    confirm.mockReturnValueOnce(true);
    domains = [domain()];
    client.delete.mockResolvedValueOnce({ data: domains[0] });
    await user.click(screen.getByRole("button", { name: "Stop sending from this domain" }));
    expect(client.delete).toHaveBeenCalledWith("/organization-domains/d1/sending/");
    await waitFor(() => expect(currentStep()).toHaveAccessibleName("2. DNS records"));
  });
});
