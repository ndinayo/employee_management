import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import { DigitalContractDocument, SignaturePad } from "./DigitalContract";
import ModalDialog from "./components/ModalDialog";
import { cancelMyLeave, changePassword, clockMyAttendance, fetchMyAttendance, fetchMyContracts, fetchMyLeave, fetchMyPhoto, fetchMyProfile, saveMyProfile, signMyContract, submitMyLeave } from "./api";
import { label, longDate, today } from "./managerConfig";

// The employer supplies only name, job title and email. Everything here is the
// employee's own to complete.
const EDITABLE = [
  { name: "phone", title: "Phone number", type: "tel", autoComplete: "tel" },
  { name: "emergency_contact", title: "Emergency contact", type: "text",
    hint: "Name and phone number of someone we can call in an emergency." },
  { name: "address", title: "Home address", type: "textarea", autoComplete: "street-address" },
];

function PasswordCard({ token, forced, onChanged }) {
  const [fields, setFields] = useState({ current_password: "", new_password: "", new_password_confirm: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const [open, setOpen] = useState(forced);

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
      setFields({ current_password: "", new_password: "", new_password_confirm: "" });
      setDone(true);
      if (!forced) setOpen(false);
      // The workspace replaces the password form, so start reading from the top.
      if (forced) window.scrollTo({ top: 0 });
      onChanged(result.access, result.user);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const passwordForm = <form className="account-panel" onSubmit={submit} aria-busy={busy}>
    <h3>{forced ? "Choose your own password" : "Change your password"}</h3>
    {forced && <p>You signed in with the temporary password from your invitation email. Set a password of your own to continue.</p>}
    {error && <p className="message error" role="alert">{error}</p>}
    {done && !forced && <p className="message success" role="status">Your password has been changed.</p>}
    <fieldset className="auth-fields" disabled={busy}>
      <label htmlFor="current-password">{forced ? "Temporary password" : "Current password"}</label>
      <input id="current-password" name="current_password" type="password" value={fields.current_password}
             onChange={update} autoComplete="current-password" maxLength={128} required />
      <label htmlFor="new-password">New password</label>
      <input id="new-password" name="new_password" type="password" value={fields.new_password}
             onChange={update} autoComplete="new-password" maxLength={128} minLength={8}
             aria-describedby="new-password-hint" required />
      <p id="new-password-hint" className="auth-hint">Use at least 8 characters. Avoid common passwords, only numbers, or your personal details.</p>
      <label htmlFor="new-password-confirm">Confirm new password</label>
      <input id="new-password-confirm" name="new_password_confirm" type="password" value={fields.new_password_confirm}
             onChange={update} autoComplete="new-password" maxLength={128} required />
      <button className="button button-coral" type="submit" disabled={busy}>
        {busy ? "Saving…" : "Save password →"}
      </button>
    </fieldset>
  </form>;
  return <>
    {!forced && <section className="panel account-panel form-launch-card"><div><h3>Password</h3><p className="muted">Choose a new password whenever you need to update account security.</p>{done && <p className="message success" role="status">Your password has been changed.</p>}</div><button className="button button-outline" type="button" onClick={() => { setError(""); setOpen(true); }}>Change password</button></section>}
    {open && <ModalDialog title={forced ? "Choose your own password" : "Change your password"} dismissible={!forced} onClose={() => setOpen(false)}>{passwordForm}</ModalDialog>}
  </>;
}

function ProfilePhoto({ token, name }) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    if (!name) return;
    let objectUrl = "";
    let cancelled = false;
    fetchMyPhoto(token).then((blob) => {
      if (cancelled) return;
      objectUrl = URL.createObjectURL(blob);
      setUrl(objectUrl);
    }).catch(() => {});
    return () => { cancelled = true; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [token, name]);
  if (!url) return null;
  return <img className="profile-photo" src={url} alt="Your profile photo" />;
}

function ProfileCard({ token, profile, onSaved }) {
  const [form, setForm] = useState(() => Object.fromEntries(EDITABLE.map((f) => [f.name, profile[f.name] || ""])));
  const [photo, setPhoto] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [open, setOpen] = useState(false);

  const incomplete = EDITABLE.filter((field) => !profile[field.name]);

  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    setError("");
    setNotice("");
    if (photo && photo.size > 5 * 1024 * 1024) {
      setError("Profile photos must be 5 MB or smaller.");
      return;
    }
    setBusy(true);
    try {
      let payload = form;
      if (photo) {
        payload = new FormData();
        Object.entries(form).forEach(([key, value]) => payload.append(key, value ?? ""));
        payload.append("photo", photo);
      }
      const saved = await saveMyProfile(token, payload);
      setPhoto(null);
      setNotice("Your details have been saved.");
      onSaved(saved);
      setOpen(false);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const profileForm = <form className="account-panel" onSubmit={submit} aria-busy={busy}>
    <h3>Your personal details</h3>
    <p>{incomplete.length
      ? "Your employer has set up your record. Please complete the details below so they have them on file."
      : "Keep these up to date so your employer can reach you."}</p>
    {error && <p className="message error" role="alert">{error}</p>}
    {notice && <p className="message success" role="status">{notice}</p>}
    <fieldset className="auth-fields" disabled={busy}>
      {EDITABLE.map((field) => <div key={field.name} className="profile-field">
        <label htmlFor={`profile-${field.name}`}>{field.title}</label>
        {field.type === "textarea"
          ? <textarea id={`profile-${field.name}`} rows={3} value={form[field.name]} autoComplete={field.autoComplete}
                      onChange={(event) => setForm({ ...form, [field.name]: event.target.value })} />
          : <input id={`profile-${field.name}`} type={field.type} value={form[field.name]} autoComplete={field.autoComplete}
                   onChange={(event) => setForm({ ...form, [field.name]: event.target.value })} />}
        {field.hint && <small className="field-hint">{field.hint}</small>}
      </div>)}
      <div className="profile-field">
        <label htmlFor="profile-photo">Profile photo (JPG, PNG, WEBP; max 5 MB)</label>
        <input id="profile-photo" type="file" accept=".jpg,.jpeg,.png,.webp"
               onChange={(event) => setPhoto(event.target.files?.[0] || null)} />
        {profile.photo_name && !photo && <small className="field-hint">Currently on file: {profile.photo_name}</small>}
      </div>
      <button className="button button-coral" type="submit" disabled={busy}>
        {busy ? "Saving…" : "Save my details →"}
      </button>
    </fieldset>
  </form>;
  return <>
    <section className="panel account-panel form-launch-card"><div><h3>Your personal details</h3><p>{incomplete.length ? `${incomplete.length} detail${incomplete.length === 1 ? " is" : "s are"} still missing.` : "Your contact and emergency details are up to date."}</p>{notice && <p className="message success" role="status">{notice}</p>}</div><button className="button button-coral" type="button" onClick={() => { setError(""); setOpen(true); }}>{incomplete.length ? "Complete details" : "Edit details"}</button></section>
    {open && <ModalDialog title="Your personal details" onClose={() => setOpen(false)}>{profileForm}</ModalDialog>}
  </>;
}

function EmploymentCard({ token, profile }) {
  return <section className="panel account-panel">
    <div className="employment-heading">
      <div>
        <h3>Your employment</h3>
        <p className="muted">Maintained by your employer. Contact them if anything here is wrong.</p>
      </div>
      <ProfilePhoto token={token} name={profile.photo_name} />
    </div>
    <dl>
      <dt>Company</dt><dd>{profile.business_name || "Not recorded"}</dd>
      <dt>Job title</dt><dd>{profile.job_title || "Not recorded"}</dd>
      <dt>Department</dt><dd>{profile.department || "Not recorded"}</dd>
      <dt>Employment type</dt><dd>{label(profile.employment_type)}</dd>
      <dt>Reports to</dt><dd>{profile.manager_name || "Not recorded"}</dd>
      <dt>Date joined</dt><dd>{profile.date_joined ? longDate(profile.date_joined) : "Not recorded"}</dd>
      <dt>Work email</dt><dd>{profile.email}</dd>
      <dt>Status</dt><dd>{profile.is_active ? "Active" : "Inactive"}</dd>
    </dl>
    {profile.job_description && <>
      <h4>Job description</h4>
      <p>{profile.job_description}</p>
    </>}
  </section>;
}

function timeOf(value) {
  return value ? new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "Not recorded";
}

function TimeClockCard({ token }) {
  const [day, setDay] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let cancelled = false;
    fetchMyAttendance(token).then((result) => { if (!cancelled) setDay(result); })
      .catch((err) => { if (!cancelled) setError(err.message); });
    return () => { cancelled = true; };
  }, [token]);

  async function clock(action) {
    if (busy) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await clockMyAttendance(token, action);
      setDay(result);
      setNotice(action === "check_in" ? "You are checked in. Have a productive day." : "You are checked out. Your worked hours have been recorded.");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const attendance = day?.attendance;
  const checkedIn = Boolean(attendance?.check_in_at);
  const checkedOut = Boolean(attendance?.check_out_at);
  return <section className="panel account-panel time-clock-card">
    <div className="time-clock-heading"><div><p className="eyebrow dark-eyebrow">TODAY</p><h3>Daily check-in</h3></div>
      <span className={`status-badge ${checkedOut ? "status-signed" : checkedIn ? "status-sent" : "status-draft"}`}>{checkedOut ? "Shift completed" : checkedIn ? "Checked in" : "Not checked in"}</span>
    </div>
    <p>{day?.date ? longDate(day.date) : "Loading today’s attendance…"}</p>
    {error && <p className="message error" role="alert">{error}</p>}
    {notice && <p className="message success" role="status">{notice}</p>}
    {day && <dl className="clock-times">
      <dt>Check-in</dt><dd>{timeOf(attendance?.check_in_at)}</dd>
      <dt>Check-out</dt><dd>{timeOf(attendance?.check_out_at)}</dd>
      <dt>Hours worked</dt><dd>{checkedOut ? attendance.hours_worked : "Calculated at check-out"}</dd>
    </dl>}
    {day && !checkedIn && <button className="button button-coral" disabled={busy} type="button" onClick={() => clock("check_in")}>{busy ? "Checking in…" : "Check in"}</button>}
    {day && checkedIn && !checkedOut && <button className="button button-coral" disabled={busy} type="button" onClick={() => clock("check_out")}>{busy ? "Checking out…" : "Check out"}</button>}
  </section>;
}

function LeaveManagementCard({ token }) {
  const [leave, setLeave] = useState(null);
  const [form, setForm] = useState({ leave_type: "annual", start_date: today(), end_date: today(), reason: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [requestOpen, setRequestOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchMyLeave(token).then((result) => { if (!cancelled) setLeave(result); })
      .catch((err) => { if (!cancelled) setError(err.message); });
    return () => { cancelled = true; };
  }, [token]);

  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const saved = await submitMyLeave(token, form);
      setLeave((current) => ({ ...current, requests: [saved, ...current.requests] }));
      setForm({ leave_type: "annual", start_date: today(), end_date: today(), reason: "" });
      setNotice("Your leave request has been sent to your employer for review.");
      setRequestOpen(false);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function cancel(record) {
    if (!window.confirm(`Cancel your ${label(record.leave_type).toLowerCase()} leave request?`)) return;
    setBusy(true);
    setError("");
    try {
      await cancelMyLeave(token, record.id);
      setLeave((current) => ({ ...current, requests: current.requests.filter((item) => item.id !== record.id) }));
      setNotice("The pending leave request was cancelled.");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const requests = leave?.requests || [];
  const upcoming = requests.filter((item) => item.end_date >= today());
  const history = requests.filter((item) => item.end_date < today());
  const requestRows = (rows) => rows.length ? <div className="leave-history-list">{rows.map((item) => <div className="leave-history-row" key={item.id}>
    <div><strong>{label(item.leave_type)}</strong><span>{item.start_date} to {item.end_date} · {item.days_requested} working day{Number(item.days_requested) === 1 ? "" : "s"}</span>{item.decision_notes && <small>{item.decision_notes}</small>}</div>
    <div><span className={`status-badge status-${item.status}`}>{label(item.status)}</span>{item.status === "pending" && <button className="text-button danger-link" disabled={busy} type="button" onClick={() => cancel(item)}>Cancel</button>}</div>
  </div>)}</div> : <p className="empty-state">No leave requests in this section.</p>;

  return <section className="leave-account-section">
    <div className="section-heading compact-heading"><div><p className="eyebrow dark-eyebrow">TIME OFF</p><h2>Leave management</h2><p>Apply for leave and follow your employer’s decision.</p></div><button className="button button-coral" type="button" onClick={() => { setError(""); setRequestOpen(true); }}>Request time off</button></div>
    {error && <p className="message error" role="alert">{error}</p>}
    {notice && <p className="message success" role="status">{notice}</p>}
    {leave && <div className="leave-balance-grid">{leave.balances.map((balance) => <article className="panel leave-balance-card" key={balance.id}>
      <span>{label(balance.leave_type)}</span><strong>{balance.unlimited ? "Unlimited" : balance.remaining_days}</strong>
      <small>{balance.unlimited ? `${balance.used_days} days recorded` : `${balance.used_days} used of ${balance.days_allocated} days`}</small>
    </article>)}</div>}
    {requestOpen && <ModalDialog title="Request time off" onClose={() => setRequestOpen(false)}><form className="account-panel leave-request-form" onSubmit={submit}>
      <h3>Request time off</h3>
      <fieldset className="auth-fields" disabled={busy}>
        <label htmlFor="leave-type">Leave type</label><select id="leave-type" value={form.leave_type} onChange={(event) => setForm({ ...form, leave_type: event.target.value })}><option value="annual">Annual leave</option><option value="sick">Sick leave</option><option value="maternity">Maternity leave</option><option value="unpaid">Unpaid leave</option></select>
        <div className="leave-date-fields"><div><label htmlFor="leave-start">Start date</label><input id="leave-start" type="date" min={today()} value={form.start_date} onChange={(event) => setForm({ ...form, start_date: event.target.value })} required /></div><div><label htmlFor="leave-end">End date</label><input id="leave-end" type="date" min={form.start_date} value={form.end_date} onChange={(event) => setForm({ ...form, end_date: event.target.value })} required /></div></div>
        <label htmlFor="leave-reason">Reason (optional)</label><textarea id="leave-reason" rows="3" value={form.reason} onChange={(event) => setForm({ ...form, reason: event.target.value })} />
        <button className="button button-coral" type="submit" disabled={busy}>{busy ? "Sending…" : "Submit leave request"}</button>
      </fieldset>
    </form></ModalDialog>}
    {leave && <div className="leave-lists"><section className="panel account-panel"><h3>Upcoming and current</h3>{requestRows(upcoming)}</section><section className="panel account-panel"><h3>Previous absences</h3>{requestRows(history)}</section></div>}
  </section>;
}

function ContractsCard({ token, profile }) {
  const [contracts, setContracts] = useState([]);
  const [signing, setSigning] = useState(null);
  const [signature, setSignature] = useState("");
  const [signerName, setSignerName] = useState(`${profile.first_name} ${profile.last_name}`.trim());
  const [accepted, setAccepted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let cancelled = false;
    fetchMyContracts(token).then((rows) => {
      if (cancelled) return;
      setContracts(rows);
      const requested = Number(new URLSearchParams(window.location.search).get("contract"));
      const contract = rows.find((row) => row.id === requested && row.signature_status === "sent");
      if (contract) {
        setSigning(contract.id);
        setTimeout(() => document.getElementById(`contract-${contract.id}`)?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
      }
    })
      .catch((err) => { if (!cancelled) setError(err.message); });
    return () => { cancelled = true; };
  }, [token]);

  async function submit(event, contract) {
    event.preventDefault();
    if (busy) return;
    setError("");
    setNotice("");
    if (!signature) {
      setError("Draw your signature before signing the contract.");
      return;
    }
    if (!window.confirm(`Sign “${contract.title}”? Your digital signature and signing time will be recorded.`)) return;
    setBusy(true);
    try {
      const saved = await signMyContract(token, contract.id, {
        signer_name: signerName, signature_data: signature, accepted,
      });
      setContracts((current) => current.map((row) => row.id === saved.id ? saved : row));
      setSigning(null);
      setSignature("");
      setAccepted(false);
      setNotice(`${saved.title} has been signed successfully.`);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (!contracts.length && !error) return null;
  return <section className="contracts-account-section" id="contracts">
    <div className="section-heading compact-heading"><div>
      <p className="eyebrow dark-eyebrow">DOCUMENTS</p>
      <h2>Your contracts</h2>
      <p>Read every contract completely before adding your digital signature.</p>
    </div></div>
    {error && <p className="message error" role="alert">{error}</p>}
    {notice && <p className="message success" role="status">{notice}</p>}
    {contracts.map((contract) => <article className="panel employee-contract-card" id={`contract-${contract.id}`} key={contract.id}>
      <div className="employee-contract-summary">
        <div><h3>{contract.title}</h3><p className="muted">From {contract.business_name} · Effective {contract.start_date}</p></div>
        <span className={`status-badge status-${contract.signature_status}`}>{contract.signature_status === "sent" ? "Awaiting your signature" : "Signed"}</span>
      </div>
      {contract.employer_message && <div className="message"><strong>Message from your employer</strong><p>{contract.employer_message}</p></div>}
      <details open={contract.signature_status === "sent"}>
        <summary>Read contract</summary>
        <DigitalContractDocument contract={contract} />
      </details>
      {contract.signature_status === "sent" && (signing === contract.id
        ? <ModalDialog title={`Sign ${contract.title}`} wide onClose={() => setSigning(null)}><form className="contract-sign-form" onSubmit={(event) => submit(event, contract)}>
            <h4>Sign this contract</h4>
            <label htmlFor={`signer-${contract.id}`}>Your full legal name</label>
            <input id={`signer-${contract.id}`} value={signerName} onChange={(event) => setSignerName(event.target.value)} required />
            <label>Draw your signature</label>
            <SignaturePad onChange={setSignature} />
            <label className="signature-consent"><input type="checkbox" checked={accepted} onChange={(event) => setAccepted(event.target.checked)} required />
              <span>I have read this complete contract and agree to sign it electronically.</span>
            </label>
            <div className="form-actions"><button className="button button-coral" disabled={busy} type="submit">{busy ? "Signing…" : "Sign contract"}</button><button className="button button-outline" type="button" onClick={() => setSigning(null)}>Cancel</button></div>
          </form></ModalDialog>
        : <button className="button button-coral" type="button" onClick={() => { setSigning(contract.id); setError(""); }}>Sign contract</button>)}
    </article>)}
  </section>;
}

export default function AccountPage({ account, token, onAccountChange }) {
  const [profile, setProfile] = useState(null);
  const [loadError, setLoadError] = useState("");
  const forced = Boolean(account.must_change_password);

  const load = useCallback(() => {
    if (!account.has_employee_record) return;
    fetchMyProfile(token).then(setProfile).catch((err) => setLoadError(err.message));
  }, [token, account.has_employee_record]);

  useEffect(load, [load]);

  // Until the temporary password is replaced, the only thing on offer is
  // replacing it.
  if (forced) {
    return <main className="workspace account-workspace">
      <div className="section-heading">
        <div>
          <p className="eyebrow dark-eyebrow">WELCOME</p>
          <h2>Hello, {account.display_name || account.username}</h2>
          <p className="workspace-identity-inline"><strong>{account.display_name || account.username}</strong><span>{account.role_label || "Employee"}</span></p>
          {account.business_name && <p>You have been added to {account.business_name}.</p>}
        </div>
      </div>
      <PasswordCard token={token} forced onChanged={onAccountChange} />
    </main>;
  }

  return <main className="workspace account-workspace">
    <div className="section-heading">
      <div>
        <p className="eyebrow dark-eyebrow">YOUR WORKSPACE</p>
        <h2>Welcome, {account.display_name || (profile ? `${profile.first_name} ${profile.last_name}` : account.username)}</h2>
        <p className="workspace-identity-inline"><strong>{account.display_name || account.username}</strong><span>{account.role_label || "Employee"}</span></p>
        <p>{account.business_name
          ? `Your employee workspace at ${account.business_name}.`
          : "Your personal account."}</p>
      </div>
    </div>

    {!account.has_employee_record && <section className="panel account-panel">
      <h3>Your account is ready</h3>
      <dl>
        <dt>Username</dt><dd>{account.username}</dd>
        <dt>Email address</dt><dd>{account.email || "Not provided"}</dd>
        <dt>Account type</dt><dd>{account.role === "employer" ? "Employer" : account.role === "manager" ? "Manager" : "Employee"}</dd>
      </dl>
      <p>Your account is not connected to a business yet. When an employer adds you to their workspace, your
        job details will appear here and you will be able to complete your own profile.</p>
    </section>}

    {loadError && <p className="message error" role="alert">{loadError}</p>}

    {profile && <>
      <EmploymentCard token={token} profile={profile} />
      <TimeClockCard token={token} />
      <LeaveManagementCard token={token} />
      <ContractsCard token={token} profile={profile} />
      <ProfileCard token={token} profile={profile} onSaved={setProfile} />
    </>}

    <PasswordCard token={token} forced={false} onChanged={onAccountChange} />

    <Link className="account-home-link" to="/">Back to main site</Link>
  </main>;
}
