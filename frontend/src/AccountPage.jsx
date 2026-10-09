import { useCallback, useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router";
import { DigitalContractDocument, SignaturePad } from "./DigitalContract";
import CompanyCalendar, { EmployeeAnnouncements } from "./CompanyCalendar";
import EmployeePayroll from "./EmployeePayroll";
import AccessControl from "./AccessControl";
import ModalDialog from "./components/ModalDialog";
import ChangePasswordDialog from "./components/ChangePasswordDialog";
import DashboardTopNav from "./components/DashboardTopNav";
import { useConfirm } from "./components/ConfirmDialog";
import LocationStatus from "./components/LocationStatus";
import { locationText, positionOrNull } from "./geolocation";
import { acknowledgeMyContractTermination, cancelMyLeave, clockMyAttendance, fetchAccount, fetchMyAnnouncements, fetchMyAttendance, fetchMyCalendar, fetchMyContracts, fetchMyLeave, fetchMyPhoto, fetchMyProfile, markAllMyAnnouncementsRead, markAllMyCalendarRead, markMyAnnouncementRead, markMyCalendarEventRead, requestMyContractTermination, saveMyProfile, signMyContract, submitMyLeave, updateMyLeave } from "./api";
import { decisionText, label, longDate, money, today } from "./managerConfig";

// The employer supplies only name, job title and email. Everything here is the
// employee's own to complete.
const EDITABLE = [
  { name: "phone", title: "Phone number", type: "tel", autoComplete: "tel" },
  { name: "emergency_contact", title: "Emergency contact", type: "text",
    hint: "Name and phone number of someone we can call in an emergency." },
  { name: "address", title: "Home address", type: "textarea", autoComplete: "street-address" },
];

export function PasswordCard({ token, forced, onChanged }) {
  const [done, setDone] = useState(false);
  const [open, setOpen] = useState(forced);
  function changed(access, user, refresh) {
    setDone(true);
    if (!forced) setOpen(false);
    onChanged(access, user, refresh);
  }
  return <>
    {!forced && <section className="panel account-panel form-launch-card" id="security"><div><h3>Password</h3><p className="muted">Choose a new password whenever you need to update account security.</p>{done && <p className="message success" role="status">Your password has been changed.</p>}</div><button className="button button-outline" type="button" onClick={() => setOpen(true)}>Change password</button></section>}
    {open && <ChangePasswordDialog token={token} forced={forced} onClose={() => setOpen(false)} onChanged={changed} />}
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
    <section className="panel account-panel form-launch-card" id="personal-details"><div><h3>Your personal details</h3><p>{incomplete.length ? `${incomplete.length} detail${incomplete.length === 1 ? " is" : "s are"} still missing.` : "Your contact and emergency details are up to date."}</p>{notice && <p className="message success" role="status">{notice}</p>}</div><button className="button button-coral" type="button" onClick={() => { setError(""); setOpen(true); }}>{incomplete.length ? "Complete details" : "Edit details"}</button></section>
    {open && <ModalDialog title="Your personal details" onClose={() => setOpen(false)}>{profileForm}</ModalDialog>}
  </>;
}

function EmploymentCard({ token, profile }) {
  return <section className="panel account-panel" id="employment">
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

function currentClockTime() {
  return new Date().toTimeString().slice(0, 5);
}

function runningTime(start, now) {
  if (!now) return "00:00:00";
  const seconds = Math.max(0, Math.floor((now - new Date(start).getTime()) / 1000));
  const hours = String(Math.floor(seconds / 3600)).padStart(2, "0");
  const minutes = String(Math.floor((seconds % 3600) / 60)).padStart(2, "0");
  return `${hours}:${minutes}:${String(seconds % 60).padStart(2, "0")}`;
}

function TimeClockCard({ token }) {
  const [day, setDay] = useState(null);
  const [shift, setShift] = useState("day");
  const [checkInTime, setCheckInTime] = useState(currentClockTime);
  const [checkOutTime, setCheckOutTime] = useState(currentClockTime);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [now, setNow] = useState(0);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchMyAttendance(token).then((result) => {
      if (!cancelled) {
        setDay(result);
        if ((result.shifts || []).some((item) => item.shift === "night" && !item.check_out_at)) setShift("night");
      }
    })
      .catch((err) => { if (!cancelled) setError(err.message); });
    return () => { cancelled = true; };
  }, [token]);

  async function clock(action) {
    if (busy) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      if (day?.workplace_configured) setBusy("locating");
      const position = day?.workplace_configured ? await positionOrNull() : null;
      setBusy(true);
      const result = await clockMyAttendance(token, action, shift, action === "check_in" ? checkInTime : checkOutTime, position);
      setDay(result);
      const where = locationText(result.attendance, action);
      setNotice(`${label(shift)} shift ${action === "check_in" ? "started" : "completed"}${where ? ` · ${where}` : ""}.`);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const shifts = day?.shifts || (day?.attendance ? [day.attendance] : []);
  const attendance = shifts.find((item) => item.shift === shift);
  const checkedIn = Boolean(attendance?.check_in_at);
  const checkedOut = Boolean(attendance?.check_out_at);
  return <section className="panel account-panel time-clock-card" id="attendance">
    <div className="time-clock-heading"><div><p className="eyebrow dark-eyebrow">TODAY</p><h3>{label(shift)} shift</h3></div>
      <span className={`status-badge ${checkedOut ? "status-signed" : checkedIn ? "status-sent" : "status-draft"}`}>{checkedOut ? "Shift completed" : checkedIn ? "Checked in" : "Not checked in"}</span>
    </div>
    <p>{day?.date ? longDate(day.date) : "Loading today’s attendance…"}</p>
    <div className="shift-tabs" aria-label="Choose attendance shift">
      {["day", "night"].map((item) => <button key={item} className={shift === item ? "active" : ""} type="button" onClick={() => { setShift(item); setError(""); setNotice(""); }}>{label(item)} shift</button>)}
    </div>
    {error && <p className="message error" role="alert">{error}</p>}
    {notice && <p className="message success" role="status">{notice}</p>}
    {day?.workplace_configured && !checkedOut && <p className="muted">Your location is checked against the office area ({day.workplace_radius_m} m) when you check in or out.</p>}
    {attendance && <dl className="clock-times">
      <dt>Check-in</dt><dd>{timeOf(attendance?.check_in_at)} <LocationStatus record={attendance} prefix="check_in" /></dd>
      <dt>Check-out</dt><dd>{timeOf(attendance?.check_out_at)} <LocationStatus record={attendance} prefix="check_out" /></dd>
      <dt>Hours worked</dt><dd>{checkedOut ? attendance.hours_worked : runningTime(attendance.check_in_at, now)}</dd>
    </dl>}
    {checkedIn && !checkedOut && <div className="live-shift-timer" aria-live="off"><span>Time in office</span><strong>{runningTime(attendance.check_in_at, now)}</strong><small>Counting live</small></div>}
    {day && !checkedIn && <div className="shift-clock-action"><label htmlFor={`${shift}-check-in-time`}>Check-in time</label><input id={`${shift}-check-in-time`} type="time" value={checkInTime} onChange={(event) => setCheckInTime(event.target.value)} /><button className="button button-coral" disabled={busy || !checkInTime} type="button" onClick={() => clock("check_in")}>{busy === "locating" ? "Checking location…" : busy ? "Checking in…" : "Check in"}</button></div>}
    {day && checkedIn && !checkedOut && <div className="shift-clock-action"><label htmlFor={`${shift}-check-out-time`}>Check-out time</label><input id={`${shift}-check-out-time`} type="time" value={checkOutTime} onChange={(event) => setCheckOutTime(event.target.value)} /><button className="button button-coral" disabled={busy || !checkOutTime} type="button" onClick={() => clock("check_out")}>{busy === "locating" ? "Checking location…" : busy ? "Checking out…" : "Check out"}</button></div>}
    {day && <div className="shift-day-summary"><strong>Total hours today: {day.total_hours || "0.00"}</strong>{shifts.length > 0 && <div>{shifts.map((item) => <span key={item.id}>{label(item.shift)}: {item.check_out_at ? `${item.hours_worked} hours` : "In progress"}</span>)}</div>}</div>}
  </section>;
}

function LeaveManagementCard({ token }) {
  const [leave, setLeave] = useState(null);
  const [form, setForm] = useState({ leave_type: "annual", start_date: today(), end_date: today(), reason: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [requestOpen, setRequestOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [previewing, setPreviewing] = useState(null);
  const [confirm, confirmation] = useConfirm();

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
      const saved = editing
        ? await updateMyLeave(token, editing.id, form)
        : await submitMyLeave(token, form);
      setLeave((current) => ({ ...current, requests: editing
        ? current.requests.map((item) => item.id === saved.id ? saved : item)
        : [saved, ...current.requests] }));
      setForm({ leave_type: "annual", start_date: today(), end_date: today(), reason: "" });
      setNotice(editing ? "Your changes have been saved and emailed to your employer." : "Your leave request has been sent to your employer for review by email.");
      setEditing(null);
      setRequestOpen(false);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function cancel(record) {
    if (!await confirm({ title: "Cancel leave request?", message: `Cancel your ${label(record.leave_type).toLowerCase()} leave request? Your employer will be notified.`, confirmLabel: "Cancel request" })) return;
    setBusy(true);
    setError("");
    try {
      await cancelMyLeave(token, record.id);
      setLeave((current) => ({ ...current, requests: current.requests.filter((item) => item.id !== record.id) }));
      setNotice("The pending leave request was cancelled and your employer was emailed.");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const requests = leave?.requests || [];
  const upcoming = requests.filter((item) => item.end_date >= today());
  const history = requests.filter((item) => item.end_date < today());

  function edit(record) {
    setEditing(record);
    setForm({ leave_type: record.leave_type, start_date: record.start_date, end_date: record.end_date, reason: record.reason || "" });
    setError("");
    setPreviewing(null);
    setRequestOpen(true);
  }

  const requestRows = (rows) => rows.length ? <div className="leave-history-list">{rows.map((item) => <div className="leave-history-row" key={item.id}>
    <div><strong>{label(item.leave_type)}</strong><span>{item.start_date} to {item.end_date} · {item.days_requested} working day{Number(item.days_requested) === 1 ? "" : "s"}</span>{item.status !== "pending" && decisionText(item.status, item.decided_by, item.decided_at) && <small>{decisionText(item.status, item.decided_by, item.decided_at)}</small>}{item.decision_notes && <small>{item.decision_notes}</small>}</div>
    <div><span className={`status-badge status-${item.status}`}>{label(item.status)}</span><button className="text-button" type="button" onClick={() => setPreviewing(item)}>Preview</button>{item.status === "pending" && <><button className="text-button" disabled={busy} type="button" onClick={() => edit(item)}>Edit</button><button className="text-button danger-link" disabled={busy} type="button" onClick={() => cancel(item)}>Cancel</button></>}</div>
  </div>)}</div> : <p className="empty-state">No leave requests in this section.</p>;

  return <section className="leave-account-section" id="leave">
    <div className="section-heading compact-heading"><div><p className="eyebrow dark-eyebrow">TIME OFF</p><h2>Leave management</h2><p>Request leave whenever you need it and follow your employer’s decision.</p></div><button className="button button-coral" type="button" onClick={() => { setEditing(null); setForm({ leave_type: "annual", start_date: today(), end_date: today(), reason: "" }); setError(""); setRequestOpen(true); }}>Request time off</button></div>
    {error && <p className="message error" role="alert">{error}</p>}
    {notice && <p className="message success" role="status">{notice}</p>}
    {requestOpen && <ModalDialog title={editing ? "Edit leave request" : "Request time off"} onClose={() => { setRequestOpen(false); setEditing(null); }}><form className="account-panel leave-request-form" onSubmit={submit}>
      <h3>{editing ? "Edit leave request" : "Request time off"}</h3>
      <fieldset className="auth-fields" disabled={busy}>
        <label htmlFor="leave-type">Leave type</label><select id="leave-type" value={form.leave_type} onChange={(event) => setForm({ ...form, leave_type: event.target.value })}><option value="annual">Annual leave</option><option value="sick">Sick leave</option><option value="maternity">Maternity leave</option><option value="unpaid">Unpaid leave</option></select>
        <div className="leave-date-fields"><div><label htmlFor="leave-start">Start date</label><input id="leave-start" type="date" min={today()} value={form.start_date} onChange={(event) => setForm({ ...form, start_date: event.target.value })} required /></div><div><label htmlFor="leave-end">End date</label><input id="leave-end" type="date" min={form.start_date} value={form.end_date} onChange={(event) => setForm({ ...form, end_date: event.target.value })} required /></div></div>
        <label htmlFor="leave-reason">Reason (optional)</label><textarea id="leave-reason" rows="3" value={form.reason} onChange={(event) => setForm({ ...form, reason: event.target.value })} />
        <button className="button button-coral" type="submit" disabled={busy}>{busy ? "Saving…" : editing ? "Save changes" : "Submit leave request"}</button>
      </fieldset>
    </form></ModalDialog>}
    {previewing && <ModalDialog title="Leave request" onClose={() => setPreviewing(null)}><section className="account-panel leave-preview">
      <h3>{label(previewing.leave_type)} leave</h3>
      <dl><dt>Start date</dt><dd>{previewing.start_date}</dd><dt>End date</dt><dd>{previewing.end_date}</dd><dt>Working days</dt><dd>{previewing.days_requested}</dd><dt>Status</dt><dd>{label(previewing.status)}</dd>{previewing.status !== "pending" && previewing.decided_at && <><dt>Decision</dt><dd>{decisionText(previewing.status, previewing.decided_by, previewing.decided_at)}</dd></>}<dt>Reason</dt><dd>{previewing.reason || "No reason provided"}</dd>{previewing.decision_notes && <><dt>Employer notes</dt><dd>{previewing.decision_notes}</dd></>}</dl>
      {previewing.status === "pending" && <button className="button button-coral" type="button" onClick={() => edit(previewing)}>Edit request</button>}
    </section></ModalDialog>}
    {confirmation}
    {leave && <div className="leave-lists"><section className="panel account-panel"><h3>Upcoming and current</h3>{requestRows(upcoming)}</section><section className="panel account-panel"><h3>Previous absences</h3>{requestRows(history)}</section></div>}
  </section>;
}

function contractAttentionCount(contracts) {
  return contracts.filter((contract) => contract.signature_status === "sent"
    || contract.termination?.initiated_by === "employer" && contract.termination.status === "awaiting_acknowledgement").length;
}

function ContractsCard({ token, profile, onSigned, onAttentionChange }) {
  const [contracts, setContracts] = useState([]);
  const [signing, setSigning] = useState(null);
  const [signature, setSignature] = useState("");
  const [signerName, setSignerName] = useState(`${profile.first_name} ${profile.last_name}`.trim());
  const [accepted, setAccepted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [terminationContract, setTerminationContract] = useState(null);
  const [terminationForm, setTerminationForm] = useState({ reason: "", proposed_last_working_date: today() });
  const [confirm, confirmation] = useConfirm();

  useEffect(() => {
    onAttentionChange?.(contractAttentionCount(contracts));
  }, [contracts, onAttentionChange]);

  useEffect(() => {
    let cancelled = false;
    let firstLoad = true;
    const loadContracts = () => fetchMyContracts(token).then((rows) => {
      if (cancelled) return;
      setContracts(rows);
      if (firstLoad) {
        firstLoad = false;
        const requested = Number(new URLSearchParams(window.location.search).get("contract"));
        const contract = rows.find((row) => row.id === requested && row.signature_status === "sent");
        if (contract) {
          setSigning(contract.id);
          setTimeout(() => document.getElementById(`contract-${contract.id}`)?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
        }
      }
    }).catch((err) => { if (!cancelled) setError(err.message); });
    loadContracts();
    const timer = window.setInterval(loadContracts, 10000);
    return () => { cancelled = true; window.clearInterval(timer); };
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
    if (!await confirm({ title: "Sign contract?", message: `Sign “${contract.title}”? Your digital signature and signing time will be recorded.`, confirmLabel: "Sign contract" })) return;
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
      onSigned?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function requestTermination(event) {
    event.preventDefault();
    if (busy || !terminationContract) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const saved = await requestMyContractTermination(token, terminationContract.id, terminationForm);
      setContracts((current) => current.map((row) => row.id === saved.id ? saved : row));
      setTerminationContract(null);
      setTerminationForm({ reason: "", proposed_last_working_date: today() });
      setNotice("Your termination request was sent to your employer for review.");
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  async function acknowledgeTermination(contract) {
    if (!await confirm({ title: "Acknowledge termination?", message: `Acknowledge the proposed last working date of ${contract.termination.proposed_last_working_date}? The contract will be marked Terminated by Mutual Agreement.`, confirmLabel: "Acknowledge" })) return;
    setBusy(true);
    setError("");
    try {
      const saved = await acknowledgeMyContractTermination(token, contract.id);
      setContracts((current) => current.map((row) => row.id === saved.id ? saved : row));
      setNotice("The termination was acknowledged. The contract is terminated by mutual agreement.");
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  if (!contracts.length && !error) return <section className="contracts-account-section" id="contracts"><div className="section-heading compact-heading"><div><p className="eyebrow dark-eyebrow">DOCUMENTS</p><h2>Your contract</h2><p>Your workspace will open after you sign your employment contract.</p></div></div><section className="panel account-panel"><h3>No contract is ready yet</h3><p>Your employer has not sent a contract for your signature. You will be able to access the rest of the workspace after it is sent and signed.</p></section></section>;
  return <section className="contracts-account-section" id="contracts">
    <div className="section-heading compact-heading"><div>
      <p className="eyebrow dark-eyebrow">DOCUMENTS</p>
      <h2>Your contract</h2>
      <p>Read every contract completely before adding your digital signature.</p>
    </div></div>
    {error && <p className="message error" role="alert">{error}</p>}
    {notice && <p className="message success" role="status">{notice}</p>}
    {contractAttentionCount(contracts) > 0 && <div className="attention-banner" role="status"><span className="attention-badge">{contractAttentionCount(contracts)}</span><div><strong>Your contract needs attention</strong><p>Open the highlighted contract and complete the action shown inside it.</p></div></div>}
    {contracts.map((contract) => <article className={`panel employee-contract-card${contractAttentionCount([contract]) ? " attention-card" : ""}`} id={`contract-${contract.id}`} key={contract.id}>
      <div className="employee-contract-summary">
        <div><h3>{contract.title}</h3><p className="muted">From {contract.business_name} · Effective {contract.start_date}</p></div>
        <span className={`status-badge ${contract.status === "terminated_mutual" ? "status-ended" : contract.signature_status === "sent" || contract.worker_approval_status !== "approved" ? "status-pending" : "status-approved"}`}>{contract.status === "terminated_mutual" ? "Terminated by Mutual Agreement" : contract.signature_status === "sent" ? "Awaiting your signature" : contract.worker_approval_status === "approved" ? "Approved to start work" : "Waiting for employer approval"}</span>
      </div>
      {contract.employer_message && <div className="message"><strong>Message from your employer</strong><p>{contract.employer_message}</p></div>}
      {(contract.signed_at || contract.worker_approved_at) && <p className="muted contract-approvals">{contract.signed_at && `Signed by ${contract.signer_name || "you"} on ${new Date(contract.signed_at).toLocaleString()}`}{contract.signed_at && contract.worker_approved_at && " · "}{contract.worker_approved_at && decisionText("approved", contract.worker_approved_by, contract.worker_approved_at)}</p>}
      {contract.monthly_salary && <p className="muted">Monthly salary: <strong>{money(contract.monthly_salary, contract.salary_currency)}</strong></p>}
      {contract.signature_status === "signed" && contract.worker_approval_status !== "approved" && <div className="message"><strong>Waiting for employer approval</strong><p>Your contract is signed. Your employer has been emailed and must approve you as a worker before the rest of the workspace opens.</p></div>}
      {contract.termination && <div className="message contract-termination-summary"><strong>{contract.termination.initiated_by === "employee" ? "Your termination request" : "Termination initiated by employer"}</strong><p>Proposed last working date: {contract.termination.proposed_last_working_date}</p><p>Reason: {contract.termination.reason}</p><p>Status: {label(contract.termination.status)}{contract.termination.responded_at && ` on ${new Date(contract.termination.responded_at).toLocaleString()}`}</p>{contract.termination.response_notes && <p>Response: {contract.termination.response_notes}</p>}</div>}
      <details open={contract.signature_status === "sent"}>
        <summary>Read contract</summary>
        <DigitalContractDocument contract={contract} />
      </details>
      {contract.signature_status === "sent" && (signing === contract.id
        ? <ModalDialog title={`Review and sign ${contract.title}`} wide onClose={() => setSigning(null)}><div className="contract-review-and-sign">
            <section className="contract-review-pane" aria-label="Complete contract to review"><DigitalContractDocument contract={contract} /></section>
            <form className="contract-sign-form" onSubmit={(event) => submit(event, contract)}>
              <h4>Sign this contract</h4>
              <p className="message">Read the complete contract shown here before signing.</p>
              <label htmlFor={`signer-${contract.id}`}>Your full legal name</label>
              <input id={`signer-${contract.id}`} value={signerName} onChange={(event) => setSignerName(event.target.value)} required />
              <label>Draw your signature</label>
              <SignaturePad onChange={setSignature} />
              <label className="signature-consent"><input type="checkbox" checked={accepted} onChange={(event) => setAccepted(event.target.checked)} required />
                <span>I have read this complete contract and agree to sign it electronically.</span>
              </label>
              <div className="form-actions"><button className="button button-coral" disabled={busy} type="submit">{busy ? "Signing…" : "Sign contract"}</button><button className="button button-outline" type="button" onClick={() => setSigning(null)}>Cancel</button></div>
            </form>
          </div></ModalDialog>
        : <button className="button button-coral" type="button" onClick={() => { setSigning(contract.id); setError(""); }}>Sign contract</button>)}
      {contract.signature_status === "signed" && contract.worker_approval_status === "approved" && contract.status === "active" && !["pending", "awaiting_acknowledgement"].includes(contract.termination?.status) && <button className="button button-outline" type="button" disabled={busy} onClick={() => { setTerminationContract(contract); setTerminationForm({ reason: "", proposed_last_working_date: today() }); setError(""); }}>Request termination</button>}
      {contract.termination?.initiated_by === "employer" && contract.termination.status === "awaiting_acknowledgement" && <button className="button button-coral" type="button" disabled={busy} onClick={() => acknowledgeTermination(contract)}>Acknowledge termination</button>}
    </article>)}
    {terminationContract && <ModalDialog title="Request contract termination" onClose={() => setTerminationContract(null)}><form className="record-form" onSubmit={requestTermination}>
      <p>Your employer will review this request before the contract status changes.</p>
      <label htmlFor="termination-date">Proposed last working date</label>
      <input id="termination-date" type="date" min={today()} value={terminationForm.proposed_last_working_date} onChange={(event) => setTerminationForm((current) => ({ ...current, proposed_last_working_date: event.target.value }))} required />
      <label htmlFor="termination-reason">Reason</label>
      <textarea id="termination-reason" rows="5" maxLength="4000" value={terminationForm.reason} onChange={(event) => setTerminationForm((current) => ({ ...current, reason: event.target.value }))} required />
      <div className="form-actions"><button className="button button-coral" type="submit" disabled={busy}>{busy ? "Sending…" : "Send request"}</button><button className="button button-outline" type="button" onClick={() => setTerminationContract(null)}>Cancel</button></div>
    </form></ModalDialog>}
    {confirmation}
  </section>;
}

function employeeViewFromLocation(location) {
  const parts = location.pathname.split("/").filter(Boolean);
  if (parts[1]?.toLowerCase() === "access-control") return "access-control";
  const pathView = parts.length > 1 ? parts.at(-1).toLowerCase() : "";
  const requested = pathView || location.hash.slice(1).toLowerCase();
  if (["contracts", "contract"].includes(requested)) return "contract";
  if (["personal-details", "security", "profile"].includes(requested)) return "profile";
  if (["attendance", "leave", "payroll", "announcements", "calendar"].includes(requested)) return requested;
  return "overview";
}

function EmployeeTopNav({ account, token, onLogout, linked, forced, contractOnly = false, contractAttention = 0, announcementAttention = 0, calendarAttention = 0, view }) {
  const link = (key, label, count = 0) => ({
    label,
    to: key === "overview" ? "/dashboard" : `/dashboard/${key}`,
    selected: view === key,
    badge: count,
    badgeLabel: `${count} items need attention`,
  });
  const items = [
    ...(!contractOnly ? [link("overview", "Overview")] : []),
    ...(contractOnly ? [link("contract", "Contract", contractAttention)] : []),
    ...(linked && !forced && !contractOnly ? [
      link("profile", "Profile"),
      link("attendance", "Attendance / Shifts"),
      link("leave", "Leave"),
      link("payroll", "Payroll"),
      link("contract", "Contract", contractAttention),
      link("announcements", "Announcements", announcementAttention),
      link("calendar", "Calendar", calendarAttention),
      link("access-control", "Access Control"),
    ] : []),
  ];
  const full = linked && !forced && !contractOnly;
  return <DashboardTopNav
    items={items}
    identity={{ eyebrow: account.business_name || "EMPLOYEE WORKSPACE", name: account.display_name || account.username || "Employee", role: account.role_label || "Employee", detail: account.email }}
    navLabel="Employee navigation"
    onLogout={onLogout}
    token={forced ? undefined : token}
    profileTo={full ? "/dashboard/profile" : undefined}
  />;
}

export default function AccountPage({ account, token, onAccountChange, onLogout }) {
  const location = useLocation();
  const navigate = useNavigate();
  const [profile, setProfile] = useState(null);
  const [loadError, setLoadError] = useState("");
  const [contractAttention, setContractAttention] = useState(0);
  const [announcements, setAnnouncements] = useState([]);
  const [calendarEvents, setCalendarEvents] = useState([]);
  const [signOutPrompt, setSignOutPrompt] = useState(null);
  const view = employeeViewFromLocation(location);
  const forced = Boolean(account.must_change_password);
  const contractLocked = Boolean(account.has_employee_record && !account.workspace_approved);

  // An employee still on shift chooses whether signing out also checks them out.
  async function requestSignOut() {
    if (!account.has_employee_record || !account.workspace_approved || forced) { onLogout(); return; }
    try {
      const day = await fetchMyAttendance(token);
      const active = (day.shifts || []).find((item) => item.check_in_at && !item.check_out_at);
      if (active) { setSignOutPrompt({ attendance: active, locate: day.workplace_configured, busy: false, error: "" }); return; }
    } catch {
      // Attendance is unavailable; signing out still goes ahead.
    }
    onLogout();
  }

  async function checkOutAndSignOut() {
    setSignOutPrompt((current) => ({ ...current, busy: true, error: "" }));
    try {
      const position = signOutPrompt.locate ? await positionOrNull() : null;
      await clockMyAttendance(token, "check_out", signOutPrompt.attendance.shift, currentClockTime(), position);
      onLogout();
    } catch (err) {
      setSignOutPrompt((current) => current && { ...current, busy: false, error: err.message });
    }
  }

  const signOutDialog = signOutPrompt && <ModalDialog title="Sign out" onClose={() => { if (!signOutPrompt.busy) setSignOutPrompt(null); }}><section className="record-form">
    <p>You are still checked in to the {label(signOutPrompt.attendance.shift).toLowerCase()} shift since {timeOf(signOutPrompt.attendance.check_in_at)}. Do you want to check out before signing out?</p>
    {signOutPrompt.error && <p className="message error" role="alert">{signOutPrompt.error}</p>}
    <div className="form-actions">
      <button className="button button-coral" type="button" disabled={signOutPrompt.busy} onClick={checkOutAndSignOut}>{signOutPrompt.busy ? "Checking out…" : "Check out and sign out"}</button>
      <button className="button button-outline" type="button" disabled={signOutPrompt.busy} onClick={onLogout}>Sign out without checking out</button>
    </div>
  </section></ModalDialog>;

  const load = useCallback(() => {
    if (!account.has_employee_record || contractLocked) return;
    fetchMyProfile(token).then(setProfile).catch((err) => setLoadError(err.message));
  }, [token, account.has_employee_record, contractLocked]);

  useEffect(load, [load]);
  useEffect(() => {
    if (!account.has_employee_record || forced) return undefined;
    let cancelled = false;
    const refreshAttention = () => fetchMyContracts(token).then((contracts) => {
      if (!cancelled) setContractAttention(contractAttentionCount(contracts));
    }).catch(() => {});
    refreshAttention();
    const timer = window.setInterval(refreshAttention, 10000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [account.has_employee_record, forced, token]);
  useEffect(() => {
    if (!account.workspace_approved || forced) return undefined;
    let cancelled = false;
    const refreshShared = () => Promise.all([fetchMyAnnouncements(token), fetchMyCalendar(token)]).then(([news, events]) => {
      if (!cancelled) { setAnnouncements(news); setCalendarEvents(events); setLoadError(""); }
    }).catch((err) => { if (!cancelled) setLoadError(err.message); });
    refreshShared();
    const timer = window.setInterval(refreshShared, 10000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [account.workspace_approved, forced, token]);
  useEffect(() => {
    const legacy = location.hash.slice(1).toLowerCase();
    const legacyView = legacy === "contracts" ? "contract" : legacy;
    if (location.pathname.toLowerCase().replace(/\/$/, "") === "/dashboard" && ["profile", "attendance", "leave", "contract", "announcements", "calendar"].includes(legacyView)) {
      navigate(`/dashboard/${legacyView}${location.search}`, { replace: true });
    }
  }, [location.hash, location.pathname, location.search, navigate]);
  useEffect(() => {
    if (contractLocked && location.pathname.toLowerCase() !== "/dashboard/contract") {
      navigate(`/dashboard/contract${location.search}`, { replace: true });
    }
  }, [contractLocked, location.pathname, location.search, navigate]);
  useEffect(() => {
    if (!contractLocked || forced) return undefined;
    const timer = window.setInterval(() => {
      fetchAccount(token).then((latest) => {
        if (latest.workspace_approved) onAccountChange(token, latest);
      }).catch(() => {});
    }, 5000);
    return () => window.clearInterval(timer);
  }, [contractLocked, forced, onAccountChange, token]);
  // Until the temporary password is replaced, the only thing on offer is
  // replacing it.
  if (forced) {
    return <><EmployeeTopNav account={account} onLogout={onLogout} linked={account.has_employee_record} forced view="overview" />
      <main className="dashboard-main employee-main topnav-main"><section className="workspace account-workspace">
      <div className="section-heading" id="overview">
        <div>
          <p className="eyebrow dark-eyebrow">WELCOME</p>
          <h2>Hello, {account.display_name || account.username}</h2>
          <p className="workspace-identity-inline"><strong>{account.display_name || account.username}</strong><span>{account.role_label || "Employee"}</span></p>
          {account.business_name && <p>You have been added to {account.business_name}.</p>}
        </div>
      </div>
      <PasswordCard token={token} forced onChanged={onAccountChange} />
      </section></main>
    </>;
  }


  if (contractLocked) {
    return <><EmployeeTopNav account={account} token={token} onLogout={onLogout} linked contractOnly contractAttention={contractAttention} view="contract" />
      <main className="dashboard-main employee-main topnav-main"><section className="workspace account-workspace">
        {loadError && <p className="message error" role="alert">{loadError}</p>}
        <ContractsCard token={token} profile={{ first_name: account.display_name || account.username, last_name: "" }} onSigned={() => onAccountChange(token, { ...account, has_signed_contract: true })} onAttentionChange={setContractAttention} />
      </section></main>
    </>;
  }

  async function openAnnouncement(item) {
    const saved = await markMyAnnouncementRead(token, item.id);
    setAnnouncements((current) => current.map((row) => row.id === saved.id ? saved : row));
    return saved;
  }

  async function clearAnnouncements() {
    setAnnouncements(await markAllMyAnnouncementsRead(token));
  }

  async function clearCalendar() {
    setCalendarEvents(await markAllMyCalendarRead(token));
  }

  async function openCalendarEvent(item) {
    const saved = await markMyCalendarEventRead(token, item.id);
    setCalendarEvents((current) => current.map((row) => row.id === saved.id ? saved : row));
    return saved;
  }

  const unreadAnnouncements = announcements.filter((item) => !item.is_read).length;
  const unreadCalendarEvents = calendarEvents.filter((item) => !item.is_read).length;

  return <><EmployeeTopNav account={account} token={token} onLogout={requestSignOut} linked={account.has_employee_record} forced={false} contractAttention={contractAttention} announcementAttention={unreadAnnouncements} calendarAttention={unreadCalendarEvents} view={view} />
    <main className="dashboard-main employee-main topnav-main"><section className="workspace account-workspace">
    {view === "overview" && <><div className="section-heading" id="overview">
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

    {profile && <EmploymentCard token={token} profile={profile} />}</>}

    {loadError && <p className="message error" role="alert">{loadError}</p>}

    {profile && view === "profile" && <><div className="section-heading"><div><p className="eyebrow dark-eyebrow">MY ACCOUNT</p><h2>Profile</h2><p>Manage your personal and sign-in details.</p></div></div><ProfileCard token={token} profile={profile} onSaved={setProfile} /><PasswordCard token={token} forced={false} onChanged={onAccountChange} /></>}
    {profile && view === "attendance" && <><div className="section-heading"><div><p className="eyebrow dark-eyebrow">WORKDAY</p><h2>Attendance</h2></div></div><TimeClockCard token={token} /></>}
    {profile && view === "leave" && <LeaveManagementCard token={token} />}
    {profile && view === "payroll" && <EmployeePayroll token={token} />}
    {profile && view === "contract" && <ContractsCard token={token} profile={profile} onAttentionChange={setContractAttention} />}
    {profile && view === "announcements" && <EmployeeAnnouncements announcements={announcements} onOpen={openAnnouncement} onClearAll={clearAnnouncements} />}
    {profile && view === "calendar" && <CompanyCalendar events={calendarEvents} onEventOpen={openCalendarEvent} onClearAll={clearCalendar} />}
    {profile && view === "access-control" && <AccessControl token={token} role="employee" />}

    </section></main>
    {signOutDialog}
  </>;
}
