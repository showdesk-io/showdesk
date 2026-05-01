/**
 * Self-service signup page (OTP-first flow).
 *
 * Internal steps:
 *  - "email": collect name + email; live-check whether the email domain
 *    matches an existing org (visual hint only — backend re-checks at
 *    verify-otp time). Submit posts /auth/signup/request-otp/.
 *  - "otp": enter the 6-digit code. Submit posts /auth/signup/verify-otp/,
 *    stores JWT, then routes:
 *       has_org      → navigate to "/" (dashboard).
 *       join_request → step="join_confirm".
 *       create_org   → step="wizard".
 *  - "join_confirm": confirm submitting a join request to the matched org.
 *  - "join_done":    success state for Path B.
 *  - "wizard":       collect org_name + slug, post /auth/signup/create-org/.
 *
 * Resume flow: if an authenticated user lands here without an org (e.g. a
 * refresh between OTP verify and wizard submit), we fetch /auth/signup/state/
 * and jump directly to the right step.
 */

import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { isAxiosError } from "axios";
import toast from "react-hot-toast";
import {
  checkDomain,
  checkSlug,
  fetchSignupState,
  signupCreateOrg,
  signupRequestJoin,
  signupRequestOTP,
  signupVerifyOTP,
  type CheckDomainResponse,
  type CheckSlugResponse,
} from "@/api/signup";
import { useAuthStore } from "@/store/authStore";

type Step = "email" | "otp" | "join_confirm" | "join_done" | "wizard";

function suggestSlug(orgName: string): string {
  return orgName
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 50);
}

export function SignupPage() {
  const navigate = useNavigate();
  const setTokens = useAuthStore((s) => s.setTokens);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [code, setCode] = useState("");

  const [domainResult, setDomainResult] = useState<CheckDomainResponse | null>(
    null,
  );
  const [matchedOrgName, setMatchedOrgName] = useState("");

  const [orgName, setOrgName] = useState("");
  const [orgSlug, setOrgSlug] = useState("");
  const [orgSlugDirty, setOrgSlugDirty] = useState(false);
  const [slugResult, setSlugResult] = useState<CheckSlugResponse | null>(null);
  // Email domain auto-derived by the backend from the verified email. Empty
  // string means a public webmail provider (gmail, etc.) — no auto-routing.
  const [signupDomain, setSignupDomain] = useState("");
  // Editable override for the email_domain. Defaults to signupDomain on
  // mount but the founder can swap to any custom domain — that path
  // creates a pending DNS challenge instead of auto-verifying.
  const [emailDomainOverride, setEmailDomainOverride] = useState("");

  const [isLoading, setIsLoading] = useState(false);
  const [resumeChecked, setResumeChecked] = useState(false);
  const codeInputRef = useRef<HTMLInputElement>(null);

  // ─── Resume flow on mount ──────────────────────────────────────────────
  // If an authenticated user lands here, ask the backend where they are.
  useEffect(() => {
    if (!isAuthenticated) {
      setResumeChecked(true);
      return;
    }
    fetchSignupState()
      .then((data) => {
        setEmail(data.user.email);
        setSignupDomain(data.domain || "");
        setEmailDomainOverride(data.domain || "");
        if (data.next_step === "has_org") {
          navigate("/", { replace: true });
          return;
        }
        if (data.next_step === "join_request") {
          setMatchedOrgName(data.org_name || "this organization");
          setStep("join_confirm");
        } else {
          setStep("wizard");
        }
      })
      .catch(() => {
        // Token invalid or other error — fall back to email step.
      })
      .finally(() => setResumeChecked(true));
  }, [isAuthenticated, navigate]);

  // ─── Auto-derive slug from org name ────────────────────────────────────
  useEffect(() => {
    if (!orgSlugDirty) setOrgSlug(suggestSlug(orgName));
  }, [orgName, orgSlugDirty]);

  // ─── Live domain check (email step only) ───────────────────────────────
  useEffect(() => {
    if (step !== "email" || !email.includes("@")) {
      setDomainResult(null);
      return;
    }
    const handle = window.setTimeout(() => {
      checkDomain(email)
        .then(setDomainResult)
        .catch(() => setDomainResult(null));
    }, 400);
    return () => window.clearTimeout(handle);
  }, [email, step]);

  // ─── Live slug check (wizard step only) ────────────────────────────────
  useEffect(() => {
    if (step !== "wizard" || !orgSlug) {
      setSlugResult(null);
      return;
    }
    const handle = window.setTimeout(() => {
      checkSlug(orgSlug)
        .then(setSlugResult)
        .catch(() => setSlugResult(null));
    }, 300);
    return () => window.clearTimeout(handle);
  }, [orgSlug, step]);

  // ─── Auto-focus OTP input ──────────────────────────────────────────────
  useEffect(() => {
    if (step === "otp") codeInputRef.current?.focus();
  }, [step]);

  // ─── Handlers ──────────────────────────────────────────────────────────

  const handleRequestOTP = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !fullName.trim()) return;
    setIsLoading(true);
    try {
      await signupRequestOTP({ email, full_name: fullName });
      toast.success("Code sent — check your email.");
      setStep("otp");
    } catch (err) {
      handleAxiosError(err, "Could not start signup. Please try again.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleVerifyOTP = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    try {
      const data = await signupVerifyOTP(email, code);
      setTokens(data.access, data.refresh);
      setSignupDomain(data.domain || "");
      setEmailDomainOverride(data.domain || "");
      if (data.next_step === "has_org") {
        navigate("/");
        return;
      }
      if (data.next_step === "join_request") {
        setMatchedOrgName(data.org_name || "this organization");
        setStep("join_confirm");
      } else {
        setStep("wizard");
      }
    } catch (err) {
      if (isAxiosError(err) && err.response?.status === 401) {
        toast.error("Invalid or expired code.");
        setCode("");
      } else {
        handleAxiosError(err, "Could not verify code.");
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleResendCode = async () => {
    setIsLoading(true);
    try {
      await signupRequestOTP({ email, full_name: fullName });
      toast.success("New code sent.");
    } catch {
      toast.error("Could not resend code.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleConfirmJoin = async () => {
    setIsLoading(true);
    try {
      await signupRequestJoin({ full_name: fullName });
      setStep("join_done");
    } catch (err) {
      handleAxiosError(err, "Could not submit join request.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleCreateOrg = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!orgName.trim() || !orgSlug || slugResult?.available === false) return;
    setIsLoading(true);
    try {
      const data = await signupCreateOrg({
        org_name: orgName,
        org_slug: orgSlug,
        email_domain: emailDomainOverride.trim().toLowerCase() || undefined,
      });
      if (data.email_domain_status === "pending_dns") {
        toast.success(
          `Workspace created. Verify ${data.email_domain} via DNS in Settings.`,
        );
      }
      navigate("/onboarding");
    } catch (err) {
      if (
        isAxiosError(err) &&
        (err.response?.data as { code?: string })?.code === "slug_taken"
      ) {
        const data = err.response?.data as { suggestion?: string };
        toast.error("That URL slug is taken. Try the suggestion below.");
        if (data.suggestion) setOrgSlug(data.suggestion);
      } else {
        handleAxiosError(err, "Could not create your workspace.");
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleStartOver = () => {
    setStep("email");
    setCode("");
  };

  // ─── Helpers ───────────────────────────────────────────────────────────

  const handleAxiosError = (err: unknown, fallback: string) => {
    if (isAxiosError(err) && err.response) {
      const data = err.response.data as { detail?: string; code?: string };
      if (data.code === "email_taken") {
        toast.error(
          data.detail ||
            "This email cannot be used for signup. Try signing in instead.",
        );
      } else if (err.response.status === 429) {
        toast.error("Too many attempts. Please try again later.");
      } else {
        toast.error(data.detail || fallback);
      }
    } else {
      toast.error(fallback);
    }
  };

  // ─── Render ────────────────────────────────────────────────────────────

  if (!resumeChecked) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50">
        <div className="text-sm text-gray-400">Loading...</div>
      </div>
    );
  }

  const heading =
    step === "join_done"
      ? "Request sent"
      : step === "wizard"
        ? "Set up your workspace"
        : step === "join_confirm"
          ? `Join ${matchedOrgName}`
          : "Create your Showdesk account";

  const subheading =
    step === "email" &&
    (domainResult?.matches_org
      ? `An organization for ${domainResult.domain} already exists.`
      : "Set up your team's helpdesk in under a minute.");

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
      <div className="w-full max-w-md rounded-xl bg-white p-8 shadow-lg">
        <div className="mb-8 text-center">
          <img src="/logo.svg" alt="Showdesk" className="mx-auto mb-4 h-12 w-12" />
          <h1 className="text-2xl font-bold text-gray-900">{heading}</h1>
          {step === "email" && (
            <p className="mt-1 text-sm text-gray-500">{subheading}</p>
          )}
          {step === "otp" && (
            <p className="mt-1 text-sm text-gray-500">
              Enter the code sent to your email.
            </p>
          )}
          {step === "join_confirm" && (
            <p className="mt-1 text-sm text-gray-500">
              An admin at {matchedOrgName} will review your request.
            </p>
          )}
          {step === "wizard" && (
            <p className="mt-1 text-sm text-gray-500">
              A few last details about your team.
            </p>
          )}
          {step === "join_done" && (
            <p className="mt-1 text-sm text-gray-500">
              We've notified the admins of {matchedOrgName}.
            </p>
          )}
        </div>

        {step === "email" && (
          <form onSubmit={handleRequestOTP} className="space-y-4">
            <div>
              <label
                htmlFor="fullName"
                className="mb-1 block text-sm font-medium text-gray-700"
              >
                Full name
              </label>
              <input
                id="fullName"
                type="text"
                required
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
                autoFocus
              />
            </div>

            <div>
              <label
                htmlFor="email"
                className="mb-1 block text-sm font-medium text-gray-700"
              >
                Work email
              </label>
              <input
                id="email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value.toLowerCase())}
                className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
                placeholder="you@company.com"
              />
              {domainResult?.matches_org && (
                <p className="mt-1.5 rounded-lg bg-blue-50 px-3 py-2 text-xs text-blue-700">
                  <strong>{domainResult.org_name}</strong> already uses
                  Showdesk. After verifying your email, you'll be able to
                  request to join their team.
                </p>
              )}
            </div>

            <button
              type="submit"
              disabled={isLoading || !email || !fullName.trim()}
              className="w-full rounded-lg bg-primary-500 py-2.5 text-sm font-medium text-white transition-colors hover:bg-primary-600 disabled:opacity-50"
            >
              {isLoading ? "Sending code..." : "Send verification code"}
            </button>

            <p className="pt-2 text-center text-sm text-gray-500">
              Already have an account?{" "}
              <Link
                to="/login"
                className="font-medium text-primary-600 hover:text-primary-700"
              >
                Sign in
              </Link>
            </p>
          </form>
        )}

        {step === "otp" && (
          <form onSubmit={handleVerifyOTP} className="space-y-4">
            <div>
              <label
                htmlFor="code"
                className="mb-1 block text-sm font-medium text-gray-700"
              >
                Verification code
              </label>
              <input
                ref={codeInputRef}
                id="code"
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                required
                maxLength={8}
                value={code}
                onChange={(e) =>
                  setCode(e.target.value.replace(/\D/g, "").slice(0, 6))
                }
                className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-center font-mono text-2xl tracking-[0.5em] focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
                placeholder="------"
              />
              <p className="mt-2 text-xs text-gray-400">
                Sent to{" "}
                <span className="font-medium text-gray-600">{email}</span>
              </p>
            </div>

            <button
              type="submit"
              disabled={isLoading || code.length < 6}
              className="w-full rounded-lg bg-primary-500 py-2.5 text-sm font-medium text-white transition-colors hover:bg-primary-600 disabled:opacity-50"
            >
              {isLoading ? "Verifying..." : "Verify and continue"}
            </button>

            <div className="flex items-center justify-between text-sm">
              <button
                type="button"
                onClick={handleStartOver}
                className="text-gray-500 hover:text-gray-700"
              >
                Use a different email
              </button>
              <button
                type="button"
                onClick={handleResendCode}
                disabled={isLoading}
                className="text-primary-600 hover:text-primary-700 disabled:opacity-50"
              >
                Resend code
              </button>
            </div>
          </form>
        )}

        {step === "join_confirm" && (
          <div className="space-y-4">
            <div className="rounded-lg bg-blue-50 p-4 text-sm text-blue-800">
              Your email is verified. To finish, request to join{" "}
              <strong>{matchedOrgName}</strong>. An admin must approve before
              you can access the dashboard.
            </div>
            <button
              type="button"
              onClick={handleConfirmJoin}
              disabled={isLoading}
              className="w-full rounded-lg bg-primary-500 py-2.5 text-sm font-medium text-white transition-colors hover:bg-primary-600 disabled:opacity-50"
            >
              {isLoading ? "Submitting..." : `Request to join ${matchedOrgName}`}
            </button>
          </div>
        )}

        {step === "join_done" && (
          <div className="space-y-4">
            <div className="rounded-lg bg-blue-50 p-4 text-sm text-blue-800">
              You'll receive an email when your request is approved.
            </div>
            <Link
              to="/login"
              className="block w-full rounded-lg bg-primary-500 py-2.5 text-center text-sm font-medium text-white transition-colors hover:bg-primary-600"
            >
              Back to sign in
            </Link>
          </div>
        )}

        {step === "wizard" && (
          <form onSubmit={handleCreateOrg} className="space-y-4">
            <div>
              <label
                htmlFor="orgName"
                className="mb-1 block text-sm font-medium text-gray-700"
              >
                Organization name
              </label>
              <input
                id="orgName"
                type="text"
                required
                value={orgName}
                onChange={(e) => setOrgName(e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
                placeholder="Acme Inc"
                autoFocus
              />
            </div>

            <div>
              <label
                htmlFor="orgSlug"
                className="mb-1 block text-sm font-medium text-gray-700"
              >
                URL slug
              </label>
              <div className="flex items-stretch overflow-hidden rounded-lg border border-gray-300 focus-within:border-primary-500 focus-within:ring-1 focus-within:ring-primary-500">
                <span className="flex items-center bg-gray-50 px-3 text-xs text-gray-500">
                  showdesk.io/
                </span>
                <input
                  id="orgSlug"
                  type="text"
                  required
                  value={orgSlug}
                  onChange={(e) => {
                    setOrgSlugDirty(true);
                    setOrgSlug(
                      e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ""),
                    );
                  }}
                  className="flex-1 px-3 py-2.5 text-sm focus:outline-none"
                  placeholder="acme"
                />
              </div>
              {slugResult && orgSlug && (
                <p
                  className={`mt-1.5 text-xs ${
                    slugResult.available ? "text-green-600" : "text-red-600"
                  }`}
                >
                  {slugResult.available
                    ? "Available"
                    : slugResult.reason === "taken"
                      ? `Taken — try “${slugResult.suggestion}”`
                      : slugResult.reason === "reserved"
                        ? `Reserved — try “${slugResult.suggestion}”`
                        : "Invalid format (lowercase letters, digits, dashes)"}
                </p>
              )}
            </div>

            <div>
              <label
                htmlFor="emailDomain"
                className="mb-1 block text-sm font-medium text-gray-700"
              >
                Email domain
              </label>
              <input
                id="emailDomain"
                type="text"
                value={emailDomainOverride}
                onChange={(e) =>
                  setEmailDomainOverride(
                    e.target.value.toLowerCase().replace(/[^a-z0-9.-]/g, ""),
                  )
                }
                className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
                placeholder={signupDomain || "acme.com"}
              />
              <p className="mt-1.5 text-xs text-gray-500">
                {(() => {
                  const v = emailDomainOverride.trim();
                  if (!v) {
                    return signupDomain
                      ? `Defaults to ${signupDomain}. Teammates with @${signupDomain} will be auto-routed.`
                      : "Optional. Add later in Settings (DNS verification required).";
                  }
                  if (v === signupDomain) {
                    return `Auto-verified from your email. Teammates with @${v} will be auto-routed.`;
                  }
                  return `Different from your email — you'll verify @${v} via DNS in Settings after creation.`;
                })()}
              </p>
            </div>

            <button
              type="submit"
              disabled={
                isLoading ||
                !orgName.trim() ||
                !orgSlug ||
                slugResult?.available === false
              }
              className="w-full rounded-lg bg-primary-500 py-2.5 text-sm font-medium text-white transition-colors hover:bg-primary-600 disabled:opacity-50"
            >
              {isLoading ? "Creating..." : "Create my workspace"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
