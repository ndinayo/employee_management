import { useEffect, useRef } from "react";

export default function ModalDialog({ children, onClose, title, wide = false, dismissible = true }) {
  const dialog = useRef(null);

  useEffect(() => {
    const element = dialog.current;
    if (element && !element.open) element.showModal();
    return () => { if (element?.open) element.close(); };
  }, []);

  return <dialog ref={dialog} className={`form-modal${wide ? " form-modal-wide" : ""}`}
    aria-label={title} onCancel={(event) => {
      if (!dismissible) event.preventDefault();
      else onClose?.();
    }} onClick={(event) => {
      if (dismissible && event.target === dialog.current) onClose?.();
    }}>
    <div className="form-modal-card">
      <div className="form-modal-heading">
        <h2>{title}</h2>
        {dismissible && <button type="button" className="modal-close" aria-label={`Close ${title}`} onClick={onClose}>×</button>}
      </div>
      {children}
    </div>
  </dialog>;
}
