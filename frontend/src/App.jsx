import { useCallback, useEffect, useState } from "react";
import { Link, Navigate, Route, Routes, useNavigate } from "react-router";
import heroImage from "./assets/images/hero.jpeg";
import { ACCESS_TOKEN } from "./constants";
import { fetchEmployees, loginUser } from "./api";
import ManagerDashboard from "./ManagerDashboard";
import "./App.css";
import "./ManagerDashboard.css";

function HomePage({
  token,
  employeeCount,
  credentials,
  setCredentials,
  onLogin,
  error,
}) {
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
            {token && <Link to="/dashboard">Dashboard</Link>}
          </nav>

          {token ? (
            <Link className="header-action" to="/dashboard">
              Open dashboard
            </Link>
          ) : (
            <a className="header-action" href="#sign-in">
              Staff sign in
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
            <Link className="button button-coral" to="/dashboard">
              Go to dashboard &rarr;
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
            <strong>{token ? employeeCount : "One place"}</strong>
            <small>
              {token ? "employee records" : "for your people records"}
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

        <section className="workspace" id="sign-in">
          <div className="section-heading">
            <div>
              <p className="eyebrow dark-eyebrow">YOUR WORKSPACE</p>
              <h2>Employee management</h2>
              <p>Sign in to manage your team.</p>
            </div>
          </div>

          {error && (
            <p className="message error" role="alert">
              {error}
            </p>
          )}

          {token ? (
            <div className="panel signed-in-panel">
              <h3>You are signed in.</h3>
              <p>Your employee records are on the dashboard.</p>
              <Link className="button button-coral" to="/dashboard">
                Open dashboard &rarr;
              </Link>
            </div>
          ) : (
            <div className="login-layout">
              <form className="panel login-panel" onSubmit={onLogin}>
                <p className="eyebrow dark-eyebrow">MANAGER ACCESS</p>
                <h3>Sign in to continue</h3>
                <p>Use your manager or administrator account.</p>

                <label htmlFor="username">Username</label>
                <input
                  id="username"
                  type="text"
                  autoComplete="username"
                  required
                  value={credentials.username}
                  onChange={(event) =>
                    setCredentials((current) => ({
                      ...current,
                      username: event.target.value,
                    }))
                  }
                />

                <label htmlFor="password">Password</label>
                <input
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  required
                  value={credentials.password}
                  onChange={(event) =>
                    setCredentials((current) => ({
                      ...current,
                      password: event.target.value,
                    }))
                  }
                />

                <button className="button button-coral" type="submit">
                  Sign in &rarr;
                </button>
              </form>

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
        </section>
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
  const [employeeCount, setEmployeeCount] = useState(0);
  const [error, setError] = useState("");
  const [credentials, setCredentials] = useState({ username: "", password: "" });

  const handleLogout = useCallback(() => {
    localStorage.removeItem(ACCESS_TOKEN);
    setToken(null);
    setEmployeeCount(0);
    setError("");
  }, []);

  const handleAuthError = useCallback((err) => {
    if (err.status === 401 || err.status === 403) {
      handleLogout();
      setError("Please sign in with a manager or administrator account.");
    }
  }, [handleLogout]);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    fetchEmployees(token).then((records) => {
      if (!cancelled) setEmployeeCount(records.length);
    }).catch((err) => {
      if (!cancelled) {
        setError(err.message);
        handleAuthError(err);
      }
    });
    return () => { cancelled = true; };
  }, [token, handleAuthError]);

  async function handleLogin(event) {
    event.preventDefault();
    setError("");
    try {
      const data = await loginUser(credentials.username, credentials.password);
      const records = await fetchEmployees(data.access);
      localStorage.setItem(ACCESS_TOKEN, data.access);
      setEmployeeCount(records.length);
      setToken(data.access);
      setCredentials({ username: "", password: "" });
      navigate("/dashboard");
    } catch (err) {
      setError(err.status === 403 ? "Manager or administrator access is required." : err.message);
    }
  }

  return <Routes>
    <Route path="/" element={<HomePage token={token} employeeCount={employeeCount} credentials={credentials} setCredentials={setCredentials} onLogin={handleLogin} error={error} />} />
    <Route path="/dashboard/*" element={token ? <ManagerDashboard token={token} onLogout={handleLogout} onAuthError={handleAuthError} /> : <Navigate to="/" replace />} />
    <Route path="*" element={<Navigate to="/" replace />} />
  </Routes>;
}

export default App;
