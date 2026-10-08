import { useEffect, useState } from "react";
import { Link } from "react-router";
import { fetchWorkplaceLocation, saveWorkplaceLocation, updateWorkplaceRadius } from "../api";
import { currentPosition } from "../geolocation";

export function WorkplaceLocationHint({ token }) {
  const [configured, setConfigured] = useState(true);
  useEffect(() => {
    let cancelled = false;
    fetchWorkplaceLocation(token).then((result) => { if (!cancelled) setConfigured(result.configured); }).catch(() => {});
    return () => { cancelled = true; };
  }, [token]);
  if (configured) return null;
  return <p className="message">Check-in locations are not being verified. <Link to="/dashboard/settings">Save your workplace location in Settings</Link> to see who checks in inside the office area.</p>;
}

export default function WorkplaceLocationCard({ token, onAuthError }) {
  const [workplace, setWorkplace] = useState(null);
  const [radius, setRadius] = useState("100");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let cancelled = false;
    fetchWorkplaceLocation(token).then((result) => {
      if (!cancelled) { setWorkplace(result); setRadius(String(result.radius_m)); }
    }).catch((err) => {
      if (!cancelled) { setError(err.message); onAuthError?.(err); }
    });
    return () => { cancelled = true; };
  }, [token, onAuthError]);

  async function run(kind, action) {
    if (busy) return;
    setBusy(kind);
    setError("");
    setNotice("");
    try {
      const { saved, message } = await action();
      setWorkplace(saved);
      setRadius(String(saved.radius_m));
      setNotice(message);
    } catch (err) {
      setError(err.message);
      onAuthError?.(err);
    } finally {
      setBusy("");
    }
  }

  function useCurrentLocation() {
    run("locate", async () => {
      const position = await currentPosition();
      const saved = await saveWorkplaceLocation(token, { latitude: position.latitude, longitude: position.longitude, radius_m: Number(radius) || 100 });
      const accuracy = Math.round(position.accuracy || 0);
      return { saved, message: accuracy > saved.radius_m
        ? `Workplace location saved, but this device only located you to within about ${accuracy} m. Save it again from a phone in the office for a precise point.`
        : `Workplace location saved (accurate to about ${accuracy} m).` };
    });
  }

  const configured = workplace?.configured;
  const radiusChanged = configured && Number(radius) !== workplace.radius_m;
  return <section className="panel record-form form-launch-card workplace-location-card" aria-labelledby="workplace-location-heading">
    <div>
      <h3 id="workplace-location-heading">Workplace location</h3>
      <p className="muted">{!workplace ? "Loading…" : configured
        ? <>Check-ins within {workplace.radius_m} m of <a href={`https://www.google.com/maps?q=${workplace.latitude},${workplace.longitude}`} target="_blank" rel="noreferrer">{Number(workplace.latitude).toFixed(5)}, {Number(workplace.longitude).toFixed(5)}</a> count as inside the office area.</>
        : "Not set. Stand in the office and use your current location so employee check-ins can be verified."}</p>
      {error && <p className="message error" role="alert">{error}</p>}
      {notice && <p className="message success" role="status">{notice}</p>}
    </div>
    <div className="workplace-location-actions">
      <label htmlFor="workplace-radius">Allowed radius (m)</label>
      <input id="workplace-radius" type="number" min="10" max="5000" step="10" value={radius} onChange={(event) => setRadius(event.target.value)} />
      {radiusChanged && <button className="button button-outline" type="button" disabled={Boolean(busy)} onClick={() => run("radius", async () => ({ saved: await updateWorkplaceRadius(token, Number(radius)), message: "Allowed radius updated." }))}>{busy === "radius" ? "Saving…" : "Save radius"}</button>}
      <button className="button button-coral" type="button" disabled={Boolean(busy) || !workplace} onClick={useCurrentLocation}>{busy === "locate" ? "Getting location…" : "Use My Current Location"}</button>
    </div>
  </section>;
}
