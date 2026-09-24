import { useEffect, useRef, useState } from "react";
import { fetchContractPreview } from "./api";

function PdfPage({ pdf, pageNumber, zoom }) {
  const viewportRef = useRef(null);
  const pageRef = useRef(null);
  const [width, setWidth] = useState(0);
  const [result, setResult] = useState({ key: "", error: "", text: "" });
  const renderKey = `${pageNumber}/${zoom}/${width}`;
  const loading = result.key !== renderKey;

  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => {
      setWidth(Math.max(120, Math.floor(entry.contentRect.width - 32)));
    });
    observer.observe(viewportRef.current);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!width) return;
    let cancelled = false;
    let renderTask;
    const container = pageRef.current;
    async function render() {
      try {
        const page = await pdf.getPage(pageNumber);
        if (cancelled) return;
        const initial = page.getViewport({ scale: 1 });
        const viewport = page.getViewport({ scale: (width / initial.width) * zoom });
        const outputScale = Math.min(window.devicePixelRatio || 1, 2);
        // Each render has its own canvas, so rapid page/zoom changes cannot race.
        const canvas = document.createElement("canvas");
        canvas.width = Math.ceil(viewport.width * outputScale);
        canvas.height = Math.ceil(viewport.height * outputScale);
        canvas.style.width = `${viewport.width}px`;
        canvas.style.height = `${viewport.height}px`;
        canvas.setAttribute("role", "img");
        canvas.setAttribute("aria-label", `Contract page ${pageNumber} of ${pdf.numPages}`);
        renderTask = page.render({
          canvasContext: canvas.getContext("2d"), viewport,
          transform: [outputScale, 0, 0, outputScale, 0, 0],
        });
        await renderTask.promise;
        if (cancelled) return;
        container.replaceChildren(canvas);
        setResult({ key: renderKey, error: "", text: "" });
        // A text alternative allows reading and copying searchable PDF content.
        const content = await page.getTextContent().catch(() => null);
        if (!cancelled && content) setResult({ key: renderKey, error: "", text: content.items.map((item) => `${item.str || ""}${item.hasEOL ? "\n" : " "}`).join("") });
      } catch (err) {
        if (!cancelled && err.name !== "RenderingCancelledException") {
          setResult({ key: renderKey, error: "This page could not be displayed. Try another page or reopen the contract.", text: "" });
        }
      }
    }
    render();
    return () => {
      cancelled = true;
      renderTask?.cancel();
    };
  }, [pdf, pageNumber, zoom, width, renderKey]);

  return <div className="pdf-viewport" ref={viewportRef} aria-busy={loading}>
    {loading && <p className="pdf-loading" role="status">Rendering page {pageNumber}…</p>}
    {!loading && result.error && <p className="message error" role="alert">{result.error}</p>}
    <div className="pdf-page" ref={pageRef} hidden={loading || Boolean(result.error)} />
    {!loading && result.text && <details className="pdf-page-text"><summary>Page text</summary><p>{result.text}</p></details>}
  </div>;
}

function PdfPreview({ contract, token, onAuthError }) {
  const [state, setState] = useState({ pdf: null, error: "" });
  const [pageNumber, setPageNumber] = useState(1);
  const [zoom, setZoom] = useState(1);
  const [passwordPrompt, setPasswordPrompt] = useState(null);
  const [password, setPassword] = useState("");

  useEffect(() => {
    let cancelled = false;
    let loadingTask;
    async function load() {
      try {
        const [blob, { loadPdf }] = await Promise.all([
          fetchContractPreview(token, contract.id), import("./pdfEngine"),
        ]);
        const bytes = new Uint8Array(await blob.arrayBuffer());
        if (cancelled) return;
        loadingTask = loadPdf(bytes);
        loadingTask.onPassword = (updatePassword, reason) => {
          if (!cancelled) setPasswordPrompt({ updatePassword, incorrect: reason === 2 });
        };
        const pdf = await loadingTask.promise;
        if (!cancelled) setState({ pdf, error: "" });
      } catch (err) {
        if (cancelled) return;
        const error = err.name === "InvalidPDFException"
          ? "This file is not a readable PDF. Upload a valid PDF copy of the contract."
          : err.message || "The contract could not be opened. Close it and try again.";
        setState({ pdf: null, error });
        onAuthError(err);
      }
    }
    load();
    return () => {
      cancelled = true;
      if (loadingTask) void loadingTask.destroy().catch(() => {});
    };
  }, [contract.id, token, onAuthError]);

  if (state.error) return <p className="message error" role="alert">{state.error}</p>;
  if (passwordPrompt) return <form className="pdf-password" onSubmit={(event) => {
    event.preventDefault();
    passwordPrompt.updatePassword(password);
    setPasswordPrompt(null);
    setPassword("");
  }}>
    <p>This contract is password protected.</p>
    {passwordPrompt.incorrect && <p className="message error" role="alert">That password was incorrect. Please try again.</p>}
    <label htmlFor="pdf-password">PDF password</label>
    <input id="pdf-password" type="password" autoComplete="off" value={password} onChange={(event) => setPassword(event.target.value)} required />
    <button className="button button-coral" type="submit">Open PDF</button>
  </form>;
  if (!state.pdf) return <p className="empty-state" role="status">Opening contract…</p>;
  return <>
    <div className="pdf-toolbar" aria-label="PDF controls">
      <div className="pdf-pagination">
        <button className="button button-outline" type="button" disabled={pageNumber === 1} onClick={() => setPageNumber((page) => page - 1)}>Previous page</button>
        <span aria-live="polite">Page {pageNumber} of {state.pdf.numPages}</span>
        <button className="button button-outline" type="button" disabled={pageNumber === state.pdf.numPages} onClick={() => setPageNumber((page) => page + 1)}>Next page</button>
      </div>
      <div className="pdf-zoom">
        <button className="button button-outline" type="button" aria-label="Zoom out" disabled={zoom <= 0.5} onClick={() => setZoom((value) => value - 0.25)}>−</button>
        <span aria-live="polite">{Math.round(zoom * 100)}%</span>
        <button className="button button-outline" type="button" aria-label="Zoom in" disabled={zoom >= 2} onClick={() => setZoom((value) => value + 0.25)}>+</button>
        <button className="text-button" type="button" onClick={() => setZoom(1)}>Fit width</button>
      </div>
    </div>
    <PdfPage pdf={state.pdf} pageNumber={pageNumber} zoom={zoom} />
  </>;
}

export default function ContractViewer({ contract, token, onClose, onAuthError }) {
  const dialog = useRef(null);
  const isPdf = contract.document_name?.toLowerCase().endsWith(".pdf");
  useEffect(() => {
    const element = dialog.current;
    element.showModal();
    return () => element.close();
  }, []);
  return <dialog ref={dialog} className="viewer-dialog" onCancel={onClose} aria-labelledby="viewer-title">
    <div className="viewer-bar">
      <div>
        <h3 id="viewer-title">{contract.title}</h3>
        <p className="muted">{contract.employee_name} · {contract.start_date} → {contract.end_date || "Ongoing"}</p>
      </div>
      <button className="button button-coral" type="button" onClick={onClose}>Close</button>
    </div>
    {isPdf ? <PdfPreview key={contract.id} contract={contract} token={token} onAuthError={onAuthError} />
      : <p className="empty-state">Word documents cannot be previewed here. Upload a PDF to read it inside the app, or use Download on the Contracts page to open the Word file.</p>}
  </dialog>;
}
