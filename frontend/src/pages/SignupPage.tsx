/**
 * Self-service signup page.
 *
 * Steps:
 *  - "form": collect name + email; if the email domain maps to an existing
 *    org, switch to "Join {OrgName}" mode (hides org name/slug fields). On
 *    submit, POST /auth/signup/.
 *  - "otp": shown after path A (org created). Mirrors the LoginPage OTP UI.
 *  - "join_requested": shown after path B (request awaiting admin approval).
 */

import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { isAxiosError } from "axios";
import toast from "react-hot-toast";
import {
  checkDomain,
  checkSlug,
  signup,
  type CheckDomainResponse,
  type CheckSlugResponse,
} from "@/api/signup";
import { requestOTP, verifyOTP } from "@/api/auth";
import { useAuthStore } from "@/store/authStore";

type Step = "form" | "otp" | "join_requested";

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

  const [step, setStep] = useState<Step>("form");
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [orgName, setOrgName] = useState("");
  const [orgSlug, setOrgSlug] = useState("");
  const [orgSlugDirty, setOrgSlugDirty] = useState(false);

  const [domainResult, setDomainResult] = useState<CheckDomainResponse | null>(
    null,
  );
  const [slugResult, setSlugResult] = useState<CheckSlugResponse | null>(null);
  const [code, setCode] = useState("");
  const [joinedOrgName, setJoinedOrgName] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const codeInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (step === "otp") codeInputRef.current?.focus();
  }, [step]);

  // Auto-derive slug from org name until the user edits the slug field.
  useEffect(() => {
    if (!orgSlugDirty) setOrgSlug(suggestSlug(orgName));
  }, [orgName, orgSlugDirty]);

  // Debounced domain check on email blur or pause.
  useEffect(() => {
    if (!email || !email.includes("@")) {
      setDomainResult(null);
      return;
    }
    const handle = window.setTimeout(() => {
      checkDomain(email)
        .then(setDomainResult)
        .catch(() => setDomainResult(null));
    }, 400);
    return () => window.clearTimeout(handle);
  }, [email]);

  // Debounced slug availability check.
  useEffect(() => {
    const isJoin = domainResult?.matches_org;
    if (isJoin || !orgSlug) {
      setSlugResult(null);
      return;
    }
    const handle = window.setTimeout(() => {
      checkSlug(orgSlug)
        .then(setSlugResult)
        .catch(() => setSlugResult(null));
    }, 300);
    return () => window.clearTimeout(handle);
  }, [orgSlug, domainResult]);

  const isJoinMode = !!domainResult?.matches_org;
  const formIsValid = isJoinMode
    ? !!email && !!fullName.trim()
    : !!email &&
      !!fullName.trim() &&
      !!orgName.trim() &&
      !!orgSlug &&
      slugResult?.available !== false;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formIsValid) return;
    setIsLoading(true);

    try {
      const result = await signup({
        email,
        full_name: fullName,
        ...(isJoinMode ? {} : { org_name: orgName, org_slug: orgSlug }),
      });
      if (result.status === "created") {
        toast.success("Account created — check your email for the login code.");
        setStep("otp");
      } else {
        setJoinedOrgName(result.organization.name);
        setStep("join_requested");
      }
    } catch (err) {
      if (isAxiosError(err) && err.response) {
        const data = err.response.data as {
          code?: string;
          detail?: string;
          suggestion?: string;
        };
        if (data.code === "email_taken") {
          toast.error(
            data.detail ||
              "This email is already in use. Try signing in instead.",
          );
        } else if (data.code === "slug_taken") {
          toast.error("That URL slug is taken. Try the suggestion below.");
          if (data.suggestion) setOrgSlug(data.suggestion);
        } else if (err.response.status === 429) {
          toast.error("Too many signup attempts. Please try again later.");
        } else {
          toast.error(data.detail || "Signup failed. Please try again.");
        }
      } else {
        toast.error("Signup failed. Please try again.");
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleVerifyOTP = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    try {
      const tokens = await verifyOTP(email, code);
      setTokens(tokens.access, tokens.refresh);
      navigate("/onboarding");
    } catch {
      toast.error("Invalid or expired code.");
      setCode("");
    } finally {
      setIsLoading(false);
    }
  };

  const handleResendCode = async () => {
    setIsLoading(true);
    try {
      await requestOTP(email);
      toast.success("New code sent — check your email.");
    } catch {
      toast.error("Could not resend code. Please try again.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleStartOver = () => {
    setStep("form");
    setCode("");
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
      <div className="w-full max-w-md rounded-xl bg-white p-8 shadow-lg">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 h-12 w-12 rounded-xl bg-primary-500" />
          <h1 className="text-2xl font-bold text-gray-900">
            {step === "join_requested"
              ? "Request sent"
              : "Create your Showdesk account"}
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            {step === "form" &&
              (isJoinMode
                ? `An organization for ${domainResult?.domain} already exists.`
                : "Set up your team's helpdesk in under a minute.")}
            {step === "otp" && "Enter the code sent to your email"}
            {step === "join_requested" &&
              `An admin at ${joinedOrgName} will review your request.`}
          </p>
        </div>

        {step === "form" && (
          <form onSubmit={handleSubmit} className="space-y-4">
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
              {isJoinMode && (
                <p className="mt-1.5 rounded-lg bg-blue-50 px-3 py-2 text-xs text-blue-700">
                  <strong>{domainResult?.org_name}</strong> already uses
                  Showdesk. Submitting this form will request to join their
                  team — an admin must approve.
                </p>
              )}
            </div>

            {!isJoinMode && (
              <>
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
                          e.target.value
                            .toLowerCase()
                            .replace(/[^a-z0-9-]/g, ""),
                        );
                      }}
                      className="flex-1 px-3 py-2.5 text-sm focus:outline-none"
                      placeholder="acme"
                    />
                  </div>
                  {slugResult && orgSlug && (
                    <p
                      className={`mt-1.5 text-xs ${
                        slugResult.available
                          ? "text-green-600"
                          : "text-red-600"
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
              </>
            )}

            <button
              type="submit"
              disabled={isLoading || !formIsValid}
              className="w-full rounded-lg bg-primary-500 py-2.5 text-sm font-medium text-white transition-colors hover:bg-primary-600 disabled:opacity-50"
            >
              {isLoading
                ? "Working..."
                : isJoinMode
                  ? `Request to join ${domainResult?.org_name}`
                  : "Create my account"}
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
                Login code
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

        {step === "join_requested" && (
          <div className="space-y-4">
            <div className="rounded-lg bg-blue-50 p-4 text-sm text-blue-800">
              We've notified the admins of <strong>{joinedOrgName}</strong>.
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
      </div>
    </div>
  );
}
