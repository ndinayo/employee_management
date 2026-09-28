import { useState } from "react";
import { Link } from "react-router";
import { fetchAccount, loginUser, signupUser } from "./api";

const emptyFields = { username: "", email: "", password: "", password_confirm: "", role: "", business_name: "" };

export default function AuthForm({ onAuthenticated, initialMode = "signin" }) {
  const [signup, setSignup] = useState(initialMode === "signup");
  const [fields, setFields] = useState(emptyFields);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function update(event) {
    const { name, value } = event.target;
    setFields((current) => ({ ...current, [name]: value }));
  }

  function switchMode(next) {
    setSignup(next);
    setError("");
    setFields((current) => ({ ...current, password: "", password_confirm: "" }));
  }

  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    setError("");
    if (signup && fields.password !== fields.password_confirm) {
      setError("Passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      const result = signup
        ? await signupUser({ ...fields, business_name: fields.role === "employer" ? fields.business_name : "" })
        : await loginUser(fields.username, fields.password);
      const account = result.user || await fetchAccount(result.access);
      onAuthenticated(result.access, account, result.refresh);
    } catch (err) {
      setError(!signup && err.status === 401
        ? "Those sign-in details are incorrect. Check your invitation email, or choose Create account if you are new here."
        : err.message);
    } finally {
      setBusy(false);
    }
  }

  return <form className="panel login-panel" onSubmit={submit} aria-busy={busy}>
    <div className="auth-tabs" aria-label="Account access">
      <button type="button" aria-pressed={!signup} disabled={busy} onClick={() => switchMode(false)}>Sign in</button>
      <button type="button" aria-pressed={signup} disabled={busy} onClick={() => switchMode(true)}>Create account</button>
    </div>
    <p className="eyebrow dark-eyebrow">{signup ? "JOIN YOUR WORKSPACE" : "ACCOUNT ACCESS"}</p>
    <h3>{signup ? "Create your account" : "Sign in to continue"}</h3>
    <p>{signup ? "Choose how you will use Employee Management." : "Welcome back. Sign in with your username and password."}</p>
    {error && <p className="message error" role="alert">{error}</p>}
    <fieldset className="auth-fields" disabled={busy}>
      {signup && <>
        <label htmlFor="account-role">Account type</label>
        <select id="account-role" name="role" value={fields.role} onChange={update} required>
          <option value="">Choose your account type</option>
          <option value="employee">Employee</option>
          <option value="employer">Employer</option>
        </select>
        {fields.role === "employer" && <>
          <label htmlFor="business-name">Business name</label>
          <input id="business-name" name="business_name" value={fields.business_name} onChange={update} autoComplete="organization" maxLength={200} required />
          <p className="auth-hint">We will create a private workspace for your business.</p>
        </>}
        {fields.role === "employee" && <p className="auth-hint">Create your personal account. This does not give access to an employer&apos;s records.</p>}
        <label htmlFor="signup-email">Email address</label>
        <input id="signup-email" name="email" type="email" value={fields.email} onChange={update} autoComplete="email" maxLength={254} required />
      </>}
      <label htmlFor="username">{signup ? "Username" : "Username or email"}</label>
      <input id="username" name="username" value={fields.username} onChange={update} autoComplete="username" maxLength={254} required />
      {!signup && <p className="auth-hint">Added to a team by your employer? Sign in with the email and temporary password they sent you. There is no need to create an account.</p>}
      <label htmlFor="password">Password</label>
      <input id="password" name="password" type="password" value={fields.password} onChange={update} autoComplete={signup ? "new-password" : "current-password"} maxLength={128} minLength={signup ? 8 : undefined} aria-describedby={signup ? "password-hint" : undefined} required />
      {!signup && <Link className="forgot-password-link" to="/forgot-password">Forgot password?</Link>}
      {signup && <>
        <p id="password-hint" className="auth-hint">Use at least 8 characters. Avoid common passwords, only numbers, or your personal details.</p>
        <label htmlFor="password-confirm">Confirm password</label>
        <input id="password-confirm" name="password_confirm" type="password" value={fields.password_confirm} onChange={update} autoComplete="new-password" maxLength={128} required />
      </>}
      <button className="button button-coral" type="submit" disabled={busy}>
        {busy ? (signup ? "Creating account…" : "Signing in…") : (signup ? "Create account →" : "Sign in →")}
      </button>
    </fieldset>
    {busy && <p className="auth-hint" role="status">Connecting to your workspace. This may take a moment.</p>}
  </form>;
}
