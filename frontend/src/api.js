// Development requests use Vite's API proxy; deployments can set VITE_API_URL.
const API_URL = (
  import.meta.env.DEV ? "" : import.meta.env.VITE_API_URL || "http://127.0.0.1:8000"
).replace(/\/$/, "");

async function request(path, { method = "GET", token, body, download = false } = {}) {
  const headers = { Accept: "application/json" };

  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const isForm = body instanceof FormData;
  if (body !== undefined && !isForm) {
    headers["Content-Type"] = "application/json";
  }

  let response;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 60000);

  try {
    response = await fetch(`${API_URL}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
      signal: controller.signal,
    });
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
    const flatten = (value) => Array.isArray(value) ? value.map(flatten).join(" ") : String(value ?? "");
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

export function clockMyAttendance(token, action) {
  return request("/api/me/attendance/", { method: "POST", token, body: { action } });
}

export function fetchMyLeave(token) {
  return request("/api/me/leave/", { token });
}

export function submitMyLeave(token, body) {
  return request("/api/me/leave/", { method: "POST", token, body });
}

export function cancelMyLeave(token, id) {
  return request(`/api/me/leave/${id}/`, { method: "DELETE", token });
}

export function fetchMyContracts(token) {
  return request("/api/me/contracts/", { token });
}

export function signMyContract(token, id, body) {
  return request(`/api/me/contracts/${id}/sign/`, { method: "POST", token, body });
}

export function fetchAdminOverview(token) {
  return request("/api/admin/overview/", { token });
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

export function deleteAdminEmployer(token, id) {
  return request(`/api/admin/employers/${id}/`, { method: "DELETE", token });
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
