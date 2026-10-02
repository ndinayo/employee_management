import { useEffect, useRef, useState } from "react";

function when(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const day = date.toLocaleDateString([], { day: "2-digit", month: "short" });
  return `${day}, ${date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
}

// What a sent message says about where it ended up. An emailed one never
// reaches the other side's dashboard, so it can only report the mail result.
function receipt(message) {
  if (message.channel !== "email") return message.read ? "Read" : "Delivered";
  return message.emailed ? "Sent by email" : "Email could not be sent";
}

// Both sides of the platform conversation render with this: the administrator
// talking to one company, and that company talking back. `mine` decides which
// bubbles sit on the right, so the same log reads correctly for either viewer.
export default function Conversation({ thread, mine, onSend, placeholder, empty, recipient }) {
  const [draft, setDraft] = useState("");
  const [channel, setChannel] = useState("message");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const log = useRef(null);
  const messages = thread?.messages || [];

  // Follow the conversation down as it grows, the way a chat window does.
  useEffect(() => {
    if (log.current) log.current.scrollTop = log.current.scrollHeight;
  }, [messages.length]);

  async function submit(event) {
    event.preventDefault();
    const body = draft.trim();
    if (!body) return;
    setBusy(true); setError("");
    try {
      await onSend(body, channel);
      setDraft("");
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  return <div className="conversation">
    <div className="chat-log" ref={log} role="log" aria-label="Conversation">
      {!messages.length ? <p className="empty-state">{empty}</p> : messages.map((message) => {
        const own = message.from_admin === mine;
        return <article key={message.id} className={`chat-message${own ? " own" : ""}`}>
          <p className="chat-meta">
            <strong>{own ? "You" : message.author || (message.from_admin ? "Platform team" : "Company")}</strong>
            <span>
              {message.channel === "email" && <span className="chat-channel">Email</span>}
              {when(message.created_at)}
            </span>
          </p>
          <p className="chat-body">{message.body}</p>
          {own && <p className={`chat-receipt${message.channel === "email" && !message.emailed ? " failed" : ""}`}>{receipt(message)}</p>}
        </article>;
      })}
    </div>
    {error && <p className="message error" role="alert">{error}</p>}
    <form className="chat-composer" onSubmit={submit}>
      <fieldset className="channel-choice" disabled={busy}>
        <legend>How should this be sent?</legend>
        <label>
          <input type="radio" name="channel" value="message" checked={channel === "message"}
                 onChange={() => setChannel("message")} />
          <span>
            <strong>Message</strong>
            <small>Appears in their dashboard here. No email is sent.</small>
          </span>
        </label>
        <label>
          <input type="radio" name="channel" value="email" checked={channel === "email"}
                 onChange={() => setChannel("email")} />
          <span>
            <strong>Email</strong>
            <small>Goes to their inbox only. It will not appear in their dashboard.</small>
          </span>
        </label>
      </fieldset>
      <label className="visually-hidden" htmlFor="chat-draft">Your message</label>
      <textarea
        id="chat-draft"
        rows={3}
        value={draft}
        maxLength={5000}
        disabled={busy}
        placeholder={placeholder}
        onChange={(event) => setDraft(event.target.value)}
      />
      <button className="button button-coral" type="submit" disabled={busy || !draft.trim()}>
        {busy ? "Sending…" : channel === "email" ? `Send email${recipient ? ` to ${recipient}` : ""}` : "Send message"}
      </button>
    </form>
  </div>;
}
