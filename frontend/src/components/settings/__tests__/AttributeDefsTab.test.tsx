/**
 * Tests for the custom attributes settings tab. Only the API client is mocked, so hooks and
 * payloads are the real ones.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AxiosError, type AxiosResponse } from "axios";
import toast from "react-hot-toast";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "@/api/client";
import type { AttributeDef, AttributeDefEntity } from "@/types";
import { AttributeDefsTab } from "../AttributeDefsTab";
import { parseOptions, suggestAttributeKey, validateAttributeKey } from "../attributeDefForm";

vi.mock("@/api/client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
}));
vi.mock("react-hot-toast", () => ({
  default: { success: vi.fn(), error: vi.fn() },
}));

const client = vi.mocked(apiClient);

function def(overrides: Partial<AttributeDef> = {}): AttributeDef {
  return {
    id: overrides.key ?? "plan",
    key: "plan",
    label: "Plan",
    type: "string",
    description: "",
    options: [],
    is_archived: false,
    position: 0,
    ...overrides,
  };
}

const manyDefs = (count: number) =>
  Array.from({ length: count }, (_, index) =>
    def({ key: `attr_${index}`, label: `Attribute ${index}`, position: index }),
  );

function refusal(data: unknown): AxiosError {
  return new AxiosError("Request failed", "ERR_BAD_REQUEST", undefined, undefined, {
    status: 400,
    data,
  } as AxiosResponse);
}

let defs: AttributeDef[];

async function renderTab({
  entity = "contact",
  isAdmin = true,
}: { entity?: AttributeDefEntity; isAdmin?: boolean } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <AttributeDefsTab entity={entity} isAdmin={isAdmin} />
    </QueryClientProvider>,
  );
  await screen.findByText(/\/ 50$/);
  return userEvent.setup();
}

const openForm = (user: ReturnType<typeof userEvent.setup>) =>
  user.click(screen.getByRole("button", { name: /New attribute/ }));

const row = (label: string) => screen.getByText(label).closest("tr") as HTMLElement;

beforeEach(() => {
  vi.clearAllMocks();
  defs = [];
  client.get.mockImplementation(() => Promise.resolve({ data: defs }));
  client.post.mockImplementation((_url, data) =>
    Promise.resolve({ data: def(data as Partial<AttributeDef>) }),
  );
  client.patch.mockResolvedValue({ data: def() });
});

describe("suggestAttributeKey", () => {
  it.each([
    ["Plan", "plan"],
    ["Plan annuel", "plan_annuel"],
    ["Été à Paris", "ete_a_paris"],
    ["  --Hello, World!--  ", "hello_world"],
    ["a  &  b", "a_b"],
    ["2024 budget", "attr_2024_budget"],
    ["日本語", ""],
    ["", ""],
  ])("turns %j into %j", (label, key) => {
    expect(suggestAttributeKey(label)).toBe(key);
  });

  it("gives a key the API accepts from a long label", () => {
    const key = suggestAttributeKey(`${"a".repeat(63)} b`);

    expect(key).toBe("a".repeat(63));
    expect(validateAttributeKey(suggestAttributeKey(`9${"a".repeat(80)}`))).toBeNull();
  });
});

describe("validateAttributeKey", () => {
  it.each(["a", "plan", "plan_2", "plan_", "a".repeat(64)])("accepts %j", (key) => {
    expect(validateAttributeKey(key)).toBeNull();
  });

  it.each(["", "Plan", "2plan", "_plan", "pl an", " plan", "plan\n", "a__b", "é", "a".repeat(65)])(
    "refuses %j",
    (key) => {
      expect(validateAttributeKey(key)).not.toBeNull();
    },
  );
});

describe("parseOptions", () => {
  it("trims, drops the empty ones and keeps one of each, in order", () => {
    expect(parseOptions(" free, pro ,, free,  ,enterprise,")).toEqual([
      "free",
      "pro",
      "enterprise",
    ]);
  });
});

describe("AttributeDefsTab", () => {
  it("reads the definitions of its entity", async () => {
    defs = [def()];
    await renderTab({ entity: "company" });

    expect(client.get).toHaveBeenCalledWith("/company-attributes/");
    expect(screen.getByRole("heading", { name: "Company attributes" })).toBeInTheDocument();
  });

  it("lists label, key, type, options and state", async () => {
    defs = [
      def({
        key: "tier",
        label: "Tier",
        type: "enum",
        options: ["free", "pro"],
        description: "What they pay for",
      }),
      def({ key: "old", label: "Old", is_archived: true }),
    ];
    await renderTab();

    const tier = within(row("Tier"));
    expect(tier.getByText("tier")).toBeInTheDocument();
    expect(tier.getByText("List")).toBeInTheDocument();
    expect(tier.getByText("free, pro")).toBeInTheDocument();
    expect(tier.getByText("What they pay for")).toBeInTheDocument();
    expect(within(row("Old")).getByText("Archived")).toBeInTheDocument();
  });

  it("says when there's nothing", async () => {
    await renderTab();
    expect(screen.getByText(/No attributes yet/)).toBeInTheDocument();
  });

  it("doesn't take a failed read for an empty list", async () => {
    client.get.mockRejectedValue(new Error("nope"));
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <AttributeDefsTab entity="contact" isAdmin />
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(/Could not load/);
    expect(screen.queryByText(/No attributes yet/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /New attribute/ })).not.toBeInTheDocument();
  });

  describe("as an agent", () => {
    it("shows the table with no form or toggle", async () => {
      defs = [def(), def({ key: "old", label: "Old", is_archived: true })];
      await renderTab({ isAdmin: false });

      expect(screen.getByText("Plan")).toBeInTheDocument();
      expect(screen.getByText("Archived")).toBeInTheDocument();
      expect(screen.queryByRole("button")).not.toBeInTheDocument();
      expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    });
  });

  describe("counter", () => {
    it("counts only the attributes not archived", async () => {
      defs = [def(), def({ key: "b", label: "B" }), def({ key: "c", label: "C", is_archived: true })];
      await renderTab();

      expect(screen.getByText("2 / 50")).toBeInTheDocument();
    });

    it("closes creation at 50", async () => {
      defs = manyDefs(50);
      await renderTab();

      expect(screen.getByText("50 / 50")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /New attribute/ })).toBeDisabled();
      expect(screen.getByText(/Archive one first/)).toBeInTheDocument();
    });

    it("keeps creation open at 50 with an archived one more", async () => {
      defs = [...manyDefs(49), def({ key: "old", label: "Old", is_archived: true })];
      await renderTab();

      expect(screen.getByRole("button", { name: /New attribute/ })).toBeEnabled();
    });
  });

  describe("creating", () => {
    it("disables an open form when the limit is reached, and lets it close", async () => {
      const archived = def({ key: "old", label: "Old", is_archived: true });
      defs = [...manyDefs(49), archived];
      const user = await renderTab();
      await openForm(user);

      defs = [...manyDefs(49), { ...archived, is_archived: false }];
      await user.click(within(row("Old")).getByRole("button", { name: "Unarchive" }));

      expect(await screen.findByText("50 / 50")).toBeInTheDocument();
      expect(screen.getByLabelText("Label")).toBeDisabled();
      expect(screen.getByRole("button", { name: "Create" })).toBeDisabled();
      await user.click(screen.getByRole("button", { name: "Cancel" }));
      expect(screen.queryByLabelText("Label")).not.toBeInTheDocument();
    });

    it("suggests the key from the label until it's edited", async () => {
      const user = await renderTab();
      await openForm(user);

      await user.type(screen.getByLabelText("Label"), "Été 2");
      expect(screen.getByLabelText("Key")).toHaveValue("ete_2");

      await user.clear(screen.getByLabelText("Key"));
      await user.type(screen.getByLabelText("Key"), "season");
      await user.type(screen.getByLabelText("Label"), "3");
      expect(screen.getByLabelText("Key")).toHaveValue("season");
    });

    it("sends what was entered, after the existing ones", async () => {
      defs = [def({ position: 4 }), def({ key: "b", label: "B", position: 2, is_archived: true })];
      const user = await renderTab({ entity: "company" });
      await openForm(user);

      await user.type(screen.getByLabelText("Label"), "Seats");
      await user.selectOptions(screen.getByLabelText("Type"), "number");
      await user.type(screen.getByLabelText("Description"), "How many");
      await user.click(screen.getByRole("button", { name: "Create" }));

      await waitFor(() => {
        expect(client.post).toHaveBeenCalledWith("/company-attributes/", {
          key: "seats",
          label: "Seats",
          type: "number",
          description: "How many",
          position: 5,
        });
      });
      await waitFor(() => expect(screen.queryByLabelText("Label")).not.toBeInTheDocument());
      expect(toast.success).toHaveBeenCalled();
    });

    it("refuses an invalid key without asking the API", async () => {
      const user = await renderTab();
      await openForm(user);

      await user.type(screen.getByLabelText("Label"), "Plan");
      await user.clear(screen.getByLabelText("Key"));
      await user.type(screen.getByLabelText("Key"), "a__b");
      await user.click(screen.getByRole("button", { name: "Create" }));

      expect(await screen.findByText(/single underscores/)).toBeInTheDocument();
      expect(client.post).not.toHaveBeenCalled();
    });

    it("requires a label", async () => {
      const user = await renderTab();
      await openForm(user);

      await user.type(screen.getByLabelText("Key"), "plan");
      await user.click(screen.getByRole("button", { name: "Create" }));

      expect(await screen.findByText("A label is required.")).toBeInTheDocument();
      expect(client.post).not.toHaveBeenCalled();
    });

    it("asks for options on a list only, and requires them", async () => {
      const user = await renderTab();
      await openForm(user);
      expect(screen.queryByLabelText("Options")).not.toBeInTheDocument();

      await user.type(screen.getByLabelText("Label"), "Tier");
      await user.selectOptions(screen.getByLabelText("Type"), "enum");
      await user.type(screen.getByLabelText("Options"), " , ,");
      await user.click(screen.getByRole("button", { name: "Create" }));

      expect(await screen.findByText(/at least one option/)).toBeInTheDocument();
      expect(client.post).not.toHaveBeenCalled();
    });

    it("sends the options cleaned", async () => {
      const user = await renderTab();
      await openForm(user);

      await user.type(screen.getByLabelText("Label"), "Tier");
      await user.selectOptions(screen.getByLabelText("Type"), "enum");
      await user.type(screen.getByLabelText("Options"), "free, pro ,free,,");
      await user.click(screen.getByRole("button", { name: "Create" }));

      await waitFor(() => {
        expect(client.post).toHaveBeenCalledWith(
          "/contact-attributes/",
          expect.objectContaining({ type: "enum", options: ["free", "pro"] }),
        );
      });
    });

    it("sends no options once the type is no longer a list", async () => {
      const user = await renderTab();
      await openForm(user);

      await user.type(screen.getByLabelText("Label"), "Tier");
      await user.selectOptions(screen.getByLabelText("Type"), "enum");
      await user.type(screen.getByLabelText("Options"), "free");
      await user.selectOptions(screen.getByLabelText("Type"), "string");
      await user.click(screen.getByRole("button", { name: "Create" }));

      await waitFor(() => expect(client.post).toHaveBeenCalled());
      expect(client.post.mock.calls[0]?.[1]).not.toHaveProperty("options");
    });

    it("shows the API's refusal on its field and stays open", async () => {
      client.post.mockRejectedValue(refusal({ key: ["Another attribute already uses this key."] }));
      const user = await renderTab();
      await openForm(user);

      await user.type(screen.getByLabelText("Label"), "Plan");
      await user.click(screen.getByRole("button", { name: "Create" }));

      expect(await screen.findByText("Another attribute already uses this key.")).toBeInTheDocument();
      expect(screen.getByLabelText("Key")).toHaveAttribute("aria-invalid", "true");
      expect(screen.getByLabelText("Label")).toHaveValue("Plan");
    });

    it("shows a refusal about no field in the form", async () => {
      client.post.mockRejectedValue(
        refusal({ non_field_errors: ["At most 50 attributes can be active. Archive one first."] }),
      );
      const user = await renderTab();
      await openForm(user);

      await user.type(screen.getByLabelText("Label"), "Plan");
      await user.click(screen.getByRole("button", { name: "Create" }));

      expect(await screen.findByRole("alert")).toHaveTextContent(/At most 50/);
    });

    it("tells of a failure the API didn't explain", async () => {
      client.post.mockRejectedValue(new Error("network"));
      const user = await renderTab();
      await openForm(user);

      await user.type(screen.getByLabelText("Label"), "Plan");
      await user.click(screen.getByRole("button", { name: "Create" }));

      await waitFor(() => expect(toast.error).toHaveBeenCalled());
    });
  });

  describe("editing", () => {
    const editRow = (user: ReturnType<typeof userEvent.setup>, label: string) =>
      user.click(within(row(label)).getByRole("button", { name: "Edit" }));

    it("shows key and type read-only", async () => {
      defs = [def({ key: "tier", label: "Tier", type: "enum", options: ["free"] })];
      const user = await renderTab();
      await editRow(user, "Tier");

      expect(screen.queryByLabelText("Key")).not.toBeInTheDocument();
      expect(screen.queryByLabelText("Type")).not.toBeInTheDocument();
      expect(screen.getByLabelText("Label")).toHaveValue("Tier");
    });

    it("doesn't suggest a key from a new label", async () => {
      defs = [def()];
      const user = await renderTab();
      await editRow(user, "Plan");

      await user.clear(screen.getByLabelText("Label"));
      await user.type(screen.getByLabelText("Label"), "Offer");
      await user.click(screen.getByRole("button", { name: "Save" }));

      await waitFor(() => {
        expect(client.patch).toHaveBeenCalledWith("/contact-attributes/plan/", { label: "Offer" });
      });
    });

    it("sends the description alone when only it changed", async () => {
      defs = [def()];
      const user = await renderTab();
      await editRow(user, "Plan");

      await user.type(screen.getByLabelText("Description"), "Their plan");
      await user.click(screen.getByRole("button", { name: "Save" }));

      await waitFor(() => {
        expect(client.patch).toHaveBeenCalledWith("/contact-attributes/plan/", {
          description: "Their plan",
        });
      });
    });

    it("edits a list's options, with a note about stored values", async () => {
      defs = [def({ key: "tier", label: "Tier", type: "enum", options: ["free", "pro"] })];
      const user = await renderTab();
      await editRow(user, "Tier");

      expect(screen.getByText(/doesn't change stored values/)).toBeInTheDocument();
      const options = screen.getByLabelText("Options");
      expect(options).toHaveValue("free, pro");
      await user.clear(options);
      await user.type(options, "pro, team");
      await user.click(screen.getByRole("button", { name: "Save" }));

      await waitFor(() => {
        expect(client.patch).toHaveBeenCalledWith("/contact-attributes/tier/", {
          options: ["pro", "team"],
        });
      });
    });

    it("requires a list to keep an option", async () => {
      defs = [def({ key: "tier", label: "Tier", type: "enum", options: ["free"] })];
      const user = await renderTab();
      await editRow(user, "Tier");

      await user.clear(screen.getByLabelText("Options"));
      await user.click(screen.getByRole("button", { name: "Save" }));

      expect(await screen.findByText(/at least one option/)).toBeInTheDocument();
      expect(client.patch).not.toHaveBeenCalled();
    });

    it("doesn't split an untouched option holding a comma", async () => {
      defs = [def({ key: "tier", label: "Tier", type: "enum", options: ["a, b", "c"] })];
      const user = await renderTab();
      await editRow(user, "Tier");

      await user.type(screen.getByLabelText("Label"), "!");
      await user.click(screen.getByRole("button", { name: "Save" }));

      await waitFor(() => {
        expect(client.patch).toHaveBeenCalledWith("/contact-attributes/tier/", { label: "Tier!" });
      });
    });

    it("has no options field for another type", async () => {
      defs = [def()];
      const user = await renderTab();
      await editRow(user, "Plan");

      expect(screen.queryByLabelText("Options")).not.toBeInTheDocument();
    });

    it("sends nothing when nothing changed", async () => {
      defs = [def()];
      const user = await renderTab();
      await editRow(user, "Plan");

      await user.click(screen.getByRole("button", { name: "Save" }));

      await waitFor(() => expect(screen.queryByLabelText("Label")).not.toBeInTheDocument());
      expect(client.patch).not.toHaveBeenCalled();
    });

    it("stays possible at 50", async () => {
      defs = manyDefs(50);
      const user = await renderTab();
      await editRow(user, "Attribute 3");

      expect(screen.getByLabelText("Label")).toBeEnabled();
      expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
    });

    it("shows the API's refusal on its field", async () => {
      defs = [def({ key: "tier", label: "Tier", type: "enum", options: ["free"] })];
      client.patch.mockRejectedValue(refusal({ options: ["The options have to be unique."] }));
      const user = await renderTab();
      await editRow(user, "Tier");

      await user.type(screen.getByLabelText("Options"), ", pro");
      await user.click(screen.getByRole("button", { name: "Save" }));

      expect(await screen.findByText("The options have to be unique.")).toBeInTheDocument();
    });
  });

  describe("archiving", () => {
    it("archives and unarchives", async () => {
      defs = [def(), def({ key: "old", label: "Old", is_archived: true })];
      const user = await renderTab();

      await user.click(within(row("Plan")).getByRole("button", { name: "Archive" }));
      await waitFor(() => {
        expect(client.patch).toHaveBeenCalledWith("/contact-attributes/plan/", { is_archived: true });
      });

      await user.click(within(row("Old")).getByRole("button", { name: "Unarchive" }));
      await waitFor(() => {
        expect(client.patch).toHaveBeenCalledWith("/contact-attributes/old/", { is_archived: false });
      });
    });

    it("can't unarchive at 50", async () => {
      defs = [...manyDefs(50), def({ key: "old", label: "Old", is_archived: true })];
      await renderTab();

      expect(within(row("Old")).getByRole("button", { name: "Unarchive" })).toBeDisabled();
      expect(within(row("Attribute 0")).getByRole("button", { name: "Archive" })).toBeEnabled();
    });

    it("shows why the API refused", async () => {
      defs = [def({ key: "old", label: "Old", is_archived: true })];
      client.patch.mockRejectedValue(
        refusal({ non_field_errors: ["At most 50 attributes can be active. Archive one first."] }),
      );
      const user = await renderTab();

      await user.click(within(row("Old")).getByRole("button", { name: "Unarchive" }));

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith(
          "At most 50 attributes can be active. Archive one first.",
        );
      });
    });
  });
});
