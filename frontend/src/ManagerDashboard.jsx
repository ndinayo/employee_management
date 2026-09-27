import { useEffect, useRef, useState } from "react";
import ContractViewer from "./ContractViewer";
import { DigitalContractDocument, RichTextEditor } from "./DigitalContract";
import ModalDialog from "./components/ModalDialog";
import { Link, NavLink, Navigate, Route, Routes } from "react-router";
import { deleteRecord, downloadContract, fetchEmailSettings, fetchEmployeePhoto, fetchRecords, fetchReports, markSalaryPaid, requestNewContractSignature, resendContractSignatureEmail, saveEmailSettings, saveRecord, sendContractForSignature } from "./api";
import { isWeekend, label, longDate, modules, money, shiftDate, today } from "./managerConfig";

function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function clockTime(value) {
  return value ? new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—";
}

function exportCsv(filename, columns, rows) {
  const escape = (value) => {
    let text = String(value ?? "");
    if (/^[=+@\-\t\r]/.test(text)) text = `'${text}`;
    return `"${text.replaceAll('"', '""')}"`;
  };
  const csv = [columns.map((column) => column.title), ...rows.map((row) => columns.map((column) => column.value(row)))];
  saveBlob(new Blob(["\uFEFF", csv.map((row) => row.map(escape).join(",")).join("\r\n")], { type: "text/csv;charset=utf-8" }), filename);
}

// Photos live behind the manager-only API, so they cannot be used as a plain
// <img src>. Fetch the bytes with the token and hand React an object URL.
function Avatar({ person, token }) {
  // Tracking which photo the object URL belongs to keeps a replaced photo from
  // briefly rendering against a URL the cleanup has already revoked.
  const [loaded, setLoaded] = useState({ name: "", url: "" });
  useEffect(() => {
    if (!person.photo_name || !token) return;
    let objectUrl = "";
    let cancelled = false;
    fetchEmployeePhoto(token, person.id).then((blob) => {
      if (cancelled) return;
      objectUrl = URL.createObjectURL(blob);
      setLoaded({ name: person.photo_name, url: objectUrl });
    }).catch(() => {});
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [person.id, person.photo_name, token]);
  if (loaded.url && loaded.name === person.photo_name) return <img className="avatar" src={loaded.url} alt="" />;
  return <span className="avatar avatar-initials" aria-hidden="true">{`${person.first_name?.[0] || ""}${person.last_name?.[0] || ""}`.toUpperCase() || "?"}</span>;
}

function Cell({ column, row, token }) {
  const value = column.value(row);
  const secondary = column.secondary && <small>{column.secondary(row)}</small>;
  if (column.avatar) {
    return <span className="name-cell"><Avatar person={row} token={token} /><span>{value || "—"}{secondary}</span></span>;
  }
  return <>
    {column.badge ? <span className={`status-badge status-${String(value).toLowerCase()}`}>{value}</span> : value || "—"}
    {secondary}
  </>;
}

function DataTable({ columns, rows, actions, token, empty = "No records yet." }) {
  if (!rows.length) return <p className="empty-state">{empty}</p>;
  return <div className="table-scroll"><table>
    <thead><tr>{columns.map((column) => <th key={column.title} scope="col">{column.title}</th>)}{actions && <th scope="col">Actions</th>}</tr></thead>
    <tbody>{rows.map((row, index) => <tr key={row.id ?? index}>
      {columns.map((column) => <td key={column.title}><Cell column={column} row={row} token={token} /></td>)}
      {actions && <td><div className="row-actions">{actions(row)}</div></td>}
    </tr>)}</tbody>
  </table></div>;
}

function Payslip({ record, onClose }) {
  const dialog = useRef(null);
  useEffect(() => {
    const element = dialog.current;
    element.showModal();
    return () => element.close();
  }, []);
  return <dialog ref={dialog} className="payslip-dialog" onCancel={onClose} aria-labelledby="payslip-title">
    <div className="payslip-actions no-print">
      <button type="button" className="button button-coral" onClick={() => window.print()}>Print / save as PDF</button>
      <button type="button" className="button button-outline" onClick={onClose}>Close</button>
    </div>
    <article className="payslip">
      <p className="eyebrow dark-eyebrow">EMPLOYEE MANAGEMENT</p>
      <h2 id="payslip-title">{record.status === "draft" ? "Draft payslip" : "Payslip"} #{String(record.id).padStart(6, "0")}</h2>
      <p>{record.period_start} to {record.period_end}</p>
      <div className="payslip-person"><strong>{record.employee_name}</strong><p>{record.job_title} · {record.department}</p><p>{record.employee_email}</p></div>
      <dl className="pay-breakdown">
        <div><dt>Base salary</dt><dd>{money(record.base_salary, record.currency)}</dd></div>
        <div><dt>Allowances</dt><dd>{money(record.allowances, record.currency)}</dd></div>
        <div><dt>Gross pay</dt><dd>{money(record.gross_pay, record.currency)}</dd></div>
        <div><dt>Deductions</dt><dd>{money(record.deductions, record.currency)}</dd></div>
        <div className="net-pay"><dt>Net pay</dt><dd>{money(record.net_pay, record.currency)}</dd></div>
      </dl>
      <p><strong>{label(record.status)}</strong>{record.paid_date && ` on ${record.paid_date}`}</p>
      {record.status === "draft" && <p className="muted">Preview only. Payment has not been recorded.</p>}
      {record.notes && <p className="preserve-lines">{record.notes}</p>}
    </article>
  </dialog>;
}

function DigitalContractDialog({ contract, onClose }) {
  const dialog = useRef(null);
  useEffect(() => {
    const element = dialog.current;
    element.showModal();
    return () => element.close();
  }, []);
  return <dialog ref={dialog} className="digital-contract-dialog" onCancel={onClose} aria-label={contract.title}>
    <div className="payslip-actions">
      <button className="button button-outline" type="button" onClick={onClose}>Close</button>
    </div>
    <DigitalContractDocument contract={contract} />
  </dialog>;
}

function RecordField({ field, value, onChange, employees }) {
  const id = `record-${field.name}`;
  const props = { id, name: field.name, value: value ?? "", required: !field.optional, onChange: (event) => onChange(field.name, event.target.value) };
  let input;
  if (field.type === "employee") {
    input = <select {...props}><option value="">Select an employee</option>{employees.map((employee) => <option key={employee.id} value={employee.id}>{employee.first_name} {employee.last_name}{!employee.is_active && " (inactive)"}</option>)}</select>;
  } else if (field.type === "select") {
    input = <select {...props}>{field.options.map(([key, title]) => <option key={key} value={key}>{title}</option>)}</select>;
  } else if (field.type === "textarea") {
    input = <textarea {...props} rows="3" />;
  } else if (field.type === "richtext") {
    input = <RichTextEditor value={value} onChange={(html) => onChange(field.name, html)} />;
  } else if (field.type === "checkbox") {
    input = <input id={id} type="checkbox" checked={Boolean(value)} onChange={(event) => onChange(field.name, event.target.checked)} />;
  } else if (field.type === "file") {
    input = <input id={id} type="file" accept={field.accept} onChange={(event) => onChange(field.name, event.target.files[0] || null)} />;
  } else {
    input = <input {...props} type={field.type} min={field.min} max={field.max} step={field.step} placeholder={field.placeholder} />;
  }
  return <div className={["textarea", "file", "richtext"].includes(field.type) ? "field-wide" : field.type === "checkbox" ? "checkbox-field" : ""}><label htmlFor={id}>{field.title}{field.optional && field.type !== "file" ? " (optional)" : ""}</label>{input}{field.hint && <small className="field-hint">{field.hint}</small>}</div>;
}

const markable = [["present", "Present"], ["remote", "Remote"], ["absent", "Absent"]];
const rosterStates = [["present", "Present"], ["remote", "Remote"], ["absent", "Absent"], ["leave", "On leave"], ["unrecorded", "Not recorded"]];

function AttendanceRoster({ date, setDate, rows, holiday, busy, token, onMark, onClear }) {
  const latest = today();
  return <section className="panel roster-panel" aria-label="Daily attendance roster">
    <div className="roster-heading">
      <div><h3>Daily roster</h3><p className="muted">{longDate(date)}{holiday ? ` · Holiday: ${holiday.name}` : isWeekend(date) ? " · Weekend" : ""}</p></div>
      <div className="roster-day">
        <button className="button button-outline" type="button" onClick={() => setDate(shiftDate(date, -1))}>← Previous</button>
        <input type="date" aria-label="Roster date" value={date} max={latest} onChange={(event) => event.target.value && setDate(event.target.value)} />
        <button className="button button-outline" type="button" disabled={date >= latest} onClick={() => setDate(shiftDate(date, 1))}>Next →</button>
        <button className="button button-outline" type="button" disabled={date === latest} onClick={() => setDate(latest)}>Today</button>
      </div>
    </div>
    <div className="roster-counts">{rosterStates.map(([key, title]) => <span key={key} className={`status-badge status-${key}`}>{rows.filter((row) => row.state === key).length} {title}</span>)}
      <span className="status-badge status-sent">{rows.filter((row) => row.record?.check_in_at).length} checked in</span>
      <span className="status-badge status-signed">{rows.filter((row) => row.record?.check_out_at).length} completed shift</span>
    </div>
    <DataTable
      columns={[
        { title: "Employee", value: (row) => `${row.first_name} ${row.last_name}`, secondary: (row) => row.department, avatar: true },
        { title: "Status", value: (row) => row.state === "unrecorded" ? "Unrecorded" : row.state === "leave" ? "Leave" : label(row.state), badge: true },
        { title: "Check-in", value: (row) => clockTime(row.record?.check_in_at) },
        { title: "Check-out", value: (row) => clockTime(row.record?.check_out_at) },
        { title: "Hours", value: (row) => row.record?.hours_worked },
        { title: "Notes", value: (row) => row.record?.notes },
      ]}
      rows={rows}
      token={token}
      empty={`No active employees had joined by ${date}.`}
      actions={(row) => row.state === "leave" ? <span className="muted">On approved leave</span> : <>
        {markable.map(([value, title]) => <button key={value} type="button" disabled={busy || row.record?.status === value} onClick={() => onMark(row, value)}>{row.record?.status === value ? `✓ ${title}` : title}</button>)}
        {row.record && <button type="button" className="danger-link" disabled={busy} onClick={() => onClear(row)}>Clear</button>}
      </>}
    />
  </section>;
}

function LeaveBalancesPanel({ balances, token, onChange, onAuthError }) {
  const year = new Date().getFullYear();
  const rows = balances.filter((row) => row.year === year);
  const [drafts, setDrafts] = useState({});
  const [busyId, setBusyId] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function save(row) {
    setBusyId(row.id);
    setError("");
    setNotice("");
    try {
      const saved = await saveRecord(token, "leave-balances", { days_allocated: drafts[row.id] }, row.id);
      onChange("leave-balances", saved);
      setNotice(`${row.employee_name}’s ${label(row.leave_type).toLowerCase()} allowance was updated.`);
    } catch (err) {
      setError(err.message);
      onAuthError(err);
    } finally {
      setBusyId(null);
    }
  }

  return <section className="panel leave-balances-panel">
    <div className="list-heading"><div><h3>Leave balances · {year}</h3><p className="muted">Approved working days are deducted automatically. Unpaid leave has no limit.</p></div></div>
    {error && <p className="message error" role="alert">{error}</p>}
    {notice && <p className="message success" role="status">{notice}</p>}
    {!rows.length ? <p className="empty-state">Add an employee to create leave balances.</p> : <div className="table-scroll"><table><thead><tr><th>Employee</th><th>Leave type</th><th>Used</th><th>Remaining</th><th>Yearly allowance</th></tr></thead><tbody>
      {rows.map((row) => <tr key={row.id}><td>{row.employee_name}</td><td>{label(row.leave_type)}</td><td>{row.used_days}</td><td>{row.unlimited ? "Unlimited" : row.remaining_days}</td><td>{row.unlimited ? "Not limited" : <div className="balance-editor"><input type="number" min="0" max="366" step="0.5" aria-label={`${row.employee_name} ${row.leave_type} allowance`} value={drafts[row.id] ?? row.days_allocated} onChange={(event) => setDrafts((current) => ({ ...current, [row.id]: event.target.value }))} /><button type="button" disabled={busyId === row.id || String(drafts[row.id]) === String(row.days_allocated)} onClick={() => save(row)}>{busyId === row.id ? "Saving…" : "Save"}</button></div>}</td></tr>)}
    </tbody></table></div>}
  </section>;
}

function ResourcePage({ resource, data, token, account, onChange, onAuthError }) {
  const config = modules[resource];
  const [form, setForm] = useState(null);
  const [editing, setEditing] = useState(null);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [payslip, setPayslip] = useState(null);
  const [viewing, setViewing] = useState(null);
  const [digitalViewing, setDigitalViewing] = useState(null);
  const [signatureRequest, setSignatureRequest] = useState(null);
  const [signatureMessage, setSignatureMessage] = useState("");
  const [rosterDate, setRosterDate] = useState(today);
  const formRef = useRef(null);
  const employees = data.employees || [];
  const payMonth = today().slice(0, 7);
  const paidThisMonth = new Set((data.payroll || [])
    .filter((row) => row.status === "paid" && String(row.period_start).slice(0, 7) === payMonth)
    .map((row) => row.employee));
  const roster = resource !== "attendance" ? [] : employees
    .filter((person) => person.is_active && person.date_joined <= rosterDate)
    .map((person) => {
      const record = (data.attendance || []).find((row) => row.employee === person.id && row.date === rosterDate) || null;
      const onLeave = (data.leave || []).some((row) => row.status === "approved" && row.employee === person.id && row.start_date <= rosterDate && row.end_date >= rosterDate);
      return { ...person, record, state: record ? record.status : onLeave ? "leave" : "unrecorded" };
    });
  const holiday = (data.holidays || []).find((row) => row.date === rosterDate);
  // Newest contract first, so an employee row opens their current agreement.
  const contractsFor = (employeeId) => (data.contracts || [])
    .filter((row) => row.employee === employeeId && row.document_name)
    .sort((a, b) => String(b.start_date).localeCompare(String(a.start_date)));
  const rows = (data[resource] || []).map((row) => {
    if (!row.employee || resource === "payroll") return row;
    const employee = employees.find((person) => person.id === row.employee);
    return employee ? { ...row, employee_name: `${employee.first_name} ${employee.last_name}` } : row;
  });
  const visible = rows.filter((row) => (!status || row.status === status) && config.columns.some((column) => `${column.value(row)} ${column.secondary?.(row) || ""}`.toLowerCase().includes(search.trim().toLowerCase())));
  const statusField = config.fields.find((field) => field.name === "status");
  const formFields = resource === "employees"
    ? config.fields.map((field) => field.name !== "email" ? field : {
      ...field,
      hint: account?.email_configured
        ? "We email sign-in details here so they can complete their own profile."
        : "Mail is not set up yet. After you save you will see the password so you can pass it on, or add Gmail in Settings.",
    })
    : config.fields;

  function handleError(err) {
    setError(err.message);
    onAuthError(err);
  }

  function openForm(row = null) {
    setError("");
    setNotice("");
    setEditing(row);
    setForm(row ? Object.fromEntries(config.fields.map((field) => [field.name, field.type === "file" ? null : row[field.name] ?? ""])) : config.defaults());
    setTimeout(() => {
      formRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      formRef.current?.querySelector("input, select")?.focus({ preventScroll: true });
    }, 0);
  }

  function updateField(name, value) {
    setForm((current) => {
      const next = { ...current, [name]: value };
      if (resource === "attendance" && name === "status" && value === "absent") next.hours_worked = "0.00";
      if (resource === "payroll" && name === "employee" && !editing) {
        const salary = data.salaries.find((record) => record.employee === Number(value) && record.effective_date <= current.period_start);
        next.base_salary = salary?.monthly_amount || "";
        next.currency = salary?.currency || "RWF";
      }
      if (resource === "payroll" && name === "status") next.paid_date = value === "paid" ? today() : "";
      return next;
    });
  }

  async function submit(event) {
    event.preventDefault();
    setError("");
    setNotice("");
    const saveAndSend = resource === "contracts" && event.nativeEvent.submitter?.value === "send";
    const recipient = saveAndSend ? employees.find((person) => person.id === Number(form.employee)) : null;
    if (saveAndSend && !form.content) {
      setError("Write the digital contract before sending it for signature.");
      return;
    }
    if (saveAndSend && !window.confirm(`Save and email this contract to ${recipient?.email || "the selected employee"} for signature? You will not be able to edit or delete it after sending.`)) return;
    const uploads = config.fields.filter((item) => item.type === "file" && form[item.name]);
    const oversized = uploads.find((item) => form[item.name].size > item.maxSize);
    if (oversized) {
      setError(`${oversized.title.split(" (")[0]} must be ${oversized.maxLabel} or smaller.`);
      return;
    }
    if (resource === "payroll" && form.status === "paid" && !window.confirm("Mark this payroll as paid? Its amounts and payslip will be locked.")) return;
    setBusy(true);
    try {
      let payload = Object.fromEntries(config.fields.filter((item) => item.type !== "file").map((item) => [item.name, item.nullable && !form[item.name] ? null : form[item.name]]));
      if (uploads.length) {
        const multipart = new FormData();
        Object.entries(payload).forEach(([key, value]) => multipart.append(key, value ?? ""));
        uploads.forEach((item) => multipart.append(item.name, form[item.name]));
        payload = multipart;
      }
      let saved = await saveRecord(token, resource, payload, editing?.id);
      if (saveAndSend) saved = await sendContractForSignature(token, saved.id);
      onChange(resource, saved);
      if (saved?.latest_contract) onChange("contracts", saved.latest_contract);
      const invite = saved?.invite;
      if (saved.notification && !saved.notification.email_sent) {
        setError(saved.notification.detail);
      } else {
        setNotice(saved.notification?.detail || (invite
          ? `${saved.first_name} ${saved.last_name} was added. ${invite.detail}${invite.temporary_password ? ` Temporary password: ${invite.temporary_password}` : ""}`
          : `${label(config.singular)} ${editing ? "updated" : "added"}.`));
      }
      setForm(null);
      setEditing(null);
    } catch (err) { handleError(err); }
    finally { setBusy(false); }
  }

  async function remove(row) {
    if (!window.confirm(resource === "employees"
      ? `Permanently delete ${row.first_name} ${row.last_name}? Their sign-in account and records will be removed so this email can be hired again.`
      : `Delete this ${config.singular}? This cannot be undone.`)) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await deleteRecord(token, resource, row.id);
      onChange(resource, row, true);
      setNotice(`${label(config.singular)} deleted.`);
      if (editing?.id === row.id) { setForm(null); setEditing(null); }
    } catch (err) { handleError(err); }
    finally { setBusy(false); }
  }

  async function download(row) {
    setBusy(true);
    setError("");
    try { saveBlob(await downloadContract(token, row.id), `contract-${row.id}.${row.document_name.split(".").pop()}`); }
    catch (err) { handleError(err); }
    finally { setBusy(false); }
  }

  async function sendForSignature(row) {
    if (!window.confirm(`Email “${row.title}” to ${row.employee_email || row.employee_name} for signature? You will not be able to edit or delete it after sending.`)) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const saved = await sendContractForSignature(token, row.id);
      onChange("contracts", saved);
      if (saved.notification?.email_sent) setNotice(saved.notification.detail);
      else setError(saved.notification?.detail || "The contract is in the employee dashboard, but the email failed.");
    } catch (err) {
      // SMTP can finish on the server after the browser has timed out. Reload
      // this row before reporting failure so a completed send never remains
      // displayed as a draft.
      try {
        const contracts = await fetchRecords(token, "contracts");
        const latest = contracts.find((contract) => contract.id === row.id);
        if (latest?.signature_status === "sent") {
          onChange("contracts", latest);
          setNotice(`Contract sent to ${latest.employee_email}.`);
          return;
        }
      } catch {
        // Preserve the original, more useful send error below.
      }
      handleError(err);
    }
    finally { setBusy(false); }
  }

  function openSignatureRequest(row, mode) {
    setError("");
    setNotice("");
    setSignatureMessage("");
    setSignatureRequest({ row, mode });
  }

  async function submitSignatureRequest(event) {
    event.preventDefault();
    const { row, mode } = signatureRequest;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      if (mode === "correct") {
        const replacement = await requestNewContractSignature(token, row.id, { message: signatureMessage });
        onChange("contracts", replacement);
        if (replacement.notification?.email_sent) setNotice(replacement.notification.detail);
        else setError(replacement.notification?.detail || "The signing request is in the employee dashboard, but its email failed.");
      } else {
        const result = await resendContractSignatureEmail(token, row.id, { message: signatureMessage });
        onChange("contracts", { ...row, employer_message: signatureMessage, notification_sent_at: new Date().toISOString() });
        setNotice(result.detail);
      }
      setSignatureRequest(null);
      setSignatureMessage("");
    } catch (err) { handleError(err); }
    finally { setBusy(false); }
  }

  async function markAttendance(person, next) {
    setBusy(true);
    setError("");
    setNotice("");
    const record = person.record;
    const hours = next === "absent" ? "0.00" : record && Number(record.hours_worked) > 0 ? record.hours_worked : "8.00";
    try {
      const saved = await saveRecord(token, "attendance", { employee: person.id, date: rosterDate, status: next, hours_worked: hours, notes: record?.notes || "" }, record?.id);
      onChange("attendance", saved);
      setNotice(`${person.first_name} ${person.last_name} marked ${next} on ${rosterDate}.`);
    } catch (err) { handleError(err); }
    finally { setBusy(false); }
  }

  async function clearAttendance(person) {
    if (!window.confirm(`Remove the attendance entry for ${person.first_name} ${person.last_name} on ${rosterDate}?`)) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await deleteRecord(token, "attendance", person.record.id);
      onChange("attendance", person.record, true);
      setNotice(`Attendance cleared for ${person.first_name} ${person.last_name} on ${rosterDate}.`);
    } catch (err) { handleError(err); }
    finally { setBusy(false); }
  }

  async function markPaid(row) {
    if (!window.confirm(`Record ${row.employee_name}'s salary as paid for ${payMonth}? This creates a locked paid payroll record and payslip.`)) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const payroll = await markSalaryPaid(token, row.id, { month: payMonth });
      onChange("payroll", payroll);
      setNotice(`Paid ${money(payroll.net_pay, payroll.currency)} to ${payroll.employee_name} for ${payMonth}. The payslip is on the Payroll & payslips page.`);
    } catch (err) { handleError(err); }
    finally { setBusy(false); }
  }

  // While hiring, ask only for what the employer knows; editing shows it all.
  const collapsing = Boolean(config.collapseExtras) && !editing;
  const coreFields = collapsing ? formFields.filter((field) => field.core) : formFields;
  const extraFields = collapsing ? formFields.filter((field) => !field.core) : [];

  const renderField = (field) => <div key={field.name} className={field.section ? "field-section field-wide" : undefined}>
    {field.section && <h4>{field.section}</h4>}
    <RecordField field={field} value={form[field.name]} employees={employees} onChange={updateField} />
  </div>;

  return <>
    <div className="section-heading"><div><p className="eyebrow dark-eyebrow">MANAGER WORKSPACE</p><h2>{config.title}</h2><p>{config.description}</p></div><button className="button button-coral" type="button" disabled={busy} onClick={() => openForm()}>+ {resource === "contracts" ? "Create contract" : `Add ${config.singular}`}</button></div>
    {error && <p className="message error" role="alert">{error}</p>}
    {notice && <p className="message success" role="status">{notice}</p>}
    {resource === "employees" && !account?.email_configured && <p className="message">Invitation emails are not being sent. <Link to="/dashboard/settings">Add a Gmail App Password in Settings</Link> so new hires receive their sign-in details.</p>}
    {resource === "leave" && <LeaveBalancesPanel balances={data["leave-balances"] || []} token={token} onChange={onChange} onAuthError={onAuthError} />}
    {config.fields.some((field) => field.type === "employee") && !employees.length && <p className="message"><Link to="/dashboard/employees">Add an employee</Link> to start recording {config.title.toLowerCase()}.</p>}
    {resource === "attendance" && employees.length > 0 && <AttendanceRoster date={rosterDate} setDate={setRosterDate} rows={roster} holiday={holiday} busy={busy} token={token} onMark={markAttendance} onClear={clearAttendance} />}
    {form && <ModalDialog title={`${editing ? "Edit" : "Add"} ${config.singular}`} wide={resource === "contracts" || config.fields.length > 6} onClose={() => { setForm(null); setEditing(null); }}><form className="record-form" ref={formRef} onSubmit={submit}>
      <h3>{editing ? "Edit" : "Add"} {config.singular}</h3>
      <fieldset disabled={busy}><div className="record-fields">{coreFields.map(renderField)}</div>
      {extraFields.length > 0 && <details className="optional-fields">
        <summary>{config.collapseExtras}</summary>
        <div className="record-fields">{extraFields.map(renderField)}</div>
      </details>}
      {resource === "contracts" && form.employee && <p className="message contract-recipient">Signature email recipient: <strong>{employees.find((person) => person.id === Number(form.employee))?.email || "Email unavailable"}</strong></p>}
      {editing?.document_name && <p className="muted">A document is attached. Choosing a new file replaces it.</p>}
      {editing?.photo_name && <div className="photo-hint"><Avatar person={editing} token={token} /><p className="muted">A profile photo is attached. Choosing a new file replaces it.</p></div>}
      {editing?.latest_contract && <div className="photo-hint"><p className="muted">{editing.latest_contract.title} is already on file. Upload another PDF to add a new contract; it will not replace the existing one.</p><button type="button" className="button button-outline" onClick={() => setViewing({ ...editing.latest_contract, employee_name: `${editing.first_name} ${editing.last_name}` })}>View current contract</button></div>}
      {resource === "payroll" && <div className="payroll-preview"><strong>Net pay: {money(Number(form.base_salary || 0) + Number(form.allowances || 0) - Number(form.deductions || 0), form.currency)}</strong><p>Review the base amount for this period. Deductions, tax, overtime, and partial periods are entered manually. Marking paid records payment; it does not transfer funds.</p></div>}
      <div className="form-actions"><button className="button button-coral" type="submit" value="draft">{busy ? "Saving…" : resource === "contracts" ? "Save draft" : "Save " + config.singular}</button>{resource === "contracts" && <button className="button button-coral" type="submit" value="send">{busy ? "Sending…" : "Save and send for signature"}</button>}<button className="button button-outline" type="button" onClick={() => { setForm(null); setEditing(null); }}>Cancel</button></div></fieldset>
    </form></ModalDialog>}
    <section className="panel records-panel" aria-label={config.title}>
      <div className="records-toolbar"><span className="record-count">{visible.length} {visible.length === 1 ? "record" : "records"}</span><div className="records-filters"><input type="search" aria-label={`Search ${config.title.toLowerCase()}`} placeholder="Search records…" value={search} onChange={(event) => setSearch(event.target.value)} />{statusField && <select aria-label="Filter by status" value={status} onChange={(event) => setStatus(event.target.value)}><option value="">All statuses</option>{statusField.options.map(([value, title]) => <option key={value} value={value}>{title}</option>)}</select>}<button className="button button-outline" type="button" disabled={!visible.length} onClick={() => exportCsv(`${resource}.csv`, config.columns, visible)}>Export CSV</button></div></div>
      <DataTable columns={config.columns} rows={visible} token={token} empty={search || status ? "No records match these filters." : `No ${config.title.toLowerCase()} yet. Use Add ${config.singular} to get started.`} actions={(row) => <>
        {!(resource === "payroll" && row.status === "paid") && !(resource === "contracts" && row.signature_status !== "draft") && <><button type="button" disabled={busy} onClick={() => openForm(row)}>{resource === "leave" ? "Review / edit" : "Edit"}</button><button type="button" disabled={busy} className="danger-link" onClick={() => remove(row)}>Delete</button></>}
        {resource === "contracts" && row.content && <button type="button" onClick={() => setDigitalViewing(row)}>Preview</button>}
        {resource === "contracts" && row.signature_status === "draft" && <button className="button button-coral" type="button" disabled={busy || !row.content} onClick={() => sendForSignature(row)}>Send for signature</button>}
        {resource === "contracts" && row.signature_status === "sent" && <button type="button" disabled={busy} onClick={() => openSignatureRequest(row, "resend")}>Resend signature email</button>}
        {resource === "contracts" && row.signature_status === "signed" && <button type="button" disabled={busy} onClick={() => openSignatureRequest(row, "correct")}>Request new signature</button>}
        {resource === "contracts" && row.document_name && <><button type="button" onClick={() => setViewing(row)}>View</button><button type="button" disabled={busy} onClick={() => download(row)}>Download</button></>}
        {resource === "employees" && (row.latest_contract || contractsFor(row.id)[0]) && <button type="button" onClick={() => setViewing({ ...(row.latest_contract || contractsFor(row.id)[0]), employee_name: `${row.first_name} ${row.last_name}` })}>View contract</button>}
        {resource === "salaries" && (paidThisMonth.has(row.employee)
          ? <span className="muted">Paid for {payMonth}</span>
          : <button type="button" disabled={busy} onClick={() => markPaid(row)}>Mark paid</button>)}
        {resource === "payroll" && <button type="button" onClick={() => setPayslip(row)}>Payslip</button>}
      </>} />
    </section>
    {payslip && <Payslip record={payslip} onClose={() => setPayslip(null)} />}
    {viewing && <ContractViewer contract={viewing} token={token} onClose={() => setViewing(null)} onAuthError={onAuthError} />}
    {digitalViewing && <DigitalContractDialog contract={digitalViewing} onClose={() => setDigitalViewing(null)} />}
    {signatureRequest && <ModalDialog title={signatureRequest.mode === "correct" ? "Request a corrected signature" : "Resend signature email"} onClose={() => setSignatureRequest(null)}><form className="record-form" onSubmit={submitSignatureRequest}>
      <p>{signatureRequest.mode === "correct" ? "The original signed contract will remain in the audit history. A fresh copy will be sent for a new signature." : `Send another signing reminder to ${signatureRequest.row.employee_email}.`}</p>
      <label htmlFor="signature-request-message">Message to employee (optional)</label>
      <textarea id="signature-request-message" rows="5" maxLength="2000" value={signatureMessage} onChange={(event) => setSignatureMessage(event.target.value)} placeholder="Example: Please sign again and enter your complete legal name." />
      <div className="form-actions"><button className="button button-coral" type="submit" disabled={busy}>{busy ? "Sending…" : signatureRequest.mode === "correct" ? "Send new signature request" : "Resend email"}</button><button className="button button-outline" type="button" disabled={busy} onClick={() => setSignatureRequest(null)}>Cancel</button></div>
    </form></ModalDialog>}
  </>;
}

function ReportCard({ title, columns, rows, empty, filename }) {
  return <section className="panel report-card"><div className="list-heading"><h3>{title} <span className="muted">({rows.length})</span></h3><button className="text-button" type="button" disabled={!rows.length} onClick={() => exportCsv(filename, columns, rows)}>Export CSV</button></div><DataTable columns={columns} rows={rows} empty={empty} /></section>;
}

function ReportsPage({ token, onAuthError, overview = false }) {
  const [date, setDate] = useState(today);
  const [days, setDays] = useState("30");
  const [report, setReport] = useState(null);
  const [error, setError] = useState("");
  const [loadedQuery, setLoadedQuery] = useState("");
  const [refresh, setRefresh] = useState(0);
  const queryKey = `${date}/${days}/${refresh}`;
  const loading = queryKey !== loadedQuery;
  useEffect(() => {
    if (!date) return;
    let cancelled = false;
    fetchReports(token, date, days).then((result) => {
      if (!cancelled) { setReport(result); setError(""); }
    }).catch((err) => {
      if (!cancelled) { setError(err.message); setReport(null); onAuthError(err); }
    }).finally(() => { if (!cancelled) setLoadedQuery(queryKey); });
    return () => { cancelled = true; };
  }, [token, date, days, queryKey, onAuthError]);
  const person = { title: "Employee", value: (row) => row.employee_name || `${row.first_name} ${row.last_name}` };
  return <>
    <div className="section-heading"><div><p className="eyebrow dark-eyebrow">TEAM AT A GLANCE</p><h2>{overview ? "Manager dashboard" : "Manager reports"}</h2><p>Follow up on absences, leave, contract renewals, and payroll.</p></div><button type="button" className="button button-outline" onClick={() => setRefresh((value) => value + 1)}>Refresh</button></div>
    {overview && <div className="quick-links"><Link to="/dashboard/employees">Manage employees →</Link><Link to="/dashboard/attendance">Record attendance →</Link><Link to="/dashboard/leave">Review leave →</Link><Link to="/dashboard/payroll">Prepare payroll →</Link></div>}
    <div className="panel report-controls"><div><label htmlFor="report-date">Report date</label><input id="report-date" type="date" value={date} required onChange={(event) => setDate(event.target.value)} /></div><div><label htmlFor="report-window">Contracts ending within</label><select id="report-window" value={days} onChange={(event) => setDays(event.target.value)}><option value="30">30 days</option><option value="60">60 days</option><option value="90">90 days</option></select></div></div>
    {error && !loading && <p className="message error" role="alert">{error}</p>}
    {!date ? <p className="empty-state">Select a report date.</p> : loading ? <p className="empty-state" role="status">Loading reports…</p> : report && <>
      <div className="summary-row manager-summary">{[["Active employees", report.active_employees], ["Present / remote", report.present_count], ["Recorded absent", report.absent.length], ["On approved leave", report.on_leave.length], ["Pending leave requests", report.pending_leave_count], ["Expiring contracts", report.expiring_contracts.length]].map(([title, value]) => <div className="summary-card" key={title}><span>{title}</span><strong>{value}</strong></div>)}</div>
      <p className="report-context">Attendance for {report.date}. Missing entries use a Monday–Friday schedule and exclude company holidays. {report.holidays.map((holiday) => holiday.name).join(", ")}{!report.working_day && " — Non-working day: missing attendance is not flagged."}</p>
      <div className="report-grid">
        <ReportCard title="Recorded absent" columns={[person, { title: "Notes", value: (row) => row.notes }]} rows={report.absent} empty="No absences recorded for this date." filename={`absences-${date}.csv`} />
        <ReportCard title="On approved leave" columns={[person, { title: "Type", value: (row) => label(row.leave_type) }, { title: "Until", value: (row) => row.end_date }]} rows={report.on_leave} empty="No approved leave on this date." filename={`leave-${date}.csv`} />
        <ReportCard title="Attendance not recorded" columns={[person, { title: "Department", value: (row) => row.department }]} rows={report.unrecorded} empty="No missing attendance entries to flag." filename={`unrecorded-${date}.csv`} />
        <ReportCard title={`Contracts expiring by ${report.contract_window_end}`} columns={[person, { title: "Contract", value: (row) => row.title }, { title: "Ends", value: (row) => row.end_date }]} rows={report.expiring_contracts} empty="No active contracts expire in this window." filename={`expiring-contracts-${date}.csv`} />
        <ReportCard title="Expired contracts still active" columns={[person, { title: "Contract", value: (row) => row.title }, { title: "Ended", value: (row) => row.end_date }]} rows={report.expired_contracts} empty="No expired active contracts." filename={`expired-contracts-${date}.csv`} />
        <ReportCard title="Hours worked this month" columns={[person, { title: "Hours", value: (row) => row.hours }]} rows={report.working_hours} empty="No hours recorded this month through the report date." filename={`working-hours-${date}.csv`} />
      </div>
      <section className="panel report-card payroll-report"><h3>Payroll totals</h3><p className="muted">Pay periods ending between {report.month_start} and {report.date}, grouped by currency.</p><DataTable rows={report.payroll_totals} columns={[{ title: "Currency", value: (row) => row.currency }, ...["gross", "deductions", "net", "paid", "draft"].map((key) => ({ title: label(key), value: (row) => money(row[key], row.currency) }))]} empty="No pay periods end in this date range." /></section>
    </>}
  </>;
}

function SettingsPage({ token, account, onAccountChange, onAuthError }) {
  const [form, setForm] = useState({ email_host_user: account?.email || "", email_host_password: "" });
  const [configured, setConfigured] = useState(Boolean(account?.email_configured));
  const [canManage, setCanManage] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [editOpen, setEditOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchEmailSettings(token).then((settings) => {
      if (cancelled) return;
      setForm({ email_host_user: settings.email_host_user || account?.email || "", email_host_password: "" });
      setConfigured(Boolean(settings.email_configured));
      setCanManage(Boolean(settings.can_manage_email_settings));
    }).catch((err) => {
      if (!cancelled) { setError(err.message); onAuthError(err); }
    });
    return () => { cancelled = true; };
  }, [token, account?.email, onAuthError]);

  function update(event) {
    const { name, value } = event.target;
    setForm((current) => ({ ...current, [name]: value }));
  }

  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    setError("");
    setNotice("");
    setBusy(true);
    try {
      const saved = await saveEmailSettings(token, form);
      setConfigured(Boolean(saved.email_configured));
      setForm((current) => ({ ...current, email_host_password: "" }));
      setNotice(saved.detail || "Invitation email is ready.");
      onAccountChange?.({ email_configured: saved.email_configured });
      setEditOpen(false);
    } catch (err) {
      setError(err.message);
      onAuthError(err);
    } finally {
      setBusy(false);
    }
  }

  return <>
    <div className="section-heading">
      <div>
        <p className="eyebrow dark-eyebrow">WORKSPACE</p>
        <h2>Settings</h2>
        <p>The platform automatically emails sign-in details when an employer adds an employee.</p>
      </div>
    </div>
    {error && <p className="message error" role="alert">{error}</p>}
    {notice && <p className="message success" role="status">{notice}</p>}
    <section className="panel record-form form-launch-card"><div><h3>Invitation email</h3><p className="muted">{configured ? `Emails are sent from ${form.email_host_user || "the platform email address"}.` : "Invitation email has not been configured."}</p></div>{canManage && <button className="button button-coral" type="button" onClick={() => { setError(""); setEditOpen(true); }}>{configured ? "Update email settings" : "Configure email"}</button>}</section>
    {editOpen && <ModalDialog title="Invitation email settings" onClose={() => setEditOpen(false)}><form className="record-form" onSubmit={submit}>
      <h3>Invitation email</h3>
      <p className="muted">{configured
        ? `Invitations are being sent from ${form.email_host_user || "your Gmail address"}.`
        : "Nothing is sent to Gmail until this is set up. New hires will still get an account; you will see their password on the employees page."}</p>
      {error && <p className="message error" role="alert">{error}</p>}
      <fieldset disabled={busy}>
        <div className="record-fields">
          <div className="field-wide">
            <label htmlFor="email-host-user">Gmail address</label>
            <input id="email-host-user" name="email_host_user" type="email" value={form.email_host_user}
                   onChange={update} autoComplete="username" required />
            <small className="field-hint">This is the From address employees will see.</small>
          </div>
          <div className="field-wide">
            <label htmlFor="email-host-password">Gmail App Password</label>
            <input id="email-host-password" name="email_host_password" type="password" value={form.email_host_password}
                   onChange={update} autoComplete="new-password" required={!configured}
                   placeholder={configured ? "Unchanged unless you enter a new one" : ""} />
            <small className="field-hint">On Google's App name field, type Employee Management. Then paste the 16-character password here — not your normal Gmail password.</small>
          </div>
        </div>
        <div className="form-actions">
          <button className="button button-coral" type="submit" disabled={busy}>
            {busy ? "Sending test…" : configured ? "Update and send a test" : "Save and send a test"}
          </button>
        </div>
      </fieldset>
    </form></ModalDialog>}
  </>;
}

export default function ManagerDashboard({ token, account, onLogout, onAuthError, onAccountChange }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let cancelled = false;
    Promise.all([...Object.keys(modules), "leave-balances"].map(async (resource) => [resource, await fetchRecords(token, resource)])).then((entries) => {
      if (!cancelled) { setData(Object.fromEntries(entries)); setError(""); }
    }).catch((err) => { if (!cancelled) { setError(err.message); onAuthError(err); } });
    return () => { cancelled = true; };
  }, [token, retry, onAuthError]);

  function updateRecords(resource, record, deleted = false) {
    setData((current) => ({ ...current, [resource]: deleted ? current[resource].filter((row) => row.id !== record.id) : current[resource].some((row) => row.id === record.id) ? current[resource].map((row) => row.id === record.id ? record : row) : [record, ...current[resource]] }));
  }

  return <>
    <aside className="dashboard-sidebar" aria-label="Manager menu"><Link className="brand" to="/"><span className="brand-mark">E</span><span>Employee<span className="brand-dot">.</span></span></Link><p className="sidebar-label">{account?.business_name || "MANAGER WORKSPACE"}</p>
      <div className="workspace-identity"><strong>{account?.display_name || account?.username}</strong><span>{account?.role_label || "Employer"}</span></div>
      <nav className="sidebar-nav" aria-label="Manager navigation">
        <NavLink end to="/dashboard" className={({ isActive }) => `sidebar-link${isActive ? " selected" : ""}`}>Overview</NavLink>
        {Object.entries(modules).map(([key, config]) => <NavLink key={key} to={`/dashboard/${key}`} className={({ isActive }) => `sidebar-link${isActive ? " selected" : ""}`}>{config.title}</NavLink>)}
        <NavLink to="/dashboard/reports" className={({ isActive }) => `sidebar-link${isActive ? " selected" : ""}`}>Reports</NavLink>
        <NavLink to="/dashboard/settings" className={({ isActive }) => `sidebar-link${isActive ? " selected" : ""}`}>Settings</NavLink>
      </nav><div className="sidebar-bottom"><Link className="sidebar-link back-link" to="/">← Back to main site</Link><button className="sidebar-signout" type="button" onClick={onLogout}>Sign out</button></div>
    </aside>
    <main className="dashboard-main"><section className="workspace dashboard-workspace">
      {error ? <div className="panel records-panel"><p className="message error" role="alert">{error}</p><button type="button" className="button button-coral" onClick={() => { setError(""); setRetry((value) => value + 1); }}>Retry loading</button></div> : !data ? <p className="empty-state" role="status">Loading manager workspace…</p> : <Routes>
        <Route index element={<ReportsPage key="overview" token={token} onAuthError={onAuthError} overview />} />
        <Route path="reports" element={<ReportsPage key="reports" token={token} onAuthError={onAuthError} />} />
        <Route path="settings" element={<SettingsPage token={token} account={account} onAccountChange={onAccountChange} onAuthError={onAuthError} />} />
        {Object.keys(modules).map((resource) => <Route key={resource} path={resource} element={<ResourcePage key={resource} resource={resource} data={data} token={token} account={account} onChange={updateRecords} onAuthError={onAuthError} />} />)}
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>}
    </section></main>
  </>;
}
