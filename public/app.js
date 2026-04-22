const state = {
  publicSnapshot: {
    company: "UTown",
    today: new Date().toISOString().slice(0, 10),
    ownerLoginId: "owner",
    employeeCount: 0,
    requests: [],
  },
  adminSnapshot: null,
  employeeSession: null,
  selectedMonth: "",
  ownerLoginId: localStorage.getItem("utownOwnerLoginId") || "",
  ownerPassword: localStorage.getItem("utownOwnerPassword") || "",
  ownerUnlocked: false,
  employeeLoginId: localStorage.getItem("utownEmployeeLoginId") || "",
  employeePassword: "",
  latestCredentials: null,
};

const elements = {
  employeeCount: document.querySelector("#employeeCount"),
  approvedCount: document.querySelector("#approvedCount"),
  pendingCount: document.querySelector("#pendingCount"),
  employeeAccessForm: document.querySelector("#employeeAccessForm"),
  employeeLoginId: document.querySelector("#employeeLoginId"),
  employeePassword: document.querySelector("#employeePassword"),
  employeeLoginButton: document.querySelector("#employeeLoginButton"),
  employeeLogoutButton: document.querySelector("#employeeLogoutButton"),
  leaveDate: document.querySelector("#leaveDate"),
  employeeIdentity: document.querySelector("#employeeIdentity"),
  employeeRequestList: document.querySelector("#employeeRequestList"),
  monthSelect: document.querySelector("#monthSelect"),
  calendarGrid: document.querySelector("#calendarGrid"),
  monthRequestList: document.querySelector("#monthRequestList"),
  ownerLoginForm: document.querySelector("#ownerLoginForm"),
  ownerLoginId: document.querySelector("#ownerLoginId"),
  ownerPassword: document.querySelector("#ownerPassword"),
  ownerContent: document.querySelector("#ownerContent"),
  ownerLogoutButton: document.querySelector("#ownerLogoutButton"),
  ownerIdentity: document.querySelector("#ownerIdentity"),
  ownerCredentialsForm: document.querySelector("#ownerCredentialsForm"),
  newOwnerLoginId: document.querySelector("#newOwnerLoginId"),
  newOwnerPassword: document.querySelector("#newOwnerPassword"),
  employeeForm: document.querySelector("#employeeForm"),
  employeeName: document.querySelector("#employeeName"),
  employeePasswordInput: document.querySelector("#employeePasswordInput"),
  generatedCredentials: document.querySelector("#generatedCredentials"),
  pendingRequestList: document.querySelector("#pendingRequestList"),
  employeeAdminList: document.querySelector("#employeeAdminList"),
  ownerRequestList: document.querySelector("#ownerRequestList"),
  toast: document.querySelector("#toast"),
};

const weekdayNames = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

document.addEventListener("DOMContentLoaded", async () => {
  elements.employeeLoginId.value = state.employeeLoginId;
  elements.ownerLoginId.value = state.ownerLoginId;
  elements.ownerPassword.value = state.ownerPassword;
  bindEvents();
  await refreshState();
  await restoreOwnerSession();
  await refreshState();
  setInterval(refreshState, 5000);
});

function bindEvents() {
  elements.employeeAccessForm.addEventListener("submit", submitLeaveRequest);
  elements.employeeLoginButton.addEventListener("click", loadEmployeeSession);
  elements.employeeLogoutButton.addEventListener("click", logoutEmployee);
  elements.monthSelect.addEventListener("change", () => {
    state.selectedMonth = elements.monthSelect.value;
    renderBoard();
  });

  elements.ownerLoginForm.addEventListener("submit", verifyOwnerLogin);
  elements.ownerLogoutButton.addEventListener("click", logoutOwner);
  elements.ownerCredentialsForm.addEventListener("submit", updateOwnerCredentials);
  elements.employeeForm.addEventListener("submit", addEmployee);
}

async function refreshState() {
  try {
    const snapshot = await api("/api/state");
    state.publicSnapshot = snapshot;

    if (!state.ownerLoginId) {
      state.ownerLoginId = snapshot.ownerLoginId;
      elements.ownerLoginId.value = state.ownerLoginId;
    }

    const monthKeys = availableMonthKeys(snapshot.requests, snapshot.today);
    if (!state.selectedMonth || !monthKeys.includes(state.selectedMonth)) {
      state.selectedMonth = monthKeys.includes(snapshot.today.slice(0, 7)) ? snapshot.today.slice(0, 7) : monthKeys[0];
    }

    if (state.ownerUnlocked) {
      await fetchAdminState();
    } else {
      state.adminSnapshot = null;
    }

    if (state.employeeSession && state.employeePassword) {
      await refreshEmployeeSession(true);
    }

    render();
  } catch (error) {
    showToast(error.message || "Unable to refresh the leave tracker right now.", true);
  }
}

async function restoreOwnerSession() {
  if (!state.ownerPassword) {
    renderOwnerState();
    return;
  }

  try {
    await api("/api/admin/verify", {
      method: "POST",
      body: {
        loginId: state.ownerLoginId,
        password: state.ownerPassword,
      },
    });
    state.ownerUnlocked = true;
  } catch (error) {
    state.ownerUnlocked = false;
    state.ownerPassword = "";
    localStorage.removeItem("utownOwnerPassword");
    elements.ownerPassword.value = "";
  }

  renderOwnerState();
}

async function fetchAdminState() {
  const adminSnapshot = await api("/api/admin/state", {
    method: "GET",
    admin: true,
  });
  state.adminSnapshot = adminSnapshot;
}

async function refreshEmployeeSession(silent = false) {
  if (!state.employeeLoginId || !state.employeePassword) {
    state.employeeSession = null;
    return;
  }

  try {
    const response = await api("/api/employee/session", {
      method: "POST",
      body: {
        loginId: state.employeeLoginId,
        password: state.employeePassword,
      },
    });
    state.employeeSession = response.session;
  } catch (error) {
    state.employeeSession = null;
    if (!silent) {
      showToast(error.message || "Employee sign-in failed.", true);
    }
  }
}

function render() {
  renderSummary();
  renderBoard();
  renderEmployeeSection();
  renderOwnerState();
}

function renderSummary() {
  const approvedCount = state.publicSnapshot.requests.filter((request) => request.status === "approved").length;
  const pendingCount = state.publicSnapshot.requests.filter((request) => request.status === "pending").length;

  elements.employeeCount.textContent = String(state.publicSnapshot.employeeCount);
  elements.approvedCount.textContent = String(approvedCount);
  elements.pendingCount.textContent = String(pendingCount);
}

function renderBoard() {
  renderMonthSelect();
  renderCalendar();
  renderMonthRequestList();
}

function renderMonthSelect() {
  const monthKeys = availableMonthKeys(state.publicSnapshot.requests, state.publicSnapshot.today);
  const options = monthKeys.map((monthKey) => new Option(formatMonthKey(monthKey), monthKey));
  elements.monthSelect.replaceChildren(...options);
  elements.monthSelect.value = state.selectedMonth;
}

function renderCalendar() {
  const monthKey = state.selectedMonth;
  if (!monthKey) {
    elements.calendarGrid.innerHTML = '<div class="empty-state">Pick a month to view the leave board.</div>';
    return;
  }

  const [year, month] = monthKey.split("-").map(Number);
  const firstDay = new Date(year, month - 1, 1);
  const daysInMonth = new Date(year, month, 0).getDate();
  const today = state.publicSnapshot.today;

  const items = weekdayNames.map((day) => {
    const label = document.createElement("div");
    label.className = "calendar-weekday";
    label.textContent = day;
    return label;
  });

  for (let index = 0; index < firstDay.getDay(); index += 1) {
    const filler = document.createElement("div");
    filler.className = "calendar-card empty";
    items.push(filler);
  }

  for (let day = 1; day <= daysInMonth; day += 1) {
    const isoDate = `${monthKey}-${String(day).padStart(2, "0")}`;
    const request = state.publicSnapshot.requests.find((entry) => entry.date === isoDate);
    const weekday = new Date(year, month - 1, day).getDay();
    const isWeekend = weekday === 0 || weekday === 6;
    const isToday = isoDate === today;

    const card = document.createElement("div");
    card.className = [
      "calendar-card",
      isWeekend ? "weekend-card" : "",
      request?.status === "approved" ? "approved-card" : "",
      request?.status === "pending" ? "pending-card" : "",
      isToday ? "today-card" : "",
    ]
      .filter(Boolean)
      .join(" ");

    const heading = document.createElement("div");
    const number = document.createElement("strong");
    number.textContent = String(day);
    const label = document.createElement("small");

    if (isWeekend) {
      label.textContent = "Weekend";
    } else if (request) {
      label.textContent = request.status === "approved" ? "Approved" : "Pending";
    } else {
      label.textContent = "Available";
    }

    heading.append(number, label);

    const content = document.createElement("p");
    if (request) {
      content.textContent = `${request.employeeName} • ${request.status}`;
    } else if (isWeekend) {
      content.textContent = "No leave allowed.";
    } else {
      content.textContent = "Open for requests";
    }

    card.append(heading, content);
    items.push(card);
  }

  elements.calendarGrid.replaceChildren(...items);
}

function renderMonthRequestList() {
  const monthRequests = state.publicSnapshot.requests.filter((request) => request.date.startsWith(state.selectedMonth));

  if (!monthRequests.length) {
    elements.monthRequestList.innerHTML =
      '<div class="empty-state compact">No leave requests in this month yet.</div>';
    return;
  }

  const list = document.createElement("div");
  list.className = "leave-list";

  monthRequests.forEach((request) => {
    list.append(createRequestRow(request));
  });

  elements.monthRequestList.replaceChildren(list);
}

function renderEmployeeSection() {
  if (!state.employeeSession) {
    elements.employeeIdentity.innerHTML =
      '<div class="empty-state compact">Sign in with an employee ID and password to view your own requests.</div>';
    elements.employeeRequestList.innerHTML =
      '<div class="empty-state compact">No employee session loaded yet.</div>';
    return;
  }

  const employee = state.employeeSession.employee;
  elements.employeeIdentity.innerHTML = `
    <div class="identity-card">
      <strong>${escapeHtml(employee.name)}</strong>
      <p>Employee ID: ${escapeHtml(employee.loginId)}</p>
    </div>
  `;

  if (!state.employeeSession.requests.length) {
    elements.employeeRequestList.innerHTML =
      '<div class="empty-state compact">This employee has not created any leave request yet.</div>';
    return;
  }

  const list = document.createElement("div");
  list.className = "leave-list";

  state.employeeSession.requests.forEach((request) => {
    const row = createRequestRow(request);
    if (request.status !== "rejected") {
      const actions = document.createElement("div");
      actions.className = "row-actions";
      const cancelButton = document.createElement("button");
      cancelButton.className = "ghost-button";
      cancelButton.type = "button";
      cancelButton.textContent = "Cancel";
      cancelButton.addEventListener("click", () => cancelEmployeeRequest(request.id));
      actions.append(cancelButton);
      row.append(actions);
    }
    list.append(row);
  });

  elements.employeeRequestList.replaceChildren(list);
}

function renderOwnerState() {
  const isUnlocked = state.ownerUnlocked;
  elements.ownerContent.classList.toggle("hidden", !isUnlocked);
  elements.ownerLoginForm.classList.toggle("hidden", isUnlocked);

  if (!isUnlocked) {
    return;
  }

  const ownerLoginId = state.adminSnapshot?.ownerLoginId || state.publicSnapshot.ownerLoginId || state.ownerLoginId;
  elements.ownerIdentity.innerHTML = `
    <div class="identity-card">
      <strong>Current owner login</strong>
      <p>${escapeHtml(ownerLoginId)}</p>
    </div>
  `;

  if (!elements.newOwnerLoginId.value) {
    elements.newOwnerLoginId.value = ownerLoginId;
  }

  renderLatestCredentials();
  renderPendingRequests();
  renderEmployeeAdminList();
  renderOwnerRequestList();
}

function renderLatestCredentials() {
  if (!state.latestCredentials) {
    elements.generatedCredentials.innerHTML =
      '<div class="empty-state compact">Newly generated employee credentials will appear here for handover.</div>';
    return;
  }

  const credentials = state.latestCredentials;
  elements.generatedCredentials.innerHTML = `
    <div class="credential-card">
      <strong>${escapeHtml(credentials.name)}</strong>
      <p>Employee ID: <span>${escapeHtml(credentials.loginId)}</span></p>
      <p>Password: <span>${escapeHtml(credentials.password)}</span></p>
      <small>Share these credentials with the employee or the business owner.</small>
    </div>
  `;
}

function renderPendingRequests() {
  const requests = state.adminSnapshot?.requests.filter((request) => request.status === "pending") || [];

  if (!requests.length) {
    elements.pendingRequestList.innerHTML =
      '<div class="empty-state compact">No pending leave requests right now.</div>';
    return;
  }

  const list = document.createElement("div");
  list.className = "leave-list";

  requests.forEach((request) => {
    const row = createRequestRow(request);
    const actions = document.createElement("div");
    actions.className = "row-actions";

    const approveButton = document.createElement("button");
    approveButton.className = "primary-button";
    approveButton.type = "button";
    approveButton.textContent = "Approve";
    approveButton.addEventListener("click", () => reviewRequest(request.id, "approve"));

    const rejectButton = document.createElement("button");
    rejectButton.className = "ghost-button";
    rejectButton.type = "button";
    rejectButton.textContent = "Disapprove";
    rejectButton.addEventListener("click", () => reviewRequest(request.id, "reject"));

    actions.append(approveButton, rejectButton);
    row.append(actions);
    list.append(row);
  });

  elements.pendingRequestList.replaceChildren(list);
}

function renderEmployeeAdminList() {
  const employees = state.adminSnapshot?.employees || [];
  if (!employees.length) {
    elements.employeeAdminList.innerHTML =
      '<div class="empty-state compact">No employees added yet.</div>';
    return;
  }

  const list = document.createElement("div");
  list.className = "employee-admin-list";

  employees.forEach((employee) => {
    const row = document.createElement("div");
    row.className = "employee-row";
    row.innerHTML = `
      <div>
        <strong>${escapeHtml(employee.name)}</strong>
        <p>Employee ID: ${escapeHtml(employee.loginId)} • ${employee.active ? "Active" : "Inactive"}</p>
      </div>
    `;

    const actions = document.createElement("div");
    actions.className = "row-actions";

    const resetButton = document.createElement("button");
    resetButton.className = "ghost-button";
    resetButton.type = "button";
    resetButton.textContent = "Reset Password";
    resetButton.addEventListener("click", () => resetEmployeePassword(employee.id));

    const toggleButton = document.createElement("button");
    toggleButton.className = "ghost-button";
    toggleButton.type = "button";
    toggleButton.textContent = employee.active ? "Deactivate" : "Reactivate";
    toggleButton.addEventListener("click", () => toggleEmployeeStatus(employee.id, !employee.active));

    actions.append(resetButton, toggleButton);
    row.append(actions);
    list.append(row);
  });

  elements.employeeAdminList.replaceChildren(list);
}

function renderOwnerRequestList() {
  const requests = state.adminSnapshot?.requests || [];
  if (!requests.length) {
    elements.ownerRequestList.innerHTML =
      '<div class="empty-state compact">No leave activity yet.</div>';
    return;
  }

  const list = document.createElement("div");
  list.className = "leave-list";

  requests.forEach((request) => {
    list.append(createRequestRow(request, true));
  });

  elements.ownerRequestList.replaceChildren(list);
}

function createRequestRow(request, includeEmployeeId = false) {
  const row = document.createElement("div");
  row.className = "leave-row";

  const details = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = request.employeeName || state.employeeSession?.employee?.name || "Leave request";

  const meta = document.createElement("p");
  const parts = [formatLongDate(request.date)];
  if (includeEmployeeId && request.employeeLoginId) {
    parts.push(`Employee ID: ${request.employeeLoginId}`);
  }
  meta.textContent = parts.join(" • ");

  details.append(title, meta);

  const statusWrap = document.createElement("div");
  statusWrap.className = "row-actions";
  statusWrap.append(createStatusBadge(request.status));

  row.append(details, statusWrap);
  return row;
}

function createStatusBadge(status) {
  const badge = document.createElement("span");
  badge.className = `status-badge status-${status}`;
  badge.textContent = capitalize(status);
  return badge;
}

async function loadEmployeeSession() {
  const loginId = elements.employeeLoginId.value.trim();
  const password = elements.employeePassword.value;

  if (!loginId || !password) {
    showToast("Enter both employee ID and password first.", true);
    return;
  }

  state.employeeLoginId = loginId;
  state.employeePassword = password;
  localStorage.setItem("utownEmployeeLoginId", loginId);

  await refreshEmployeeSession();
  if (state.employeeSession) {
    renderEmployeeSection();
    showToast("Employee session loaded.");
  }
}

function logoutEmployee() {
  state.employeePassword = "";
  state.employeeSession = null;
  state.employeeLoginId = "";
  localStorage.removeItem("utownEmployeeLoginId");
  elements.employeeLoginId.value = "";
  elements.employeePassword.value = "";
  renderEmployeeSection();
  showToast("Employee session removed from this browser.");
}

async function submitLeaveRequest(event) {
  event.preventDefault();
  const loginId = elements.employeeLoginId.value.trim();
  const password = elements.employeePassword.value;
  const date = elements.leaveDate.value;

  if (!loginId || !password || !date) {
    showToast("Fill in employee ID, password, and leave date.", true);
    return;
  }

  try {
    const response = await api("/api/employee/requests", {
      method: "POST",
      body: {
        loginId,
        password,
        date,
      },
    });

    state.employeeLoginId = loginId;
    state.employeePassword = password;
    localStorage.setItem("utownEmployeeLoginId", loginId);
    await refreshState();
    showToast(
      response.request.action === "updated"
        ? "Leave request updated and sent back for approval."
        : "Leave request submitted."
    );
  } catch (error) {
    showToast(error.message || "Unable to submit the leave request.", true);
  }
}

async function cancelEmployeeRequest(requestId) {
  try {
    await api("/api/employee/requests/cancel", {
      method: "POST",
      body: {
        loginId: state.employeeLoginId,
        password: state.employeePassword,
        requestId,
      },
    });
    await refreshState();
    showToast("Leave request cancelled.");
  } catch (error) {
    showToast(error.message || "Unable to cancel that request.", true);
  }
}

async function verifyOwnerLogin(event) {
  event.preventDefault();
  const loginId = elements.ownerLoginId.value.trim();
  const password = elements.ownerPassword.value;

  try {
    const response = await api("/api/admin/verify", {
      method: "POST",
      body: { loginId, password },
    });
    state.ownerLoginId = response.ownerLoginId || loginId;
    state.ownerPassword = password;
    state.ownerUnlocked = true;
    localStorage.setItem("utownOwnerLoginId", state.ownerLoginId);
    localStorage.setItem("utownOwnerPassword", password);
    await refreshState();
    showToast("Owner panel unlocked.");
  } catch (error) {
    showToast(error.message || "Owner login failed.", true);
  }
}

function logoutOwner() {
  state.ownerUnlocked = false;
  state.ownerPassword = "";
  state.adminSnapshot = null;
  localStorage.removeItem("utownOwnerPassword");
  elements.ownerPassword.value = "";
  renderOwnerState();
  showToast("Owner session removed from this browser.");
}

async function updateOwnerCredentials(event) {
  event.preventDefault();
  const loginId = elements.newOwnerLoginId.value.trim();
  const password = elements.newOwnerPassword.value;

  try {
    const response = await api("/api/admin/owner", {
      method: "POST",
      admin: true,
      body: { loginId, password },
    });

    state.ownerLoginId = response.owner.ownerLoginId;
    state.ownerPassword = password;
    localStorage.setItem("utownOwnerLoginId", state.ownerLoginId);
    localStorage.setItem("utownOwnerPassword", password);
    elements.ownerLoginId.value = state.ownerLoginId;
    elements.ownerPassword.value = password;
    elements.newOwnerPassword.value = "";
    await refreshState();
    showToast("Owner credentials updated.");
  } catch (error) {
    showToast(error.message || "Unable to update owner credentials.", true);
  }
}

async function addEmployee(event) {
  event.preventDefault();
  const name = elements.employeeName.value.trim();
  const password = elements.employeePasswordInput.value.trim();

  try {
    const response = await api("/api/admin/employees", {
      method: "POST",
      admin: true,
      body: { name, password },
    });
    state.latestCredentials = response.employee;
    elements.employeeName.value = "";
    elements.employeePasswordInput.value = "";
    await refreshState();
    showToast("Employee account created.");
  } catch (error) {
    showToast(error.message || "Unable to create the employee account.", true);
  }
}

async function resetEmployeePassword(employeeId) {
  try {
    const response = await api("/api/admin/employees/password/reset", {
      method: "POST",
      admin: true,
      body: { employeeId },
    });
    state.latestCredentials = response.employee;
    renderLatestCredentials();
    showToast("New employee password generated.");
  } catch (error) {
    showToast(error.message || "Unable to reset that employee password.", true);
  }
}

async function toggleEmployeeStatus(employeeId, active) {
  try {
    await api("/api/admin/employees/status", {
      method: "POST",
      admin: true,
      body: { employeeId, active },
    });
    await refreshState();
    showToast(active ? "Employee reactivated." : "Employee deactivated.");
  } catch (error) {
    showToast(error.message || "Unable to update employee status.", true);
  }
}

async function reviewRequest(requestId, action) {
  try {
    await api("/api/admin/requests/review", {
      method: "POST",
      admin: true,
      body: { requestId, action },
    });
    await refreshState();
    showToast(action === "approve" ? "Leave request approved." : "Leave request disapproved.");
  } catch (error) {
    showToast(error.message || "Unable to review that leave request.", true);
  }
}

async function api(url, options = {}) {
  const headers = {
    "Content-Type": "application/json",
  };

  if (options.admin) {
    headers["X-Admin-Login"] = state.ownerLoginId;
    headers["X-Admin-Password"] = state.ownerPassword;
  }

  const response = await fetch(url, {
    method: options.method || "GET",
    headers,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || "Request failed.");
  }
  return payload;
}

function availableMonthKeys(requests, todayIso) {
  const keys = new Set();
  const today = new Date(`${todayIso}T00:00:00`);

  for (let offset = 0; offset < 12; offset += 1) {
    const month = new Date(today.getFullYear(), today.getMonth() + offset, 1);
    keys.add(`${month.getFullYear()}-${String(month.getMonth() + 1).padStart(2, "0")}`);
  }

  requests.forEach((request) => keys.add(request.date.slice(0, 7)));
  return Array.from(keys).sort();
}

function formatMonthKey(monthKey) {
  if (!monthKey) {
    return "-";
  }

  const [year, month] = monthKey.split("-").map(Number);
  return new Intl.DateTimeFormat("en-US", {
    month: "long",
    year: "numeric",
  }).format(new Date(year, month - 1, 1));
}

function formatLongDate(isoDate) {
  const [year, month, day] = isoDate.split("-").map(Number);
  return new Intl.DateTimeFormat("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(year, month - 1, day));
}

function capitalize(value) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

let toastTimeout;
function showToast(message, isError = false) {
  elements.toast.textContent = message;
  elements.toast.classList.remove("hidden", "error");
  if (isError) {
    elements.toast.classList.add("error");
  }

  window.clearTimeout(toastTimeout);
  toastTimeout = window.setTimeout(() => {
    elements.toast.classList.add("hidden");
  }, 3200);
}
