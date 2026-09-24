import { Link } from "react-router";

export default function AccountPage({ account, onLogout }) {
  return <main className="workspace account-workspace">
    <div className="section-heading">
      <div><p className="eyebrow dark-eyebrow">YOUR ACCOUNT</p><h2>Welcome, {account.username}</h2></div>
      <button className="button button-outline" onClick={onLogout}>Sign out</button>
    </div>
    <section className="panel account-panel">
      <h3>{account.role === "employee" ? "Your employee account is ready" : "Account details"}</h3>
      <dl>
        <dt>Username</dt><dd>{account.username}</dd>
        <dt>Email address</dt><dd>{account.email || "Not provided"}</dd>
        <dt>Account type</dt><dd>{account.role === "employer" ? "Employer" : account.role === "manager" ? "Manager" : "Employee"}</dd>
        {account.business_name && <><dt>Business</dt><dd>{account.business_name}</dd></>}
      </dl>
      {account.can_manage
        ? <Link className="button button-coral" to="/dashboard">Open business workspace →</Link>
        : <p>You can sign in with this account at any time. Your account is not connected to a business. Employee records, contracts and payroll are managed separately by your employer.</p>}
      <Link className="account-home-link" to="/">Back to main site</Link>
    </section>
  </main>;
}
