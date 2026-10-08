import { useState } from "react";
import { changePassword } from "../api";
import ModalDialog from "./ModalDialog";
import PasswordInput from "./PasswordInput";

const empty = { current_password: "", new_password: "", new_password_confirm: "" };

export default function ChangePasswordDialog({ token, forced = false, onClose, onChanged }) {
  const [fields, setFields] = useState(empty);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const title = forced ? "Choose your own password" : "Change your password";

  function update(event) {
    const { name, value } = event.target;
    setFields((current) => ({ ...current, [name]: value }));
  }

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
      const result = await changePassword(token, fields);
      setFields(empty);
      setDone(true);
      // The workspace replaces the password form, so start reading from the top.
      if (forced) window.scrollTo({ top: 0 });
      onChanged(result.access, result.user, result.refresh);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <ModalDialog title={title} dismissible={!forced} onClose={onClose}>
    {done && !forced ? <div className="account-panel">
      <p className="message success" role="status">Your password has been changed.</p>
      <button className="button button-coral" type="button" onClick={onClose}>Done</button>
    </div> : <form className="account-panel" onSubmit={submit} aria-busy={busy}>
      <h3>{title}</h3>
      {forced && <p>You signed in with the temporary password from your invitation email. Set a password of your own to continue.</p>}
      {error && <p className="message error" role="alert">{error}</p>}
      <fieldset className="auth-fields" disabled={busy}>
        <label htmlFor="current-password">{forced ? "Temporary password" : "Current password"}</label>
        <PasswordInput id="current-password" name="current_password" value={fields.current_password}
          onChange={update} autoComplete="current-password" maxLength={128} required />
        <label htmlFor="new-password">New password</label>
        <PasswordInput id="new-password" name="new_password" value={fields.new_password}
          onChange={update} autoComplete="new-password" maxLength={128} minLength={8}
          aria-describedby="new-password-hint" required />
        <p id="new-password-hint" className="auth-hint">Use at least 8 characters. Avoid common passwords, only numbers, or your personal details.</p>
        <label htmlFor="new-password-confirm">Confirm new password</label>
        <PasswordInput id="new-password-confirm" name="new_password_confirm" value={fields.new_password_confirm}
          onChange={update} autoComplete="new-password" maxLength={128} required />
        <button className="button button-coral" type="submit" disabled={busy}>
          {busy ? "Saving…" : "Save password →"}
        </button>
      </fieldset>
    </form>}
  </ModalDialog>;
}
