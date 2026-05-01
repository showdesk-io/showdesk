/**
 * Post-signup onboarding wizard. Three steps:
 *   1. Customize widget (color, position, greeting)
 *   2. Invite teammates (skippable)
 *   3. Copy embed snippet + test in widget demo
 *
 * State persists on Organization (`onboarding_step`, `onboarding_completed_at`)
 * so the user can resume mid-flow. If completed, the page redirects to /.
 */

import { useEffect, useMemo, useState } from "react";
import { Navigate, Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import toast from "react-hot-toast";
import { clsx } from "clsx";
import {
  fetchOrganization,
  inviteAgent,
  updateOrganization,
} from "@/api/users";
import type { Organization } from "@/types";

const STEP_LABELS = ["Widget", "Teammates", "Embed"] as const;

export function OnboardingPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { data: org, isLoading } = useQuery({
    queryKey: ["organization"],
    queryFn: fetchOrganization,
  });

  const [step, setStep] = useState(0);

  useEffect(() => {
    if (org && org.onboarding_step > 0 && step === 0) {
      setStep(Math.min(org.onboarding_step, STEP_LABELS.length - 1));
    }
  }, [org, step]);

  const updateMutation = useMutation({
    mutationFn: (data: Partial<Organization>) => {
      if (!org) throw new Error("No organization loaded");
      return updateOrganization(org.id, data);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["organization"] });
    },
  });

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="text-sm text-gray-400">Loading...</div>
      </div>
    );
  }
  if (!org) {
    return <Navigate to="/" replace />;
  }
  if (org.onboarding_completed_at) {
    return <Navigate to="/" replace />;
  }

  const goNext = () => {
    const next = Math.min(step + 1, STEP_LABELS.length - 1);
    setStep(next);
    updateMutation.mutate({ onboarding_step: next });
  };

  const finish = () => {
    updateMutation.mutate(
      {
        onboarding_step: STEP_LABELS.length,
        onboarding_completed_at: new Date().toISOString(),
      },
      {
        onSuccess: () => {
          toast.success("You're all set!");
          navigate("/");
        },
      },
    );
  };

  return (
    <div className="min-h-screen bg-gray-50 px-4 py-12">
      <div className="mx-auto w-full max-w-2xl">
        <div className="mb-6 text-center">
          <h1 className="text-2xl font-bold text-gray-900">
            Welcome to Showdesk, {org.name}
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            A few quick steps to get your support widget live.
          </p>
        </div>

        <Stepper current={step} />

        <div className="mt-6 rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
          {step === 0 && (
            <WidgetStep
              org={org}
              onSave={(patch) =>
                updateMutation.mutate(
                  { ...patch, onboarding_step: 1 },
                  { onSuccess: () => setStep(1) },
                )
              }
              isSaving={updateMutation.isPending}
            />
          )}
          {step === 1 && <InviteStep onNext={goNext} onSkip={goNext} />}
          {step === 2 && (
            <EmbedStep
              org={org}
              isFinishing={updateMutation.isPending}
              onFinish={finish}
            />
          )}
        </div>

        <div className="mt-4 text-center">
          <Link
            to="/"
            className="text-xs text-gray-400 hover:text-gray-600"
          >
            Skip and explore the dashboard
          </Link>
        </div>
      </div>
    </div>
  );
}

function Stepper({ current }: { current: number }) {
  return (
    <div className="flex items-center justify-center gap-3">
      {STEP_LABELS.map((label, i) => (
        <div key={label} className="flex items-center gap-3">
          <div
            className={clsx(
              "flex h-7 w-7 items-center justify-center rounded-full text-xs font-medium",
              i < current && "bg-primary-100 text-primary-700",
              i === current && "bg-primary-500 text-white",
              i > current && "bg-gray-100 text-gray-400",
            )}
          >
            {i < current ? "✓" : i + 1}
          </div>
          <span
            className={clsx(
              "text-sm",
              i === current
                ? "font-medium text-gray-900"
                : "text-gray-400",
            )}
          >
            {label}
          </span>
          {i < STEP_LABELS.length - 1 && (
            <div className="h-px w-8 bg-gray-200" />
          )}
        </div>
      ))}
    </div>
  );
}

function WidgetStep({
  org,
  onSave,
  isSaving,
}: {
  org: Organization;
  onSave: (patch: Partial<Organization>) => void;
  isSaving: boolean;
}) {
  const [color, setColor] = useState(org.widget_color);
  const [position, setPosition] = useState<Organization["widget_position"]>(
    org.widget_position,
  );
  const [greeting, setGreeting] = useState(org.widget_greeting);

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-gray-900">
          Customize your widget
        </h2>
        <p className="mt-1 text-sm text-gray-500">
          You can change all of this later in Settings.
        </p>
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium text-gray-700">
          Primary color
        </label>
        <div className="flex items-center gap-3">
          <input
            type="color"
            value={color}
            onChange={(e) => setColor(e.target.value)}
            className="h-10 w-16 cursor-pointer rounded border border-gray-300"
          />
          <input
            type="text"
            value={color}
            onChange={(e) => setColor(e.target.value)}
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono"
          />
        </div>
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium text-gray-700">
          Position
        </label>
        <div className="flex gap-2">
          {(["bottom-right", "bottom-left"] as const).map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => setPosition(p)}
              className={clsx(
                "flex-1 rounded-lg border px-4 py-2 text-sm",
                position === p
                  ? "border-primary-500 bg-primary-50 text-primary-700"
                  : "border-gray-300 text-gray-600 hover:bg-gray-50",
              )}
            >
              {p === "bottom-right" ? "Bottom right" : "Bottom left"}
            </button>
          ))}
        </div>
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium text-gray-700">
          Greeting
        </label>
        <input
          type="text"
          value={greeting}
          onChange={(e) => setGreeting(e.target.value)}
          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
          maxLength={255}
        />
      </div>

      <div className="flex justify-end">
        <button
          type="button"
          disabled={isSaving}
          onClick={() =>
            onSave({
              widget_color: color,
              widget_position: position,
              widget_greeting: greeting,
            })
          }
          className="rounded-lg bg-primary-500 px-5 py-2 text-sm font-medium text-white hover:bg-primary-600 disabled:opacity-50"
        >
          {isSaving ? "Saving..." : "Continue"}
        </button>
      </div>
    </div>
  );
}

interface InviteRow {
  email: string;
  name: string;
}

function InviteStep({
  onNext,
  onSkip,
}: {
  onNext: () => void;
  onSkip: () => void;
}) {
  const queryClient = useQueryClient();
  const [rows, setRows] = useState<InviteRow[]>([
    { email: "", name: "" },
    { email: "", name: "" },
    { email: "", name: "" },
  ]);
  const [submitting, setSubmitting] = useState(false);

  const updateRow = (i: number, patch: Partial<InviteRow>) => {
    setRows((prev) =>
      prev.map((r, idx) => (idx === i ? { ...r, ...patch } : r)),
    );
  };

  const validRows = rows.filter((r) => r.email.trim());

  const sendInvites = async () => {
    if (validRows.length === 0) {
      onSkip();
      return;
    }
    setSubmitting(true);
    let successes = 0;
    for (const row of validRows) {
      try {
        const [first, ...rest] = row.name.trim().split(" ");
        await inviteAgent({
          email: row.email.trim(),
          first_name: first || "",
          last_name: rest.join(" "),
          role: "agent",
        });
        successes += 1;
      } catch (err) {
        const msg = isAxiosError(err)
          ? (err.response?.data as { detail?: string })?.detail ||
            `Invite for ${row.email} failed`
          : `Invite for ${row.email} failed`;
        toast.error(msg);
      }
    }
    setSubmitting(false);
    if (successes > 0) {
      toast.success(
        `${successes} invitation${successes > 1 ? "s" : ""} sent`,
      );
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
    }
    onNext();
  };

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-gray-900">
          Invite your teammates
        </h2>
        <p className="mt-1 text-sm text-gray-500">
          They'll get a sign-in link by email. You can invite more later from
          Settings.
        </p>
      </div>

      <div className="space-y-2">
        {rows.map((row, i) => (
          <div key={i} className="flex gap-2">
            <input
              type="email"
              value={row.email}
              onChange={(e) => updateRow(i, { email: e.target.value })}
              placeholder="teammate@company.com"
              className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm"
            />
            <input
              type="text"
              value={row.name}
              onChange={(e) => updateRow(i, { name: e.target.value })}
              placeholder="Name (optional)"
              className="w-44 rounded-lg border border-gray-300 px-3 py-2 text-sm"
            />
          </div>
        ))}
      </div>

      <div className="flex justify-between">
        <button
          type="button"
          onClick={onSkip}
          className="text-sm text-gray-500 hover:text-gray-700"
        >
          Skip for now
        </button>
        <button
          type="button"
          onClick={sendInvites}
          disabled={submitting}
          className="rounded-lg bg-primary-500 px-5 py-2 text-sm font-medium text-white hover:bg-primary-600 disabled:opacity-50"
        >
          {submitting
            ? "Sending..."
            : validRows.length === 0
              ? "Continue"
              : `Send ${validRows.length} invite${validRows.length > 1 ? "s" : ""}`}
        </button>
      </div>
    </div>
  );
}

function EmbedStep({
  org,
  isFinishing,
  onFinish,
}: {
  org: Organization;
  isFinishing: boolean;
  onFinish: () => void;
}) {
  const snippet = useMemo(
    () =>
      `<script src="${window.location.origin}/cdn/widget.js" data-token="${org.api_token}"></script>`,
    [org.api_token],
  );
  const [copied, setCopied] = useState(false);

  const copy = () => {
    void navigator.clipboard.writeText(snippet).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-gray-900">
          Drop the widget on your site
        </h2>
        <p className="mt-1 text-sm text-gray-500">
          Paste this snippet into your site's HTML, just before
          <code className="mx-1 rounded bg-gray-100 px-1 text-xs">
            {`</body>`}
          </code>
          .
        </p>
      </div>

      <div className="relative">
        <pre className="overflow-x-auto rounded-lg bg-gray-900 p-4 text-xs text-gray-100">
          <code>{snippet}</code>
        </pre>
        <button
          type="button"
          onClick={copy}
          className="absolute right-2 top-2 rounded bg-gray-700 px-2 py-1 text-xs text-white hover:bg-gray-600"
        >
          {copied ? "Copied!" : "Copy"}
        </button>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <a
          href={`/widget-demo?token=${encodeURIComponent(org.api_token)}`}
          target="_blank"
          rel="noopener noreferrer"
          className="text-sm text-primary-600 hover:text-primary-700"
        >
          → Try it on the demo page
        </a>
        <button
          type="button"
          onClick={onFinish}
          disabled={isFinishing}
          className="rounded-lg bg-primary-500 px-5 py-2 text-sm font-medium text-white hover:bg-primary-600 disabled:opacity-50"
        >
          {isFinishing ? "Finishing..." : "Open my dashboard"}
        </button>
      </div>
    </div>
  );
}
