import { useCallback, useEffect, useState } from "react";
import { Link, NavLink, Navigate, Route, Routes, useLocation, useNavigate, useParams, useSearchParams } from "react-router";
import {
  deleteAdminBusiness, deleteAdminEmployee, fetchAdminBusinesses, fetchAdminEmployees,
  fetchAdminEmployers, fetchAdminOverview, fetchAdminThread, fetchAdminThreads,
  markAdminThreadRead, markAllAdminThreadsRead, saveAdminEmployee, saveAdminEmployer,
  saveCompanyStatus, sendAdminMessage,
} from "../api";
import Conversation from "./Conversation";
import PlatformOverview from "./PlatformOverview";
import ModalDialog from "./ModalDialog";
import { useConfirm } from "./ConfirmDialog";

function whenCreated(value) {
  if (!value) return "Never";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const day = String(date.getDate()).padStart(2, "0");
  const month = String(date.getMonth() + 1).padStart(2, "0");
  return `${day}/${month}/${date.getFullYear()}`;
}

const emptyEmployer = { username: "", email: "", password: "", business_name: "" };
const emptyEmployee = { business: "", first_name: "", last_name: "", job_title: "", email: "" };

// Overview tiles deep-link into these lists, so the filter lives in the URL
// rather than in component state.
const employeeFilters = [["", "All employees"], ["active", "Active employees"],
  ["inactive", "Inactive employees"], ["invited", "Awaiting first sign-in"]];

const employerFilters = [["", "All employers"], ["active", "Signed in"],
  ["dormant", "Never signed in"], ["suspended", "Suspended"]];

const companyFilters = [["", "All companies"], ["active", "Active"],
  ["pending", "Awaiting verification"], ["suspended", "Suspended"]];

const companyStatusLabels = { active: "Active", pending: "Awaiting verification", suspended: "Suspended" };
const companyStatusClass = { active: "active", pending: "pending", suspended: "ended" };

function matchesFilter(row, status) {
  if (status === "active") return row.is_active;
  if (status === "inactive") return !row.is_active;
  if (status === "invited") return row.account_status === "pending_first_sign_in";
  return true;
}

// The administrator's attention belongs at company level. An employer who has
// never used their sign-in, or one that has been suspended, is the platform's
// problem; an employee who has not activated their account is their own
// employer's, so it raises nothing here.
function employerNeedsAttention(row) {
  return row.is_active && !row.last_login;
}

function matchesEmployerFilter(row, status) {
  if (status === "active") return row.is_active && Boolean(row.last_login);
  if (status === "dormant") return employerNeedsAttention(row);
  if (status === "suspended") return !row.is_active;
  return true;
}

// Every page below the overview carries a way back, so an admin who arrived
// from a tile, a filtered link, or a bookmark is never stranded.
function BackButton() {
  const navigate = useNavigate();
  // The router stamps an index onto each entry it pushes. At 0 this page is the
  // first in the tab, so stepping back would leave the dashboard altogether;
  // fall back to the overview instead.
  const hasHistory = (window.history.state?.idx ?? 0) > 0;
  return <button className="page-back" type="button" onClick={() => hasHistory ? navigate(-1) : navigate("/admin")}>
    <span aria-hidden="true">&larr;</span> Back
  </button>;
}

function Table({ columns, rows, empty, actions, rowClassName }) {
  if (!rows.length) return <p className="empty-state">{empty}</p>;
  return <div className="table-scroll"><table>
    <thead><tr>{columns.map((column) => <th key={column.title} scope="col">{column.title}</th>)}{actions && <th scope="col">Actions</th>}</tr></thead>
    <tbody>{rows.map((row) => <tr key={row.id} className={rowClassName?.(row) || undefined}>
      {columns.map((column) => <td key={column.title}>{column.value(row) || "Not recorded"}</td>)}
      {actions && <td><div className="row-actions">{actions(row)}</div></td>}
    </tr>)}</tbody>
  </table></div>;
}

// A company is the unit the platform admin can remove. With many companies on
// one platform, deleting a single employer sign-in would strand its workspace,
// so that action lives here and takes the whole company with it.
// The administrator writes to a company, and reads what it writes back. The
// list stays visible beside the open thread so a reply can be picked up without
// losing the conversation.
function MessagesPage({ token, onAuthError }) {
  const { business } = useParams();
  const [threads, setThreads] = useState(null);
  const [thread, setThread] = useState(null);
  const [error, setError] = useState("");
  const [clearing, setClearing] = useState(false);
  // Hold the loaded thread against the company in the URL, so switching
  // companies shows "loading" rather than the previous conversation.
  const open = thread && String(thread.business) === String(business) ? thread : null;

  const loadThreads = useCallback(() => fetchAdminThreads(token).then(setThreads).catch((err) => {
    setError(err.message); onAuthError(err);
  }), [token, onAuthError]);
  useEffect(() => { loadThreads(); }, [loadThreads]);

  // Opening a company's thread is what clears its badge, so the list is
  // reloaded straight afterwards to drop the count.
  useEffect(() => {
    if (!business) return undefined;
    let cancelled = false;
    markAdminThreadRead(token, business).then((data) => {
      if (!cancelled) { setThread(data); setError(""); loadThreads(); }
    }).catch((err) => {
      if (!cancelled) { setError(err.message); onAuthError(err); }
    });
    const timer = window.setInterval(() => fetchAdminThread(token, business).then((data) => {
      if (!cancelled) setThread(data);
    }).catch(() => {}), 15000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [token, business, onAuthError, loadThreads]);

  const totalUnread = threads ? threads.reduce((total, row) => total + row.unread, 0) : 0;

  async function clearAll() {
    setClearing(true);
    try { await markAllAdminThreadsRead(token); await loadThreads(); }
    catch (err) { setError(err.message); onAuthError(err); }
    finally { setClearing(false); }
  }

  async function send(body, channel) {
    const sent = await sendAdminMessage(token, business, body, channel);
    setThread((current) => current ? { ...current, messages: [...current.messages, sent] } : current);
    loadThreads();
  }

  return <>
    <div className="section-heading"><div><p className="eyebrow dark-eyebrow">PLATFORM</p><h2>Messages</h2><p>Write to a company directly. Choose whether it lands in their dashboard or in their inbox: a message appears here in their workspace and sends no email, an email goes to their inbox and stays out of their dashboard. Their replies come back here the same way.</p></div>{totalUnread > 0 && <button className="button button-outline" type="button" disabled={clearing} onClick={clearAll}>{clearing ? "Clearing\u2026" : `Mark all ${totalUnread} as read`}</button>}</div>
    {error && <p className="message error" role="alert">{error}</p>}
    <section className="panel records-panel">
      {!threads ? <p className="empty-state" role="status">Loading conversations…</p> : !threads.length
        ? <p className="empty-state">No companies on the platform yet.</p>
        : <div className="thread-layout">
          <nav className="thread-list" aria-label="Companies">
            {threads.map((row) => <Link key={row.business} to={`/admin/messages/${row.business}`}
              className={`thread-link${String(row.business) === String(business) ? " selected" : ""}`}>
              <strong>{row.business_name}{row.unread > 0 && <span className="attention-badge" aria-label={`${row.unread} unread`}>{row.unread}</span>}</strong>
              <small>{row.last_body ? `${row.last_from_admin ? "You: " : ""}${row.last_body}` : "No messages yet"}</small>
            </Link>)}
          </nav>
          <div>
            {!business ? <p className="empty-state">Choose a company to open its conversation.</p>
              : !open ? <p className="empty-state" role="status">Loading conversation…</p>
                : <Conversation
                  thread={open}
                  mine
                  onSend={send}
                  recipient={threads.find((row) => String(row.business) === String(business))?.employer_email}
                  placeholder={`Write to ${open.business_name}…`}
                  empty={`No messages with ${open.business_name} yet. Write the first one.`}
                />}
          </div>
        </div>}
    </section>
  </>;
}

function CompaniesPage({ token, onAuthError }) {
  const [rows, setRows] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [confirm, confirmation] = useConfirm();
  const [params, setParams] = useSearchParams();
  const status = params.get("status") || "";
  const highlighted = params.get("company") || "";
  const visible = rows ? rows.filter((row) => !status || row.status === status) : null;
  const pending = rows ? rows.filter((row) => row.status === "pending").length : 0;

  function filterBy(value) {
    setParams(value ? { status: value } : {}, { replace: true });
  }

  function load() {
    fetchAdminBusinesses(token).then(setRows).catch((err) => { setError(err.message); onAuthError(err); });
  }
  useEffect(load, [token, onAuthError]);

  async function setStatus(row, next) {
    if (next === "suspended" && !await confirm({
      title: "Suspend this company?",
      message: `Suspend ${row.name}? Its employer will not be able to sign in until you activate it again. Nothing the company holds is deleted.`,
      confirmLabel: "Suspend company",
    })) return;
    setBusy(true); setError(""); setNotice("");
    try {
      await saveCompanyStatus(token, row.id, next);
      setNotice(next === "active" ? `${row.name} is active.`
        : next === "suspended" ? `${row.name} was suspended.`
          : `${row.name} is marked as awaiting verification.`);
      load();
    } catch (err) { setError(err.message); onAuthError(err); }
    finally { setBusy(false); }
  }

  async function remove(row) {
    const people = `${row.employee_count} ${row.employee_count === 1 ? "employee" : "employees"}`;
    if (!await confirm({
      title: "Delete this company?",
      message: `Permanently delete ${row.name}, its employer sign-in${row.employer_username ? ` (${row.employer_username})` : ""} and all ${people} with every record they hold? This cannot be undone.`,
      confirmLabel: "Delete company",
    })) return;
    setBusy(true); setError(""); setNotice("");
    try {
      await deleteAdminBusiness(token, row.id);
      setNotice(`${row.name} was deleted.`);
      load();
    } catch (err) { setError(err.message); onAuthError(err); }
    finally { setBusy(false); }
  }

  return <>
    <div className="section-heading"><div><p className="eyebrow dark-eyebrow">PLATFORM</p><h2>Companies</h2><p>Every company using the platform, and where each one stands. Suspending closes a company\u2019s workspace without deleting anything; deleting removes it, its employer sign-in and its employees for good. Add a company from <Link to="/admin/employers">Employers</Link>, which opens the company and its sign-in together.</p></div></div>
    {error && <p className="message error" role="alert">{error}</p>}
    {notice && <p className="message success" role="status">{notice}</p>}
    {pending > 0 && status !== "pending" && <button className="attention-banner attention-banner-button" type="button" onClick={() => filterBy("pending")}><span className="attention-badge">{pending}</span><span><strong>{pending === 1 ? "A company is awaiting verification" : "Companies are awaiting verification"}</strong><p>They signed themselves up and have not been checked yet. Select to see only those.</p></span><span aria-hidden="true">&rarr;</span></button>}
    <section className="panel records-panel">
      {rows && <div className="records-toolbar">
        <span className="record-count">{visible.length} {visible.length === 1 ? "company" : "companies"}</span>
        <div className="records-filters"><select aria-label="Filter companies" value={status} onChange={(event) => filterBy(event.target.value)}>
          {companyFilters.map(([value, title]) => <option key={value} value={value}>{title}</option>)}
        </select></div>
      </div>}
      {!rows ? <p className="empty-state" role="status">Loading companies\u2026</p> : <Table
        columns={[
          { title: "Company", value: (row) => row.name },
          { title: "Status", value: (row) => <span className={`status-badge status-${companyStatusClass[row.status] || "pending"}`}>{companyStatusLabels[row.status] || row.status}</span> },
          { title: "Employer", value: (row) => row.employer_username },
          { title: "Email", value: (row) => row.employer_email },
          { title: "Employees", value: (row) => `${row.active_employee_count} / ${row.employee_count}` },
          { title: "Opened", value: (row) => whenCreated(row.created_at) },
          { title: "Last sign-in", value: (row) => whenCreated(row.last_login_at) },
        ]}
        rows={visible}
        rowClassName={(row) => String(row.id) === highlighted ? "attention-row" : ""}
        empty={status ? "No companies match this filter." : "No companies on the platform yet."}
        actions={(row) => <>
          {row.status !== "active" && <button type="button" disabled={busy} onClick={() => setStatus(row, "active")}>Activate</button>}
          {row.status !== "suspended" && <button type="button" disabled={busy} className="danger-link" onClick={() => setStatus(row, "suspended")}>Suspend</button>}
          <button type="button" disabled={busy} className="danger-link" onClick={() => remove(row)}>Delete</button>
        </>}
      />}
    </section>
    {confirmation}
  </>;
}

function EmployersPage({ token, onAuthError }) {
  const [rows, setRows] = useState(null);
  const [form, setForm] = useState(null);
  const [editing, setEditing] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [confirm, confirmation] = useConfirm();
  const [params, setParams] = useSearchParams();
  const status = params.get("status") || "";
  const visible = rows ? rows.filter((row) => matchesEmployerFilter(row, status)) : null;
  const dormant = rows ? rows.filter(employerNeedsAttention).length : 0;

  function filterBy(value) {
    setParams(value ? { status: value } : {}, { replace: true });
  }

  function load() {
    fetchAdminEmployers(token).then(setRows).catch((err) => { setError(err.message); onAuthError(err); });
  }
  useEffect(load, [token, onAuthError]);

  function open(row = null) {
    setError(""); setNotice("");
    setEditing(row);
    setForm(row
      ? { username: row.username, email: row.email, password: "", business_name: row.business_name, is_active: row.is_active }
      : { ...emptyEmployer });
  }

  async function submit(event) {
    event.preventDefault();
    setBusy(true); setError(""); setNotice("");
    try {
      const payload = { ...form };
      if (editing && !payload.password) delete payload.password;
      await saveAdminEmployer(token, payload, editing?.id);
      setForm(null); setEditing(null);
      setNotice(editing ? "Employer updated." : "Employer workspace created.");
      load();
    } catch (err) { setError(err.message); onAuthError(err); }
    finally { setBusy(false); }
  }

  async function setActive(row, isActive) {
    if (isActive === false && !await confirm({ title: "Deactivate employer?", message: `Deactivate ${row.business_name}? ${row.username} will not be able to sign in until you activate them again. Their employees stay in place.`, confirmLabel: "Deactivate" })) return;
    setBusy(true); setError(""); setNotice("");
    try {
      await saveAdminEmployer(token, { is_active: isActive }, row.id);
      setNotice(isActive ? `${row.business_name} is active again.` : `${row.business_name} was deactivated.`);
      load();
    } catch (err) { setError(err.message); onAuthError(err); }
    finally { setBusy(false); }
  }

  return <>
    <div className="section-heading"><div><p className="eyebrow dark-eyebrow">PLATFORM</p><h2>Employers</h2><p>Create, update, or suspend the sign-in a company uses. Deactivating blocks that sign-in and keeps the company and its employees on file. To remove an employer account, delete the whole company from <Link to="/admin/companies">Companies</Link> instead.</p></div><button className="button button-coral" type="button" disabled={busy} onClick={() => open()}>+ Add employer</button></div>
    {error && <p className="message error" role="alert">{error}</p>}
    {notice && <p className="message success" role="status">{notice}</p>}
    {dormant > 0 && status !== "dormant" && <button className="attention-banner attention-banner-button" type="button" onClick={() => filterBy("dormant")}><span className="attention-badge">{dormant}</span><span><strong>{dormant === 1 ? "A company has never signed in" : "Companies have never signed in"}</strong><p>Their employer account was created but has not been used yet, so the workspace is still empty. Select to see only those.</p></span><span aria-hidden="true">&rarr;</span></button>}
    {form && <ModalDialog title={editing ? "Edit employer" : "Add employer"} onClose={() => { setForm(null); setEditing(null); }}><form className="record-form" onSubmit={submit}>
      <h3>{editing ? "Edit employer" : "Add employer"}</h3>
      <fieldset disabled={busy}><div className="record-fields">
        <div><label htmlFor="admin-employer-username">Username</label><input id="admin-employer-username" value={form.username} onChange={(event) => setForm({ ...form, username: event.target.value })} required /></div>
        <div><label htmlFor="admin-employer-email">Email</label><input id="admin-employer-email" type="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} required /></div>
        <div><label htmlFor="admin-employer-business">Business name</label><input id="admin-employer-business" value={form.business_name} onChange={(event) => setForm({ ...form, business_name: event.target.value })} required /></div>
        <div><label htmlFor="admin-employer-password">{editing ? "New password (optional)" : "Password"}</label><input id="admin-employer-password" type="password" value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} required={!editing} minLength={8} /></div>
        {editing && <div className="checkbox-field"><input id="admin-employer-active" type="checkbox" checked={form.is_active} onChange={(event) => setForm({ ...form, is_active: event.target.checked })} /><label htmlFor="admin-employer-active">Active account</label></div>}
      </div>
      {editing && <dl className="admin-employer-meta">
        <div><dt>Account created</dt><dd>{whenCreated(editing.date_joined)}</dd></div>
        <div><dt>Last sign-in</dt><dd>{whenCreated(editing.last_login)}</dd></div>
        <div><dt>Workspace started</dt><dd>{whenCreated(editing.workspace_started)}</dd></div>
        <div><dt>Invitation email</dt><dd>{editing.email_configured ? "Set up" : "Not set up"}</dd></div>
      </dl>}
      <div className="form-actions"><button className="button button-coral" type="submit">{busy ? "Saving…" : "Save employer"}</button><button className="button button-outline" type="button" onClick={() => { setForm(null); setEditing(null); }}>Cancel</button></div></fieldset>
    </form></ModalDialog>}
    <section className="panel records-panel">
      {rows && <div className="records-toolbar">
        <span className="record-count">{visible.length} {visible.length === 1 ? "employer" : "employers"}</span>
        <div className="records-filters"><select aria-label="Filter employers" value={status} onChange={(event) => filterBy(event.target.value)}>
          {employerFilters.map(([value, title]) => <option key={value} value={value}>{title}</option>)}
        </select></div>
      </div>}
      {!rows ? <p className="empty-state" role="status">Loading employers…</p> : <Table
        columns={[
          { title: "Business", value: (row) => row.business_name },
          { title: "Username", value: (row) => row.username },
          { title: "Email", value: (row) => row.email },
          { title: "Account created", value: (row) => whenCreated(row.date_joined) },
          { title: "Last sign-in", value: (row) => whenCreated(row.last_login) },
          { title: "Employees", value: (row) => `${row.active_employee_count ?? row.employee_count} / ${row.employee_count}` },
          { title: "Mail", value: (row) => row.email_configured ? "Set up" : "Not set up" },
          { title: "Status", value: (row) => <span className={`status-badge status-${row.is_active ? "active" : "ended"}`}>{row.is_active ? "Active" : "Deactivated"}</span> },
        ]}
        rows={visible}
        rowClassName={(row) => employerNeedsAttention(row) ? "attention-row" : ""}
        empty={status ? "No employers match this filter." : "No employer workspaces yet."}
        actions={(row) => <>
          <button type="button" disabled={busy} onClick={() => open(row)}>Edit</button>
          {row.is_active
            ? <button type="button" disabled={busy} className="danger-link" onClick={() => setActive(row, false)}>Deactivate</button>
            : <button type="button" disabled={busy} onClick={() => setActive(row, true)}>Activate</button>}
        </>}
      />}
    </section>
    {confirmation}
  </>;
}

function EmployeesPage({ token, onAuthError }) {
  const [rows, setRows] = useState(null);
  const [businesses, setBusinesses] = useState([]);
  const [form, setForm] = useState(null);
  const [editing, setEditing] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [confirm, confirmation] = useConfirm();
  const [params, setParams] = useSearchParams();
  const status = params.get("status") || "";
  const visible = rows ? rows.filter((row) => matchesFilter(row, status)) : null;
  function filterBy(value) {
    setParams(value ? { status: value } : {}, { replace: true });
  }

  function load() {
    Promise.all([fetchAdminEmployees(token), fetchAdminBusinesses(token)]).then(([people, companies]) => {
      setRows(people); setBusinesses(companies);
    }).catch((err) => { setError(err.message); onAuthError(err); });
  }
  useEffect(load, [token, onAuthError]);

  function open(row = null) {
    setError(""); setNotice("");
    setEditing(row);
    setForm(row
      ? { business: row.business || "", first_name: row.first_name, last_name: row.last_name, job_title: row.job_title, email: row.email, is_active: row.is_active }
      : { ...emptyEmployee, business: businesses[0]?.id || "" });
  }

  async function submit(event) {
    event.preventDefault();
    setBusy(true); setError(""); setNotice("");
    try {
      const saved = await saveAdminEmployee(token, form, editing?.id);
      setForm(null); setEditing(null);
      const invite = saved?.invite;
      setNotice(invite
        ? `${saved.first_name} ${saved.last_name} was added. ${invite.detail}${invite.temporary_password ? ` Temporary password: ${invite.temporary_password}` : ""}`
        : "Employee updated.");
      load();
    } catch (err) { setError(err.message); onAuthError(err); }
    finally { setBusy(false); }
  }

  async function remove(row) {
    if (!await confirm({ title: "Delete employee permanently?", message: `Permanently delete ${row.first_name} ${row.last_name} and their sign-in account?`, confirmLabel: "Delete permanently" })) return;
    setBusy(true); setError("");
    try {
      await deleteAdminEmployee(token, row.id);
      setNotice(`${row.first_name} ${row.last_name} was deleted.`);
      if (editing?.id === row.id) { setForm(null); setEditing(null); }
      load();
    } catch (err) { setError(err.message); onAuthError(err); }
    finally { setBusy(false); }
  }

  return <>
    <div className="section-heading"><div><p className="eyebrow dark-eyebrow">PLATFORM</p><h2>Employees</h2><p>Hire someone into any business. Their employer will also see them in that workspace. Day-to-day onboarding and approvals stay between each employer and their own staff.</p></div><button className="button button-coral" type="button" disabled={busy || !businesses.length} onClick={() => open()}>+ Add employee</button></div>
    {error && <p className="message error" role="alert">{error}</p>}
    {notice && <p className="message success" role="status">{notice}</p>}
    {!businesses.length && rows && <p className="message">Create an employer workspace before adding employees.</p>}
    {form && <ModalDialog title={editing ? "Edit employee" : "Add employee"} onClose={() => { setForm(null); setEditing(null); }}><form className="record-form" onSubmit={submit}>
      <h3>{editing ? "Edit employee" : "Add employee"}</h3>
      <fieldset disabled={busy}><div className="record-fields">
        <div className="field-wide"><label htmlFor="admin-employee-business">Business</label>
          <select id="admin-employee-business" value={form.business} onChange={(event) => setForm({ ...form, business: event.target.value })} required>
            <option value="">Select a business</option>
            {businesses.map((business) => <option key={business.id} value={business.id}>{business.name}</option>)}
          </select>
        </div>
        <div><label htmlFor="admin-employee-first">First name</label><input id="admin-employee-first" value={form.first_name} onChange={(event) => setForm({ ...form, first_name: event.target.value })} required /></div>
        <div><label htmlFor="admin-employee-last">Last name</label><input id="admin-employee-last" value={form.last_name} onChange={(event) => setForm({ ...form, last_name: event.target.value })} required /></div>
        <div><label htmlFor="admin-employee-title">Job title</label><input id="admin-employee-title" value={form.job_title} onChange={(event) => setForm({ ...form, job_title: event.target.value })} required /></div>
        <div><label htmlFor="admin-employee-email">Email</label><input id="admin-employee-email" type="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} required /></div>
        {editing && <div className="checkbox-field"><input id="admin-employee-active" type="checkbox" checked={form.is_active} onChange={(event) => setForm({ ...form, is_active: event.target.checked })} /><label htmlFor="admin-employee-active">Active employee</label></div>}
      </div>
      <div className="form-actions"><button className="button button-coral" type="submit">{busy ? "Saving…" : "Save employee"}</button><button className="button button-outline" type="button" onClick={() => { setForm(null); setEditing(null); }}>Cancel</button></div></fieldset>
    </form></ModalDialog>}
    <section className="panel records-panel">
      {rows && <div className="records-toolbar">
        <span className="record-count">{visible.length} {visible.length === 1 ? "employee" : "employees"}</span>
        <div className="records-filters"><select aria-label="Filter employees" value={status} onChange={(event) => filterBy(event.target.value)}>
          {employeeFilters.map(([value, title]) => <option key={value} value={value}>{title}</option>)}
        </select></div>
      </div>}
      {!rows ? <p className="empty-state" role="status">Loading employees…</p> : <Table
        columns={[
          { title: "Name", value: (row) => `${row.first_name} ${row.last_name}` },
          { title: "Email", value: (row) => row.email },
          { title: "Business", value: (row) => row.business_name },
          { title: "Job title", value: (row) => row.job_title },
          { title: "Account", value: (row) => row.account_status === "active" ? "Active" : row.account_status === "pending_first_sign_in" ? "Invited" : "No account" },
          { title: "Status", value: (row) => row.is_active ? "Active" : "Inactive" },
        ]}
        rows={visible}
        empty={status ? "No employees match this filter." : "No employees on the platform yet."}
        actions={(row) => <><button type="button" disabled={busy} onClick={() => open(row)}>Edit</button><button type="button" disabled={busy} className="danger-link" onClick={() => remove(row)}>Delete</button></>}
      />}
    </section>
    {confirmation}
  </>;
}

export default function AdminDashboard({ token, account, onLogout, onAuthError }) {
  const [attention, setAttention] = useState(null);
  const { pathname } = useLocation();
  const atOverview = pathname.replace(/\/$/, "") === "/admin";
  useEffect(() => {
    let cancelled = false;
    const refresh = () => fetchAdminOverview(token).then((data) => {
      if (!cancelled) setAttention(data);
    }).catch((err) => onAuthError(err));
    refresh();
    const timer = window.setInterval(refresh, 15000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [token, onAuthError]);
  // The sidebar badges read the same live overview the dashboard does.
  const pendingCompanies = attention?.scale?.pending_companies || 0;
  const dormantEmployers = attention?.issues?.dormant_employers || 0;
  const unreadMessages = attention?.messages?.unread || 0;
  return <>
    <aside className="dashboard-sidebar" aria-label="Admin menu">
      <Link className="brand" to="/"><span className="brand-mark">E</span><span>Employee<span className="brand-dot">.</span></span></Link>
      <p className="sidebar-label">SUPER ADMIN</p>
      <div className="workspace-identity"><strong>{account?.display_name || account?.username}</strong><span>{account?.role_label || "Administrator"}</span></div>
      <nav className="sidebar-nav" aria-label="Admin navigation">
        <NavLink end to="/admin" className={({ isActive }) => `sidebar-link${isActive ? " selected" : ""}`}>Overview</NavLink>
        <NavLink to="/admin/companies" className={({ isActive }) => `sidebar-link${isActive ? " selected" : ""}`}><span>Companies</span>{pendingCompanies > 0 && <span className="attention-badge" aria-label={`${pendingCompanies} companies awaiting verification`}>{pendingCompanies}</span>}</NavLink>
        <NavLink to="/admin/employers" className={({ isActive }) => `sidebar-link${isActive ? " selected" : ""}`}><span>Employers</span>{dormantEmployers > 0 && <span className="attention-badge" aria-label={`${dormantEmployers} employers have never signed in`}>{dormantEmployers}</span>}</NavLink>
        <NavLink to="/admin/employees" className={({ isActive }) => `sidebar-link${isActive ? " selected" : ""}`}>Employees</NavLink>
        <NavLink to="/admin/messages" className={({ isActive }) => `sidebar-link${isActive ? " selected" : ""}`}><span>Messages</span>{unreadMessages > 0 && <span className="attention-badge" aria-label={`${unreadMessages} unread messages`}>{unreadMessages}</span>}</NavLink>
      </nav>
      <div className="sidebar-bottom">
        <p className="sidebar-label">{account?.email}</p>
        <Link className="sidebar-link back-link" to="/">← Back to main site</Link>
        <button className="sidebar-signout" type="button" onClick={onLogout}>Sign out</button>
      </div>
    </aside>
    <main className="dashboard-main"><section className="workspace dashboard-workspace">
      {!atOverview && <BackButton />}
      <Routes>
        <Route index element={<PlatformOverview token={token} onAuthError={onAuthError} />} />
        <Route path="companies" element={<CompaniesPage token={token} onAuthError={onAuthError} />} />
        <Route path="messages" element={<MessagesPage token={token} onAuthError={onAuthError} />} />
        <Route path="messages/:business" element={<MessagesPage token={token} onAuthError={onAuthError} />} />
        <Route path="employers" element={<EmployersPage token={token} onAuthError={onAuthError} />} />
        <Route path="employees" element={<EmployeesPage token={token} onAuthError={onAuthError} />} />
        <Route path="*" element={<Navigate to="/admin" replace />} />
      </Routes>
    </section></main>
  </>;
}
