import { useEffect, useState } from "react";
import ModalDialog from "./components/ModalDialog";
import Payslip from "./components/Payslip";
import { useConfirm } from "./components/ConfirmDialog";
import { cancelMySalaryAdvanceRequest, fetchMyPayroll, requestMySalaryAdvance } from "./api";
import { decisionText, label, money } from "./managerConfig";

const ADVANCE_STATUS = { disbursed: "Active", partially_repaid: "Partially repaid", repaid: "Repaid" };
const EMPTY_REQUEST = { amount: "", reason: "" };

export default function EmployeePayroll({ token }) {
  const [payroll, setPayroll] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState(null);
  const [payslip, setPayslip] = useState(null);
  const [confirm, confirmation] = useConfirm();

  useEffect(() => {
    let cancelled = false;
    fetchMyPayroll(token).then((result) => { if (!cancelled) setPayroll(result); })
      .catch((err) => { if (!cancelled) setError(err.message); });
    return () => { cancelled = true; };
  }, [token]);

  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const saved = await requestMySalaryAdvance(token, form);
      setPayroll((current) => ({ ...current, requests: [saved, ...current.requests] }));
      setForm(null);
      setNotice("Your salary advance request has been sent to your employer for approval.");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function cancel(record) {
    if (!await confirm({ title: "Cancel advance request?", message: `Cancel your request for ${money(record.amount, record.currency)}?`, confirmLabel: "Cancel request" })) return;
    setBusy(true);
    setError("");
    try {
      await cancelMySalaryAdvanceRequest(token, record.id);
      setPayroll((current) => ({ ...current, requests: current.requests.filter((item) => item.id !== record.id) }));
      setNotice("Your pending advance request was cancelled.");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const salary = payroll?.salary;
  const currency = salary?.currency || "RWF";
  const months = payroll?.months || [];
  const payslips = payroll?.payslips || [];
  const advances = payroll?.advances || [];
  const requests = payroll?.requests || [];
  const lastPaid = months.find((row) => row.status === "paid");
  const outstanding = advances.reduce((sum, row) => sum + Number(row.outstanding_balance), 0);
  const pending = requests.some((row) => row.status === "pending");
  const openPayslip = (id) => {
    const record = payslips.find((row) => row.id === id);
    if (record) setPayslip(record);
  };

  return <section className="leave-account-section" id="payroll">
    <div className="section-heading compact-heading"><div><p className="eyebrow dark-eyebrow">PAY</p><h2>Payroll</h2><p>Your salary, monthly payments, deductions and payslips.</p></div>
      {payroll && <button className="button button-coral" type="button" disabled={!salary || pending} title={!salary ? "Your employer has not set your salary yet." : pending ? "You already have a pending request." : undefined} onClick={() => { setError(""); setNotice(""); setForm(EMPTY_REQUEST); }}>Request salary advance</button>}</div>
    {error && <p className="message error" role="alert">{error}</p>}
    {notice && <p className="message success" role="status">{notice}</p>}
    {!payroll ? !error && <p className="empty-state" role="status">Loading your payroll…</p> : <>
      {!salary && <p className="message">Your employer has not set your salary yet.</p>}
      <div className="summary-row manager-summary">
        <div className="summary-card"><span>Monthly salary</span><strong>{salary ? money(salary.monthly_amount, salary.currency) : "Not set"}</strong>{salary && <small className="muted">Since {salary.effective_date}</small>}</div>
        <div className="summary-card"><span>Last net pay</span><strong>{lastPaid ? money(lastPaid.net_salary, currency) : "None yet"}</strong>{lastPaid && <small className="muted">{lastPaid.month} · paid {lastPaid.paid_date}</small>}</div>
        <div className="summary-card"><span>Advances outstanding</span><strong>{money(outstanding, currency)}</strong><small className="muted">Deducted automatically from your salary</small></div>
      </div>

      <section className="panel account-panel"><h3>Monthly payments</h3>
        {!months.length ? <p className="empty-state">No payments yet.</p> : <div className="table-scroll"><table>
          <thead><tr><th scope="col">Month</th><th scope="col">Status</th><th scope="col">Gross pay</th><th scope="col">Deductions</th><th scope="col">Net pay</th><th scope="col">Paid on</th><th scope="col">Actions</th></tr></thead>
          <tbody>{months.map((row) => <tr key={row.month} className={row.payroll ? "clickable-row" : undefined} tabIndex={row.payroll ? 0 : undefined}
            onClick={(event) => { if (row.payroll && !event.target.closest("button")) openPayslip(row.payroll); }}
            onKeyDown={(event) => { if (row.payroll && (event.key === "Enter" || event.key === " ") && !event.target.closest("button")) { event.preventDefault(); openPayslip(row.payroll); } }}>
            <td>{row.month}</td>
            <td><span className={`status-badge status-${row.status === "paid" ? "paid" : "pending"}`}>{row.status === "paid" ? "Paid" : "Not paid yet"}</span></td>
            <td>{row.monthly_salary === null ? "—" : money(row.monthly_salary, currency)}</td>
            <td>{row.total_deductions === null ? "—" : <>{money(row.total_deductions, currency)}{row.lines.map((line, index) => <small className="muted deduction-note" key={index}>{line.name}: {money(line.amount, currency)}</small>)}</>}</td>
            <td>{row.net_salary === null ? "—" : <strong>{money(row.net_salary, currency)}</strong>}</td>
            <td>{row.paid_date || "—"}</td>
            <td><div className="row-actions">{row.payroll && <button type="button" onClick={() => openPayslip(row.payroll)}>Payslip</button>}</div></td>
          </tr>)}</tbody>
        </table></div>}
      </section>

      <div className="leave-lists">
        <section className="panel account-panel"><h3>Advance requests</h3>
          {!requests.length ? <p className="empty-state">You have not requested a salary advance.</p> : <div className="leave-history-list">{requests.map((item) => <div className="leave-history-row" key={item.id}>
            <div><strong>{money(item.amount, item.currency)}</strong><span>Requested {new Date(item.requested_at).toLocaleDateString()}{item.reason ? ` · ${item.reason}` : ""}</span>{item.status !== "pending" && item.decided_at && <small>{decisionText(item.status, item.decided_by, item.decided_at)}</small>}{item.decision_notes && <small>{item.decision_notes}</small>}</div>
            <div><span className={`status-badge status-${item.status}`}>{label(item.status)}</span>{item.status === "pending" && <button className="text-button danger-link" disabled={busy} type="button" onClick={() => cancel(item)}>Cancel</button>}</div>
          </div>)}</div>}
        </section>
        <section className="panel account-panel"><h3>Salary advances</h3>
          {!advances.length ? <p className="empty-state">No salary advances.</p> : <div className="leave-history-list">{advances.map((item) => <div className="leave-history-row" key={item.id}>
            <div><strong>{money(item.amount, item.currency)}</strong><span>Given {item.issue_date} · repaid {money(item.total_repaid, item.currency)} · outstanding {money(item.outstanding_balance, item.currency)}</span>{Number(item.next_installment) > 0 && <small>Next deduction: up to {money(item.next_installment, item.currency)}</small>}</div>
            <div><span className={`status-badge status-${item.status === "repaid" ? "paid" : "approved"}`}>{ADVANCE_STATUS[item.status] || label(item.status)}</span></div>
          </div>)}</div>}
        </section>
      </div>
    </>}

    {form && <ModalDialog title="Request salary advance" onClose={() => setForm(null)}><form className="account-panel leave-request-form" onSubmit={submit}>
      <h3>Request salary advance</h3>
      <fieldset className="auth-fields" disabled={busy}>
        <label htmlFor="advance-amount">Amount ({currency})</label><input id="advance-amount" type="number" min="1" step="0.01" value={form.amount} onChange={(event) => setForm({ ...form, amount: event.target.value })} required />
        <label htmlFor="advance-reason">Reason (optional)</label><textarea id="advance-reason" rows="3" value={form.reason} onChange={(event) => setForm({ ...form, reason: event.target.value })} />
        <p className="muted">Your employer reviews the request. Once approved, the advance is deducted automatically from your salary.</p>
        <button className="button button-coral" type="submit" disabled={busy}>{busy ? "Sending…" : "Send request"}</button>
      </fieldset>
    </form></ModalDialog>}
    {payslip && <Payslip record={payslip} calculation={{ lines: payslip.lines }} onClose={() => setPayslip(null)} />}
    {confirmation}
  </section>;
}
