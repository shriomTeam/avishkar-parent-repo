"use client";
import { useEffect, useState } from "react";
import { Brand, Field, Select, FormError } from "@clinic/ui";
import { useAuth } from "@/lib/auth/provider";
import { SignOut } from "./sign-out";
export function Onboarding() {
  const { auth, write } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // Until the page has loaded its scripts the form below has no handler, and the browser would submit it as a
  // plain GET, putting the name and phone number in the address. The button stays off until the handler exists.
  const [ready, setReady] = useState(false);
  useEffect(() => setReady(true), []);
  return (
    <main className="onboarding-page">
      <Brand />
      <div className="auth onboarding">
        <span className="badge pale">Workspace setup · 1 of 1</span>
        <h1 className="spaced">Let’s meet your practice.</h1>
        <p className="form-intro">
          Welcome, {auth.user.display_name}. Create your workspace to get
          started.
        </p>
        <section className="panel">
          <form
            onSubmit={async (event) => {
              event.preventDefault();
              const data = new FormData(event.currentTarget);
              setBusy(true);
              setError("");
              try {
                await write("/api/v1/workspaces", {
                  name: String(data.get("name")).trim(),
                  timezone: data.get("timezone"),
                  clinic_type: data.get("clinic_type"),
                  phone: String(data.get("phone")).trim() || null,
                });
                window.location.replace("/");
              } catch (error) {
                setError(
                  error instanceof Error
                    ? error.message
                    : "Could not create workspace.",
                );
                setBusy(false);
              }
            }}
          >
            <Field
              label="Workspace name"
              name="name"
              required
              maxLength={80}
              pattern=".*\S.*"
            />
            <Select
              label="Clinic type"
              name="clinic_type"
              defaultValue="medspa"
            >
              <option value="medspa">Med spa</option>
              <option value="wellness">Wellness</option>
              <option value="hrt">HRT</option>
            </Select>
            <Select
              label="Timezone"
              name="timezone"
              defaultValue="Asia/Kolkata"
            >
              <option>Asia/Kolkata</option>
              <option>America/Los_Angeles</option>
              <option>UTC</option>
            </Select>
            <Field
              label="Callback number (E.164, optional)"
              name="phone"
              type="tel"
              pattern="\+[1-9][0-9]{6,14}"
              placeholder="+919876543210"
            />
            <FormError message={error} />
            <button className="primary" disabled={busy || !ready}>
              {busy ? "Creating workspace…" : "Create workspace"}
            </button>
          </form>
        </section>
        <div className="spaced">
          <SignOut />
        </div>
      </div>
    </main>
  );
}
