import { locationText } from "../geolocation";

export default function LocationStatus({ record, prefix }) {
  if (!record?.[`${prefix}_at`]) return null;
  const text = locationText(record, prefix);
  if (!text) return <span className="status-badge location-badge location-unverified">Location not verified</span>;
  return <span className={`status-badge location-badge location-${record[`${prefix}_location_status`]}`}>{text}</span>;
}
