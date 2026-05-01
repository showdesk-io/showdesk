/**
 * Login page with OTP authentication.
 *
 * Two-step flow:
 * 1. Enter email -> receive OTP code via email
 * 2. Enter OTP code -> receive JWT tokens
 */

import { useState, useRef, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import toast from "react-hot-toast";
import { requestOTP, verifyOTP } from "@/api/auth";
import { useAuthStore } from "@/store/authStore";

type Step = "email" | "otp";

export function LoginPage() {
  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const navigate = useNavigate();
  const setTokens = useAuthStore((s) => s.setTokens);
  const codeInputRef = useRef<HTMLInputElement>(null);

  // Auto-focus code input when step changes
  useEffect(() => {
    if (step === "otp") {
      codeInputRef.current?.focus();
    }
  }, [step]);

  const handleRequestOTP = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    setIsLoading(true);

    try {
      await requestOTP(email);
      setStep("otp");
      toast.success("Code sent! Check your email.");
    } catch {
      toast.error("Something went wrong. Please try again.");
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

  const handleBack = () => {
    setStep("email");
    setCode("");
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50">
      <div className="w-full max-w-md rounded-xl bg-white p-8 shadow-lg">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 h-12 w-12 rounded-xl bg-primary-500" />
          <h1 className="text-2xl font-bold text-gray-900">Showdesk</h1>
          <p className="mt-1 text-sm text-gray-500">
            {step === "email"
              ? "Sign in to your agent dashboard"
              : "Enter the code sent to your email"}
          </p>
        </div>

        {step === "email" ? (
          <form onSubmit={handleRequestOTP} className="space-y-4">
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
                placeholder="agent@company.com"
                autoFocus
              />
            </div>

            <button
              type="submit"
              disabled={isLoading}
              className="w-full rounded-lg bg-primary-500 py-2.5 text-sm font-medium text-white transition-colors hover:bg-primary-600 disabled:opacity-50"
            >
              {isLoading ? "Sending code..." : "Send login code"}
            </button>

            <p className="pt-2 text-center text-sm text-gray-500">
              No account yet?{" "}
              <Link
                to="/signup"
                className="font-medium text-primary-600 hover:text-primary-700"
              >
                Create one
              </Link>
            </p>
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
              {isLoading ? "Verifying..." : "Sign in"}
            </button>

            <div className="flex items-center justify-between text-sm">
              <button
                type="button"
                onClick={handleBack}
                className="text-gray-500 hover:text-gray-700"
              >
                Use a different email
              </button>
              <button
                type="button"
                onClick={() => handleRequestOTP()}
                disabled={isLoading}
                className="text-primary-500 hover:text-primary-600 disabled:opacity-50"
              >
                Resend code
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
