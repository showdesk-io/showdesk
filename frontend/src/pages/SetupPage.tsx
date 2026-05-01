/**
 * Instance setup wizard — shown when no users exist.
 *
 * Two-step flow:
 * 1. Enter admin name + email -> creates platform admin + sends OTP
 * 2. Enter OTP code -> verifies and logs in
 */

import { useState, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import toast from "react-hot-toast";
import { initializeInstance } from "@/api/setup";
import { verifyOTP } from "@/api/auth";
import { useAuthStore } from "@/store/authStore";

type Step = "admin" | "otp";

export function SetupPage() {
  const [step, setStep] = useState<Step>("admin");
  const [email, setEmail] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [code, setCode] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const navigate = useNavigate();
  const setTokens = useAuthStore((s) => s.setTokens);
  const codeInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (step === "otp") {
      codeInputRef.current?.focus();
    }
  }, [step]);

  const handleCreateAdmin = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);

    try {
      await initializeInstance({
        email,
        first_name: firstName,
        last_name: lastName,
      });
      setStep("otp");
      toast.success("Admin account created! Check your email for the login code.");
    } catch {
      toast.error("Setup failed. Please try again.");
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
      navigate("/");
    } catch {
      toast.error("Invalid or expired code.");
      setCode("");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50">
      <div className="w-full max-w-md rounded-xl bg-white p-8 shadow-lg">
        <div className="mb-8 text-center">
          <img src="/logo.svg" alt="Showdesk" className="mx-auto mb-4 h-12 w-12" />
          <h1 className="text-2xl font-bold text-gray-900">Welcome to Showdesk</h1>
          <p className="mt-1 text-sm text-gray-500">
            {step === "admin"
              ? "Create the platform administrator account"
              : "Enter the code sent to your email"}
          </p>
        </div>

        {step === "admin" ? (
          <form onSubmit={handleCreateAdmin} className="space-y-4">
            <div className="flex gap-3">
              <div className="flex-1">
                <label
                  htmlFor="firstName"
                  className="mb-1 block text-sm font-medium text-gray-700"
                >
                  First name
                </label>
                <input
                  id="firstName"
                  type="text"
                  required
                  value={firstName}
                  onChange={(e) => setFirstName(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
                  autoFocus
                />
              </div>
              <div className="flex-1">
                <label
                  htmlFor="lastName"
                  className="mb-1 block text-sm font-medium text-gray-700"
                >
                  Last name
                </label>
                <input
                  id="lastName"
                  type="text"
                  value={lastName}
                  onChange={(e) => setLastName(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
                />
              </div>
            </div>

            <div>
              <label
                htmlFor="email"
                className="mb-1 block text-sm font-medium text-gray-700"
              >
                Email
              </label>
              <input
                id="email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
                placeholder="admin@showdesk.io"
              />
            </div>

            <button
              type="submit"
              disabled={isLoading}
              className="w-full rounded-lg bg-primary-500 py-2.5 text-sm font-medium text-white transition-colors hover:bg-primary-600 disabled:opacity-50"
            >
              {isLoading ? "Creating account..." : "Create admin account"}
            </button>
          </form>
        ) : (
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
                className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-center text-2xl font-mono tracking-[0.5em] focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
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
              {isLoading ? "Verifying..." : "Complete setup"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
