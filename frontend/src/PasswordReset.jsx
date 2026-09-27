import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { confirmPasswordReset, requestPasswordReset } from "./api";

export function ForgotPasswordPage() {
  const [identifier, setIdentifier] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await requestPasswordReset(identifier);
      setDone(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <main className="workspace account-workspace reset-workspace">
    <form className="panel login-panel" onSubmit={submit} aria-busy={busy}>
      <p className="eyebrow dark-eyebrow">ACCOUNT RECOVERY</p>
      <h3>Forgot your password?</h3>
      <p>Enter your username or email address. We will email you a secure link to choose a new password.</p>
      {error && <p className="message error" role="alert">{error}</p>}
      {done ? <>
        <p className="message success" role="status">If a matching account has an email address, password reset instructions have been sent.</p>
        <p className="auth-hint">If the email is used by more than one account, you will receive a separate message showing each username.</p>
      </> : <fieldset className="auth-fields" disabled={busy}>
        <label htmlFor="reset-identifier">Username or email</label>
        <input id="reset-identifier" value={identifier} onChange={(event) => setIdentifier(event.target.value)} autoComplete="username" maxLength={254} required autoFocus />
        <button className="button button-coral" type="submit" disabled={busy}>{busy ? "Sending…" : "Email reset link →"}</button>
      </fieldset>}
      <Link className="auth-secondary-link" to="/#sign-in">Back to sign in</Link>
    </form>
  </main>;
}

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const uid = params.get("uid") || "";
  const token = params.get("token") || "";
  const [fields, setFields] = useState({ new_password: "", new_password_confirm: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    setError("");
    if (fields.new_password !== fields.new_password_confirm) {
      setError("Passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await confirmPasswordReset({ uid, token, ...fields });
      setDone(true);
      setFields({ new_password: "", new_password_confirm: "" });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const missingLink = !uid || !token;
  return <main className="workspace account-workspace reset-workspace">
    <form className="panel login-panel" onSubmit={submit} aria-busy={busy}>
      <p className="eyebrow dark-eyebrow">ACCOUNT RECOVERY</p>
      <h3>Choose a new password</h3>
      {missingLink && <p className="message error" role="alert">This password reset link is incomplete. Request a new one.</p>}
      {error && <p className="message error" role="alert">{error}</p>}
      {done ? <>
        <p className="message success" role="status">Your password has been reset. You can now sign in.</p>
        <Link className="button button-coral" to="/#sign-in">Continue to sign in →</Link>
      </> : !missingLink && <fieldset className="auth-fields" disabled={busy}>
        <label htmlFor="reset-new-password">New password</label>
        <input id="reset-new-password" type="password" value={fields.new_password} onChange={(event) => setFields({ ...fields, new_password: event.target.value })} autoComplete="new-password" minLength={8} maxLength={128} required autoFocus />
        <p className="auth-hint">Use at least 8 characters. Avoid common passwords, only numbers, or your personal details.</p>
        <label htmlFor="reset-confirm-password">Confirm new password</label>
        <input id="reset-confirm-password" type="password" value={fields.new_password_confirm} onChange={(event) => setFields({ ...fields, new_password_confirm: event.target.value })} autoComplete="new-password" minLength={8} maxLength={128} required />
        <button className="button button-coral" type="submit" disabled={busy}>{busy ? "Saving…" : "Reset password →"}</button>
      </fieldset>}
      {!done && <Link className="auth-secondary-link" to="/forgot-password">Request a new reset link</Link>}
    </form>
  </main>;
}
