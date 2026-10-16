import { ArrowRight, AudioLines, ShieldCheck } from "lucide-react";
import { Brand } from "@clinic/ui";
export const metadata = { title: "Sign in" };
export default async function Login({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const { error } = await searchParams;
  const messages: Record<string, string> = {
    not_configured:
      "Google sign-in has not been configured yet. Please contact the workspace administrator.",
    unavailable: "Sign-in is temporarily unavailable. Please try again.",
    invalid_login:
      "This sign-in attempt expired or is invalid. Please start again.",
    cancelled: "Google sign-in was cancelled. You can try again.",
    account_disabled:
      "This account is disabled. Please contact the workspace administrator.",
    failed: "We could not complete sign-in. Please try again.",
  };
  return (
    <main className="login-page">
      <section className="login-story">
        <Brand />
        <div className="login-pitch">
          <span className="pill">AVISHKAR VOICE</span>
          <h2>
            Every call.
            <br /> A better conversation.
          </h2>
          <p>
            Your always-on voice workspace. Create assistants, capture enquiries
            and bring every conversation into focus.
          </p>
          <div className="login-visual">
            <AudioLines size={42} strokeWidth={1.5} />
            <div>
              <strong>Your front desk, always available.</strong>
              <small>Thoughtful conversations. Clear outcomes.</small>
            </div>
          </div>
          <div className="login-bars" aria-hidden="true">
            {[
              24, 48, 32, 72, 44, 96, 58, 80, 40, 68, 30, 52, 88, 44, 64, 28,
            ].map((height, index) => (
              <i key={index} style={{ height }} />
            ))}
          </div>
        </div>
        <p className="story-footer">Built for the conversations that matter.</p>
      </section>
      <section className="login-content">
        <div className="login-card">
          <span className="badge pale">Welcome to your workspace</span>
          <h1>Good to see you.</h1>
          <p>Sign in to manage your voice agents and conversations.</p>
          <a className="button google-button" href="/api/v1/auth/google/login">
            <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
              <path
                fill="#4285F4"
                d="M21.6 12.2c0-.7-.1-1.4-.2-2.1H12v4h5.4a4.6 4.6 0 0 1-2 3v2.5h3.2c1.9-1.8 3-4.3 3-7.4Z"
              />
              <path
                fill="#34A853"
                d="M12 22c2.7 0 5-.9 6.6-2.4l-3.2-2.5c-.9.6-2 .9-3.4.9-2.6 0-4.8-1.7-5.6-4H3.1v2.6A10 10 0 0 0 12 22Z"
              />
              <path
                fill="#FBBC05"
                d="M6.4 14a6 6 0 0 1 0-4V7.4H3.1a10 10 0 0 0 0 9.2L6.4 14Z"
              />
              <path
                fill="#EA4335"
                d="M12 6c1.5 0 2.8.5 3.8 1.5l2.9-2.9A9.6 9.6 0 0 0 12 2a10 10 0 0 0-8.9 5.4L6.4 10C7.2 7.7 9.4 6 12 6Z"
              />
            </svg>
            Continue with Google
            <ArrowRight size={16} />
          </a>
          {error && (
            <p className="form-error" role="alert">
              {messages[error] || messages.failed}
            </p>
          )}
          <div className="login-preview">
            <ShieldCheck size={19} />
            <p>
              <strong>Secure Google sign-in</strong>
              <br />
              Use your Google account to access your workspace. We only request
              your name and email; voice data remains a sample preview.
            </p>
          </div>
        </div>
        <p className="login-foot">
          Avishkar Voice · Simple, natural conversations.
        </p>
      </section>
    </main>
  );
}
