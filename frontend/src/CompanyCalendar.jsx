import { useMemo, useState } from "react";
import ModalDialog from "./components/ModalDialog";
import { eventEnd, label, longDate, today, upcomingEvents } from "./managerConfig";

function monthKey(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function isOnDay(item, day) {
  return item.date <= day && eventEnd(item) >= day;
}

const EVENT_RANGES = [
  ["upcoming", "Today and upcoming"],
  ["today", "Today only"],
  ["week", "Next 7 days"],
  ["month", "This month"],
  ["past", "Already finished"],
  ["all", "All events"],
];

function inRange(item, range, month) {
  const from = today();
  if (range === "today") return isOnDay(item, from);
  if (range === "upcoming") return eventEnd(item) >= from;
  if (range === "week") return upcomingEvents([item], 7).length > 0;
  if (range === "month") return item.date.slice(0, 7) === month || eventEnd(item).slice(0, 7) === month;
  if (range === "past") return eventEnd(item) < from;
  return true;
}

function dayLabel(item) {
  const from = today();
  if (isOnDay(item, from)) return "Today";
  const days = Math.round((new Date(`${item.date}T00:00:00`) - new Date(`${from}T00:00:00`)) / 86400000);
  if (days === 1) return "Tomorrow";
  if (days > 1) return `In ${days} days`;
  return `${Math.abs(days)} day${Math.abs(days) === 1 ? "" : "s"} ago`;
}

function googleCalendarUrl(event) {
  const compactDateTime = (date, time) => `${date.replaceAll("-", "")}T${time.slice(0, 5).replace(":", "")}00`;
  const endDate = event.end_date || event.date;
  const query = new URLSearchParams({
    action: "TEMPLATE",
    text: event.title,
    dates: `${compactDateTime(event.date, event.start_time)}/${compactDateTime(endDate, event.end_time)}`,
    details: event.description || `${label(event.category)} from your company calendar`,
    location: event.location || "",
    ctz: Intl.DateTimeFormat().resolvedOptions().timeZone,
  });
  return `https://calendar.google.com/calendar/render?${query}`;
}

export default function CompanyCalendar({ events, canManage = false, busy = false, onCreate, onDelete, onEventOpen, onClearAll }) {
  const [month, setMonth] = useState(() => monthKey(new Date()));
  const [selected, setSelected] = useState(null);
  const [creating, setCreating] = useState(null);
  const [tab, setTab] = useState("month");
  const [range, setRange] = useState("upcoming");
  const [category, setCategory] = useState("");
  const [search, setSearch] = useState("");
  const [created, setCreated] = useState(null);
  const [clearing, setClearing] = useState(false);
  const unreadCount = events.filter((item) => item.is_read === false).length;

  async function clearAll() {
    setClearing(true);
    try { await onClearAll(); } finally { setClearing(false); }
  }
  const [form, setForm] = useState({ title: "", category: "other", date: today(), end_date: "", start_time: "09:00", end_time: "10:00", location: "", description: "" });
  const days = useMemo(() => {
    const [year, value] = month.split("-").map(Number);
    const first = new Date(year, value - 1, 1);
    const start = new Date(year, value - 1, 1 - first.getDay());
    return Array.from({ length: 42 }, (_, index) => {
      const date = new Date(start);
      date.setDate(start.getDate() + index);
      const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
      return { key, number: date.getDate(), outside: date.getMonth() !== value - 1 };
    });
  }, [month]);

  const upcoming = useMemo(() => upcomingEvents(events), [events]);

  // Soonest first for anything still to come, most recent first for the past.
  const listed = useMemo(() => {
    const text = search.trim().toLowerCase();
    const rows = events.filter((item) => inRange(item, range, month)
      && (!category || item.category === category)
      && (!text || item.title.toLowerCase().includes(text)
        || (item.location || "").toLowerCase().includes(text)));
    return rows.sort((left, right) => range === "past"
      ? right.date.localeCompare(left.date) || right.start_time.localeCompare(left.start_time)
      : left.date.localeCompare(right.date) || left.start_time.localeCompare(right.start_time));
  }, [events, range, category, search, month]);

  function moveMonth(change) {
    const [year, value] = month.split("-").map(Number);
    setMonth(monthKey(new Date(year, value - 1 + change, 1)));
  }

  function openCreate(date) {
    if (!canManage) return;
    setForm({ title: "", category: "other", date, end_date: "", start_time: "09:00", end_time: "10:00", location: "", description: "" });
    setCreating(date);
  }

  async function submit(event) {
    event.preventDefault();
    const payload = { ...form, end_date: form.end_date || null };
    const saved = await onCreate(payload);
    // One dialog closes as the confirmation opens, so only ever one is shown.
    setCreating(null);
    setCreated(saved || payload);
  }

  async function openEvent(item) {
    const latest = onEventOpen && item.is_read === false ? await onEventOpen(item) : item;
    setSelected(latest);
  }

  return <section className="company-calendar-page">
    <div className="section-heading"><div><p className="eyebrow dark-eyebrow">IMPORTANT DATES</p><h2>Calendar</h2><p>Open a date to see company events or add one to Google Calendar.</p></div>{unreadCount > 0 && onClearAll && <button className="button button-outline" type="button" disabled={clearing} onClick={clearAll}>{clearing ? "Clearing\u2026" : `Mark all ${unreadCount} as read`}</button>}{canManage && <button className="button button-coral" type="button" onClick={() => openCreate(today())}>+ Add event</button>}</div>
    <div className="calendar-tabs" role="tablist" aria-label="Calendar views">
      <button type="button" role="tab" aria-selected={tab === "month"} className={`calendar-tab${tab === "month" ? " selected" : ""}`} onClick={() => setTab("month")}>Month</button>
      <button type="button" role="tab" aria-selected={tab === "events"} className={`calendar-tab${tab === "events" ? " selected" : ""}`} onClick={() => setTab("events")}>
        <span>Events</span>{upcoming.length > 0 && <span className="attention-badge" aria-label={`${upcoming.length} events coming up`}>{upcoming.length}</span>}
      </button>
    </div>
    {tab === "events" ? <section className="panel calendar-panel">
      <div className="records-toolbar">
        <span className="record-count">{listed.length} {listed.length === 1 ? "event" : "events"}</span>
        <div className="records-filters">
          <input type="search" aria-label="Search events" placeholder="Search events\u2026" value={search} onChange={(event) => setSearch(event.target.value)} />
          <select aria-label="Filter by date" value={range} onChange={(event) => setRange(event.target.value)}>
            {EVENT_RANGES.map(([value, title]) => <option key={value} value={value}>{title}</option>)}
          </select>
          <select aria-label="Filter by type" value={category} onChange={(event) => setCategory(event.target.value)}>
            <option value="">All types</option>
            {["holiday", "presentation", "meeting", "training", "other"].map((value) => <option key={value} value={value}>{label(value)}</option>)}
          </select>
        </div>
      </div>
      {!listed.length ? <p className="empty-state">No events match these filters.</p> : <ul className="event-list">
        {listed.map((item) => <li key={item.id}>
          <button type="button" className={`event-row${item.is_read === false ? " unread" : ""}`} onClick={() => openEvent(item)}>
            <span className="event-when">
              <strong>{longDate(item.date)}</strong>
              <small>{item.start_time.slice(0, 5)} to {item.end_time.slice(0, 5)}</small>
            </span>
            <span className="event-what">
              <strong>{item.is_read === false && <span className="calendar-unread-dot" aria-label="New event" />}{item.title}</strong>
              <small>
                {item.location || "No location"}
                {item.end_date && item.end_date !== item.date ? ` \u00b7 until ${longDate(item.end_date)}` : ""}
              </small>
            </span>
            <span className="event-tags">
              <span className={`status-badge category-${item.category}`}>{label(item.category)}</span>
              <small>{dayLabel(item)}</small>
            </span>
          </button>
        </li>)}
      </ul>}
    </section> : <section className="panel calendar-panel">
      <div className="calendar-toolbar"><button className="button button-outline" type="button" onClick={() => moveMonth(-1)}>Previous</button><h3>{new Date(`${month}-01T00:00:00`).toLocaleDateString("en-GB", { month: "long", year: "numeric" })}</h3><div><button className="button button-outline" type="button" onClick={() => setMonth(monthKey(new Date()))}>Today</button><button className="button button-outline" type="button" onClick={() => moveMonth(1)}>Next</button></div></div>
      <div className="calendar-weekdays">{["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((day) => <span key={day}>{day}</span>)}</div>
      <div className="calendar-grid">{days.map((day) => {
        const dayEvents = events.filter((item) => item.date <= day.key && (item.end_date || item.date) >= day.key);
        return <div className={`calendar-day${canManage ? " can-create" : ""}${day.outside ? " outside" : ""}${day.key === today() ? " today" : ""}`} key={day.key}
          role={canManage ? "button" : undefined} tabIndex={canManage ? 0 : undefined} aria-label={canManage ? `Add event on ${day.key}` : undefined}
          onClick={(event) => { if (canManage && !event.target.closest(".calendar-event")) openCreate(day.key); }}
          onKeyDown={(event) => { if (canManage && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); openCreate(day.key); } }}>
          <span className="calendar-day-number">{day.number}</span>
          <div className="calendar-day-events">{dayEvents.slice(0, 3).map((item) => <button className={`calendar-event category-${item.category}${item.is_read === false ? " unread" : ""}`} type="button" key={item.id} onClick={(event) => { event.stopPropagation(); openEvent(item); }}>{item.is_read === false && <span className="calendar-unread-dot" aria-label="New event" />} {item.title}</button>)}{dayEvents.length > 3 && <small>+{dayEvents.length - 3} more</small>}</div>
        </div>;
      })}</div>
    </section>}
    {created && <ModalDialog title="Event created" onClose={() => setCreated(null)}>
      <section className="calendar-event-details created-confirmation">
        <p className="message success" role="status">
          {created.title} was added to the company calendar. Everyone invited can see it now.
        </p>
        <dl>
          <dt>Date</dt><dd>{longDate(created.date)}{created.end_date && created.end_date !== created.date ? ` to ${longDate(created.end_date)}` : ""}</dd>
          <dt>Time</dt><dd>{created.start_time.slice(0, 5)} to {created.end_time.slice(0, 5)}</dd>
          <dt>Type</dt><dd>{label(created.category)}</dd>
          <dt>Location</dt><dd>{created.location || "Not specified"}</dd>
        </dl>
        <div className="form-actions">
          <a className="button button-coral" href={googleCalendarUrl(created)} target="_blank" rel="noreferrer">Add to Google Calendar</a>
          <button className="button button-outline" type="button" onClick={() => { setCreated(null); setTab("events"); }}>See all events</button>
          <button className="button button-outline" type="button" onClick={() => setCreated(null)}>Done</button>
        </div>
      </section>
    </ModalDialog>}
    {selected && <ModalDialog title={selected.title} onClose={() => setSelected(null)}><section className="calendar-event-details"><span className={`status-badge category-${selected.category}`}>{label(selected.category)}</span><dl><dt>Date</dt><dd>{longDate(selected.date)}{selected.end_date && selected.end_date !== selected.date ? ` to ${longDate(selected.end_date)}` : ""}</dd><dt>Time</dt><dd>{selected.start_time.slice(0, 5)} to {selected.end_time.slice(0, 5)}</dd><dt>Location</dt><dd>{selected.location || "Not specified"}</dd><dt>Details</dt><dd className="preserve-lines">{selected.description || "No additional information."}</dd></dl><div className="form-actions"><a className="button button-coral" href={googleCalendarUrl(selected)} target="_blank" rel="noreferrer">Add to Google Calendar</a>{canManage && <button className="button button-outline danger-link" type="button" disabled={busy} onClick={async () => { await onDelete(selected); setSelected(null); }}>Delete event</button>}</div></section></ModalDialog>}
    {creating && <ModalDialog title="Add calendar event" onClose={() => setCreating(null)}><form className="record-form" onSubmit={submit}><fieldset disabled={busy}><label htmlFor="event-title">Title</label><input id="event-title" value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} required /><label htmlFor="event-category">Type</label><select id="event-category" value={form.category} onChange={(event) => setForm({ ...form, category: event.target.value })}>{["holiday", "presentation", "meeting", "training", "other"].map((value) => <option value={value} key={value}>{label(value)}</option>)}</select><div className="record-fields"><div><label htmlFor="event-date">Start date</label><input id="event-date" type="date" value={form.date} onChange={(event) => setForm({ ...form, date: event.target.value })} required /></div><div><label htmlFor="event-end-date">End date (optional)</label><input id="event-end-date" type="date" min={form.date} value={form.end_date} onChange={(event) => setForm({ ...form, end_date: event.target.value })} /></div><div><label htmlFor="event-start-time">Start time</label><input id="event-start-time" type="time" value={form.start_time} onChange={(event) => setForm({ ...form, start_time: event.target.value })} required /></div><div><label htmlFor="event-end-time">End time</label><input id="event-end-time" type="time" value={form.end_time} onChange={(event) => setForm({ ...form, end_time: event.target.value })} required /></div></div><label htmlFor="event-location">Location (optional)</label><input id="event-location" value={form.location} onChange={(event) => setForm({ ...form, location: event.target.value })} /><label htmlFor="event-description">More information (optional)</label><textarea id="event-description" rows="5" value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /><div className="form-actions"><button className="button button-coral" type="submit">Save event</button><button className="button button-outline" type="button" onClick={() => setCreating(null)}>Cancel</button></div></fieldset></form></ModalDialog>}
  </section>;
}

export function EmployeeAnnouncements({ announcements, onOpen, onClearAll }) {
  const [selected, setSelected] = useState(null);
  const [clearing, setClearing] = useState(false);
  const unread = announcements.filter((item) => !item.is_read).length;
  async function open(item) {
    const latest = item.is_read ? item : await onOpen(item);
    setSelected(latest);
  }
  async function clearAll() {
    setClearing(true);
    try { await onClearAll(); } finally { setClearing(false); }
  }
  return <section><div className="section-heading"><div><p className="eyebrow dark-eyebrow">COMPANY NEWS</p><h2>Announcements</h2><p>Important updates shared by your employer.</p></div>{unread > 0 && onClearAll && <button className="button button-outline" type="button" disabled={clearing} onClick={clearAll}>{clearing ? "Clearing\u2026" : `Mark all ${unread} as read`}</button>}</div>
    {!announcements.length ? <section className="panel account-panel"><p className="empty-state">No announcements yet.</p></section> : <div className="announcement-list">{announcements.map((item) => <button type="button" className={`panel announcement-card${item.is_read ? "" : " unread"}`} key={item.id} onClick={() => open(item)}><div><h3>{item.title}</h3><p>{item.message}</p><small>{new Date(item.published_at).toLocaleString()}{item.created_by ? ` · ${item.created_by}` : ""}</small></div>{!item.is_read && <span className="attention-badge">New</span>}</button>)}</div>}
    {selected && <ModalDialog title={selected.title} onClose={() => setSelected(null)}><article className="announcement-details"><p className="preserve-lines">{selected.message}</p><small>Published {new Date(selected.published_at).toLocaleString()}{selected.created_by ? ` by ${selected.created_by}` : ""}</small></article></ModalDialog>}
  </section>;
}
