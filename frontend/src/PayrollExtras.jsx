import { useCallback, useEffect, useState } from "react";
import ModalDialog from "./components/ModalDialog";
import { useConfirm } from "./components/ConfirmDialog";
import { addAdvanceRepayment, decideSalaryAdvanceRequest, deleteRecord, downloadEvidence, fetchAssetSummary,
  fetchRecords, saveRecord } from "./api";
import { decisionText, label, money, today } from "./managerConfig";

const CURRENCIES = ["RWF", "ZAR", "USD", "EUR", "GBP", "BWP", "NAD", "LSL", "SZL", "KES", "NGN"];
const METHODS = [["bank_transfer", "Bank transfer"], ["mobile_money", "Mobile money"], ["cash", "Cash"]];
const EVIDENCE_ACCEPT = ".pdf,.jpg,.jpeg,.png,.webp,.doc,.docx";
const MAX_EVIDENCE = 10 * 1024 * 1024;
const STATUS_TEXT = {
  pending: "Pending", reported: "Reported", under_review: "Under review", resolved: "Resolved", closed: "Closed",
  disbursed: "Disbursed", partially_repaid: "Partially repaid", repaid: "Repaid", scheduled: "Scheduled",
  not_applied: "Not applied",
};

const methodText = (value) => METHODS.find(([key]) => key === value)?.[1] || label(value);
const statusText = (value) => STATUS_TEXT[value] || label(value);
const dateTime = (value) => value ? new Date(value).toLocaleString() : "Not recorded";
const contains = (values, search) => values.join(" ").toLowerCase().includes(search.trim().toLowerCase());

function StatusBadge({ value, text }) {
  return <span className={`status-badge status-${value}`}>{text || statusText(value)}</span>;
}

function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function useRecords(token, resource, onAuthError) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [version, setVersion] = useState(0);
  useEffect(() => {
    let cancelled = false;
    fetchRecords(token, resource)
      .then((result) => { if (!cancelled) { setRows(result); setError(""); } })
      .catch((err) => { if (!cancelled) { setError(err.message); onAuthError(err); } })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [token, resource, version, onAuthError]);
  const reload = useCallback(() => setVersion((value) => value + 1), []);
  const upsert = useCallback((record, removed = false) => setRows((current) => removed
    ? current.filter((row) => row.id !== record.id)
    : current.some((row) => row.id === record.id)
      ? current.map((row) => row.id === record.id ? record : row)
      : [record, ...current]), []);
  return { rows, loading, error, reload, upsert };
}

function Table({ columns, rows, empty, onRowClick, actions }) {
  if (!rows.length) return <p className="empty-state">{empty}</p>;
  const open = (event, row) => {
    if (onRowClick && !event.target.closest("button, a, input, select, textarea")) onRowClick(row);
  };
  return <div className="table-scroll"><table>
    <thead><tr>{columns.map((column) => <th key={column.title} scope="col">{column.title}</th>)}{actions && <th scope="col">Actions</th>}</tr></thead>
    <tbody>{rows.map((row, index) => <tr key={row.id ?? index} className={onRowClick ? "clickable-row" : undefined} tabIndex={onRowClick ? 0 : undefined}
      onClick={(event) => open(event, row)}
      onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { if (onRowClick && !event.target.closest("button, a, input, select, textarea")) { event.preventDefault(); onRowClick(row); } } }}>
      {columns.map((column) => <td key={column.title}>{column.render(row)}</td>)}
      {actions && <td><div className="row-actions">{actions(row)}</div></td>}
    </tr>)}</tbody>
  </table></div>;
}

function Tabs({ tabs, value, onChange, label: ariaLabel }) {
  return <div className="calendar-tabs payroll-tabs" role="tablist" aria-label={ariaLabel}>
    {tabs.map(([key, title]) => <button key={key} type="button" role="tab" aria-selected={value === key}
      className={`calendar-tab${value === key ? " selected" : ""}`} onClick={() => onChange(key)}>{title}</button>)}
  </div>;
}

function Summary({ items }) {
  return <div className="summary-row manager-summary">{items.map(([title, value, note]) => <div className="summary-card" key={title}>
    <span>{title}</span><strong>{value}</strong>{note && <small className="muted">{note}</small>}
  </div>)}</div>;
}

function Heading({ eyebrow = "PAYROLL", title, description, action }) {
  return <div className="section-heading"><div><p className="eyebrow dark-eyebrow">{eyebrow}</p><h2>{title}</h2>{description && <p>{description}</p>}</div>{action}</div>;
}

function Messages({ error, notice }) {
  return <>
    {error && <p className="message error" role="alert">{error}</p>}
    {notice && <p className="message success" role="status">{notice}</p>}
  </>;
}

function Field({ id, title, optional, hint, wide, children }) {
  return <div className={wide ? "field-wide" : undefined}>
    <label htmlFor={id}>{title}{optional ? " (optional)" : ""}</label>
    {children}
    {hint && <small className="field-hint">{hint}</small>}
  </div>;
}

function Facts({ items }) {
  return <dl className="employee-manage-facts payroll-facts">{items.filter(Boolean).map(([title, value]) => <div key={title}><dt>{title}</dt><dd>{value || "Not recorded"}</dd></div>)}</dl>;
}

function useForm(initial = null, prefix = "payroll-extra") {
  const [form, setForm] = useState(initial);
  const bind = (name) => ({
    id: `${prefix}-${name}`,
    name,
    value: form?.[name] ?? "",
    onChange: (event) => setForm((current) => ({ ...current, [name]: event.target.value })),
  });
  const bindFile = (name) => ({
    id: `${prefix}-${name}`,
    name,
    type: "file",
    accept: EVIDENCE_ACCEPT,
    onChange: (event) => setForm((current) => ({ ...current, [name]: event.target.files[0] || null })),
  });
  return { form, setForm, bind, bindFile };
}

function withEvidence(payload, file) {
  if (!file) return payload;
  const body = new FormData();
  Object.entries(payload).forEach(([key, value]) => { if (value !== null && value !== undefined) body.append(key, value); });
  body.append("evidence", file);
  return body;
}

function employeeOptions(employees) {
  return employees.map((person) => <option key={person.id} value={person.id}>{person.first_name} {person.last_name}{!person.is_active ? " (inactive)" : ""}</option>);
}

// --- Asset Misuse ------------------------------------------------------------

const INCIDENT_STATUSES = [["reported", "Reported"], ["under_review", "Under review"], ["resolved", "Resolved"], ["closed", "Closed"]];
const INCIDENT_TYPES = [["damaged", "Damaged"], ["lost", "Lost"], ["misused", "Misused"]];

export function AssetMisusePage({ token, employees, onAuthError }) {
  const incidents = useRecords(token, "asset-incidents", onAuthError);
  const [summary, setSummary] = useState([]);
  const [tab, setTab] = useState("incidents");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [type, setType] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [viewingId, setViewingId] = useState(null);
  const { form, setForm, bind, bindFile } = useForm();
  const [confirm, confirmation] = useConfirm();
  const { rows } = incidents;

  useEffect(() => {
    let cancelled = false;
    fetchAssetSummary(token).then((result) => { if (!cancelled) setSummary(result); }).catch((err) => onAuthError(err));
    return () => { cancelled = true; };
  }, [token, onAuthError, rows]);

  const fail = (err) => { setError(err.message); onAuthError(err); };
  const viewing = rows.find((row) => row.id === viewingId) || null;
  const visible = rows.filter((row) => (!status || row.status === status) && (!type || row.incident_type === type)
    && contains([row.employee_name, row.asset_name, row.asset_tag, row.description], search));
  const open = rows.filter((row) => ["reported", "under_review"].includes(row.status)).length;
  const rwfLoss = rows.filter((row) => row.currency === "RWF").reduce((sum, row) => sum + Number(row.estimated_loss), 0);
  const rwfRecovery = rows.filter((row) => row.currency === "RWF").reduce((sum, row) => sum + Number(row.recovery_amount), 0);

  function openForm(row = null) {
    setError("");
    setNotice("");
    setForm(row ? { id: row.id, employee: row.employee, asset_name: row.asset_name, asset_tag: row.asset_tag, incident_type: row.incident_type, incident_date: row.incident_date, description: row.description, estimated_loss: row.estimated_loss, currency: row.currency, status: row.status, investigation_findings: row.investigation_findings, employee_response: row.employee_response, resolution: row.resolution, recovery_amount: row.recovery_amount, recovery_authorization: row.recovery_authorization, evidence: null, evidence_name: row.evidence_name }
      : { employee: "", asset_name: "", incident_type: "damaged", estimated_loss: "0", description: "" });
  }

  async function submit(event) {
    event.preventDefault();
    setError("");
    if (form.evidence && form.evidence.size > MAX_EVIDENCE) { setError("Evidence files must be 10 MB or smaller."); return; }
    if (Number(form.recovery_amount) > Number(form.estimated_loss)) { setError("The recovery amount cannot exceed the estimated loss."); return; }
    if (Number(form.recovery_amount) > 0 && !form.recovery_authorization.trim()) { setError("Record the legal basis or the employee's written agreement before recording a recovery amount."); return; }
    setBusy(true);
    try {
      const { id, evidence, ...fields } = form;
      delete fields.evidence_name;
      const saved = await saveRecord(token, "asset-incidents", withEvidence(fields, evidence), id);
      incidents.upsert(saved);
      setNotice(id ? `Incident for ${saved.asset_name} updated.` : `Incident recorded for ${saved.employee_name}. Nothing is deducted from salary while it is unresolved.`);
      setForm(null);
    } catch (err) { fail(err); } finally { setBusy(false); }
  }

  async function setIncidentStatus(row, next) {
    if (["resolved", "closed"].includes(next) && !row.resolution.trim()) {
      openForm(row);
      setForm((current) => ({ ...current, status: next }));
      setError("Describe the resolution before resolving or closing the incident.");
      return;
    }
    if (next === "closed" && !await confirm({ title: "Close this incident?", message: "Closed incidents are kept as a permanent record and can no longer be edited.", confirmLabel: "Close incident" })) return;
    setBusy(true);
    setError("");
    try {
      const saved = await saveRecord(token, "asset-incidents", { status: next }, row.id);
      incidents.upsert(saved);
      setNotice(`Incident marked ${statusText(next).toLowerCase()}.`);
    } catch (err) { fail(err); } finally { setBusy(false); }
  }

  async function remove(row) {
    if (!await confirm({ title: "Delete incident?", message: `Delete the ${row.asset_name} incident? Only incidents that are still Reported can be deleted.`, confirmLabel: "Delete" })) return;
    setBusy(true);
    try {
      await deleteRecord(token, "asset-incidents", row.id);
      incidents.upsert(row, true);
      setViewingId(null);
      setNotice("Incident deleted.");
    } catch (err) { fail(err); } finally { setBusy(false); }
  }

  async function download(row) {
    try { saveBlob(await downloadEvidence(token, "asset-incidents", row.id), row.evidence_name || `incident-${row.id}`); }
    catch (err) { fail(err); }
  }

  return <>
    <Heading title="Asset misuse" description="Record company assets that were damaged, lost or misused, investigate, and keep the outcome on file. Recorded losses are deducted automatically through payroll, within the legal deduction limit."
      action={<button type="button" className="button button-coral" disabled={!employees.length} onClick={() => openForm()}>+ Report incident</button>} />
    <Messages error={error || incidents.error} notice={notice} />
    <Summary items={[
      ["Open incidents", open, "Reported or under review"],
      ["Documented losses", money(rwfLoss), "RWF incidents"],
      ["Authorized recovery", money(rwfRecovery), "Replaces the estimated loss when set"],
      ["Employees involved", summary.length ? new Set(summary.map((row) => row.employee)).size : 0],
    ]} />
    <Tabs label="Asset misuse views" value={tab} onChange={setTab} tabs={[["incidents", "Incidents"], ["history", "Employee history"]]} />
    {incidents.loading ? <p className="empty-state" role="status">Loading incidents…</p> : tab === "incidents" ? <section className="panel records-panel" aria-label="Asset incidents">
      <div className="records-toolbar"><span className="record-count">{visible.length} {visible.length === 1 ? "incident" : "incidents"}</span><div className="records-filters">
        <input type="search" aria-label="Search incidents" placeholder="Search incidents…" value={search} onChange={(event) => setSearch(event.target.value)} />
        <select aria-label="Filter by status" value={status} onChange={(event) => setStatus(event.target.value)}><option value="">All statuses</option>{INCIDENT_STATUSES.map(([key, title]) => <option key={key} value={key}>{title}</option>)}</select>
        <select aria-label="Filter by type" value={type} onChange={(event) => setType(event.target.value)}><option value="">All types</option>{INCIDENT_TYPES.map(([key, title]) => <option key={key} value={key}>{title}</option>)}</select>
      </div></div>
      <Table rows={visible} onRowClick={(row) => setViewingId(row.id)} empty={rows.length ? "No incidents match these filters." : "No asset incidents recorded."} columns={[
        { title: "Employee", render: (row) => row.employee_name },
        { title: "Asset", render: (row) => <span>{row.asset_name}{row.asset_tag && <small className="muted"> {row.asset_tag}</small>}</span> },
        { title: "Type", render: (row) => label(row.incident_type) },
        { title: "Date", render: (row) => row.incident_date },
        { title: "Estimated loss", render: (row) => money(row.estimated_loss, row.currency) },
        { title: "Recovery", render: (row) => Number(row.recovery_amount) ? money(row.recovery_amount, row.currency) : "—" },
        { title: "Status", render: (row) => <StatusBadge value={row.status} /> },
      ]} actions={(row) => <>
        <button type="button" onClick={() => setViewingId(row.id)}>Details</button>
        {row.status !== "closed" && <button type="button" disabled={busy} onClick={() => openForm(row)}>Update</button>}
      </>} />
    </section> : <section className="panel records-panel" aria-label="Employee incident history">
      <Table rows={summary.map((row) => ({ ...row, id: `${row.employee}-${row.currency}` }))} empty="No incidents recorded." columns={[
        { title: "Employee", render: (row) => row.employee_name },
        { title: "Incidents", render: (row) => row.incidents },
        { title: "Open", render: (row) => row.open_incidents },
        { title: "Total documented loss", render: (row) => money(row.total_loss, row.currency) },
        { title: "Authorized recovery", render: (row) => money(row.total_recovery, row.currency) },
      ]} actions={(row) => <button type="button" onClick={() => { setTab("incidents"); setSearch(row.employee_name); }}>View incidents</button>} />
    </section>}

    {viewing && <ModalDialog title="Asset incident" wide onClose={() => setViewingId(null)}><section className="account-panel leave-preview payroll-detail">
      <h3>{viewing.asset_name} <StatusBadge value={viewing.status} /></h3>
      <Facts items={[
        ["Employee", viewing.employee_name], ["Asset tag", viewing.asset_tag], ["Incident type", label(viewing.incident_type)],
        ["Incident date", viewing.incident_date], ["Estimated loss", money(viewing.estimated_loss, viewing.currency)],
        ["Authorized recovery", Number(viewing.recovery_amount) ? money(viewing.recovery_amount, viewing.currency) : "None"],
        ["Recovered through payroll", money(viewing.recovered_amount, viewing.currency)],
        ["Recovery outstanding", money(viewing.outstanding_recovery, viewing.currency)],
        ["Reported by", viewing.reported_by], ["Reported on", dateTime(viewing.created_at)], ["Resolved", viewing.resolved_at ? dateTime(viewing.resolved_at) : "Not yet"],
      ]} />
      <h4>Description</h4><p className="preserve-lines">{viewing.description}</p>
      <h4>Investigation findings</h4><p className="preserve-lines">{viewing.investigation_findings || "Not recorded yet."}</p>
      <h4>Employee response</h4><p className="preserve-lines">{viewing.employee_response || "Not recorded yet."}</p>
      <h4>Resolution</h4><p className="preserve-lines">{viewing.resolution || "Not resolved yet."}</p>
      {Number(viewing.recovery_amount) > 0 && <><h4>Recovery authorization</h4><p className="preserve-lines">{viewing.recovery_authorization}</p></>}
      <p className="muted">The estimated loss, or the authorized recovery amount when one is set, is deducted automatically when salary is paid, within the legal deduction limit.</p>
      <div className="form-actions">
        {viewing.evidence_name && <button type="button" className="button button-outline" onClick={() => download(viewing)}>Download evidence</button>}
        {viewing.status === "reported" && <button type="button" className="button button-outline" disabled={busy} onClick={() => setIncidentStatus(viewing, "under_review")}>Start review</button>}
        {["reported", "under_review"].includes(viewing.status) && <button type="button" className="button button-outline" disabled={busy} onClick={() => setIncidentStatus(viewing, "resolved")}>Resolve</button>}
        {viewing.status === "resolved" && <button type="button" className="button button-outline" disabled={busy} onClick={() => setIncidentStatus(viewing, "closed")}>Close</button>}
        {viewing.status !== "closed" && <button type="button" className="button button-coral" onClick={() => { const row = viewing; setViewingId(null); openForm(row); }}>Update details</button>}
        {viewing.status === "reported" && <button type="button" className="danger-link" disabled={busy} onClick={() => remove(viewing)}>Delete</button>}
      </div>
    </section></ModalDialog>}

    {form && <ModalDialog title={form.id ? "Update incident" : "Report an asset incident"} wide onClose={() => setForm(null)}>
      <form className="record-form" onSubmit={submit}><fieldset disabled={busy}>
        {error && <p className="message error" role="alert">{error}</p>}
        {!form.id ? <div className="record-fields">
          <Field id="payroll-extra-employee" title="Employee"><select {...bind("employee")} required><option value="">Select an employee</option>{employeeOptions(employees)}</select></Field>
          <Field id="payroll-extra-asset_name" title="Asset name"><input {...bind("asset_name")} required maxLength="200" /></Field>
          <Field id="payroll-extra-incident_type" title="Incident type"><select {...bind("incident_type")}>{INCIDENT_TYPES.map(([key, title]) => <option key={key} value={key}>{title}</option>)}</select></Field>
          <Field id="payroll-extra-estimated_loss" title="Estimated loss (RWF)"><input {...bind("estimated_loss")} type="number" min="0" step="0.01" required /></Field>
          <Field id="payroll-extra-description" title="Description" wide><textarea {...bind("description")} rows="3" required /></Field>
        </div> : <div className="record-fields">
          <Field id="payroll-extra-employee" title="Assigned employee"><select {...bind("employee")} required><option value="">Select an employee</option>{employeeOptions(employees)}</select></Field>
          <Field id="payroll-extra-asset_name" title="Asset name"><input {...bind("asset_name")} required maxLength="200" /></Field>
          <Field id="payroll-extra-asset_tag" title="Asset tag or serial" optional><input {...bind("asset_tag")} maxLength="100" /></Field>
          <Field id="payroll-extra-incident_type" title="What happened"><select {...bind("incident_type")}>{INCIDENT_TYPES.map(([key, title]) => <option key={key} value={key}>{title}</option>)}</select></Field>
          <Field id="payroll-extra-incident_date" title="Incident date"><input {...bind("incident_date")} type="date" max={today()} required /></Field>
          <Field id="payroll-extra-estimated_loss" title="Estimated loss"><input {...bind("estimated_loss")} type="number" min="0" step="0.01" required /></Field>
          <Field id="payroll-extra-currency" title="Currency"><select {...bind("currency")}>{CURRENCIES.map((value) => <option key={value}>{value}</option>)}</select></Field>
          <Field id="payroll-extra-status" title="Status"><select {...bind("status")}>{INCIDENT_STATUSES.map(([key, title]) => <option key={key} value={key}>{title}</option>)}</select></Field>
          <Field id="payroll-extra-description" title="Description" wide><textarea {...bind("description")} rows="3" required /></Field>
          <Field id="payroll-extra-evidence" title="Evidence (PDF, image or Word; max 10 MB)" optional wide hint={form.evidence_name ? `Current file: ${form.evidence_name}. Choosing a new file replaces it.` : undefined}><input {...bindFile("evidence")} /></Field>
          <Field id="payroll-extra-investigation_findings" title="Investigation findings" optional wide><textarea {...bind("investigation_findings")} rows="3" /></Field>
          <Field id="payroll-extra-employee_response" title="Employee response" optional wide><textarea {...bind("employee_response")} rows="3" /></Field>
          <Field id="payroll-extra-resolution" title="Resolution" optional={!["resolved", "closed"].includes(form.status)} wide><textarea {...bind("resolution")} rows="2" required={["resolved", "closed"].includes(form.status)} /></Field>
          <Field id="payroll-extra-recovery_amount" title="Authorized recovery amount" hint="Optional. Deducted through payroll instead of the estimated loss."><input {...bind("recovery_amount")} type="number" min="0" step="0.01" /></Field>
          <Field id="payroll-extra-recovery_authorization" title="Legal basis or written agreement" optional={!(Number(form.recovery_amount) > 0)} wide><textarea {...bind("recovery_authorization")} rows="2" required={Number(form.recovery_amount) > 0} /></Field>
        </div>}
        <div className="form-actions"><button type="submit" className="button button-coral">{busy ? "Saving…" : form.id ? "Save changes" : "Report incident"}</button><button type="button" className="button button-outline" onClick={() => setForm(null)}>Cancel</button></div>
      </fieldset></form>
    </ModalDialog>}
    {confirmation}
  </>;
}

// --- Salary Advances ---------------------------------------------------------

const ADVANCE_STATUSES = [["disbursed", "Disbursed"], ["partially_repaid", "Partially repaid"], ["repaid", "Repaid"]];

export function SalaryAdvancesPage({ token, employees, onAuthError, onRequestsChange }) {
  const advances = useRecords(token, "salary-advances", onAuthError);
  const requests = useRecords(token, "salary-advance-requests", onAuthError);
  const [rejecting, setRejecting] = useState(null);
  const pendingRequests = requests.rows.filter((row) => row.status === "pending");
  const decidedRequests = requests.rows.filter((row) => row.status !== "pending");
  const pendingCount = pendingRequests.length;
  useEffect(() => { if (!requests.loading) onRequestsChange?.(pendingCount); }, [requests.loading, pendingCount, onRequestsChange]);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [viewingId, setViewingId] = useState(null);
  const [action, setAction] = useState(null);
  const { form, setForm, bind } = useForm();
  const [confirm, confirmation] = useConfirm();
  const rows = advances.rows;

  const fail = (err) => { setError(err.message); onAuthError(err); };
  const viewing = rows.find((row) => row.id === viewingId) || null;
  const visible = rows.filter((row) => (!status || row.status === status) && contains([row.employee_name, row.reason, row.disbursement_reference], search));
  const rwf = rows.filter((row) => row.currency === "RWF");
  const outstanding = rwf.reduce((sum, row) => sum + Number(row.outstanding_balance), 0);
  const repaid = rwf.reduce((sum, row) => sum + Number(row.total_repaid), 0);

  function openForm(row = null) {
    setError("");
    setNotice("");
    setAction("edit");
    setForm(row ? { id: row.id, employee: row.employee, amount: row.amount, currency: row.currency, issue_date: row.issue_date, notes: row.notes, locked: row.repayments.length > 0 }
      : { employee: "", amount: "", currency: "RWF", issue_date: today(), notes: "" });
  }

  function openAction(kind, row) {
    setError("");
    setNotice("");
    setAction(kind);
    setForm({ id: row.id, amount: "", repaid_on: today(), reference: "", notes: "" });
  }

  async function submit(event) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      const { id, ...fields } = form;
      delete fields.locked;
      let saved;
      if (action === "edit") {
        saved = await saveRecord(token, "salary-advances", fields, id);
        setNotice(id ? "Advance updated." : `Advance recorded for ${saved.employee_name}. It is deducted automatically when their salary is paid.`);
      } else {
        saved = await addAdvanceRepayment(token, id, fields);
        setNotice("Direct repayment recorded.");
      }
      advances.upsert(saved);
      setAction(null);
      setForm(null);
    } catch (err) { fail(err); } finally { setBusy(false); }
  }

  async function decide(row, decision, notes = "") {
    if (decision === "approve" && !await confirm({ title: "Approve advance request?", message: `Approve ${row.employee_name}'s request for ${money(row.amount, row.currency)}? It is recorded as a salary advance given today and deducted automatically when their salary is paid.`, confirmLabel: "Approve" })) return;
    setError("");
    setNotice("");
    setBusy(true);
    try {
      const saved = await decideSalaryAdvanceRequest(token, row.id, decision, { decision_notes: notes });
      requests.upsert(saved);
      setRejecting(null);
      if (decision === "approve") {
        advances.reload();
        setNotice(`Advance approved for ${row.employee_name}. It is deducted automatically when their salary is paid.`);
      } else {
        setNotice(`${row.employee_name}'s advance request was rejected.`);
      }
    } catch (err) { fail(err); } finally { setBusy(false); }
  }

  async function remove(row) {
    if (!await confirm({ title: "Delete advance?", message: "Only advances without recorded repayments can be deleted.", confirmLabel: "Delete" })) return;
    setBusy(true);
    try {
      await deleteRecord(token, "salary-advances", row.id);
      advances.upsert(row, true);
      setViewingId(null);
      setNotice("Advance deleted.");
    } catch (err) { fail(err); } finally { setBusy(false); }
  }

  return <>
    <Heading title="Salary advances"
      action={<button type="button" className="button button-coral" disabled={!employees.length} onClick={() => openForm()}>+ Add Salary Advance</button>} />
    <Messages error={error || advances.error || requests.error} notice={notice} />
    {pendingCount > 0 && <section className="panel records-panel" aria-label="Advance requests from employees">
      <div className="records-toolbar"><span className="record-count">{pendingCount} {pendingCount === 1 ? "request" : "requests"} from employees awaiting your decision</span></div>
      <Table rows={pendingRequests} empty="No pending requests." columns={[
        { title: "Employee", render: (row) => row.employee_name },
        { title: "Requested", render: (row) => dateTime(row.requested_at) },
        { title: "Amount", render: (row) => money(row.amount, row.currency) },
        { title: "Reason", render: (row) => row.reason || "—" },
      ]} actions={(row) => <>
        <button type="button" className="button button-coral" disabled={busy} onClick={() => decide(row, "approve")}>Approve</button>
        <button type="button" disabled={busy} onClick={() => { setError(""); setRejecting({ row, notes: "" }); }}>Reject</button>
      </>} />
    </section>}
    <Summary items={[
      ["Outstanding balance", money(outstanding), "RWF advances"],
      ["Total repaid", money(repaid), "RWF advances"],
      ["Active advances", rows.filter((row) => ["disbursed", "partially_repaid"].includes(row.status)).length],
    ]} />
    {advances.loading ? <p className="empty-state" role="status">Loading advances…</p> : <section className="panel records-panel" aria-label="Salary advances">
      <div className="records-toolbar"><span className="record-count">{visible.length} {visible.length === 1 ? "advance" : "advances"}</span><div className="records-filters">
        <input type="search" aria-label="Search advances" placeholder="Search advances…" value={search} onChange={(event) => setSearch(event.target.value)} />
        <select aria-label="Filter by status" value={status} onChange={(event) => setStatus(event.target.value)}><option value="">All statuses</option>{ADVANCE_STATUSES.map(([key, title]) => <option key={key} value={key}>{title}</option>)}</select>
      </div></div>
      <Table rows={visible} onRowClick={(row) => setViewingId(row.id)} empty={rows.length ? "No advances match these filters." : "No salary advances issued yet."} columns={[
        { title: "Employee", render: (row) => row.employee_name },
        { title: "Issued", render: (row) => row.issue_date },
        { title: "Original amount", render: (row) => money(row.amount, row.currency) },
        { title: "Repaid", render: (row) => money(row.total_repaid, row.currency) },
        { title: "Outstanding", render: (row) => money(row.outstanding_balance, row.currency) },
        { title: "Next installment", render: (row) => Number(row.next_installment) ? money(row.next_installment, row.currency) : "—" },
        { title: "Status", render: (row) => <StatusBadge value={row.status} /> },
      ]} actions={(row) => <button type="button" onClick={() => setViewingId(row.id)}>Details</button>} />
    </section>}
    {decidedRequests.length > 0 && <details className="panel records-panel decided-requests"><summary>Decided requests from employees ({decidedRequests.length})</summary>
      <Table rows={decidedRequests} empty="No decided requests." columns={[
        { title: "Employee", render: (row) => row.employee_name },
        { title: "Requested", render: (row) => dateTime(row.requested_at) },
        { title: "Amount", render: (row) => money(row.amount, row.currency) },
        { title: "Decision", render: (row) => decisionText(row.status, row.decided_by, row.decided_at) },
        { title: "Notes", render: (row) => row.decision_notes || "—" },
      ]} />
    </details>}

    {viewing && <ModalDialog title="Salary advance" wide onClose={() => setViewingId(null)}><section className="account-panel leave-preview payroll-detail">
      <h3>{viewing.employee_name} <StatusBadge value={viewing.status} /></h3>
      <Facts items={[
        ["Original amount", money(viewing.amount, viewing.currency)], ["Total repaid", money(viewing.total_repaid, viewing.currency)],
        ["Outstanding balance", money(viewing.outstanding_balance, viewing.currency)], ["Scheduled in draft payroll", money(viewing.scheduled_deductions, viewing.currency)],
        ["Next installment", Number(viewing.next_installment) ? money(viewing.next_installment, viewing.currency) : "None"], ["Monthly installment", money(viewing.installment_amount, viewing.currency)],
        ["Issued", viewing.issue_date], ["Approved by", viewing.approved_by], ["Repayment starts", String(viewing.first_repayment_month).slice(0, 7)],
        ["Given to employee", viewing.disbursed_on ? `${viewing.disbursed_on} · ${methodText(viewing.disbursement_method)}` : viewing.issue_date],
        viewing.disbursement_reference && ["Payment reference", viewing.disbursement_reference],
        ["Interest", "None"],
      ]} />
      {viewing.reason && <><h4>Reason</h4><p className="preserve-lines">{viewing.reason}</p></>}
      {viewing.notes && <><h4>Notes</h4><p className="preserve-lines">{viewing.notes}</p></>}
      <h4>Repayment schedule</h4>
      <Table rows={viewing.schedule.map((row) => ({ ...row, id: row.month }))} empty="No schedule." columns={[
        { title: "Month", render: (row) => row.month }, { title: "Planned installment", render: (row) => money(row.amount, viewing.currency) },
      ]} />
      <h4>Repayment history</h4>
      <Table rows={viewing.repayments} empty="No repayments yet." columns={[
        { title: "Date", render: (row) => row.repaid_on },
        { title: "Source", render: (row) => row.source === "payroll" ? `Payroll ${row.payroll_period}` : "Direct repayment" },
        { title: "Amount", render: (row) => money(row.amount, viewing.currency) },
        { title: "Reference", render: (row) => row.reference || "—" },
        { title: "State", render: (row) => <StatusBadge value={row.state} text={row.state === "scheduled" ? "Scheduled (draft payroll)" : row.state === "not_applied" ? "Not applied (payroll edited)" : "Repaid"} /> },
      ]} />
      <div className="form-actions">
        {["disbursed", "partially_repaid"].includes(viewing.status) && <button type="button" className="button button-outline" disabled={busy} onClick={() => openAction("repay", viewing)}>Record direct repayment</button>}
        {viewing.status !== "repaid" && !viewing.from_request && <button type="button" className="button button-outline" onClick={() => { const row = viewing; setViewingId(null); openForm(row); }}>Edit</button>}
        {viewing.repayments.length === 0 && !viewing.from_request && <button type="button" className="danger-link" disabled={busy} onClick={() => remove(viewing)}>Delete</button>}
      </div>
      {viewing.from_request && <p className="muted">Approved from the employee's request, so it can no longer be edited or deleted.</p>}
    </section></ModalDialog>}

    {form && action && <ModalDialog title={action === "repay" ? "Record direct repayment" : form.id ? "Edit advance" : "Issue salary advance"} wide={action === "edit"} onClose={() => { setForm(null); setAction(null); }}>
      <form className="record-form" onSubmit={submit}><fieldset disabled={busy}>
        {error && <p className="message error" role="alert">{error}</p>}
        <div className="record-fields">
          {action === "edit" && <>
            <Field id="payroll-extra-employee" title="Employee"><select {...bind("employee")} required disabled={form.locked}><option value="">Select an employee</option>{employeeOptions(employees.filter((person) => person.is_active || person.id === Number(form.employee)))}</select></Field>
            <Field id="payroll-extra-amount" title="Advance amount"><input {...bind("amount")} type="number" min="0.01" step="0.01" required readOnly={form.locked} /></Field>
            <Field id="payroll-extra-currency" title="Currency"><select {...bind("currency")} disabled={form.locked}>{CURRENCIES.map((value) => <option key={value}>{value}</option>)}</select></Field>
            <Field id="payroll-extra-issue_date" title="Issue date"><input {...bind("issue_date")} type="date" required readOnly={form.locked} /></Field>
            <Field id="payroll-extra-notes" title="Notes" optional wide><textarea {...bind("notes")} rows="2" /></Field>
          </>}
          {action === "repay" && <>
            <Field id="payroll-extra-amount" title="Amount repaid" hint={viewing ? `Up to ${money(Number(viewing.outstanding_balance) - Number(viewing.scheduled_deductions), viewing.currency)} after scheduled payroll deductions.` : undefined}><input {...bind("amount")} type="number" min="0.01" step="0.01" required /></Field>
            <Field id="payroll-extra-repaid_on" title="Repaid on"><input {...bind("repaid_on")} type="date" max={today()} required /></Field>
            <Field id="payroll-extra-reference" title="Reference" optional><input {...bind("reference")} maxLength="120" /></Field>
            <Field id="payroll-extra-notes" title="Notes" optional wide><textarea {...bind("notes")} rows="2" /></Field>
          </>}
        </div>
        <div className="form-actions"><button type="submit" className="button button-coral">{busy ? "Saving…" : "Save"}</button><button type="button" className="button button-outline" onClick={() => { setForm(null); setAction(null); }}>Cancel</button></div>
      </fieldset></form>
    </ModalDialog>}
    {rejecting && <ModalDialog title="Reject advance request" onClose={() => setRejecting(null)}>
      <form className="record-form" onSubmit={(event) => { event.preventDefault(); decide(rejecting.row, "reject", rejecting.notes); }}><fieldset disabled={busy}>
        {error && <p className="message error" role="alert">{error}</p>}
        <p>Reject {rejecting.row.employee_name}'s request for {money(rejecting.row.amount, rejecting.row.currency)}?</p>
        <div className="record-fields">
          <Field id="advance-request-notes" title="Reason shown to the employee" optional wide><textarea id="advance-request-notes" rows="2" value={rejecting.notes} onChange={(event) => setRejecting((current) => ({ ...current, notes: event.target.value }))} /></Field>
        </div>
        <div className="form-actions"><button type="submit" className="button button-coral">{busy ? "Saving…" : "Reject request"}</button><button type="button" className="button button-outline" onClick={() => setRejecting(null)}>Cancel</button></div>
      </fieldset></form>
    </ModalDialog>}
    {confirmation}
  </>;
}
