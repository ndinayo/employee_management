const DEVICE_LOCATION_HELP = "Turn on location for this device (on Windows: Settings › Privacy & security › Location, "
  + "including “Let desktop apps access your location”), make sure Wi-Fi is on, then try again.";

const LOCATION_ERRORS = {
  1: "Location permission was denied. Click the lock icon next to the address bar, allow Location for this site, and try again.",
  2: `Your location could not be determined. ${DEVICE_LOCATION_HELP}`,
  3: `Finding your location took too long. ${DEVICE_LOCATION_HELP}`,
};

function locate(options, limit) {
  return new Promise((resolve, reject) => {
    // Some browsers never call back while the permission prompt is ignored.
    const timer = window.setTimeout(() => reject({ code: 3 }), limit + 2000);
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        window.clearTimeout(timer);
        resolve({ latitude: coords.latitude, longitude: coords.longitude, accuracy: coords.accuracy });
      },
      (error) => {
        window.clearTimeout(timer);
        reject(error);
      },
      { ...options, timeout: limit },
    );
  });
}

export async function currentPosition(timeout = 20000) {
  if (!navigator.geolocation) throw new Error("This browser cannot share your location.");
  if (!window.isSecureContext) throw new Error("Location only works on https:// or localhost addresses.");
  const precise = Math.min(8000, Math.round(timeout / 2));
  try {
    return await locate({ enableHighAccuracy: true, maximumAge: 0 }, precise);
  } catch (error) {
    if (error.code === 1) throw new Error(LOCATION_ERRORS[1], { cause: error });
  }
  // Computers without GPS rarely answer a high-accuracy request; Wi-Fi positioning usually does.
  try {
    return await locate({ enableHighAccuracy: false, maximumAge: 60000 }, timeout - precise);
  } catch (error) {
    throw new Error(LOCATION_ERRORS[error.code] || LOCATION_ERRORS[2], { cause: error });
  }
}

export function positionOrNull(timeout) {
  return currentPosition(timeout).catch(() => null);
}

export function distanceText(metres) {
  if (metres === null || metres === undefined) return "";
  return metres < 1000 ? `${metres} m` : `${(metres / 1000).toFixed(1)} km`;
}

export const LOCATION_LABELS = { inside: "Inside office area", outside: "Not in office", unavailable: "Location unavailable" };

export function locationText(record, prefix) {
  const status = record?.[`${prefix}_location_status`];
  if (!status) return "";
  const distance = record[`${prefix}_distance_m`];
  if (status === "outside") return `${LOCATION_LABELS.outside} · ${distanceText(distance)} away`;
  if (status === "inside") return `${LOCATION_LABELS.inside} · ${distanceText(distance)}`;
  return LOCATION_LABELS[status] || status;
}
