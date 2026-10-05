import { useState } from "react";

function EyeIcon({ crossed }) {
  return <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
    <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" />
    <circle cx="12" cy="12" r="3" />
    {crossed && <path d="M3 3l18 18" />}
  </svg>;
}

export default function PasswordInput(props) {
  const [visible, setVisible] = useState(false);
  return <div className="password-input">
    <input {...props} type={visible ? "text" : "password"} />
    <button type="button" className="password-toggle" onClick={() => setVisible((current) => !current)}
            aria-label={visible ? "Hide password" : "Show password"} aria-pressed={visible}
            aria-controls={props.id} title={visible ? "Hide password" : "Show password"}>
      <EyeIcon crossed={visible} />
    </button>
  </div>;
}
