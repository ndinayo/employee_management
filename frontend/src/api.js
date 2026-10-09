import { ACCESS_TOKEN, REFRESH_TOKEN } from "./constants";

// Development requests use Vite's API proxy; deployments can set VITE_API_URL.
const API_URL = (
  import.meta.env.DEV ? "" : import.meta.env.VITE_API_URL || "http://127.0.0.1:8000"
).replace(/\/$/, "");

let refreshPromise = null;

async function refreshAccessToken() {
  const refresh = localStorage.getItem(REFRESH_TOKEN);
  if (!refresh) return null;
  if (!refreshPromise) {
    refreshPromise = fetch(`${API_URL}/api/token/refresh/`, {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({ refresh }),
    }).then(async (response) => {
      if (!response.ok) return null;
      const result = await response.json();
      if (result.access) localStorage.setItem(ACCESS_TOKEN, result.access);
      if (result.refresh) localStorage.setItem(REFRESH_TOKEN, result.refresh);
      return result.access || null;
    }).catch(() => null).finally(() => { refreshPromise = null; });
  }
  return refreshPromise;
}

function expireSession() {
  localStorage.removeItem(ACCESS_TOKEN);
  localStorage.removeItem(REFRESH_TOKEN);
  window.dispatchEvent(new Event("auth:expired"));
}

async function request(path, { method = "GET", token, body, download = false } = {}) {
  const headers = { Accept: "application/json" };

  if (token) {
    headers.Authorization = `Bearer ${localStorage.getItem(ACCESS_TOKEN) || token}`;
  }

  const isForm = body instanceof FormData;
  if (body !== undefined && !isForm) {
    headers["Content-Type"] = "application/json";
  }

  let response;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 60000);

  try {
    const options = {
      method,
      headers,
      body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
      signal: controller.signal,
    };
    response = await fetch(`${API_URL}${path}`, options);
    if (response.status === 401 && token) {
      const renewed = await refreshAccessToken();
      if (renewed) {
        headers.Authorization = `Bearer ${renewed}`;
        response = await fetch(`${API_URL}${path}`, options);
        if (response.status === 401) expireSession();
      } else {
        expireSession();
      }
    }
  } catch (error) {
    throw new Error(error.name === "AbortError"
      ? "The server is taking too long to respond. Please try again shortly."
      : "Cannot reach the server. Please check your connection and try again.", { cause: error });
  } finally {
    clearTimeout(timeout);
  }

  if (response.ok && download) return response.blob();

  const data = response.status === 204
    ? null
    : await response.json().catch(() => null);

  if (!response.ok) {
    const flatten = (value) => Array.isArray(value)
      ? value.map(flatten).join(" ")
      : value && typeof value === "object"
        ? Object.values(value).map(flatten).join(" ")
        : String(value ?? "");
    // "detail" and "non_field_errors" are whole sentences already; anything else
    // is a field name worth showing next to its message.
    const bare = new Set(["detail", "non_field_errors"]);

    const message = (Array.isArray(data)
      ? flatten(data)
      : data && typeof data === "object"
        ? Object.entries(data)
            .map(([field, value]) => bare.has(field) ? flatten(value) : `${field}: ${flatten(value)}`)
            .join(" • ")
        : "") || `Request failed (${response.status}).`;

    const error = new Error(message);
    error.status = response.status;
    throw error;
  }

  return data;
}

export function loginUser(username, password) {
  return request("/api/token/", {
    method: "POST",
    body: { username, password },
  });
}

export function fetchEmployees(token) {
  return request("/api/employees/", { token });
}

export function saveEmployee(token, employee, id) {
  return request(id ? `/api/employees/${id}/` : "/api/employees/", {
    method: id ? "PATCH" : "POST",
    token,
    body: employee,
  });
}

export function removeEmployee(token, id) {
  return request(`/api/employees/${id}/`, {
    method: "DELETE",
    token,
  });
}

export function fetchRecords(token, resource) {
  return request(`/api/${resource}/`, { token });
}

export function saveRecord(token, resource, record, id) {
  return request(`/api/${resource}/${id ? `${id}/` : ""}`, {
    method: id ? "PATCH" : "POST", token, body: record,
  });
}

export function deleteRecord(token, resource, id) {
  return request(`/api/${resource}/${id}/`, { method: "DELETE", token });
}

export function markSalaryPaid(token, id, body) {
  return request(`/api/salaries/${id}/mark_paid/`, { method: "POST", token, body });
}

export function fetchSalaryPaymentPreview(token, id, month) {
  return request(`/api/salaries/${id}/payment_preview/?${new URLSearchParams({ month })}`, { token });
}

export function fetchSalaryPaymentHistory(token, id) {
  return request(`/api/salaries/${id}/payment_history/`, { token });
}

export function fetchReports(token, date, days) {
  const query = new URLSearchParams({ date, days });
  return request(`/api/reports/?${query}`, { token });
}

export function downloadContract(token, id) {
  return request(`/api/contracts/${id}/document/`, { token, download: true });
}

export function sendContractForSignature(token, id) {
  return request(`/api/contracts/${id}/send-for-signature/`, { method: "POST", token });
}

export function resendContractSignatureEmail(token, id, body) {
  return request(`/api/contracts/${id}/resend-signature-email/`, { method: "POST", token, body });
}

export function requestNewContractSignature(token, id, body) {
  return request(`/api/contracts/${id}/request-new-signature/`, { method: "POST", token, body });
}

export function approveContractWorker(token, id) {
  return request(`/api/contracts/${id}/approve-worker/`, { method: "POST", token });
}

export function signupUser(account) {
  return request("/api/signup/", { method: "POST", body: account });
}

export function requestPasswordReset(identifier) {
  return request("/api/password-reset/", { method: "POST", body: { identifier } });
}

export function confirmPasswordReset(body) {
  return request("/api/password-reset/confirm/", { method: "POST", body });
}

export function fetchAccount(token) {
  return request("/api/account/", { token });
}

export function fetchEmailSettings(token) {
  return request("/api/account/email/", { token });
}

export function saveEmailSettings(token, body) {
  return request("/api/account/email/", { method: "PATCH", token, body });
}

export function fetchContractPreview(token, id) {
  return request(`/api/contracts/${id}/preview/`, { token, download: true });
}

export function fetchEmployeePhoto(token, id) {
  return request(`/api/employees/${id}/photo/`, { token, download: true });
}

export function changePassword(token, body) {
  return request("/api/account/password/", { method: "POST", token, body });
}

export function fetchMyProfile(token) {
  return request("/api/me/profile/", { token });
}

export function saveMyProfile(token, body) {
  return request("/api/me/profile/", { method: "PATCH", token, body });
}

export function fetchMyPhoto(token) {
  return request("/api/me/photo/", { token, download: true });
}

export function fetchMyAttendance(token) {
  return request("/api/me/attendance/", { token });
}

export function clockMyAttendance(token, action, shift = "day", time, position = null) {
  return request("/api/me/attendance/", { method: "POST", token, body: { action, shift, time, ...(position || {}) } });
}

export function fetchWorkplaceLocation(token) {
  return request("/api/workplace-location/", { token });
}

export function saveWorkplaceLocation(token, body) {
  return request("/api/workplace-location/", { method: "PUT", token, body });
}

export function updateWorkplaceRadius(token, radius_m) {
  return request("/api/workplace-location/", { method: "PATCH", token, body: { radius_m } });
}

export function fetchMyLeave(token) {
  return request("/api/me/leave/", { token });
}

export function submitMyLeave(token, body) {
  return request("/api/me/leave/", { method: "POST", token, body });
}

export function updateMyLeave(token, id, body) {
  return request(`/api/me/leave/${id}/`, { method: "PATCH", token, body });
}

export function cancelMyLeave(token, id) {
  return request(`/api/me/leave/${id}/`, { method: "DELETE", token });
}

export function fetchMyPayroll(token) {
  return request("/api/me/payroll/", { token });
}

export function requestMySalaryAdvance(token, body) {
  return request("/api/me/salary-advance-requests/", { method: "POST", token, body });
}

export function cancelMySalaryAdvanceRequest(token, id) {
  return request(`/api/me/salary-advance-requests/${id}/`, { method: "DELETE", token });
}

export function decideSalaryAdvanceRequest(token, id, decision, body = {}) {
  return request(`/api/salary-advance-requests/${id}/${decision}/`, { method: "POST", token, body });
}

export function fetchMyContracts(token) {
  return request("/api/me/contracts/", { token });
}

export function fetchMyAnnouncements(token) {
  return request("/api/me/announcements/", { token });
}

export function markMyAnnouncementRead(token, id) {
  return request(`/api/me/announcements/${id}/read/`, { method: "POST", token });
}

export function fetchMyCalendar(token) {
  return request("/api/me/calendar/", { token });
}

export function markMyCalendarEventRead(token, id) {
  return request(`/api/me/calendar/${id}/read/`, { method: "POST", token });
}

export function signMyContract(token, id, body) {
  return request(`/api/me/contracts/${id}/sign/`, { method: "POST", token, body });
}

export function requestMyContractTermination(token, id, body) {
  return request(`/api/me/contracts/${id}/termination/`, { method: "POST", token, body });
}

export function acknowledgeMyContractTermination(token, id) {
  return request(`/api/me/contracts/${id}/termination/acknowledge/`, { method: "POST", token });
}

export function initiateContractTermination(token, id, body) {
  return request(`/api/contracts/${id}/initiate-termination/`, { method: "POST", token, body });
}

export function decideContractTermination(token, id, body) {
  return request(`/api/contracts/${id}/termination-decision/`, { method: "POST", token, body });
}

export function fetchAdminOverview(token) {
  return request("/api/admin/overview/", { token });
}

export function fetchAdminActivity(token) {
  return request("/api/admin/activity/", { token });
}

export function fetchAdminCompanyActivity(token, id) {
  return request(`/api/admin/businesses/${id}/activity/`, { token });
}

export function fetchAdminEmployeeActivity(token, id) {
  return request(`/api/admin/employees/${id}/activity/`, { token });
}

export function fetchAdminRecords(token, resource, scope) {
  return request(`/api/admin/records/${resource}/?${new URLSearchParams(scope)}`, { token });
}

export function fetchAdminBusinesses(token) {
  return request("/api/admin/businesses/", { token });
}

export function fetchAdminEmployers(token) {
  return request("/api/admin/employers/", { token });
}

export function saveAdminEmployer(token, body, id) {
  return request(id ? `/api/admin/employers/${id}/` : "/api/admin/employers/", {
    method: id ? "PATCH" : "POST", token, body,
  });
}

// Companies are the only thing the platform admin deletes. An employer account
// is suspended through saveAdminEmployer({ is_active: false }) instead.
export function deleteAdminBusiness(token, id) {
  return request(`/api/admin/businesses/${id}/`, { method: "DELETE", token });
}

export function fetchAdminEmployees(token) {
  return request("/api/admin/employees/", { token });
}

export function saveAdminEmployee(token, body, id) {
  return request(id ? `/api/admin/employees/${id}/` : "/api/admin/employees/", {
    method: id ? "PATCH" : "POST", token, body,
  });
}

export function deleteAdminEmployee(token, id) {
  return request(`/api/admin/employees/${id}/`, { method: "DELETE", token });
}

// Platform conversation: the administrator and one company, both directions.
export function fetchAdminThreads(token) {
  return request("/api/admin/messages/", { token });
}

export function fetchAdminThread(token, business) {
  return request(`/api/admin/messages/${business}/`, { token });
}

export function sendAdminMessage(token, business, body, channel) {
  return request(`/api/admin/messages/${business}/`, { method: "POST", token, body: { body, channel } });
}

export function markAdminThreadRead(token, business) {
  return request(`/api/admin/messages/${business}/read/`, { method: "POST", token });
}

export function fetchCompanyThread(token) {
  return request("/api/messages/", { token });
}

export function sendCompanyMessage(token, body, channel) {
  return request("/api/messages/", { method: "POST", token, body: { body, channel } });
}

export function markCompanyThreadRead(token) {
  return request("/api/messages/read/", { method: "POST", token });
}

export function fetchAdminHealth(token) {
  return request("/api/admin/health/", { token });
}

export function saveCompanyStatus(token, business, status) {
  return request(`/api/admin/businesses/${business}/`, { method: "PATCH", token, body: { status } });
}

// Clearing a badge in one go, for when there are too many to open one by one.
// None of these delete anything: they only mark what is already there as read.
export function markAllMyAnnouncementsRead(token) {
  return request("/api/me/announcements/read-all/", { method: "POST", token });
}

export function markAllMyCalendarRead(token) {
  return request("/api/me/calendar/read-all/", { method: "POST", token });
}

export function markAllAdminThreadsRead(token) {
  return request("/api/admin/messages/read-all/", { method: "POST", token });
}

// Payroll extensions: salary advances and asset misuse. They sit beside the
// existing payroll endpoints.
export function calculatePayroll(token, payroll, otherDeductions) {
  const body = { payroll };
  if (otherDeductions !== undefined && otherDeductions !== "") body.other_deductions = otherDeductions;
  return request("/api/payroll-calculations/", { method: "POST", token, body });
}

export function addAdvanceRepayment(token, id, body) {
  return request(`/api/salary-advances/${id}/repayments/`, { method: "POST", token, body });
}

export function fetchAssetSummary(token) {
  return request("/api/asset-incidents/summary/", { token });
}

// Smart room access control. Unlocking always goes through the server, which
// checks the permission and asks the door hardware integration to open the door.
export function fetchAccessRecords(token, resource, query = {}) {
  return request(`/api/access-control/${resource}/?${new URLSearchParams(query)}`, { token });
}

export function saveRoom(token, body, id) {
  return request(`/api/access-control/rooms/${id ? `${id}/` : ""}`, { method: id ? "PATCH" : "POST", token, body });
}

export function deleteRoom(token, id) {
  return request(`/api/access-control/rooms/${id}/`, { method: "DELETE", token });
}

export function grantRoomAccess(token, room, email) {
  return request("/api/access-control/grants/", { method: "POST", token, body: { room, email } });
}

export function grantRoomAccessBulk(token, employees, rooms) {
  return request("/api/access-control/grants/bulk/", { method: "POST", token, body: { employees, rooms } });
}

export function revokeRoomAccess(token, id) {
  return request(`/api/access-control/grants/${id}/`, { method: "DELETE", token });
}

export function unlockRoom(token, id, body) {
  return request(`/api/access-control/rooms/${id}/unlock/`, { method: "POST", token, body });
}

export function startDoorSimulator(token, room) {
  return request(`/api/access-control/simulator/${room}/`, { method: "POST", token });
}

export function fetchDoorSimulator(token, room) {
  return request(`/api/access-control/simulator/${room}/`, { token });
}

export function stopDoorSimulator(token, room) {
  return request(`/api/access-control/simulator/${room}/`, { method: "DELETE", token });
}

export function fetchMyRooms(token) {
  return request("/api/me/rooms/", { token });
}

export function fetchMyAccessHistory(token) {
  return request("/api/me/access-history/", { token });
}

export function downloadEvidence(token, resource, id) {
  return request(`/api/${resource}/${id}/evidence/`, { token, download: true });
}