import { useEffect, useState } from "react";
import { Link } from "react-router";
import { fetchAdminActivity, fetchAdminOverview } from "../api";

// Every figure on this page comes from /api/admin/overview/ and
// /api/admin/activity/, counted from live rows. Nothing here is a fixed value.

function shortDate(value) {
  if (!value) return "Never";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString([], { day: "2-digit", month: "short", year: "numeric" });
}

function sinceDays(value) {
  if (!value) return "";
  const days = Math.floor((Date.now() - new Date(value).getTime()) / 86400000);
  if (Number.isNaN(days)) return "";
  if (days <= 0) return "today";
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

function Tile({ title, value, note, to, tone }) {
  const body = <>
    <span>{title}</span>
    <strong className={tone ? `tone-${tone}` : undefined}>{value}</strong>
    {note && <small>{note}</small>}
  </>;
  if (!to) return <div className="summary-card">{body}</div>;
  return <Link className="summary-card summary-card-link" to={to} aria-label={`Open ${title.toLowerCase()}`}>{body}</Link>;
}

function CompanyList({ title, description, rows, empty, stamp }) {
  return <section className="panel platform-panel">
    <h3>{title}</h3>
    <p className="panel-note">{description}</p>
    {!rows.length ? <p className="empty-state">{empty}</p> : <ul className="platform-list">
      {rows.map((row) => <li key={row.id}>
        <Link to={`/dashboard/companies?company=${row.id}`}>
          <strong>{row.name}</strong>
          <small>
            {row.employer_username || "No employer account"}
            {" · "}
            {row.employee_count} {row.employee_count === 1 ? "employee" : "employees"}
          </small>
        </Link>
        <span className="platform-stamp">{stamp(row)}</span>
      </li>)}
    </ul>}
  </section>;
}

export default function PlatformOverview({ token, onAuthError }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    const load = () => Promise.all([fetchAdminOverview(token), fetchAdminActivity(token)]).then(([result, activity]) => {
      if (!cancelled) { setData({ ...result, activity }); setError(""); }
    }).catch((err) => {
      if (!cancelled) { setError(err.message); onAuthError(err); }
    });
    load();
    const timer = window.setInterval(load, 30000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [token, onAuthError]);

  if (error && !data) return <>
    <div className="section-heading"><div><p className="eyebrow dark-eyebrow">PLATFORM</p><h2>Platform overview</h2></div></div>
    <p className="message error" role="alert">{error}</p>
  </>;
  if (!data) return <>
    <div className="section-heading"><div><p className="eyebrow dark-eyebrow">PLATFORM</p><h2>Platform overview</h2></div></div>
    <p className="empty-state" role="status">Loading the platform…</p>
  </>;

  const { scale, lifecycle, usage, issues, messages, activity } = data;
  const counts = activity.counts;
  const growth = usage.growth_percent;
  const attention = issues.dormant_employers + issues.suspended_employers
    + issues.companies_without_employer + issues.failed_invitations
    + (issues.email_delivery_configured ? 0 : 1);

  return <>
    <div className="section-heading"><div>
      <p className="eyebrow dark-eyebrow">PLATFORM</p>
      <h2>Platform overview</h2>
      <p>Every company on the platform and the accounts that run them. Company activity is shown
        as counts only; each company&apos;s own records stay inside its employer&apos;s workspace.</p>
    </div></div>
    {error && <p className="message error" role="alert">{error}</p>}

    <h3 className="platform-heading">Platform scale</h3>
    <div className="summary-row platform-tiles">
      <Tile title="Companies" value={scale.companies} to="/dashboard/companies"
            note={`${scale.companies_this_month} added this month`} />
      <Tile title="Active companies" value={scale.active_companies} to="/dashboard/companies?status=active" />
      <Tile title="Awaiting verification" value={scale.pending_companies} to="/dashboard/companies?status=pending"
            tone={scale.pending_companies ? "warn" : undefined} />
      <Tile title="Suspended companies" value={scale.suspended_companies} to="/dashboard/companies?status=suspended"
            tone={scale.suspended_companies ? "bad" : undefined} />
      <Tile title="Employers" value={scale.employers} to="/dashboard/employers" />
      <Tile title="Employees" value={scale.employees} to="/dashboard/employees"
            note={`${scale.active_employees} active`} />
    </div>

    <h3 className="platform-heading">Platform usage</h3>
    <div className="summary-row platform-tiles">
      <Tile title="Companies active today" value={usage.active_today} />
      <Tile title="Active this week" value={usage.active_week} note="Last 7 days" />
      <Tile title="Active this month" value={usage.active_month} note="Last 30 days" />
      <Tile title="Total platform users" value={usage.total_users} note="Every role" />
      <Tile title="Growth on last month" value={`${growth > 0 ? "+" : ""}${growth}%`}
            tone={growth > 0 ? "good" : growth < 0 ? "bad" : undefined}
            note={`${usage.companies_this_month} this month, ${usage.companies_last_month} last`} />
    </div>

    <h3 className="platform-heading">Platform activity</h3>
    <div className="summary-row platform-tiles">
      <Tile title="Checked in today" value={counts.checked_in_today} note={`${counts.on_shift_now} on shift now`} />
      <Tile title="Shifts completed today" value={counts.shifts_completed_today} />
      <Tile title="On leave today" value={counts.on_leave_today}
            note={`${counts.leave_requests_pending} leave ${counts.leave_requests_pending === 1 ? "request" : "requests"} pending`} />
      <Tile title="Signed contracts" value={counts.contracts_active} note={`${counts.contracts_awaiting_signature} awaiting signature`} />
      <Tile title="Salaries paid this month" value={counts.payslips_this_month} note="Payslips issued" />
      <Tile title="Announcements this month" value={counts.announcements_this_month}
            note={`${counts.upcoming_events} calendar ${counts.upcoming_events === 1 ? "event" : "events"} in the next 30 days`} />
      <Tile title="Workplace location set" value={activity.companies_with_workplace_location}
            note={`of ${scale.companies} ${scale.companies === 1 ? "company" : "companies"}`} />
    </div>
    <h3 className="platform-heading">Company lifecycle</h3>
    <div className="platform-grid">
      <CompanyList title="Recent registrations" description="The newest companies on the platform."
                   rows={lifecycle.recent_registrations} empty="No companies yet."
                   stamp={(row) => shortDate(row.created_at)} />
      <CompanyList title="Awaiting verification"
                   description="Signed themselves up and have not been verified yet."
                   rows={lifecycle.awaiting_activation} empty="Nothing waiting."
                   stamp={(row) => shortDate(row.created_at)} />
      <CompanyList title="Recently suspended" description="Their workspace is closed."
                   rows={lifecycle.recently_suspended} empty="No suspended companies."
                   stamp={(row) => shortDate(row.status_changed_at || row.created_at)} />
      <CompanyList title={`Quiet for over ${lifecycle.dormant_days} days`}
                   description="Signed in once, but not for a long time."
                   rows={lifecycle.dormant} empty="Every company has been active recently."
                   stamp={(row) => sinceDays(row.last_login_at)} />
    </div>

    <h3 className="platform-heading">Account issues{attention > 0 && <span className="attention-badge">{attention}</span>}</h3>
    <div className="summary-row platform-tiles">
      <Tile title="Employers never signed in" value={issues.dormant_employers}
            to="/dashboard/employers?status=dormant" tone={issues.dormant_employers ? "warn" : undefined} />
      <Tile title="Suspended employers" value={issues.suspended_employers}
            to="/dashboard/employers?status=suspended" tone={issues.suspended_employers ? "bad" : undefined} />
      <Tile title="Disabled accounts" value={issues.disabled_accounts} note="Any role" />
      <Tile title="Companies with no employer" value={issues.companies_without_employer}
            to="/dashboard/companies" tone={issues.companies_without_employer ? "warn" : undefined} />
      <Tile title="Failed invitations" value={issues.failed_invitations}
            tone={issues.failed_invitations ? "bad" : undefined}
            note={`${issues.companies_with_failed_invitations} ${issues.companies_with_failed_invitations === 1 ? "company" : "companies"} affected`} />
    </div>
    {!issues.email_delivery_configured && <p className="message error" role="status">
      Email delivery is not set up, so invitations and emailed messages cannot leave the platform.
    </p>}

    <h3 className="platform-heading">Communication</h3>
    <div className="summary-row platform-tiles">
      <Tile title="Unread messages" value={messages.unread} to="/dashboard/messages"
            tone={messages.unread ? "warn" : undefined} />
      <Tile title="Awaiting your reply" value={messages.unresolved} to="/dashboard/messages"
            tone={messages.unresolved ? "warn" : undefined} />
    </div>
    <section className="panel platform-panel">
      <h3>Recent conversations</h3>
      <p className="panel-note">The latest exchange with each company.</p>
      {!messages.recent.length ? <p className="empty-state">No conversations yet.</p>
        : <ul className="platform-list">
          {messages.recent.map((row) => <li key={row.business}>
            <Link to={`/dashboard/messages/${row.business}`}>
              <strong>{row.business_name}{row.awaiting_reply && <span className="attention-badge">1</span>}</strong>
              <small>{row.from_admin ? "You: " : ""}{row.body}</small>
            </Link>
            <span className="platform-stamp">{shortDate(row.created_at)}</span>
          </li>)}
        </ul>}
    </section>
  </>;
}
