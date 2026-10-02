import { useCallback, useEffect, useState } from "react";
import { Link, Navigate, Route, Routes, useLocation, useNavigate } from "react-router";
import heroImage from "./assets/images/hero.jpeg";
import { ACCESS_TOKEN, REFRESH_TOKEN } from "./constants";
import { fetchAccount } from "./api";
import AuthForm from "./AuthForm";
import EmployeeWorkspace from "./components/EmployeeWorkspace";
import EmployerWorkspace from "./components/EmployerWorkspace";
import AdminDashboard from "./components/AdminDashboard";
import ModalDialog from "./components/ModalDialog";
import { ForgotPasswordPage, ResetPasswordPage } from "./PasswordReset";
import { workspaceLabel, workspacePath } from "./workspace";
import "./App.css";
import "./ManagerDashboard.css";

// Shared site chrome for public and password-reset pages. Signed-in workspaces
// use their own sidebar navigation.
export function SiteHeader({ token, workspacePath, workspaceLabel = "My Account", onLogout, home = false }) {
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
            <Link to="/about">About</Link>
            {token && <Link to={workspacePath}>{workspaceLabel}</Link>}
            {token && <button type="button" className="nav-signout" onClick={onLogout}>Sign out</button>}
          </nav>

          {token ? (
            <Link className="header-action" to={workspacePath}>
              Open {workspaceLabel === "My Account" ? "workspace" : "dashboard"}
            </Link>
          ) : <Link className="header-action" to="/signin">Sign in / Sign up</Link>}
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
  sessionStorage.setItem("employeeSignInDestination", `${location.pathname}${location.search}`);
  return <Navigate to="/signin" replace />;
}

function HomePage({
  token,
  account,
  onAuthenticated,
  onLogout,
  error,
  intent = "",
}) {
  const navigate = useNavigate();
  // Both panels are states of this page with a path of their own, so no part of
  // the site ever puts a fragment in the address bar.
  const showAuth = intent === "signin" && !token;
  const canManage = Boolean(account?.can_manage);
  const canAdmin = Boolean(account?.can_admin);
  const path = workspacePath(account);

  useEffect(() => {
    if (intent === "about") document.getElementById("about")?.scrollIntoView({ behavior: "smooth" });
  }, [intent]);

  return (
    <>
      <SiteHeader token={token} workspacePath={path} workspaceLabel={workspaceLabel(account)} onLogout={onLogout} home />

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
            <Link className="button button-coral" to="/signin">
              Explore the workspace &rarr;
            </Link>
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
            <p>{canAdmin ? "Your platform dashboard is ready." : "Your workspace is ready."}</p>
            <Link className="button button-coral" to={path}>
              Open {canAdmin ? "admin dashboard" : "workspace"} &rarr;
            </Link>
          </div> : <div className="login-layout aside-only"><div className="login-aside">
            <span className="aside-icon" aria-hidden="true">*</span>
            <h3>Your team, clearly organized.</h3>
            <p>Manage employee profiles, contracts, attendance, leave, salaries, and payslips in one workspace.</p>
          </div></div>}
        </section>}
      </main>

      {showAuth && <ModalDialog title="Sign in" onClose={() => navigate("/")}><AuthForm initialMode="signin" onAuthenticated={onAuthenticated} /></ModalDialog>}

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
    localStorage.removeItem(REFRESH_TOKEN);
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
    const expired = () => {
      handleLogout();
      setError("Your session has ended. Please sign in again.");
    };
    window.addEventListener("auth:expired", expired);
    return () => window.removeEventListener("auth:expired", expired);
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

  function handleAuthenticated(access, profile, refresh) {
    localStorage.setItem(ACCESS_TOKEN, access);
    if (refresh) localStorage.setItem(REFRESH_TOKEN, refresh);
    setAccount(profile);
    setToken(access);
    setError("");
    const destination = sessionStorage.getItem("employeeSignInDestination");
    sessionStorage.removeItem("employeeSignInDestination");
    navigate(!profile.can_manage && !profile.can_admin && destination?.startsWith("/MyAccount")
      && (profile.workspace_approved || destination.toLowerCase().startsWith("/myaccount/contract"))
      ? destination
      : workspacePath(profile));
  }

  const pendingAccount = <main className="workspace account-workspace">
    {error ? <><p className="message error" role="alert">{error}</p><button className="button button-coral" onClick={() => { setError(""); setRetry((value) => value + 1); }}>Retry</button><button className="button button-outline" onClick={handleLogout}>Sign out</button></>
      : <p role="status">Loading your account…</p>}
  </main>;

  const withSiteChrome = (content) => <div className="account-layout">
    <SiteHeader token={token} workspacePath={workspacePath(account)} workspaceLabel={workspaceLabel(account)} onLogout={handleLogout} />
    {content}
    <SiteFooter />
  </div>;

  return <Routes>
    {["/", "/about", "/signin"].map((path) => <Route key={path} path={path} element={
      <HomePage token={token} account={account} onAuthenticated={handleAuthenticated}
                onLogout={handleLogout} error={error}
                intent={path === "/" ? "" : path.slice(1)} />} />)}
    <Route path="/forgot-password" element={withSiteChrome(<ForgotPasswordPage />)} />
    <Route path="/reset-password" element={withSiteChrome(<ResetPasswordPage />)} />
    <Route path="/MyAccount/*" element={!token ? <RememberEmployeeDestination /> : !account ? withSiteChrome(pendingAccount) : account.can_admin ? <Navigate to="/admin" replace /> : <EmployeeWorkspace account={account} token={token} onAccountChange={handleAuthenticated} onLogout={handleLogout} />} />
    <Route path="/admin/*" element={!token ? <Navigate to="/signin" replace /> : !account ? pendingAccount : account.can_admin ? <AdminDashboard token={token} account={account} onLogout={handleLogout} onAuthError={handleAuthError} /> : <Navigate to={workspacePath(account)} replace />} />
    <Route path="/dashboard/*" element={!token ? <Navigate to="/signin" replace /> : !account ? pendingAccount : account.can_admin ? <Navigate to="/admin" replace /> : account.can_manage ? <EmployerWorkspace token={token} account={account} onLogout={handleLogout} onAuthError={handleAuthError} onAccountChange={(partial) => setAccount((current) => current ? { ...current, ...partial } : current)} /> : <Navigate to="/MyAccount" replace />} />
    <Route path="*" element={<Navigate to="/" replace />} />
  </Routes>;
}

export default App;
