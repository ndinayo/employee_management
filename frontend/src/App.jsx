import { useCallback, useEffect, useState } from "react";
import { Link, Navigate, Route, Routes, useNavigate } from "react-router";
import heroImage from "./assets/images/hero.jpeg";
import { ACCESS_TOKEN } from "./constants";
import { fetchAccount } from "./api";
import AuthForm from "./AuthForm";
import AccountPage from "./AccountPage";
import ManagerDashboard from "./ManagerDashboard";
import "./App.css";
import "./ManagerDashboard.css";

function HomePage({
  token,
  account,
  onAuthenticated,
  onLogout,
  error,
}) {
  const canManage = Boolean(account?.can_manage);
  const workspacePath = canManage ? "/dashboard" : "/account";
  return (
    <>
      <section className="hero" id="home">
        <div
          className="hero-photo"
          style={{ backgroundImage: `url(${heroImage})` }}
          aria-hidden="true"
        />

        <header className="site-header">
          <Link className="brand" to="/">
            <span className="brand-mark">E</span>
            <span>
              Employee<span className="brand-dot">.</span>
            </span>
          </Link>

          <nav className="site-nav" aria-label="Main navigation">
            <Link to="/">Home</Link>
            <a href="#about">About</a>
            {token && <Link to={workspacePath}>My workspace</Link>}
            {token && <button type="button" className="nav-signout" onClick={onLogout}>Sign out</button>}
          </nav>

          {token ? (
            <Link className="header-action" to={workspacePath}>
              Open workspace
            </Link>
          ) : (
            <a className="header-action" href="#sign-in">
              Sign in / Sign up
            </a>
          )}
        </header>

        <div className="hero-content">
          <p className="eyebrow">EMPLOYEE MANAGEMENT SYSTEM</p>
          <h1>
            Where people grow
            <br />
            and teams thrive.
          </h1>
          <p className="hero-description">
            Keep your people records organized in one thoughtful workspace.
            Find employees, update details, and stay connected to your team.
          </p>
          {token ? (
            <Link className="button button-coral" to={workspacePath}>
              Go to workspace &rarr;
            </Link>
          ) : (
            <a className="button button-coral" href="#sign-in">
              Explore the workspace &rarr;
            </a>
          )}
        </div>

        <div className="hero-stat">
          <div className="avatar-stack" aria-hidden="true">
            <span>HR</span>
            <span>IT</span>
            <span>OP</span>
          </div>
          <div>
            <strong>{account?.can_manage ? "Your business" : "One place"}</strong>
            <small>
              for your people records
            </small>
          </div>
        </div>

        <div className="hero-note">
          <span className="note-symbol" aria-hidden="true">*</span>
          <div>
            <strong>People first</strong>
            <small>A clearer way to manage your team</small>
          </div>
        </div>
      </section>

      <main>
        <section className="intro-section" id="about">
          <div>
            <p className="eyebrow dark-eyebrow">BUILT FOR YOUR TEAM</p>
            <h2>Every person has a place here.</h2>
          </div>
          <p>
            A simple, secure space for employee information from the first
            day onward.
          </p>
        </section>

        {(!token || canManage) && <section className="workspace" id="sign-in">
          <div className="section-heading">
            <div>
              <p className="eyebrow dark-eyebrow">YOUR WORKSPACE</p>
              <h2>Employee management</h2>
              <p>Sign in or create an employee or employer account.</p>
            </div>
          </div>

          {error && (
            <p className="message error" role="alert">
              {error}
            </p>
          )}

          {canManage ? (
            <div className="panel signed-in-panel">
              <h3>You are signed in.</h3>
              <p>Your workspace is ready.</p>
              <Link className="button button-coral" to="/dashboard">
                Open workspace &rarr;
              </Link>
            </div>
          ) : (
            <div className="login-layout">
              <AuthForm onAuthenticated={onAuthenticated} />

              <div className="login-aside">
                <span className="aside-icon" aria-hidden="true">*</span>
                <h3>Your team, clearly organized.</h3>
                <p>
                  Manage employee profiles, contracts, attendance, leave,
                  salaries, and payslips in one workspace.
                </p>
              </div>
            </div>
          )}
        </section>}
      </main>

      <footer className="site-footer">
        <strong>
          Employee<span>.</span>
        </strong>
        <p>A thoughtful place for your people records.</p>
      </footer>
    </>
  );
}

function App() {
  const navigate = useNavigate();
  const [token, setToken] = useState(() => localStorage.getItem(ACCESS_TOKEN));
  const [account, setAccount] = useState(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);

  const handleLogout = useCallback(() => {
    localStorage.removeItem(ACCESS_TOKEN);
    setToken(null);
    setAccount(null);
    setError("");
  }, []);

  const handleAuthError = useCallback((err) => {
    if (err.status === 401 || err.status === 403) {
      handleLogout();
      setError("Your session has ended. Please sign in again.");
    }
  }, [handleLogout]);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    fetchAccount(token).then((profile) => {
      if (!cancelled) { setAccount(profile); setError(""); }
    }).catch((err) => {
      if (!cancelled) {
        setError(err.message);
        handleAuthError(err);
      }
    });
    return () => { cancelled = true; };
  }, [token, retry, handleAuthError]);

  function handleAuthenticated(access, profile) {
    localStorage.setItem(ACCESS_TOKEN, access);
    setAccount(profile);
    setToken(access);
    setError("");
    navigate(profile.can_manage ? "/dashboard" : "/account");
  }

  const pendingAccount = <main className="workspace account-workspace">
    {error ? <><p className="message error" role="alert">{error}</p><button className="button button-coral" onClick={() => { setError(""); setRetry((value) => value + 1); }}>Retry</button><button className="button button-outline" onClick={handleLogout}>Sign out</button></>
      : <p role="status">Loading your account…</p>}
  </main>;

  return <Routes>
    <Route path="/" element={<HomePage token={token} account={account} onAuthenticated={handleAuthenticated} onLogout={handleLogout} error={error} />} />
    <Route path="/account" element={!token ? <Navigate to="/#sign-in" replace /> : !account ? pendingAccount : <AccountPage account={account} onLogout={handleLogout} />} />
    <Route path="/dashboard/*" element={!token ? <Navigate to="/#sign-in" replace /> : !account ? pendingAccount : account.can_manage ? <ManagerDashboard token={token} account={account} onLogout={handleLogout} onAuthError={handleAuthError} /> : <Navigate to="/account" replace />} />
    <Route path="*" element={<Navigate to="/" replace />} />
  </Routes>;
}

export default App;
