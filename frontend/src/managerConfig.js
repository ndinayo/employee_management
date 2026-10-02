function isoDate(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

export function today() {
  return isoDate(new Date());
}

// Shifts a YYYY-MM-DD string by whole days in local time, so the roster never
// slips a day the way toISOString() would for non-UTC offsets.
export function shiftDate(value, days) {
  const date = new Date(`${value}T00:00:00`);
  date.setDate(date.getDate() + days);
  return isoDate(date);
}

export function longDate(value) {
  return new Date(`${value}T00:00:00`).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
}

export function isWeekend(value) {
  const day = new Date(`${value}T00:00:00`).getDay();
  return day === 0 || day === 6;
}

export function label(value) {
  return String(value ?? "").replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}

export function money(value, currency = "RWF") {
  return new Intl.NumberFormat("en", { style: "currency", currency }).format(Number(value || 0));
}

const field = (name, title, type = "text", extra = {}) => ({ name, title, type, ...extra });
const choices = (...values) => values.map((value) => [value, label(value)]);
const departments = choices("IT", "Marketing", "Sales", "Finance", "Human Resources", "Operations");
const employee = field("employee", "Employee", "employee");
const notes = field("notes", "Notes", "textarea", { optional: true });
const currency = field("currency", "Currency", "select", { options: choices("RWF", "ZAR", "USD", "EUR", "GBP", "BWP", "NAD", "LSL", "SZL", "KES", "NGN") });
const amount = (name, title) => field(name, title, "number", { min: 0, step: "0.01" });
const upload = (name, title, accept, megabytes) => field(name, title, "file", { optional: true, accept, maxSize: megabytes * 1024 * 1024, maxLabel: `${megabytes} MB` });
const personColumn = { title: "Employee", value: (row) => row.employee_name };
const periodColumn = { title: "Period", value: (row) => `${row.start_date || row.period_start} → ${row.end_date || row.period_end || "Ongoing"}` };
const statusColumn = { title: "Status", value: (row) => label(row.status), badge: true };

export const modules = {
  employees: {
    title: "Employees", singular: "employee", description: "Add someone with their name, job title and email. They complete the rest themselves.",
    // Hiring only needs the core fields; the employee fills in the rest.
    collapseExtras: "Add more job details now (optional)",
    defaults: () => ({ first_name: "", last_name: "", email: "", department: "Operations", job_title: "", date_joined: today(), phone: "", address: "", emergency_contact: "", manager_name: "", job_description: "", employment_type: "full_time", is_active: true, photo: null, contract_title: "", contract_document: null }),
    fields: [field("first_name", "First name", "text", { core: true }), field("last_name", "Last name", "text", { core: true }), field("job_title", "Job title", "text", { core: true }), field("email", "Work email", "email", { core: true, hint: "We email sign-in details here so they can complete their own profile." }), field("department", "Department", "select", { options: departments }), field("date_joined", "Date joined", "date", { optional: true }), field("employment_type", "Employment type", "select", { options: choices("full_time", "part_time", "contract", "intern") }), field("is_active", "Active employee", "checkbox"), field("manager_name", "Reports to", "text", { optional: true }), field("job_description", "Job description", "textarea", { optional: true }), field("phone", "Phone", "tel", { optional: true }), field("address", "Home address", "textarea", { optional: true }), field("emergency_contact", "Emergency contact", "text", { optional: true }), upload("photo", "Profile photo (JPG, PNG, WEBP; max 5 MB)", ".jpg,.jpeg,.png,.webp", 5), field("contract_title", "Contract title", "text", { optional: true, placeholder: "Employment contract", section: "Employment contract" }), upload("contract_document", "Contract document (PDF, DOC, DOCX; max 10 MB)", ".pdf,.doc,.docx", 10)],
    columns: [{ title: "Name", value: (row) => `${row.first_name} ${row.last_name}`, secondary: (row) => row.email, avatar: true }, { title: "Job title", value: (row) => row.job_title }, { title: "Department", value: (row) => row.department }, { title: "Joined", value: (row) => row.date_joined }, { title: "Account", value: (row) => row.account_status === "active" ? "Active" : row.account_status === "pending_first_sign_in" ? "Invited" : "No account", badge: true }, { title: "Status", value: (row) => row.is_active ? "Active" : "Inactive", badge: true }],
  },
  contracts: {
    title: "Contracts", singular: "contract", description: "Write contracts digitally, send them to employees, and keep their signatures on record.",
    defaults: () => ({ employee: "", job_title: "", department: "Operations", title: "", start_date: today(), end_date: "", status: "draft", content: "", document: null }),
    fields: [employee, field("job_title", "Job title", "text", { readOnly: true, placeholder: "Select an employee" }), field("department", "Department", "select", { options: departments }), field("title", "Contract title"), field("start_date", "Start date", "date"), field("end_date", "End date", "date", { optional: true, nullable: true }), field("status", "Employment status", "select", { options: choices("draft", "active", "ended", "terminated_mutual") }), field("content", "Contract document", "richtext"), upload("document", "Optional supporting PDF, DOC or DOCX (max 10 MB)", ".pdf,.doc,.docx", 10)],
    columns: [{ ...personColumn, secondary: (row) => row.employee_email }, { title: "Contract", value: (row) => row.title, secondary: (row) => row.revision_of ? "Signature correction request" : "" }, { title: "Department", value: (row) => row.department }, periodColumn, { title: "Status", value: (row) => label(row.status), badge: true }, { title: "Signature", value: (row) => row.signature_status === "sent" ? "Awaiting signature" : label(row.signature_status), badge: true }, { title: "Worker approval", value: (row) => row.signature_status !== "signed" ? "Waiting for signature" : row.worker_approval_status === "approved" ? "Approved" : "Needs approval", badge: true }, { title: "Email", value: (row) => row.notification_sent_at ? "Sent" : row.signature_status === "sent" ? "Failed" : "Pending", secondary: (row) => row.notification_sent_at ? new Date(row.notification_sent_at).toLocaleString() : "", badge: true }, { title: "File", value: (row) => row.document_name ? "Attached" : "Not attached" }],
  },
  attendance: {
    title: "Attendance", singular: "attendance record", description: "Record daily attendance and actual hours worked, including remote work.",
    defaults: () => ({ employee: "", date: today(), shift: "day", status: "present", hours_worked: "8.00", notes: "" }),
    fields: [employee, field("date", "Work date", "date"), field("shift", "Shift", "select", { options: choices("day", "night") }), field("status", "Status", "select", { options: choices("present", "remote", "absent") }), { ...amount("hours_worked", "Hours worked"), max: 24 }, notes],
    columns: [personColumn, { title: "Date", value: (row) => row.date }, { title: "Shift", value: (row) => label(row.shift) }, statusColumn, { title: "Hours", value: (row) => row.hours_worked }, { title: "Notes", value: (row) => row.notes }],
  },
  leave: {
    title: "Leave", singular: "leave request", description: "Review employee leave requests, approve or reject them, and manage yearly balances.",
    defaults: () => ({ employee: "", leave_type: "annual", start_date: today(), end_date: today(), reason: "", status: "pending", decision_notes: "" }),
    fields: [employee, field("leave_type", "Leave type", "select", { options: choices("annual", "sick", "maternity", "unpaid") }), field("start_date", "Start date", "date"), field("end_date", "End date", "date"), field("reason", "Reason", "textarea", { optional: true }), field("status", "Decision", "select", { options: choices("pending", "approved", "rejected") }), field("decision_notes", "Decision notes", "textarea", { optional: true })],
    columns: [personColumn, { title: "Type", value: (row) => label(row.leave_type) }, periodColumn, { title: "Days", value: (row) => row.days_requested }, statusColumn, { title: "Decision", value: (row) => row.decision_notes || row.decided_by }],
  },
  announcements: {
    title: "Announcements", singular: "announcement", description: "Share important company updates with every employee.",
    defaults: () => ({ title: "", message: "" }),
    fields: [field("title", "Title"), field("message", "Announcement", "textarea")],
    columns: [{ title: "Title", value: (row) => row.title }, { title: "Announcement", value: (row) => row.message }, { title: "Published", value: (row) => new Date(row.published_at).toLocaleString() }, { title: "Opened", value: (row) => `${row.read_count} employees` }],
  },
  "calendar-events": {
    title: "Calendar", singular: "calendar event", description: "Mark important company dates for employees.", custom: true,
  },
  holidays: {
    title: "Holidays", singular: "holiday", description: "Maintain the company holiday calendar used by attendance reports.",
    defaults: () => ({ name: "", date: today(), notes: "" }),
    fields: [field("name", "Holiday name"), field("date", "Date", "date"), notes],
    columns: [{ title: "Holiday", value: (row) => row.name }, { title: "Date", value: (row) => row.date }, { title: "Notes", value: (row) => row.notes }],
  },
  salaries: {
    title: "Salaries", singular: "salary", description: "Set each employee’s current monthly salary. Existing payroll records keep their original amounts.",
    defaults: () => ({ employee: "", monthly_amount: "", currency: "RWF", effective_date: today(), notes: "" }),
    fields: [employee, amount("monthly_amount", "Monthly base salary"), currency, field("effective_date", "Effective from", "date"), notes],
    columns: [personColumn, { title: "Monthly salary", value: (row) => money(row.monthly_amount, row.currency) }, { title: "Effective from", value: (row) => row.effective_date }, { title: "Notes", value: (row) => row.notes }],
  },
  payroll: {
    title: "Payroll & payslips", singular: "payroll record", description: "Prepare payroll, enter allowances and deductions, record payment, and print payslips.",
    defaults: () => {
      const date = today();
      const end = new Date(Number(date.slice(0, 4)), Number(date.slice(5, 7)), 0).getDate();
      return { employee: "", period_start: `${date.slice(0, 8)}01`, period_end: `${date.slice(0, 8)}${end}`, base_salary: "", allowances: "0.00", deductions: "0.00", currency: "RWF", status: "draft", paid_date: "", notes: "" };
    },
    fields: [employee, field("period_start", "Period start", "date"), field("period_end", "Period end", "date"), amount("base_salary", "Base salary for this period"), amount("allowances", "Allowances"), amount("deductions", "Total deductions"), currency, field("status", "Payment status", "select", { options: choices("draft", "paid") }), field("paid_date", "Payment date", "date", { optional: true, nullable: true }), notes],
    columns: [personColumn, periodColumn, { title: "Gross", value: (row) => money(row.gross_pay, row.currency) }, { title: "Deductions", value: (row) => money(row.deductions, row.currency) }, { title: "Net pay", value: (row) => money(row.net_pay, row.currency) }, statusColumn],
  },
};

// An event runs from its start date to its end date, so a multi-day event that
// is already under way still counts as happening today.
export function eventEnd(item) {
  return item.end_date || item.date;
}

// Events happening today or within the next `days` days. The employer sidebar
// badge and the calendar's Events tab both count the same thing.
export function upcomingEvents(events, days = 7) {
  const from = today();
  const limit = new Date(`${from}T00:00:00`);
  limit.setDate(limit.getDate() + days);
  const until = `${limit.getFullYear()}-${String(limit.getMonth() + 1).padStart(2, "0")}-${String(limit.getDate()).padStart(2, "0")}`;
  return events.filter((item) => eventEnd(item) >= from && item.date <= until);
}
