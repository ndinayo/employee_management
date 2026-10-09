import { useEffect, useRef, useState } from "react";
import ContractViewer from "./ContractViewer";
import { DigitalContractDocument, RichTextEditor } from "./DigitalContract";
import CompanyCalendar from "./CompanyCalendar";
import GoogleMeetPage from "./GoogleMeetPage";
import ModalDialog from "./components/ModalDialog";
import Payslip from "./components/Payslip";
import LocationStatus from "./components/LocationStatus";
import WorkplaceLocationCard, { WorkplaceLocationHint } from "./components/WorkplaceLocationCard";
import { useConfirm } from "./components/ConfirmDialog";
import { Link, Navigate, Route, Routes } from "react-router";
import { approveContractWorker, calculatePayroll, decideContractTermination, deleteRecord, downloadContract, fetchCompanyThread, fetchEmailSettings, fetchEmployeePhoto, fetchRecords, fetchReports, fetchSalaryPaymentHistory, fetchSalaryPaymentPreview, initiateContractTermination, markCompanyThreadRead, markSalaryPaid, requestNewContractSignature, resendContractSignatureEmail, saveEmailSettings, saveRecord, sendCompanyMessage, sendContractForSignature } from "./api";
import { AssetMisusePage, SalaryAdvancesPage } from "./PayrollExtras";
import AccessControl from "./AccessControl";
import Conversation from "./components/Conversation";
import DashboardTopNav from "./components/DashboardTopNav";
import { PasswordCard } from "./AccountPage";
import { ACCESS_TOKEN, REFRESH_TOKEN } from "./constants";
import { decisionText, isWeekend, label, longDate, modules, money, shiftDate, today, upcomingEvents } from "./managerConfig";

function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function clockTime(value) {
  return value ? new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "Not recorded";
}

function runningTime(start, now) {
  if (!start) return "Not recorded";
  if (!now) return "00:00:00";
  const seconds = Math.max(0, Math.floor((now - new Date(start).getTime()) / 1000));
  const hours = String(Math.floor(seconds / 3600)).padStart(2, "0");
  const minutes = String(Math.floor((seconds % 3600) / 60)).padStart(2, "0");
  return `${hours}:${minutes}:${String(seconds % 60).padStart(2, "0")}`;
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
    return <span className="name-cell"><Avatar person={row} token={token} /><span>{value || "Not recorded"}{secondary}</span></span>;
  }
  return <>
    {column.badge ? <span className={`status-badge status-${String(value).toLowerCase()}`}>{value}</span> : value || "Not recorded"}
    {secondary}
  </>;
}

function DataTable({ columns, rows, actions, token, empty = "No records yet.", onRowClick, rowClassName }) {
  if (!rows.length) return <p className="empty-state">{empty}</p>;
  return <div className="table-scroll"><table>
    <thead><tr>{columns.map((column) => <th key={column.title} scope="col">{column.title}</th>)}{actions && <th scope="col">Actions</th>}</tr></thead>
    <tbody>{rows.map((row, index) => <tr key={row.id ?? index} className={[onRowClick ? "clickable-row" : "", rowClassName?.(row) || ""].filter(Boolean).join(" ") || undefined} tabIndex={onRowClick ? 0 : undefined}
      onClick={(event) => { if (onRowClick && !event.target.closest("button, a, input, select, textarea")) onRowClick(row); }}
      onKeyDown={(event) => { if (onRowClick && !event.target.closest("button, a, input, select, textarea") && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); onRowClick(row); } }}>
      {columns.map((column) => <td key={column.title}><Cell column={column} row={row} token={token} /></td>)}
      {actions && <td><div className="row-actions">{actions(row)}</div></td>}
    </tr>)}</tbody>
  </table></div>;
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
  const props = { id, name: field.name, value: value ?? "", required: !field.optional, readOnly: field.readOnly, onChange: (event) => onChange(field.name, event.target.value) };
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

const rosterStates = [["present", "Present"], ["remote", "Remote"], ["absent", "Absent"], ["leave", "On leave"], ["unrecorded", "Not recorded"]];

function AttendanceRoster({ date, setDate, rows, holiday, token }) {
  const latest = today();
  const [now, setNow] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
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
      <span className="status-badge status-sent">{rows.filter((row) => row.activeRecord).length} currently checked in</span>
      <span className="status-badge status-signed">{rows.reduce((sum, row) => sum + row.records.filter((record) => record.check_out_at).length, 0)} completed shifts</span>
    </div>
    <DataTable
      columns={[
        { title: "Employee", value: (row) => `${row.first_name} ${row.last_name}`, secondary: (row) => row.department, avatar: true },
        { title: "Status", value: (row) => row.state === "unrecorded" ? "Unrecorded" : row.state === "leave" ? "Leave" : label(row.state), badge: true },
        { title: "Check-in", value: (row) => clockTime(row.record?.check_in_at), secondary: (row) => <LocationStatus record={row.record} prefix="check_in" /> },
        { title: "Check-out", value: (row) => clockTime(row.record?.check_out_at), secondary: (row) => <LocationStatus record={row.record} prefix="check_out" /> },
        { title: "Live time", value: (row) => row.activeRecord ? runningTime(row.activeRecord.check_in_at, now) : "Not recorded" },
        { title: "Shifts", value: (row) => row.records?.map((record) => label(record.shift)).join(", ") },
        { title: "Total hours", value: (row) => row.totalHours },
      ]}
      rows={rows.filter((row) => row.records.some((record) => record.check_in_at))}
      token={token}
      empty={date === latest ? "Nobody has checked in today yet." : `Nobody checked in on ${longDate(date)}.`}
    />
  </section>;
}

function ManagerCalendarPage({ token, events, onChange, onAuthError }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [confirm, confirmation] = useConfirm();

  async function createEvent(payload) {
    setBusy(true);
    setError("");
    try {
      const saved = await saveRecord(token, "calendar-events", payload);
      onChange("calendar-events", saved);
      setNotice("");
      return saved;
    } catch (err) { setError(err.message); onAuthError(err); throw err; }
    finally { setBusy(false); }
  }

  async function removeEvent(row) {
    if (!await confirm({ title: "Delete calendar event?", message: `Delete ${row.title} from the company calendar?`, confirmLabel: "Delete event" })) return;
    setBusy(true);
    setError("");
    try {
      await deleteRecord(token, "calendar-events", row.id);
      onChange("calendar-events", row, true);
      setNotice("Calendar event deleted.");
    } catch (err) { setError(err.message); onAuthError(err); throw err; }
    finally { setBusy(false); }
  }

  return <>{error && <p className="message error" role="alert">{error}</p>}{notice && <p className="message success" role="status">{notice}</p>}<CompanyCalendar events={events} canManage busy={busy} onCreate={createEvent} onDelete={removeEvent} />{confirmation}</>;
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
  const [terminationAction, setTerminationAction] = useState(null);
  const [workerApprovalViewing, setWorkerApprovalViewing] = useState(null);
  const [attentionOpen, setAttentionOpen] = useState(false);
  const [terminationFields, setTerminationFields] = useState({ reason: "", proposed_last_working_date: today(), response_notes: "" });
  const [leaveViewing, setLeaveViewing] = useState(null);
  const [signatureMessage, setSignatureMessage] = useState("");
  const [rosterDate, setRosterDate] = useState(today);
  const [payrollExtras, setPayrollExtras] = useState({ loaded: false, calculations: {} });
  const [calculating, setCalculating] = useState(null);
  const [paying, setPaying] = useState(null);
  const [paymentHistory, setPaymentHistory] = useState(null);
  const [payMonth, setPayMonth] = useState(() => today().slice(0, 7));
  const [payPreviews, setPayPreviews] = useState({ month: null, rows: {} });
  const [confirm, confirmation] = useConfirm();
  const formRef = useRef(null);
  useEffect(() => {
    if (resource !== "payroll") return undefined;
    let cancelled = false;
    fetchRecords(token, "payroll-calculations").catch(() => null).then((calculations) => {
      if (cancelled) return;
      setPayrollExtras({
        loaded: Boolean(calculations),
        calculations: Object.fromEntries((calculations || []).map((row) => [row.payroll, row])),
      });
    });
    return () => { cancelled = true; };
  }, [resource, token]);
  const currentCalculation = (row) => {
    const calculation = payrollExtras.calculations[row.id];
    return calculation && Number(calculation.gross_pay) === Number(row.gross_pay) && Number(calculation.total_deductions) === Number(row.deductions) ? calculation : null;
  };
  const employees = data.employees || [];
  // One row per employee with a salary in force during the chosen month.
  const toPay = resource !== "payroll" ? [] : employees.flatMap((person) => {
    const salary = (data.salaries || [])
      .filter((record) => record.employee === person.id && record.effective_date <= `${payMonth}-31`)
      .sort((a, b) => String(b.effective_date).localeCompare(String(a.effective_date)))[0];
    if (!salary) return [];
    const payroll = (data.payroll || []).find((row) => row.employee === person.id
      && row.period_start <= `${payMonth}-31` && row.period_end >= `${payMonth}-01`);
    if (!person.is_active && !payroll) return [];
    const contract = (data.contracts || [])
      .filter((row) => row.employee === person.id && row.signature_status === "signed" && row.worker_approval_status === "approved"
        && row.status !== "draft" && row.start_date <= `${payMonth}-31` && (!row.end_date || row.end_date >= `${payMonth}-01`))
      .sort((a, b) => String(b.start_date).localeCompare(String(a.start_date)) || b.id - a.id)[0];
    const monthly = contract?.monthly_salary ? { monthly_amount: contract.monthly_salary, currency: contract.salary_currency } : {};
    return [{ ...salary, ...monthly, contract, employee_name: `${person.first_name} ${person.last_name}`,
      pay_status: payroll ? label(payroll.status) : contract ? "Unpaid" : "No contract",
      pay_key: `${salary.id}:${monthly.monthly_amount || salary.monthly_amount}:${payroll ? `${payroll.id}-${payroll.status}-${payroll.deductions}` : ""}` }];
  });
  const toPayKey = toPay.filter((row) => row.pay_status !== "No contract").map((row) => row.pay_key).join(",");
  useEffect(() => {
    if (!toPayKey) return undefined;
    let cancelled = false;
    const ids = toPayKey.split(",").map((key) => Number(key.split(":")[0]));
    Promise.all(ids.map((id) => fetchSalaryPaymentPreview(token, id, payMonth).then((preview) => [id, preview], () => [id, null])))
      .then((entries) => { if (!cancelled) setPayPreviews({ month: payMonth, rows: Object.fromEntries(entries) }); });
    return () => { cancelled = true; };
  }, [token, payMonth, toPayKey]);
  const previewFor = (row) => payPreviews.month === payMonth ? payPreviews.rows[row.id] : undefined;
  const previewMoney = (row, key) => {
    if (row.pay_status === "No contract") return "—";
    const preview = previewFor(row);
    return preview === undefined ? "Calculating…" : preview ? money(preview[key], preview.currency) : "Unavailable";
  };
  const unpaidRows = toPay.filter((row) => row.pay_status === "Unpaid");
  const unpaidTotal = unpaidRows.every((row) => previewFor(row)) && unpaidRows.length
    ? money(unpaidRows.reduce((sum, row) => sum + Number(previewFor(row).net_salary), 0), unpaidRows[0].currency) : null;
  const payColumns = [
    { title: "Employee", value: (row) => row.employee_name },
    { title: "Contract", value: (row) => row.contract?.title || "No signed and approved contract for this month" },
    { title: "Monthly salary", value: (row) => money(row.monthly_amount, row.currency) },
    { title: "Deductions", value: (row) => previewMoney(row, "total_deductions") },
    { title: "Net salary", value: (row) => previewMoney(row, "net_salary") },
    { title: "Status", value: (row) => row.pay_status, badge: true },
  ];
  const roster = resource !== "attendance" ? [] : employees
    .filter((person) => person.is_active && person.date_joined <= rosterDate)
    .map((person) => {
      const records = (data.attendance || []).filter((row) => row.employee === person.id && row.date === rosterDate);
      const activeRecord = records.find((row) => row.check_in_at && !row.check_out_at) || null;
      const record = activeRecord || records.find((row) => row.shift === "day") || records[0] || null;
      const totalHours = records.reduce((sum, row) => sum + Number(row.hours_worked || 0), 0).toFixed(2);
      const onLeave = (data.leave || []).some((row) => row.status === "approved" && row.employee === person.id && row.start_date <= rosterDate && row.end_date >= rosterDate);
      return { ...person, record, records, activeRecord, totalHours, state: record ? record.status : onLeave ? "leave" : "unrecorded" };
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
  const requiresAttention = (row) => resource === "leave"
    ? row.status === "pending"
    : resource === "contracts" && (row.signature_status === "signed" && row.worker_approval_status !== "approved"
      || row.termination?.initiated_by === "employee" && row.termination.status === "pending");
  const attentionItems = resource === "contracts" ? rows.flatMap((row) => [
    ...(row.signature_status === "signed" && row.worker_approval_status !== "approved" ? [{ type: "worker", row }] : []),
    ...(row.termination?.initiated_by === "employee" && row.termination.status === "pending" ? [{ type: "termination", row }] : []),
  ]) : resource === "leave" ? rows.filter((row) => row.status === "pending").map((row) => ({ type: "leave", row })) : [];
  const attentionTotal = attentionItems.length;
  const workerApprovalTotal = resource === "contracts" ? rows.filter((row) => row.signature_status === "signed" && row.worker_approval_status !== "approved").length : 0;
  const terminationReviewTotal = resource === "contracts" ? rows.filter((row) => row.termination?.initiated_by === "employee" && row.termination.status === "pending").length : 0;
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

  function openAttentionItem(item) {
    setAttentionOpen(false);
    if (item.type === "worker") {
      setWorkerApprovalViewing(item.row);
    } else if (item.type === "termination") {
      setTerminationAction({ row: item.row, mode: "review" });
      setTerminationFields({ reason: "", proposed_last_working_date: item.row.termination.proposed_last_working_date, response_notes: "" });
    } else {
      setLeaveViewing(item.row);
    }
  }

  function openAttentionItems() {
    if (attentionItems.length === 1) openAttentionItem(attentionItems[0]);
    else setAttentionOpen(true);
  }

  function openForm(row = null) {
    setError("");
    setNotice("");
    setEditing(row);
    const nextForm = row ? Object.fromEntries(config.fields.map((field) => [field.name, field.type === "file" ? null : row[field.name] ?? ""])) : config.defaults();
    if (resource === "contracts" && nextForm.employee) {
      const employee = employees.find((person) => person.id === Number(nextForm.employee));
      nextForm.job_title = employee?.job_title || "";
      nextForm.department = nextForm.department || employee?.department || "Operations";
    }
    setForm(nextForm);
    setTimeout(() => {
      formRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      formRef.current?.querySelector("input, select")?.focus({ preventScroll: true });
    }, 0);
  }

  function updateField(name, value) {
    setForm((current) => {
      const next = { ...current, [name]: value };
      if (resource === "attendance" && name === "status" && value === "absent") next.hours_worked = "0.00";
      if (resource === "contracts" && name === "employee") {
        const employee = employees.find((person) => person.id === Number(value));
        next.job_title = employee?.job_title || "";
        next.department = employee?.department || "Operations";
      }
      if (resource === "payroll" && name === "employee" && !editing) {
        const contract = (data.contracts || []).find((record) => record.employee === Number(value) && record.monthly_salary
          && record.signature_status === "signed" && record.worker_approval_status === "approved"
          && record.start_date <= current.period_end && (!record.end_date || record.end_date >= current.period_start));
        const salary = data.salaries.find((record) => record.employee === Number(value) && record.effective_date <= current.period_start);
        next.base_salary = contract?.monthly_salary || salary?.monthly_amount || "";
        next.currency = contract?.salary_currency || salary?.currency || "RWF";
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
    if (saveAndSend && !await confirm({ title: "Send contract for signature?", message: `Save and email this contract to ${recipient?.email || "the selected employee"} for signature? You will not be able to edit or delete it after sending.`, confirmLabel: "Save and send" })) return;
    const savedFields = resource === "employees" && editing ? config.fields.filter((item) => item.core) : config.fields;
    const uploads = savedFields.filter((item) => item.type === "file" && form[item.name]);
    const oversized = uploads.find((item) => form[item.name].size > item.maxSize);
    if (oversized) {
      setError(`${oversized.title.split(" (")[0]} must be ${oversized.maxLabel} or smaller.`);
      return;
    }
    if (resource === "payroll" && form.status === "paid" && !await confirm({ title: "Mark payroll as paid?", message: "Its amounts and payslip will be locked after payment is recorded.", confirmLabel: "Mark as paid" })) return;
    setBusy(true);
    try {
      let payload = Object.fromEntries(savedFields.filter((item) => item.type !== "file" && !item.readOnly).map((item) => [item.name, item.nullable && !form[item.name] ? null : form[item.name]]));
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
    if (!await confirm({
      title: resource === "employees" ? "Delete employee permanently?" : `Delete ${config.singular}?`,
      message: resource === "employees"
        ? `Permanently delete ${row.first_name} ${row.last_name}? Their sign-in account and records will be removed so this email can be hired again.`
        : `Delete this ${config.singular}? This cannot be undone.`,
      confirmLabel: "Delete",
    })) return;
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

  async function decideLeave(row, status) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const saved = await saveRecord(token, "leave", { status }, row.id);
      onChange("leave", saved);
      setLeaveViewing(saved);
      setNotice(`${saved.employee_name}'s leave request was ${status}. An email notification was sent to the employee.`);
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
    if (!await confirm({ title: "Send contract for signature?", message: `Email “${row.title}” to ${row.employee_email || row.employee_name} for signature? You will not be able to edit or delete it after sending.`, confirmLabel: "Send contract" })) return;
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

  async function approveWorker(row) {
    if (!await confirm({ title: "Approve worker?", message: `Approve ${row.employee_name} to start working and unlock their employee workspace? A congratulations email will be sent.`, confirmLabel: "Approve worker" })) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const saved = await approveContractWorker(token, row.id);
      onChange("contracts", saved);
      if (saved.monthly_salary) {
        const salary = (await fetchRecords(token, "salaries").catch(() => [])).find((item) => item.employee === saved.employee);
        if (salary) onChange("salaries", salary);
      }
      if (saved.notification?.email_sent) setNotice(saved.notification.detail);
      else setError(saved.notification?.detail || "The worker was approved, but the congratulations email could not be sent.");
      return true;
    } catch (err) { handleError(err); return false; }
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

  async function submitTermination(event) {
    event.preventDefault();
    if (!terminationAction) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const saved = await initiateContractTermination(token, terminationAction.row.id, {
        reason: terminationFields.reason,
        proposed_last_working_date: terminationFields.proposed_last_working_date,
      });
      onChange("contracts", saved);
      setTerminationAction(null);
      setNotice(`Termination sent to ${saved.employee_name} for acknowledgement and emailed to them.`);
    } catch (err) { handleError(err); }
    finally { setBusy(false); }
  }

  async function decideTermination(decision) {
    if (!terminationAction) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const saved = await decideContractTermination(token, terminationAction.row.id, {
        request_id: terminationAction.row.termination.id,
        decision,
        response_notes: terminationFields.response_notes,
      });
      onChange("contracts", saved);
      setTerminationAction(null);
      setNotice(`Termination request ${decision}. The employee was notified by email.`);
    } catch (err) { handleError(err); }
    finally { setBusy(false); }
  }

  function openCalculation(row) {
    setError("");
    setNotice("");
    const previous = payrollExtras.calculations[row.id];
    setCalculating({ row, other: previous ? previous.other_deductions : row.deductions });
  }

  async function submitCalculation(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const calculation = await calculatePayroll(token, calculating.row.id, calculating.other);
      const updated = await fetchRecords(token, `payroll/${calculating.row.id}`);
      onChange("payroll", updated);
      setPayrollExtras((current) => ({ ...current, calculations: { ...current.calculations, [updated.id]: calculation } }));
      setNotice(`Deductions calculated for ${updated.employee_name}: ${money(calculation.total_deductions, updated.currency)} in total, net pay ${money(calculation.net_pay, updated.currency)}.${calculation.warnings.length ? ` ${calculation.warnings.join(" ")}` : ""}`);
      setCalculating(null);
    } catch (err) { handleError(err); }
    finally { setBusy(false); }
  }

  async function markPaid(row, month = payMonth) {
    setError("");
    setNotice("");
    setPaymentHistory(null);
    setPaying({ row, month, preview: null });
    try {
      const preview = await fetchSalaryPaymentPreview(token, row.id, month);
      setPaying((current) => current?.row.id === row.id && current.month === month ? { row, month, preview } : current);
    } catch (err) {
      setPaying(null);
      handleError(err);
    }
  }

  async function confirmPaid() {
    const { row, month } = paying;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const payroll = await markSalaryPaid(token, row.id, { month });
      onChange("payroll", payroll);
      setPaying(null);
      setNotice(`Paid ${money(payroll.net_pay, payroll.currency)} to ${payroll.employee_name} for ${month}${Number(payroll.deductions) > 0 ? ` after ${money(payroll.deductions, payroll.currency)} in deductions` : ""}. The payslip is in the payroll records list.`);
    } catch (err) {
      setPaying(null);
      handleError(err);
    }
    finally { setBusy(false); }
  }

  async function openPaymentHistory(row) {
    setError("");
    setNotice("");
    setPaymentHistory({ row, data: null });
    try {
      const history = await fetchSalaryPaymentHistory(token, row.id);
      setPaymentHistory((current) => current?.row.id === row.id ? { row, data: history } : current);
    } catch (err) {
      setPaymentHistory(null);
      handleError(err);
    }
  }

  // While hiring, ask only for what the employer knows. An employee's other details are their own to edit.
  const collapsing = Boolean(config.collapseExtras) && !editing;
  const editableFields = resource === "attendance" && editing ? formFields.filter((field) => field.name !== "shift") : formFields;
  const coreFields = collapsing || (resource === "employees" && editing) ? editableFields.filter((field) => field.core) : editableFields;
  const extraFields = collapsing ? formFields.filter((field) => !field.core) : [];

  const renderField = (field) => <div key={field.name} className={field.section ? "field-section field-wide" : undefined}>
    {field.section && <h4>{field.section}</h4>}
    <RecordField field={field} value={form[field.name]} employees={employees} onChange={updateField} />
  </div>;

  return <>
    <div className="section-heading"><div><p className="eyebrow dark-eyebrow">MANAGER WORKSPACE</p><h2>{config.title}</h2><p>{config.description}</p></div>{resource !== "leave" && <button className="button button-coral" type="button" disabled={busy} onClick={() => openForm()}>+ {resource === "contracts" ? "Create contract" : `Add ${config.singular}`}</button>}</div>
    {error && <p className="message error" role="alert">{error}</p>}
    {notice && <p className="message success" role="status">{notice}</p>}
    {attentionTotal > 0 && <button className="attention-banner attention-banner-button" type="button" onClick={openAttentionItems}><span className="attention-badge">{attentionTotal}</span><span><strong>{resource === "contracts"
      ? workerApprovalTotal > 0 && terminationReviewTotal > 0
        ? `${workerApprovalTotal} worker approval and ${terminationReviewTotal} termination request need action`
        : workerApprovalTotal > 0
          ? `${workerApprovalTotal} signed ${workerApprovalTotal === 1 ? "contract is" : "contracts are"} awaiting worker approval`
          : `${terminationReviewTotal} employee termination ${terminationReviewTotal === 1 ? "request needs" : "requests need"} your decision`
      : "Leave requests need your decision"}</strong><p>{resource === "contracts"
        ? workerApprovalTotal > 0
          ? "Open the highlighted row and approve the worker. Any highlighted termination request must be approved or rejected separately."
          : "The contracts are approved. Open the highlighted row and review the employee's termination request."
        : "Open a highlighted request to approve or reject it."}</p></span><span className="attention-open-label">Open</span></button>}
    {resource === "employees" && !account?.email_configured && <p className="message">Invitation emails are not being sent. <Link to="/dashboard/settings">Add a Gmail App Password in Settings</Link> so new hires receive their sign-in details.</p>}
    {config.fields.some((field) => field.type === "employee") && !employees.length && <p className="message"><Link to="/dashboard/employees">Add an employee</Link> to start recording {config.title.toLowerCase()}.</p>}
    {resource === "attendance" && <WorkplaceLocationHint token={token} />}
    {resource === "attendance" && employees.length > 0 && <AttendanceRoster date={rosterDate} setDate={setRosterDate} rows={roster} holiday={holiday} token={token} />}
    {form && <ModalDialog title={`${editing ? "Edit" : "Add"} ${config.singular}`} wide={resource === "contracts" || config.fields.length > 6} onClose={() => { setForm(null); setEditing(null); }}><form className="record-form" ref={formRef} onSubmit={submit}>
      <h3>{editing ? "Edit" : "Add"} {config.singular}</h3>
      <fieldset disabled={busy}><div className="record-fields">{coreFields.map(renderField)}</div>
      {extraFields.length > 0 && <details className="optional-fields">
        <summary>{config.collapseExtras}</summary>
        <div className="record-fields">{extraFields.map(renderField)}</div>
      </details>}
      {resource === "contracts" && form.employee && <p className="message contract-recipient">Signature email recipient: <strong>{employees.find((person) => person.id === Number(form.employee))?.email || "Email unavailable"}</strong></p>}
      {editing?.document_name && <p className="muted">A document is attached. Choosing a new file replaces it.</p>}
      {resource === "payroll" && <div className="payroll-preview"><strong>Net pay: {money(Number(form.base_salary || 0) + Number(form.allowances || 0) - Number(form.deductions || 0), form.currency)}</strong><p>Review the base amount for this period. Deductions, tax, overtime, and partial periods are entered manually. Marking paid records payment; it does not transfer funds.</p></div>}
      <div className="form-actions"><button className="button button-coral" type="submit" value="draft">{busy ? "Saving…" : resource === "contracts" ? "Save draft" : "Save " + config.singular}</button>{resource === "contracts" && <button className="button button-coral" type="submit" value="send">{busy ? "Sending…" : "Save and send for signature"}</button>}<button className="button button-outline" type="button" onClick={() => { setForm(null); setEditing(null); }}>Cancel</button></div></fieldset>
    </form></ModalDialog>}
    {resource === "payroll" && <section className="panel records-panel" aria-label="Salaries to pay">
      <div className="records-toolbar"><span className="record-count">{unpaidRows.length} of {toPay.length} to pay for {payMonth}{unpaidTotal && ` · ${unpaidTotal} in total`}</span><div className="records-filters"><input type="month" aria-label="Pay month" value={payMonth} max={today().slice(0, 7)} onChange={(event) => { if (event.target.value) setPayMonth(event.target.value); }} /></div></div>
      <DataTable columns={payColumns} rows={toPay} token={token} onRowClick={(row) => { if (row.pay_status !== "No contract") markPaid(row); }} empty={<>No salaries are set for {payMonth}. Approve a signed <Link to="/dashboard/contracts">contract</Link> with a monthly salary to pay an employee.</>} actions={(row) => <>
        {row.pay_status === "Unpaid"
          ? <button className="button button-coral" type="button" disabled={busy} onClick={() => markPaid(row)}>Pay</button>
          : row.pay_status !== "No contract" && <button type="button" onClick={() => markPaid(row)}>View payment</button>}
        <button type="button" onClick={() => openPaymentHistory(row)}>Payment history</button>
      </>} />
    </section>}
    <section className="panel records-panel" aria-label={config.title}>
      <div className="records-toolbar"><span className="record-count">{visible.length} {visible.length === 1 ? "record" : "records"}</span><div className="records-filters"><input type="search" aria-label={`Search ${config.title.toLowerCase()}`} placeholder="Search records…" value={search} onChange={(event) => setSearch(event.target.value)} />{statusField && <select aria-label="Filter by status" value={status} onChange={(event) => setStatus(event.target.value)}><option value="">All statuses</option>{statusField.options.map(([value, title]) => <option key={value} value={value}>{title}</option>)}</select>}<button className="button button-outline" type="button" disabled={!visible.length} onClick={() => exportCsv(`${resource}.csv`, config.columns, visible)}>Export CSV</button></div></div>
      <DataTable columns={config.columns} rows={visible} token={token} rowClassName={(row) => requiresAttention(row) ? "attention-row" : ""} onRowClick={resource === "leave" ? setLeaveViewing : undefined} empty={search || status ? "No records match these filters." : `No ${config.title.toLowerCase()} yet. Use Add ${config.singular} to get started.`} actions={(row) => <>
        {resource === "leave" && <button type="button" onClick={() => setLeaveViewing(row)}>Preview</button>}
        {resource === "leave" && row.status === "pending" && <><button className="button button-coral" type="button" disabled={busy} onClick={() => decideLeave(row, "approved")}>Approve</button><button type="button" disabled={busy} onClick={() => decideLeave(row, "rejected")}>Reject</button></>}
        {resource !== "leave" && !(resource === "payroll" && row.status === "paid") && !(resource === "contracts" && row.signature_status !== "draft") && !(resource === "salaries" && row.from_contract) && <><button type="button" disabled={busy} onClick={() => openForm(row)}>Edit</button><button type="button" disabled={busy} className="danger-link" onClick={() => remove(row)}>Delete</button></>}
        {resource === "contracts" && row.content && <button type="button" onClick={() => setDigitalViewing(row)}>Preview</button>}
        {resource === "contracts" && row.signature_status === "draft" && <button className="button button-coral" type="button" disabled={busy || !row.content} onClick={() => sendForSignature(row)}>Send for signature</button>}
        {resource === "contracts" && row.signature_status === "sent" && <button type="button" disabled={busy} onClick={() => openSignatureRequest(row, "resend")}>Resend signature email</button>}
        {resource === "contracts" && row.signature_status === "signed" && row.worker_approval_status !== "approved" && <button className="button button-coral" type="button" disabled={busy} onClick={() => approveWorker(row)}>Approve worker</button>}
        {resource === "contracts" && row.signature_status === "signed" && <button type="button" disabled={busy} onClick={() => openSignatureRequest(row, "correct")}>Request new signature</button>}
        {resource === "contracts" && row.signature_status === "signed" && row.worker_approval_status === "approved" && row.status === "active" && !["pending", "awaiting_acknowledgement"].includes(row.termination?.status) && <button type="button" disabled={busy} onClick={() => { setTerminationAction({ row, mode: "initiate" }); setTerminationFields({ reason: "", proposed_last_working_date: today(), response_notes: "" }); }}>Initiate termination</button>}
        {resource === "contracts" && row.termination?.initiated_by === "employee" && row.termination.status === "pending" && <button className="button button-coral" type="button" disabled={busy} onClick={() => { setTerminationAction({ row, mode: "review" }); setTerminationFields({ reason: "", proposed_last_working_date: row.termination.proposed_last_working_date, response_notes: "" }); }}>Review termination</button>}
        {resource === "contracts" && row.termination?.initiated_by === "employer" && row.termination.status === "awaiting_acknowledgement" && <span className="muted">Awaiting employee acknowledgement</span>}
        {resource === "contracts" && row.document_name && <><button type="button" onClick={() => setViewing(row)}>View</button><button type="button" disabled={busy} onClick={() => download(row)}>Download</button></>}
        {resource === "employees" && (row.latest_contract || contractsFor(row.id)[0]) && <button type="button" onClick={() => setViewing({ ...(row.latest_contract || contractsFor(row.id)[0]), employee_name: `${row.first_name} ${row.last_name}` })}>View contract</button>}
        {resource === "payroll" && row.status === "draft" && payrollExtras.loaded && <button type="button" disabled={busy} onClick={() => openCalculation(row)}>{currentCalculation(row) ? "Recalculate deductions" : "Calculate deductions"}</button>}
        {resource === "payroll" && <button type="button" onClick={() => setPayslip(row)}>Payslip</button>}
      </>} />
    </section>
    {payslip && <Payslip record={payslip} calculation={currentCalculation(payslip)} onClose={() => setPayslip(null)} />}
    {calculating && <ModalDialog title="Calculate deductions" onClose={() => setCalculating(null)}><form className="record-form" onSubmit={submitCalculation}><fieldset disabled={busy}>
      <p>Apply any salary advance installment and asset misuse recovery due for <strong>{calculating.row.employee_name}</strong> ({calculating.row.period_start} to {calculating.row.period_end}).</p>
      <div className="record-fields"><div className="field-wide"><label htmlFor="calculation-other">Other deductions (not advances)</label><input id="calculation-other" type="number" min="0" step="0.01" value={calculating.other} onChange={(event) => setCalculating((current) => ({ ...current, other: event.target.value }))} required /><small className="field-hint">The record's Total deductions is replaced by the calculated total. Recalculating is safe: it replaces the previous result and never deducts an advance twice.</small></div></div>
      <div className="form-actions"><button className="button button-coral" type="submit">{busy ? "Calculating…" : "Calculate"}</button><button className="button button-outline" type="button" onClick={() => setCalculating(null)}>Cancel</button></div>
    </fieldset></form></ModalDialog>}
    {paying && <ModalDialog title={paying.preview && paying.preview.status !== "unpaid" ? "Salary payment" : "Record salary payment"} onClose={() => { if (!busy) setPaying(null); }}><section className="record-form"><fieldset disabled={busy}>
      {!paying.preview ? <p className="muted" role="status">Calculating deductions…</p> : <>
        <p>{paying.preview.status === "paid"
          ? `${paying.row.employee_name}'s salary for ${paying.month} was paid on ${paying.preview.paid_date}. This is the saved breakdown; nothing is recalculated or deducted again.`
          : paying.preview.status === "draft"
            ? `A draft payroll record already covers ${paying.month} for ${paying.row.employee_name}. Review it in the payroll records list.`
            : `Review ${paying.row.employee_name}'s salary for ${paying.month}. Paying creates a locked payroll record and payslip.`}</p>
        {paying.preview.contract && <p className="muted">Contract: <strong>{paying.preview.contract.title}</strong> ({paying.preview.contract.start_date} → {paying.preview.contract.end_date || "Ongoing"})</p>}
        <dl className="pay-breakdown">
          <div><dt>Monthly salary</dt><dd>{money(paying.preview.monthly_salary, paying.preview.currency)}</dd></div>
          <div><dt>Salary advances</dt><dd>{money(paying.preview.advance_deductions, paying.preview.currency)}</dd></div>
          {paying.preview.lines.filter((line) => line.kind === "advance").map((line, index) => <div className="pay-breakdown-line" key={`advance-${index}`}><dt>{line.name}</dt><dd>{money(line.amount, paying.preview.currency)}</dd></div>)}
          <div><dt>Asset misuse</dt><dd>{money(paying.preview.asset_deductions, paying.preview.currency)}</dd></div>
          {paying.preview.lines.filter((line) => line.kind === "asset").map((line, index) => <div className="pay-breakdown-line" key={`asset-${index}`}><dt>{line.name}</dt><dd>{money(line.amount, paying.preview.currency)}</dd></div>)}
          {Number(paying.preview.other_deductions) > 0 && <div><dt>Other deductions</dt><dd>{money(paying.preview.other_deductions, paying.preview.currency)}</dd></div>}
          <div><dt>Total deductions</dt><dd>{money(paying.preview.total_deductions, paying.preview.currency)}</dd></div>
          <div className="net-pay"><dt>{paying.preview.status === "paid" ? "Net salary paid" : "Net salary to pay"}</dt><dd>{money(paying.preview.net_salary, paying.preview.currency)}</dd></div>
        </dl>
        {paying.preview.status === "unpaid" && <p className="muted">Deductions come from recorded salary advances and asset incidents, are calculated automatically, and never exceed {Number(paying.preview.limit_percent)}% of the salary.</p>}
        {paying.preview.warnings.map((warning) => <p className="message" key={warning}>{warning}</p>)}
      </>}
      <div className="form-actions">{paying.preview?.status === "unpaid" && <button className="button button-coral" type="button" onClick={confirmPaid}>{busy ? "Paying…" : "Pay"}</button>}<button className="button button-outline" type="button" onClick={() => setPaying(null)}>{paying.preview && paying.preview.status !== "unpaid" ? "Close" : "Cancel"}</button></div>
    </fieldset></section></ModalDialog>}
    {paymentHistory && <ModalDialog title={`${paymentHistory.row.employee_name} · payment history`} wide onClose={() => setPaymentHistory(null)}><section className="record-form">
      {!paymentHistory.data ? <p className="muted" role="status">Loading payment history…</p> : <div className="table-scroll"><table>
        <thead><tr><th scope="col">Month</th><th scope="col">Status</th><th scope="col">Monthly salary</th><th scope="col">Deductions</th><th scope="col">Net salary</th><th scope="col">Paid on</th><th scope="col">Actions</th></tr></thead>
        <tbody>{paymentHistory.data.months.map((item) => <tr key={item.month}>
          <td>{item.month}</td>
          <td><span className={`status-badge status-${item.status === "unpaid" ? "pending" : item.status}`}>{item.status === "unpaid" ? "Unpaid" : label(item.status)}</span></td>
          <td>{item.monthly_salary === null ? "—" : money(item.monthly_salary, paymentHistory.data.currency)}</td>
          <td>{item.total_deductions === null ? "—" : money(item.total_deductions, paymentHistory.data.currency)}</td>
          <td>{item.net_salary === null ? "—" : money(item.net_salary, paymentHistory.data.currency)}</td>
          <td>{item.paid_date || "—"}</td>
          <td><div className="row-actions"><button type="button" onClick={() => markPaid(paymentHistory.row, item.month)}>{item.status === "unpaid" ? "Review and pay" : "View breakdown"}</button></div></td>
        </tr>)}</tbody>
      </table></div>}
      <div className="form-actions"><button className="button button-outline" type="button" onClick={() => setPaymentHistory(null)}>Close</button></div>
    </section></ModalDialog>}
    {viewing && <ContractViewer contract={viewing} token={token} onClose={() => setViewing(null)} onAuthError={onAuthError} />}
    {digitalViewing && <DigitalContractDialog contract={digitalViewing} onClose={() => setDigitalViewing(null)} />}
    {attentionOpen && <ModalDialog title="Items needing attention" onClose={() => setAttentionOpen(false)}><section className="attention-picker"><p>Choose an item to review. It will remain here until you complete its action.</p>{attentionItems.map((item) => <button type="button" className="attention-picker-item" key={`${item.type}-${item.row.id}`} onClick={() => openAttentionItem(item)}><span><strong>{item.row.employee_name}</strong><small>{item.row.title || label(item.row.leave_type)}</small></span><span>{item.type === "worker" ? "Approve worker" : item.type === "termination" ? "Review termination" : "Review leave"}</span></button>)}</section></ModalDialog>}
    {workerApprovalViewing && <ModalDialog title="Worker approval" onClose={() => setWorkerApprovalViewing(null)}><section className="account-panel leave-preview"><h3>{workerApprovalViewing.employee_name}</h3><dl><dt>Contract</dt><dd>{workerApprovalViewing.title}</dd><dt>Department</dt><dd>{workerApprovalViewing.department || "Not recorded"}</dd><dt>Signed by</dt><dd>{workerApprovalViewing.signer_name || workerApprovalViewing.employee_name}</dd><dt>Signed at</dt><dd>{workerApprovalViewing.signed_at ? new Date(workerApprovalViewing.signed_at).toLocaleString() : "Not recorded"}</dd></dl><div className="form-actions">{workerApprovalViewing.content && <button className="button button-outline" type="button" onClick={() => setDigitalViewing(workerApprovalViewing)}>Preview contract</button>}<button className="button button-coral" type="button" disabled={busy} onClick={async () => { if (await approveWorker(workerApprovalViewing)) setWorkerApprovalViewing(null); }}>Approve worker</button></div></section></ModalDialog>}
    {leaveViewing && <ModalDialog title="Leave request" onClose={() => setLeaveViewing(null)}><section className="account-panel leave-preview">
      <h3>{leaveViewing.employee_name}</h3>
      <dl><dt>Leave type</dt><dd>{label(leaveViewing.leave_type)}</dd><dt>Start date</dt><dd>{leaveViewing.start_date}</dd><dt>End date</dt><dd>{leaveViewing.end_date}</dd><dt>Working days</dt><dd>{leaveViewing.days_requested}</dd><dt>Status</dt><dd>{label(leaveViewing.status)}</dd><dt>Requested</dt><dd>{new Date(leaveViewing.requested_at).toLocaleString()}</dd>{leaveViewing.status !== "pending" && leaveViewing.decided_at && <><dt>Decision</dt><dd>{decisionText(leaveViewing.status, leaveViewing.decided_by, leaveViewing.decided_at)}</dd></>}<dt>Reason</dt><dd>{leaveViewing.reason || "No reason provided"}</dd>{leaveViewing.decision_notes && <><dt>Decision notes</dt><dd>{leaveViewing.decision_notes}</dd></>}</dl>
      {leaveViewing.status === "pending" && <div className="form-actions"><button className="button button-coral" type="button" disabled={busy} onClick={() => decideLeave(leaveViewing, "approved")}>Approve and email employee</button><button className="button button-outline" type="button" disabled={busy} onClick={() => decideLeave(leaveViewing, "rejected")}>Reject and email employee</button></div>}
    </section></ModalDialog>}
    {signatureRequest && <ModalDialog title={signatureRequest.mode === "correct" ? "Request a corrected signature" : "Resend signature email"} onClose={() => setSignatureRequest(null)}><form className="record-form" onSubmit={submitSignatureRequest}>
      <p>{signatureRequest.mode === "correct" ? "The original signed contract will remain in the audit history. A fresh copy will be sent for a new signature." : `Send another signing reminder to ${signatureRequest.row.employee_email}.`}</p>
      <label htmlFor="signature-request-message">Message to employee (optional)</label>
      <textarea id="signature-request-message" rows="5" maxLength="2000" value={signatureMessage} onChange={(event) => setSignatureMessage(event.target.value)} placeholder="Example: Please sign again and enter your complete legal name." />
      <div className="form-actions"><button className="button button-coral" type="submit" disabled={busy}>{busy ? "Sending…" : signatureRequest.mode === "correct" ? "Send new signature request" : "Resend email"}</button><button className="button button-outline" type="button" disabled={busy} onClick={() => setSignatureRequest(null)}>Cancel</button></div>
    </form></ModalDialog>}
    {terminationAction && <ModalDialog title={terminationAction.mode === "review" ? "Review termination request" : "Initiate contract termination"} onClose={() => setTerminationAction(null)}>
      {terminationAction.mode === "review" ? <section className="account-panel leave-preview">
        <h3>{terminationAction.row.employee_name}</h3>
        <dl><dt>Proposed last working date</dt><dd>{terminationAction.row.termination.proposed_last_working_date}</dd><dt>Reason</dt><dd>{terminationAction.row.termination.reason}</dd><dt>Status</dt><dd>{label(terminationAction.row.termination.status)}</dd></dl>
        <label htmlFor="termination-response-notes">Response notes (optional)</label>
        <textarea id="termination-response-notes" rows="4" maxLength="4000" value={terminationFields.response_notes} onChange={(event) => setTerminationFields((current) => ({ ...current, response_notes: event.target.value }))} />
        <div className="form-actions"><button className="button button-coral" type="button" disabled={busy} onClick={() => decideTermination("approved")}>Approve</button><button className="button button-outline" type="button" disabled={busy} onClick={() => decideTermination("rejected")}>Reject</button></div>
      </section> : <form className="record-form" onSubmit={submitTermination}>
        <p>The employee will receive an email and must acknowledge the termination.</p>
        <label htmlFor="employer-termination-date">Termination date</label>
        <input id="employer-termination-date" type="date" min={today()} value={terminationFields.proposed_last_working_date} onChange={(event) => setTerminationFields((current) => ({ ...current, proposed_last_working_date: event.target.value }))} required />
        <label htmlFor="employer-termination-reason">Reason</label>
        <textarea id="employer-termination-reason" rows="5" maxLength="4000" value={terminationFields.reason} onChange={(event) => setTerminationFields((current) => ({ ...current, reason: event.target.value }))} required />
        <div className="form-actions"><button className="button button-coral" type="submit" disabled={busy}>{busy ? "Sending…" : "Initiate and notify employee"}</button><button className="button button-outline" type="button" onClick={() => setTerminationAction(null)}>Cancel</button></div>
      </form>}
    </ModalDialog>}
    {confirmation}
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
      <div className="summary-row manager-summary">{[
        ["Active employees", report.active_employees, "/dashboard/employees"],
        ["Present / remote", report.present_count, "/dashboard/attendance"],
        ["Recorded absent", report.absent.length, "/dashboard/attendance"],
        ["On approved leave", report.on_leave.length, "/dashboard/leave"],
        ["Pending leave requests", report.pending_leave_count, "/dashboard/leave"],
        ["Expiring contracts", report.expiring_contracts.length, "/dashboard/contracts"],
      ].map(([title, value, destination]) => <Link className="summary-card summary-card-link" to={destination} aria-label={`Open ${title.toLowerCase()}`} key={title}><span>{title}</span><strong>{value}</strong><small>Open →</small></Link>)}</div>
      <p className="report-context">Attendance for {report.date}. Missing entries use a Monday-Friday schedule and exclude company holidays. {report.holidays.map((holiday) => holiday.name).join(", ")}{!report.working_day && " Non-working day: missing attendance is not flagged."}</p>
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

  function passwordChanged(access, user, refresh) {
    localStorage.setItem(ACCESS_TOKEN, access);
    if (refresh) localStorage.setItem(REFRESH_TOKEN, refresh);
    onAccountChange?.(user);
  }

  return <>
    <div className="section-heading">
      <div>
        <p className="eyebrow dark-eyebrow">WORKSPACE</p>
        <h2>Settings</h2>
        <p>Manage your account details, password, and the email used to invite employees.</p>
      </div>
    </div>
    {error && <p className="message error" role="alert">{error}</p>}
    {notice && <p className="message success" role="status">{notice}</p>}
    <div className="settings-stack">
      <section className="panel settings-card" aria-labelledby="settings-account-heading">
        <h3 id="settings-account-heading">Your account</h3>
        <dl className="employee-manage-facts">
          <div><dt>Name</dt><dd>{account?.display_name || account?.username || "Not recorded"}</dd></div>
          <div><dt>Email</dt><dd>{account?.email || "Not recorded"}</dd></div>
          <div><dt>Username</dt><dd>{account?.username || "Not recorded"}</dd></div>
          <div><dt>Role</dt><dd>{account?.role_label || "Employer"}</dd></div>
          <div><dt>Business</dt><dd>{account?.business_name || "Not recorded"}</dd></div>
        </dl>
      </section>
      <PasswordCard token={token} forced={false} onChanged={passwordChanged} />
      <WorkplaceLocationCard token={token} onAuthError={onAuthError} />
      <section className="panel record-form form-launch-card"><div><h3>Invitation email</h3><p className="muted">{configured ? `Emails are sent from ${form.email_host_user || "the platform email address"}.` : "Invitation email has not been configured."}</p></div>{canManage && <button className="button button-coral" type="button" onClick={() => { setError(""); setEditOpen(true); }}>{configured ? "Update email settings" : "Configure email"}</button>}</section>
    </div>
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
            <small className="field-hint">On Google's App name field, type Employee Management. Then paste the 16-character password here, not your normal Gmail password.</small>
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

// The company's side of the platform conversation. Opening the page clears the
// badge; the administrator's replies arrive here and by email.
function PlatformMessagesPage({ token, onAuthError }) {
  const [thread, setThread] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    markCompanyThreadRead(token).then((data) => {
      if (!cancelled) { setThread(data); setError(""); }
    }).catch((err) => {
      if (!cancelled) { setError(err.message); onAuthError(err); }
    });
    const timer = window.setInterval(() => fetchCompanyThread(token).then((data) => {
      if (!cancelled) setThread(data);
    }).catch(() => {}), 15000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [token, onAuthError]);

  async function send(body, channel) {
    const sent = await sendCompanyMessage(token, body, channel);
    setThread((current) => current ? { ...current, messages: [...current.messages, sent] } : current);
  }

  return <>
    <div className="section-heading"><div><p className="eyebrow dark-eyebrow">PLATFORM</p><h2>Messages</h2><p>Write to the team that runs Employee Management. Choose whether it lands in their dashboard or in their inbox: a message appears here in their workspace and sends no email, an email goes to their inbox and stays out of their dashboard. Your employees are not part of this conversation.</p></div></div>
    {error && <p className="message error" role="alert">{error}</p>}
    <section className="panel records-panel">
      {!thread ? <p className="empty-state" role="status">Loading conversation…</p> : <Conversation
        thread={thread}
        mine={false}
        onSend={send}
        placeholder="Write to the platform team…"
        empty="No messages yet. Write the first one."
      />}
    </section>
  </>;
}

// Every manager page appears exactly once: as a top-level tab or inside a group.
const managerNav = [
  { label: "Dashboard", to: "/dashboard", end: true },
  { key: "employees" },
  { key: "contracts" },
  { key: "attendance", label: "Attendance / Shifts" },
  { key: "leave" },
  { label: "Schedule", items: [{ key: "calendar-events" }, { key: "holidays" }] },
  { label: "Payroll", items: [
    { key: "salaries" }, { key: "payroll" },
    { key: "asset-misuse", label: "Asset Misuse" }, { key: "salary-advances", label: "Salary Advances" },
  ] },
  { label: "Communication", items: [{ key: "announcements" }, { key: "messages", label: "Messages" }, { key: "google-meet", label: "Google Meet" }] },
  { key: "reports", label: "Reports" },
  { key: "access-control", label: "Access Control" },
  { key: "settings", label: "Settings" },
];

function badgeLabel(key, count) {
  if (key === "calendar-events") return `${count} events in the next 7 days`;
  if (key === "messages") return `${count} unread messages`;
  if (key === "salary-advances") return `${count} salary advance requests awaiting approval`;
  return `${count} items need attention`;
}

function managerNavItems(badges) {
  const entry = (item) => ({
    ...item,
    label: item.label || modules[item.key].title,
    to: item.to || `/dashboard/${item.key}`,
    badge: badges[item.key] || 0,
    badgeLabel: badgeLabel(item.key, badges[item.key]),
  });
  return managerNav.map((item) => item.items ? { label: item.label, items: item.items.map(entry) } : entry(item));
}

export default function ManagerDashboard({ token, account, onLogout, onAuthError, onAccountChange }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [unreadMessages, setUnreadMessages] = useState(0);
  const [pendingAdvanceRequests, setPendingAdvanceRequests] = useState(0);
  useEffect(() => {
    let cancelled = false;
    Promise.all(Object.keys(modules).map(async (resource) => [resource, await fetchRecords(token, resource)])).then((entries) => {
      if (!cancelled) { setData(Object.fromEntries(entries)); setError(""); }
    }).catch((err) => { if (!cancelled) { setError(err.message); onAuthError(err); } });
    return () => { cancelled = true; };
  }, [token, retry, onAuthError]);

  useEffect(() => {
    let cancelled = false;
    const refreshAttendance = () => fetchRecords(token, "attendance").then((attendance) => {
      if (!cancelled) setData((current) => current ? { ...current, attendance } : current);
    }).catch((err) => onAuthError(err));
    const timer = window.setInterval(refreshAttendance, 3000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [token, onAuthError]);

  useEffect(() => {
    let cancelled = false;
    const refreshAttention = () => Promise.all([
      fetchRecords(token, "contracts"), fetchRecords(token, "leave"),
    ]).then(([contracts, leave]) => {
      if (!cancelled) setData((current) => current ? { ...current, contracts, leave } : current);
    }).catch((err) => onAuthError(err));
    const timer = window.setInterval(refreshAttention, 10000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [token, onAuthError]);

  useEffect(() => {
    let cancelled = false;
    const refreshMessages = () => fetchCompanyThread(token).then((thread) => {
      if (!cancelled) setUnreadMessages(thread.unread);
    }).catch(() => {});
    refreshMessages();
    const timer = window.setInterval(refreshMessages, 15000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [token]);

  useEffect(() => {
    let cancelled = false;
    const refreshAdvanceRequests = () => fetchRecords(token, "salary-advance-requests").then((rows) => {
      if (!cancelled) setPendingAdvanceRequests(rows.filter((row) => row.status === "pending").length);
    }).catch(() => {});
    refreshAdvanceRequests();
    const timer = window.setInterval(refreshAdvanceRequests, 15000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [token]);

  function updateRecords(resource, record, deleted = false) {
    setData((current) => ({ ...current, [resource]: deleted ? current[resource].filter((row) => row.id !== record.id) : current[resource].some((row) => row.id === record.id) ? current[resource].map((row) => row.id === record.id ? record : row) : [record, ...current[resource]] }));
  }

  const attention = data ? {
    contracts: (data.contracts || []).reduce((total, row) => total
      + (row.signature_status === "signed" && row.worker_approval_status !== "approved" ? 1 : 0)
      + (row.termination?.initiated_by === "employee" && row.termination.status === "pending" ? 1 : 0), 0),
    leave: (data.leave || []).filter((row) => row.status === "pending").length,
    "calendar-events": upcomingEvents(data["calendar-events"] || []).length,
  } : {};

  return <>
    <DashboardTopNav
      items={managerNavItems({ ...attention, messages: unreadMessages, "salary-advances": pendingAdvanceRequests })}
      identity={{ eyebrow: account?.business_name || "MANAGER WORKSPACE", name: account?.display_name || account?.username || "Manager", role: account?.role_label || "Employer", detail: account?.email }}
      navLabel="Manager navigation"
      onLogout={onLogout}
      token={token}
      menu={[
        { title: "Account", links: [{ label: "Settings", to: "/dashboard/settings" }] },
        { title: "Manage", links: [
          { label: account?.business_name ? `Company: ${account.business_name}` : "Company dashboard", to: "/dashboard" },
          { label: "Messages", to: "/dashboard/messages" },
          { label: "Reports", to: "/dashboard/reports" },
        ] },
      ]}
    />
    <main className="dashboard-main topnav-main"><section className="workspace dashboard-workspace">
      {error ? <div className="panel records-panel"><p className="message error" role="alert">{error}</p><button type="button" className="button button-coral" onClick={() => { setError(""); setRetry((value) => value + 1); }}>Retry loading</button></div> : !data ? <p className="empty-state" role="status">Loading manager workspace…</p> : <Routes>
        <Route index element={<ReportsPage key="overview" token={token} onAuthError={onAuthError} overview />} />
        <Route path="reports" element={<ReportsPage key="reports" token={token} onAuthError={onAuthError} />} />
        <Route path="messages" element={<PlatformMessagesPage token={token} onAuthError={onAuthError} />} />
        <Route path="google-meet" element={<GoogleMeetPage token={token} employees={data.employees || []} onChange={updateRecords} />} />
        <Route path="settings" element={<SettingsPage token={token} account={account} onAccountChange={onAccountChange} onAuthError={onAuthError} />} />
        <Route path="asset-misuse" element={<AssetMisusePage token={token} employees={data.employees || []} onAuthError={onAuthError} />} />
        <Route path="access-control/*" element={<AccessControl token={token} role="employer" employees={data.employees || []} onAuthError={onAuthError} />} />
        <Route path="salary-advances" element={<SalaryAdvancesPage token={token} employees={data.employees || []} onAuthError={onAuthError} onRequestsChange={setPendingAdvanceRequests} />} />
        {Object.keys(modules).map((resource) => <Route key={resource} path={resource} element={modules[resource].custom
          ? <ManagerCalendarPage token={token} events={data[resource] || []} onChange={updateRecords} onAuthError={onAuthError} />
          : <ResourcePage key={resource} resource={resource} data={data} token={token} account={account} onChange={updateRecords} onAuthError={onAuthError} />} />)}
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>}
    </section></main>
  </>;
}
