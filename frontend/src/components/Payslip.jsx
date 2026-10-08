import { useEffect, useRef } from "react";
import { label, money } from "../managerConfig";

export default function Payslip({ record, onClose, calculation }) {
  const deductionLines = calculation ? calculation.lines.filter((line) => Number(line.amount) > 0) : [];
  const dialog = useRef(null);
  useEffect(() => {
    const element = dialog.current;
    element.showModal();
    return () => element.close();
  }, []);
  return <dialog ref={dialog} className="payslip-dialog" onCancel={onClose} aria-labelledby="payslip-title">
    <div className="payslip-actions no-print">
      <button type="button" className="button button-coral" onClick={() => window.print()}>Print / save as PDF</button>
      <button type="button" className="button button-outline" onClick={onClose}>Close</button>
    </div>
    <article className="payslip">
      <p className="eyebrow dark-eyebrow">EMPLOYEE MANAGEMENT</p>
      <h2 id="payslip-title">{record.status === "draft" ? "Draft payslip" : "Payslip"} #{String(record.id).padStart(6, "0")}</h2>
      <p>{record.period_start} to {record.period_end}</p>
      <div className="payslip-person"><strong>{record.employee_name}</strong><p>{record.job_title} · {record.department}</p><p>{record.employee_email}</p></div>
      <dl className="pay-breakdown">
        <div><dt>Base salary</dt><dd>{money(record.base_salary, record.currency)}</dd></div>
        <div><dt>Allowances</dt><dd>{money(record.allowances, record.currency)}</dd></div>
        <div><dt>Gross pay</dt><dd>{money(record.gross_pay, record.currency)}</dd></div>
        <div><dt>Deductions</dt><dd>{money(record.deductions, record.currency)}</dd></div>
        {deductionLines.map((line, index) => <div className="pay-breakdown-line" key={`${line.kind}-${index}`}><dt>{line.name}</dt><dd>{money(line.amount, record.currency)}</dd></div>)}
        <div className="net-pay"><dt>Net pay</dt><dd>{money(record.net_pay, record.currency)}</dd></div>
      </dl>
      <p><strong>{label(record.status)}</strong>{record.paid_date && ` on ${record.paid_date}`}</p>
      {record.status === "draft" && <p className="muted">Preview only. Payment has not been recorded.</p>}
      {record.notes && <p className="preserve-lines">{record.notes}</p>}
    </article>
  </dialog>;
}
