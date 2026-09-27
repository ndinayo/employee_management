import { useEffect, useRef } from "react";

const tools = [
  ["bold", "Bold", "B"], ["italic", "Italic", "I"], ["underline", "Underline", "U"],
  ["insertUnorderedList", "Bulleted list", "• List"],
  ["insertOrderedList", "Numbered list", "1. List"],
  ["justifyLeft", "Align left", "Left"], ["justifyCenter", "Centre", "Centre"],
  ["justifyRight", "Align right", "Right"], ["undo", "Undo", "↶"], ["redo", "Redo", "↷"],
];

export function RichTextEditor({ value, onChange }) {
  const editor = useRef(null);

  useEffect(() => {
    if (editor.current && document.activeElement !== editor.current && editor.current.innerHTML !== (value || "")) {
      editor.current.innerHTML = value || "";
    }
  }, [value]);

  function command(name, argument = null) {
    editor.current?.focus();
    document.execCommand(name, false, argument);
    onChange(editor.current?.innerHTML || "");
  }

  return <div className="contract-editor-shell">
    <div className="contract-toolbar" role="toolbar" aria-label="Contract formatting">
      <select aria-label="Text style" defaultValue="p" onChange={(event) => command("formatBlock", event.target.value)}>
        <option value="p">Normal text</option><option value="h1">Title</option>
        <option value="h2">Heading</option><option value="h3">Subheading</option>
      </select>
      {tools.map(([name, title, text]) => <button key={name} type="button" title={title} aria-label={title}
        onMouseDown={(event) => { event.preventDefault(); command(name); }}>{text}</button>)}
    </div>
    <div ref={editor} className="contract-editor" contentEditable suppressContentEditableWarning
      data-placeholder="Write the complete employment contract here…"
      onInput={(event) => onChange(event.currentTarget.innerHTML)} />
  </div>;
}

export function DigitalContractDocument({ contract }) {
  return <article className="digital-contract-document">
    <header>
      <p className="eyebrow dark-eyebrow">DIGITAL CONTRACT</p>
      <h2>{contract.title}</h2>
      <p>{contract.business_name || ""}{contract.employee_name ? ` · ${contract.employee_name}` : ""}</p>
      <p className="muted">Effective {contract.start_date}{contract.end_date ? ` to ${contract.end_date}` : " · ongoing"}</p>
    </header>
    <div className="contract-paper-body" dangerouslySetInnerHTML={{ __html: contract.content }} />
    {contract.signature_status === "signed" && <section className="contract-signature-record">
      <p>Digitally signed by</p>
      {contract.signature_data && <img src={contract.signature_data} alt={`Signature of ${contract.signer_name}`} />}
      <strong>{contract.signer_name}</strong>
      <span>{contract.signed_at ? new Date(contract.signed_at).toLocaleString() : ""}</span>
    </section>}
  </article>;
}

export function SignaturePad({ onChange }) {
  const canvasRef = useRef(null);
  const drawing = useRef(false);

  function point(event) {
    const canvas = canvasRef.current;
    const rect = canvas.getBoundingClientRect();
    return {
      x: (event.clientX - rect.left) * canvas.width / rect.width,
      y: (event.clientY - rect.top) * canvas.height / rect.height,
    };
  }

  function start(event) {
    const canvas = canvasRef.current;
    const context = canvas.getContext("2d");
    const current = point(event);
    drawing.current = true;
    canvas.setPointerCapture(event.pointerId);
    context.beginPath();
    context.moveTo(current.x, current.y);
  }

  function move(event) {
    if (!drawing.current) return;
    const context = canvasRef.current.getContext("2d");
    const current = point(event);
    context.lineWidth = 4;
    context.lineCap = "round";
    context.lineJoin = "round";
    context.strokeStyle = "#2b2530";
    context.lineTo(current.x, current.y);
    context.stroke();
  }

  function finish() {
    if (!drawing.current) return;
    drawing.current = false;
    onChange(canvasRef.current.toDataURL("image/png"));
  }

  function clear() {
    const canvas = canvasRef.current;
    canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
    onChange("");
  }

  return <div className="signature-pad-wrap">
    <canvas ref={canvasRef} className="signature-pad" width="1000" height="240"
      onPointerDown={start} onPointerMove={move} onPointerUp={finish} onPointerCancel={finish}
      aria-label="Draw your signature" />
    <button className="text-button" type="button" onClick={clear}>Clear signature</button>
  </div>;
}
