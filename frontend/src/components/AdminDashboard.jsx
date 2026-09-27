import { useEffect, useState } from "react";
import { Link, NavLink, Navigate, Route, Routes } from "react-router";
import {
  deleteAdminEmployee, deleteAdminEmployer, fetchAdminBusinesses, fetchAdminEmployees,
  fetchAdminEmployers, fetchAdminOverview, saveAdminEmployee, saveAdminEmployer,
} from "../api";
import ModalDialog from "./ModalDialog";

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

function Table({ columns, rows, empty, actions }) {
  if (!rows.length) return <p className="empty-state">{empty}</p>;
  return <div className="table-scroll"><table>
    <thead><tr>{columns.map((column) => <th key={column.title} scope="col">{column.title}</th>)}{actions && <th scope="col">Actions</th>}</tr></thead>
    <tbody>{rows.map((row) => <tr key={row.id}>
      {columns.map((column) => <td key={column.title}>{column.value(row) || "—"}</td>)}
      {actions && <td><div className="row-actions">{actions(row)}</div></td>}
    </tr>)}</tbody>
  </table></div>;
}

function Overview({ token, onAuthError }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    fetchAdminOverview(token).then((result) => {
      if (!cancelled) { setData(result); setError(""); }
    }).catch((err) => {
      if (!cancelled) { setError(err.message); onAuthError(err); }
    });
    return () => { cancelled = true; };
  }, [token, onAuthError]);
  return <>
    <div className="section-heading"><div><p className="eyebrow dark-eyebrow">PLATFORM</p><h2>Admin dashboard</h2><p>Every employer workspace and every employee record, across businesses.</p></div></div>
    {error && <p className="message error" role="alert">{error}</p>}
    {!data ? <p className="empty-state" role="status">Loading platform…</p> : <>
      <div className="summary-row manager-summary">
        {[["Businesses", data.businesses], ["Employers", data.employers], ["Employees", data.employees], ["Active employees", data.active_employees], ["Awaiting first sign-in", data.invited_employees]].map(([title, value]) => (
          <div className="summary-card" key={title}><span>{title}</span><strong>{value}</strong></div>
        ))}
      </div>
      <div className="quick-links">
        <Link to="/admin/employers">Manage employers →</Link>
        <Link to="/admin/employees">Manage employees →</Link>
      </div>
    </>}
  </>;
}

function EmployersPage({ token, onAuthError }) {
  const [rows, setRows] = useState(null);
  const [form, setForm] = useState(null);
  const [editing, setEditing] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

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
    if (isActive === false && !window.confirm(`Deactivate ${row.business_name}? ${row.username} will not be able to sign in until you activate them again. Their employees stay in place.`)) return;
    setBusy(true); setError(""); setNotice("");
    try {
      await saveAdminEmployer(token, { is_active: isActive }, row.id);
      setNotice(isActive ? `${row.business_name} is active again.` : `${row.business_name} was deactivated.`);
      load();
    } catch (err) { setError(err.message); onAuthError(err); }
    finally { setBusy(false); }
  }

  async function remove(row) {
    if (!window.confirm(`Permanently delete ${row.business_name} and every employee in that workspace?`)) return;
    setBusy(true); setError("");
    try {
      await deleteAdminEmployer(token, row.id);
      setNotice(`${row.business_name} was deleted.`);
      if (editing?.id === row.id) { setForm(null); setEditing(null); }
      load();
    } catch (err) { setError(err.message); onAuthError(err); }
    finally { setBusy(false); }
  }

  return <>
    <div className="section-heading"><div><p className="eyebrow dark-eyebrow">PLATFORM</p><h2>Employers</h2><p>Create, deactivate, or remove employer workspaces. Deactivating blocks their sign-in and keeps their employees on file.</p></div><button className="button button-coral" type="button" disabled={busy} onClick={() => open()}>+ Add employer</button></div>
    {error && <p className="message error" role="alert">{error}</p>}
    {notice && <p className="message success" role="status">{notice}</p>}
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
        rows={rows}
        empty="No employer workspaces yet."
        actions={(row) => <>
          <button type="button" disabled={busy} onClick={() => open(row)}>Edit</button>
          {row.is_active
            ? <button type="button" disabled={busy} className="danger-link" onClick={() => setActive(row, false)}>Deactivate</button>
            : <button type="button" disabled={busy} onClick={() => setActive(row, true)}>Activate</button>}
          <button type="button" disabled={busy} className="danger-link" onClick={() => remove(row)}>Delete</button>
        </>}
      />}
    </section>
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
    if (!window.confirm(`Permanently delete ${row.first_name} ${row.last_name} and their sign-in account?`)) return;
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
    <div className="section-heading"><div><p className="eyebrow dark-eyebrow">PLATFORM</p><h2>Employees</h2><p>Hire someone into any business. Their employer will also see them in that workspace.</p></div><button className="button button-coral" type="button" disabled={busy || !businesses.length} onClick={() => open()}>+ Add employee</button></div>
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
      {!rows ? <p className="empty-state" role="status">Loading employees…</p> : <Table
        columns={[
          { title: "Name", value: (row) => `${row.first_name} ${row.last_name}` },
          { title: "Email", value: (row) => row.email },
          { title: "Business", value: (row) => row.business_name },
          { title: "Job title", value: (row) => row.job_title },
          { title: "Account", value: (row) => row.account_status === "active" ? "Active" : row.account_status === "pending_first_sign_in" ? "Invited" : "No account" },
          { title: "Status", value: (row) => row.is_active ? "Active" : "Inactive" },
        ]}
        rows={rows}
        empty="No employees on the platform yet."
        actions={(row) => <><button type="button" disabled={busy} onClick={() => open(row)}>Edit</button><button type="button" disabled={busy} className="danger-link" onClick={() => remove(row)}>Delete</button></>}
      />}
    </section>
  </>;
}

export default function AdminDashboard({ token, account, onLogout, onAuthError }) {
  return <>
    <aside className="dashboard-sidebar" aria-label="Admin menu">
      <Link className="brand" to="/"><span className="brand-mark">E</span><span>Employee<span className="brand-dot">.</span></span></Link>
      <p className="sidebar-label">SUPER ADMIN</p>
      <div className="workspace-identity"><strong>{account?.display_name || account?.username}</strong><span>{account?.role_label || "Administrator"}</span></div>
      <nav className="sidebar-nav" aria-label="Admin navigation">
        <NavLink end to="/admin" className={({ isActive }) => `sidebar-link${isActive ? " selected" : ""}`}>Overview</NavLink>
        <NavLink to="/admin/employers" className={({ isActive }) => `sidebar-link${isActive ? " selected" : ""}`}>Employers</NavLink>
        <NavLink to="/admin/employees" className={({ isActive }) => `sidebar-link${isActive ? " selected" : ""}`}>Employees</NavLink>
      </nav>
      <div className="sidebar-bottom">
        <p className="sidebar-label">{account?.email}</p>
        <Link className="sidebar-link back-link" to="/">← Back to main site</Link>
        <button className="sidebar-signout" type="button" onClick={onLogout}>Sign out</button>
      </div>
    </aside>
    <main className="dashboard-main"><section className="workspace dashboard-workspace">
      <Routes>
        <Route index element={<Overview token={token} onAuthError={onAuthError} />} />
        <Route path="employers" element={<EmployersPage token={token} onAuthError={onAuthError} />} />
        <Route path="employees" element={<EmployeesPage token={token} onAuthError={onAuthError} />} />
        <Route path="*" element={<Navigate to="/admin" replace />} />
      </Routes>
    </section></main>
  </>;
}
