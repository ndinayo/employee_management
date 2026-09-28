import { useCallback, useState } from "react";
import ModalDialog from "./ModalDialog";

export function useConfirm() {
  const [pending, setPending] = useState(null);

  const confirm = useCallback((options) => new Promise((resolve) => {
    const details = typeof options === "string" ? { message: options } : options;
    setPending({
      title: "Please confirm",
      confirmLabel: "Confirm",
      cancelLabel: "Cancel",
      ...details,
      resolve,
    });
  }), []);

  const finish = (answer) => {
    pending?.resolve(answer);
    setPending(null);
  };

  const dialog = pending ? <ModalDialog title={pending.title} onClose={() => finish(false)}>
    <div className="confirm-dialog-content">
      <p>{pending.message}</p>
      <div className="form-actions">
        <button className="button button-coral" type="button" onClick={() => finish(true)}>{pending.confirmLabel}</button>
        <button className="button button-outline" type="button" onClick={() => finish(false)}>{pending.cancelLabel}</button>
      </div>
    </div>
  </ModalDialog> : null;

  return [confirm, dialog];
}
