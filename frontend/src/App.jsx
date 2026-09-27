import { useCallback, useEffect, useState } from "react";
import { Link, Navigate, Route, Routes, useLocation, useNavigate } from "react-router";
import heroImage from "./assets/images/hero.jpeg";
import { ACCESS_TOKEN } from "./constants";
import { fetchAccount } from "./api";
import AuthForm from "./AuthForm";
import EmployeeWorkspace from "./components/EmployeeWorkspace";
import EmployerWorkspace from "./components/EmployerWorkspace";
import AdminDashboard from "./components/AdminDashboard";
import ModalDialog from "./components/ModalDialog";
import { ForgotPasswordPage, ResetPasswordPage } from "./PasswordReset";
import { workspacePath } from "./workspace";
import "./App.css";
import "./ManagerDashboard.css";

// Shared site chrome. The public pages and the employee account page use the
// same header and footer; the manager dashboard keeps its own sidebar layout.
export function SiteHeader({ token, workspacePath, onLogout, onAuthenticate, home = false }) {
  // The header is pinned, so it needs a solid backing wherever its white text
  // is not sitting over the dark hero photo.
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    if (!home) return;
    const onScroll = () => setScrolled(window.scrollY > 40);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [home]);
  return (
      <header className={`site-header${home ? "" : " solid"}${scrolled ? " scrolled" : ""}`}>
        <div className="site-header-inner">
          <Link className="brand" to="/">
            <span className="brand-mark">E</span>
            <span>
              Employee<span className="brand-dot">.</span>
            </span>
          </Link>

          <nav className="site-nav" aria-label="Main navigation">
            <Link to="/">Home</Link>
            {home ? <a href="#about">About</a> : <Link to="/#about">About</Link>}
            {token && <Link to={workspacePath}>My workspace</Link>}
            {token && <button type="button" className="nav-signout" onClick={onLogout}>Sign out</button>}
          </nav>

          {token ? (
            <Link className="header-action" to={workspacePath}>
              Open workspace
            </Link>
          ) : onAuthenticate ? (
            <button className="header-action" type="button" onClick={() => onAuthenticate("signin")}>Sign in / Sign up</button>
          ) : <Link className="header-action" to="/#sign-in">Sign in / Sign up</Link>}
        </div>
      </header>
  );
}

export function SiteFooter() {
  return (
      <footer className="site-footer">
        <strong>
          Employee<span>.</span>
        </strong>
        <p>A thoughtful place for your people records.</p>
      </footer>
  );
}

function RememberEmployeeDestination() {
  const location = useLocation();
  sessionStorage.setItem("employeeSignInDestination", `${location.pathname}${location.search}${location.hash}`);
  return <Navigate to="/#sign-in" replace />;
}

function HomePage({
  token,
  account,
  onAuthenticated,
  onLogout,
  error,
}) {
  const [authMode, setAuthMode] = useState(() => window.location.hash === "#sign-in" ? "signin" : null);
  const canManage = Boolean(account?.can_manage);
  const canAdmin = Boolean(account?.can_admin);
  const path = workspacePath(account);
  return (
    <>
      <SiteHeader token={token} workspacePath={path} onLogout={onLogout} onAuthenticate={setAuthMode} home />

      <section className="hero" id="home">
        <div
          className="hero-photo"
          style={{ backgroundImage: `url(${heroImage})` }}
          aria-hidden="true"
        />

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
            <Link className="button button-coral" to={path}>
              Go to workspace &rarr;
            </Link>
          ) : (
            <button className="button button-coral" type="button" onClick={() => setAuthMode("signin")}>
              Explore the workspace &rarr;
            </button>
          )}
        </div>

        <div className="hero-stat">
          <div className="avatar-stack" aria-hidden="true">
            <span>HR</span>
            <span>IT</span>
            <span>OP</span>
          </div>
          <div>
            <strong>{account?.can_admin ? "Platform admin" : account?.can_manage ? "Your business" : "One place"}</strong>
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

        {(!token || canManage || canAdmin) && <section className="workspace" id="sign-in">
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

          {canManage || canAdmin ? <div className="panel signed-in-panel">
            <h3>You are signed in.</h3>
            <p>Your workspace is ready.</p>
            <Link className="button button-coral" to={path}>
              Open workspace &rarr;
            </Link>
          </div> : <div className="login-layout aside-only"><div className="login-aside">
            <span className="aside-icon" aria-hidden="true">*</span>
            <h3>Your team, clearly organized.</h3>
            <p>Manage employee profiles, contracts, attendance, leave, salaries, and payslips in one workspace.</p>
          </div></div>}
        </section>}
      </main>

      {authMode && !token && <ModalDialog title={authMode === "signup" ? "Create account" : "Sign in"} onClose={() => setAuthMode(null)}><AuthForm key={authMode} initialMode={authMode} onAuthenticated={onAuthenticated} /></ModalDialog>}

      <SiteFooter />
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
    const destination = sessionStorage.getItem("employeeSignInDestination");
    sessionStorage.removeItem("employeeSignInDestination");
    navigate(!profile.can_manage && !profile.can_admin && destination?.startsWith("/account")
      ? destination
      : workspacePath(profile));
  }

  const pendingAccount = <main className="workspace account-workspace">
    {error ? <><p className="message error" role="alert">{error}</p><button className="button button-coral" onClick={() => { setError(""); setRetry((value) => value + 1); }}>Retry</button><button className="button button-outline" onClick={handleLogout}>Sign out</button></>
      : <p role="status">Loading your account…</p>}
  </main>;

  const withSiteChrome = (content) => <div className="account-layout">
    <SiteHeader token={token} workspacePath={workspacePath(account)} onLogout={handleLogout} />
    {content}
    <SiteFooter />
  </div>;

  return <Routes>
    <Route path="/" element={<HomePage token={token} account={account} onAuthenticated={handleAuthenticated} onLogout={handleLogout} error={error} />} />
    <Route path="/forgot-password" element={withSiteChrome(<ForgotPasswordPage />)} />
    <Route path="/reset-password" element={withSiteChrome(<ResetPasswordPage />)} />
    <Route path="/account" element={!token ? <RememberEmployeeDestination /> : !account ? withSiteChrome(pendingAccount) : account.can_admin ? <Navigate to="/admin" replace /> : withSiteChrome(<EmployeeWorkspace account={account} token={token} onAccountChange={handleAuthenticated} />)} />
    <Route path="/dashboard/*" element={!token ? <Navigate to="/#sign-in" replace /> : !account ? pendingAccount : account.can_admin ? <Navigate to="/admin" replace /> : account.can_manage ? <EmployerWorkspace token={token} account={account} onLogout={handleLogout} onAuthError={handleAuthError} onAccountChange={(partial) => setAccount((current) => current ? { ...current, ...partial } : current)} /> : <Navigate to="/account" replace />} />
    <Route path="/admin/*" element={!token ? <Navigate to="/#sign-in" replace /> : !account ? pendingAccount : account.can_admin ? <AdminDashboard token={token} account={account} onLogout={handleLogout} onAuthError={handleAuthError} /> : <Navigate to={workspacePath(account)} replace />} />
    <Route path="*" element={<Navigate to="/" replace />} />
  </Routes>;
}

export default App;
