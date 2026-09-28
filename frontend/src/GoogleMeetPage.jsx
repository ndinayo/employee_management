import { useState } from "react";
import { saveRecord } from "./api";
import { label, today } from "./managerConfig";

const purposes = ["interview", "team_meeting", "presentation", "training", "other"];

function compactDateTime(date, time) {
  return `${date.replaceAll("-", "")}T${time.replace(":", "")}00`;
}

export default function GoogleMeetPage({ token, employees, onChange }) {
  const [form, setForm] = useState({ purpose: "interview", audience: "external", title: "Interview", guest_emails: "", all_employees: false, employee_ids: [], date: today(), start_time: "09:00", end_time: "10:00", details: "" });
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const activeEmployees = employees.filter((employee) => employee.is_active);

  function update(name, value) {
    setForm((current) => {
      const next = { ...current, [name]: value };
      if (name === "purpose" && (!current.title || purposes.some((purpose) => label(purpose) === current.title))) {
        next.title = label(value);
        if (value !== "interview") next.audience = "employees";
      }
      return next;
    });
  }

  function toggleEmployee(id) {
    setForm((current) => ({ ...current, employee_ids: current.employee_ids.includes(id)
      ? current.employee_ids.filter((value) => value !== id)
      : [...current.employee_ids, id] }));
  }

  async function continueToGoogle(event) {
    event.preventDefault();
    setError("");
    setNotice("");
    const selectedEmployees = form.all_employees ? activeEmployees : activeEmployees.filter((employee) => form.employee_ids.includes(employee.id));
    const guests = form.audience === "employees"
      ? selectedEmployees.map((employee) => employee.email).filter(Boolean)
      : form.guest_emails.split(/[;,\s]+/).map((email) => email.trim()).filter(Boolean);
    const invalid = guests.find((email) => !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email));
    if (!guests.length) { setError(form.audience === "employees" ? "Select at least one employee with an email address." : "Enter at least one guest email address."); return; }
    if (invalid) { setError(`${invalid} is not a valid email address.`); return; }
    if (form.end_time <= form.start_time) { setError("End time must be later than start time."); return; }

    const query = new URLSearchParams({
      action: "TEMPLATE",
      text: form.title,
      dates: `${compactDateTime(form.date, form.start_time)}/${compactDateTime(form.date, form.end_time)}`,
      details: `${label(form.purpose)}\n\n${form.details}`.trim(),
      ctz: Intl.DateTimeFormat().resolvedOptions().timeZone,
    });
    guests.forEach((email) => query.append("add", email));
    const googleTab = window.open("about:blank", "_blank");
    if (googleTab) googleTab.opener = null;
    setBusy(true);
    try {
      if (form.audience === "employees") {
        const category = ["presentation", "training"].includes(form.purpose) ? form.purpose : "meeting";
        const saved = await saveRecord(token, "calendar-events", {
          title: form.title, category, date: form.date, end_date: form.date,
          start_time: form.start_time, end_time: form.end_time, location: "Google Meet",
          description: `${form.details}${form.details ? "\n\n" : ""}A Google Meet invitation will be sent by Google Calendar.`,
          all_employees: form.all_employees, employee_ids: form.all_employees ? [] : form.employee_ids,
        });
        onChange("calendar-events", saved);
        setNotice(`Meeting added to ${form.all_employees ? "all employee calendars" : `${selectedEmployees.length} employee calendar${selectedEmployees.length === 1 ? "" : "s"}`}. Their Calendar notifications are now active.`);
      }
      const destination = `https://calendar.google.com/calendar/render?${query}`;
      if (googleTab) googleTab.location.replace(destination);
      else window.open(destination, "_blank", "noopener,noreferrer");
    } catch (err) {
      if (googleTab) googleTab.close();
      setError(err.message);
    } finally { setBusy(false); }
  }

  return <section className="google-meet-page">
    <div className="section-heading"><div><p className="eyebrow dark-eyebrow">VIDEO MEETING</p><h2>Create Google Meet</h2><p>Prepare a meeting for an employee, candidate, or external guest.</p></div></div>
    {error && <p className="message error" role="alert">{error}</p>}
    {notice && <p className="message success" role="status">{notice}</p>}
    <section className="panel meet-create-card">
      <form className="record-form" onSubmit={continueToGoogle}>
        <div className="record-fields">
          <div><label htmlFor="meet-purpose">What is this meeting for?</label><select id="meet-purpose" value={form.purpose} onChange={(event) => update("purpose", event.target.value)}>{purposes.map((purpose) => <option key={purpose} value={purpose}>{label(purpose)}</option>)}</select></div>
          <div><label htmlFor="meet-title">Meeting title</label><input id="meet-title" value={form.title} onChange={(event) => update("title", event.target.value)} required /></div>
          <div className="field-wide"><label htmlFor="meet-audience">Who is invited?</label><select id="meet-audience" value={form.audience} onChange={(event) => update("audience", event.target.value)}><option value="employees">Employees</option><option value="external">External guest</option></select></div>
          {form.audience === "external" ? <div className="field-wide"><label htmlFor="meet-guests">Guest email</label><input id="meet-guests" type="text" value={form.guest_emails} onChange={(event) => update("guest_emails", event.target.value)} placeholder="candidate@example.com" required /><small className="field-hint">For several guests, separate email addresses with commas. External meetings do not appear in employee calendars.</small></div> : <div className="field-wide employee-meet-picker"><label>Employees</label><label className="meet-employee-option"><input type="checkbox" checked={form.all_employees} onChange={(event) => update("all_employees", event.target.checked)} /> <span>All active employees</span></label>{!form.all_employees && <div className="meet-employee-list">{activeEmployees.map((employee) => <label className="meet-employee-option" key={employee.id}><input type="checkbox" checked={form.employee_ids.includes(employee.id)} onChange={() => toggleEmployee(employee.id)} /><span><strong>{employee.first_name} {employee.last_name}</strong><small>{employee.email}</small></span></label>)}</div>}<small className="field-hint">Selected employees receive an unread Calendar notification and are added as Google Calendar guests.</small></div>}
          <div><label htmlFor="meet-date">Date</label><input id="meet-date" type="date" min={today()} value={form.date} onChange={(event) => update("date", event.target.value)} required /></div>
          <div className="meet-time-fields"><label htmlFor="meet-start">Start time</label><input id="meet-start" type="time" value={form.start_time} onChange={(event) => update("start_time", event.target.value)} required /></div>
          <div className="meet-time-fields"><label htmlFor="meet-end">End time</label><input id="meet-end" type="time" value={form.end_time} onChange={(event) => update("end_time", event.target.value)} required /></div>
          <div className="field-wide"><label htmlFor="meet-details">Message or agenda (optional)</label><textarea id="meet-details" rows="5" value={form.details} onChange={(event) => update("details", event.target.value)} placeholder="Add interview instructions or the meeting agenda." /></div>
        </div>
        <div className="meet-google-note"><strong>Final step in Google Calendar</strong><p>Click Add Google Meet video conferencing, then Save. Google will email the invitation and meeting link to every guest.</p></div>
        <button className="button button-coral" type="submit" disabled={busy}>{busy ? "Preparing meeting..." : "Continue to Google Calendar"}</button>
      </form>
    </section>
  </section>;
}
