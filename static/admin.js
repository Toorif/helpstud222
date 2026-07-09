const loginForm = document.querySelector("#admin-login-form");
const sessionCard = document.querySelector("#admin-session");
const sessionUsername = document.querySelector("#session-username");
const filtersForm = document.querySelector("#filters-form");
const statusNode = document.querySelector("#admin-status");
const requestList = document.querySelector("#request-list");
const emptyNode = document.querySelector("#admin-empty");
const reviewAdminList = document.querySelector("#review-admin-list");
const reviewsEmptyNode = document.querySelector("#reviews-empty");
const workAdminForm = document.querySelector("#work-admin-form");
const workAdminList = document.querySelector("#work-admin-list");
const worksEmptyNode = document.querySelector("#works-empty");
const workFileInput = document.querySelector("#work-file-input");
const workAttachmentName = document.querySelector("#work-attachment-name");
const logoutButton = document.querySelector("#logout-button");
const changeUserButton = document.querySelector("#change-user-button");
const refreshButton = document.querySelector("#refresh-button");
const refreshReviewsButton = document.querySelector("#refresh-reviews-button");
const refreshWorksButton = document.querySelector("#refresh-works-button");
const resetFiltersButton = document.querySelector("#reset-filters-button");
const resetWorkFormButton = document.querySelector("#reset-work-form-button");
const taskTypeFilter = document.querySelector("#task-type-filter");
const reviewStatusFilter = document.querySelector("#review-status-filter");
const counterNode = document.querySelector("#admin-counter");
let pendingWorkAttachment = null;

function setAdminStatus(message, isError = false) {
  if (!statusNode) {
    return;
  }
  statusNode.textContent = message;
  statusNode.classList.toggle("is-error", isError);
}

function updateCounter(count) {
  if (!counterNode) {
    return;
  }
  const suffix = count === 1 ? "заявка" : count >= 2 && count <= 4 ? "заявки" : "заявок";
  counterNode.textContent = `${count} ${suffix}`;
}

function getStoredAuth() {
  return window.localStorage.getItem("adminAuth") || "";
}

function storeAuth(username, password) {
  const token = btoa(`${username}:${password}`);
  window.localStorage.setItem("adminAuth", token);
  window.localStorage.setItem("adminUser", username);
}

function clearAuth() {
  window.localStorage.removeItem("adminAuth");
  window.localStorage.removeItem("adminUser");
}

function getStoredUser() {
  return window.localStorage.getItem("adminUser") || "";
}

function setAuthorizedState(isAuthorized) {
  document.documentElement.classList.toggle("admin-authenticated", isAuthorized);
  if (loginForm) {
    loginForm.classList.toggle("is-hidden", isAuthorized);
  }
  if (sessionCard) {
    sessionCard.classList.toggle("is-hidden", !isAuthorized);
  }
  if (sessionUsername) {
    sessionUsername.textContent = getStoredUser() || "admin";
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function getFilterParams() {
  if (!filtersForm) {
    return new URLSearchParams();
  }
  const params = new URLSearchParams();
  const formData = new FormData(filtersForm);
  for (const [key, rawValue] of formData.entries()) {
    const value = String(rawValue).trim();
    if (value) {
      params.set(key, value);
    }
  }
  return params;
}

function collectTaskTypes(items) {
  if (!taskTypeFilter) {
    return;
  }
  const existingValue = taskTypeFilter.value;
  const uniqueTypes = [...new Set(items.map((item) => String(item.taskType || "").trim()).filter(Boolean))].sort((a, b) => a.localeCompare(b, "ru"));
  taskTypeFilter.innerHTML = '<option value="">Все типы</option>';
  uniqueTypes.forEach((type) => {
    const option = document.createElement("option");
    option.value = type;
    option.textContent = type;
    taskTypeFilter.appendChild(option);
  });
  taskTypeFilter.value = uniqueTypes.includes(existingValue) ? existingValue : "";
}

function renderRequests(items) {
  if (!requestList || !emptyNode) {
    return;
  }
  requestList.innerHTML = "";
  updateCounter(items.length);
  if (!items.length) {
    emptyNode.hidden = false;
    emptyNode.textContent = getStoredAuth()
      ? "По текущим фильтрам ничего не найдено."
      : "Войдите, чтобы увидеть заявки.";
    return;
  }
  emptyNode.hidden = true;
  items.forEach((item) => {
    const card = document.createElement("article");
    card.className = "request-card";
    card.innerHTML = `
      <div class="request-card-head">
        <div>
          <strong>Заявка #${escapeHtml(item.id)}</strong>
          <span>${escapeHtml(formatDate(item.createdAt))}</span>
        </div>
        <button class="button button-danger request-delete" type="button" data-request-id="${escapeHtml(item.id)}">Удалить</button>
      </div>
      <div class="request-grid">
        <p><span>Имя</span>${escapeHtml(item.name)}</p>
        <p><span>Контакт</span>${escapeHtml(item.contact)}</p>
        <p><span>Тип работы</span>${escapeHtml(item.taskType)}</p>
        <p><span>Антиплагиат</span>${escapeHtml(item.antiPlagiarism || "Не указан")}</p>
        <p><span>Дедлайн</span>${escapeHtml(item.deadline)}</p>
        <p><span>Аккаунт</span>${item.userId ? `ID ${escapeHtml(item.userId)}` : "Не связан"}</p>
      </div>
      <div class="request-details">
        <span>Описание</span>
        <p>${escapeHtml(item.details).replaceAll("\n", "<br>")}</p>
        ${item.attachment?.path ? `
          <a class="chat-attachment" href="${escapeHtml(item.attachment.path)}" target="_blank" rel="noopener noreferrer">
            <span>Вложение</span>
            <strong>${escapeHtml(item.attachment.name)}</strong>
          </a>
        ` : ""}
      </div>
    `;
    requestList.appendChild(card);
  });
}

function renderAdminReviews(items) {
  if (!reviewAdminList || !reviewsEmptyNode) {
    return;
  }
  reviewAdminList.innerHTML = "";
  if (!items.length) {
    reviewsEmptyNode.hidden = false;
    reviewsEmptyNode.textContent = getStoredAuth()
      ? "По текущему фильтру отзывов ничего не найдено."
      : "Войдите, чтобы увидеть отзывы.";
    return;
  }
  reviewsEmptyNode.hidden = true;
  items.forEach((item) => {
    const actions = [];
    actions.push(`<button class="button button-secondary review-save" type="button" data-review-id="${escapeHtml(item.id)}">Сохранить</button>`);
    if (item.status !== "approved") {
      actions.push(`<button class="button button-primary review-approve" type="button" data-review-id="${escapeHtml(item.id)}">Одобрить</button>`);
    }
    if (item.status !== "rejected") {
      actions.push(`<button class="button button-secondary review-reject" type="button" data-review-id="${escapeHtml(item.id)}">Отклонить</button>`);
    }
    actions.push(`<button class="button button-danger review-delete" type="button" data-review-id="${escapeHtml(item.id)}">Удалить</button>`);

    const card = document.createElement("article");
    card.className = "request-card";
    card.dataset.reviewId = String(item.id);
    card.innerHTML = `
      <div class="request-card-head">
        <div>
          <strong>Отзыв #${escapeHtml(item.id)}</strong>
          <span>${escapeHtml(formatDate(item.createdAt))}</span>
        </div>
        <span class="review-status review-status-${escapeHtml(item.status)}">${escapeHtml(item.status)}</span>
      </div>
      <div class="request-grid">
        <label class="review-edit-field">
          <span>Имя</span>
          <input class="review-edit-input" type="text" name="name" value="${escapeHtml(item.name)}">
        </label>
        <label class="review-edit-field">
          <span>Подпись</span>
          <input class="review-edit-input" type="text" name="role" value="${escapeHtml(item.role)}">
        </label>
      </div>
      <label class="request-details review-edit-field">
        <span>Текст</span>
        <textarea class="review-edit-textarea" name="text" rows="5">${escapeHtml(item.text)}</textarea>
      </label>
      <div class="admin-actions review-actions">${actions.join("")}</div>
    `;
    reviewAdminList.appendChild(card);
  });
}

function renderAdminWorks(items) {
  if (!workAdminList || !worksEmptyNode) {
    return;
  }
  workAdminList.innerHTML = "";
  if (!items.length) {
    worksEmptyNode.hidden = false;
    worksEmptyNode.textContent = getStoredAuth()
      ? "Работы пока не добавлены."
      : "Войдите, чтобы увидеть работы.";
    return;
  }
  worksEmptyNode.hidden = true;
  items.forEach((item) => {
    const card = document.createElement("article");
    card.className = "request-card";
    card.innerHTML = `
      <div class="request-card-head">
        <div>
          <strong>${escapeHtml(item.title)}</strong>
          <span>${escapeHtml(item.workType)} · ${escapeHtml(item.subject)}</span>
        </div>
        <span class="review-status ${item.published ? "review-status-approved" : "review-status-pending"}">
          ${item.published ? "published" : "draft"}
        </span>
      </div>
      <div class="request-grid">
        <p><span>Оригинальность</span>${escapeHtml(item.originality || "Не указана")}</p>
        <p><span>Теги</span>${escapeHtml(item.tags || "Без тегов")}</p>
      </div>
      <div class="request-details">
        <span>Описание</span>
        <p>${escapeHtml(item.description).replaceAll("\n", "<br>")}</p>
        ${item.attachment?.path ? `
          <a class="chat-attachment" href="${escapeHtml(item.attachment.path)}" target="_blank" rel="noopener noreferrer">
            <span>Файл работы</span>
            <strong>${escapeHtml(item.attachment.name)}</strong>
          </a>
        ` : ""}
      </div>
      <div class="admin-actions review-actions">
        <button class="button button-secondary work-edit" type="button" data-work-id="${escapeHtml(item.id)}">Редактировать</button>
        <button class="button button-danger work-delete" type="button" data-work-id="${escapeHtml(item.id)}">Удалить</button>
      </div>
    `;
    card.dataset.workPayload = JSON.stringify(item);
    workAdminList.appendChild(card);
  });
}

async function fetchAdminJson(url, options = {}) {
  const auth = getStoredAuth();
  if (!auth) {
    throw new Error("Сначала выполните вход.");
  }
  const response = await fetch(url, {
    ...options,
    headers: {
      ...(options.headers || {}),
      Authorization: `Basic ${auth}`,
    },
  });
  const result = await response.json();
  if (!response.ok) {
    throw new Error(result.message || "Не удалось выполнить запрос.");
  }
  return result;
}

async function loadRequests() {
  const auth = getStoredAuth();
  if (!auth) {
    setAuthorizedState(false);
    renderRequests([]);
    setAdminStatus("Введите логин и пароль администратора.");
    return;
  }
  setAuthorizedState(true);
  setAdminStatus("Загружаю заявки...");
  try {
    const params = getFilterParams();
    const suffix = params.toString() ? `?${params.toString()}` : "";
    const result = await fetchAdminJson(`/api/requests${suffix}`);
    renderRequests(result.items || []);
    collectTaskTypes(result.items || []);
    setAdminStatus(`Заявки загружены: ${result.items.length}.`);
  } catch (error) {
    renderRequests([]);
    clearAuth();
    setAuthorizedState(false);
    setAdminStatus(error instanceof Error ? error.message : "Ошибка соединения.", true);
  }
}

async function loadAdminReviews() {
  if (!getStoredAuth()) {
    renderAdminReviews([]);
    return;
  }
  try {
    const params = new URLSearchParams();
    if (reviewStatusFilter && reviewStatusFilter.value) {
      params.set("status", reviewStatusFilter.value);
    }
    const suffix = params.toString() ? `?${params.toString()}` : "";
    const result = await fetchAdminJson(`/api/admin/reviews${suffix}`);
    renderAdminReviews(result.items || []);
  } catch (error) {
    renderAdminReviews([]);
    setAdminStatus(error instanceof Error ? error.message : "Ошибка загрузки отзывов.", true);
  }
}

async function loadAdminWorks() {
  if (!getStoredAuth()) {
    renderAdminWorks([]);
    return;
  }
  try {
    const result = await fetchAdminJson("/api/admin/works");
    renderAdminWorks(result.items || []);
  } catch (error) {
    renderAdminWorks([]);
    setAdminStatus(error instanceof Error ? error.message : "Ошибка загрузки работ.", true);
  }
}

async function deleteRequest(requestId) {
  const confirmed = window.confirm(`Удалить заявку #${requestId}? Это действие нельзя отменить.`);
  if (!confirmed) {
    return;
  }
  setAdminStatus(`Удаляю заявку #${requestId}...`);
  try {
    const result = await fetchAdminJson(`/api/requests/${requestId}`, { method: "DELETE" });
    setAdminStatus(result.message);
    await loadRequests();
  } catch (error) {
    setAdminStatus(error instanceof Error ? error.message : "Ошибка соединения.", true);
  }
}

async function moderateReview(reviewId, action) {
  const label = action === "approve" ? "одобряю" : "отклоняю";
  setAdminStatus(`${label.charAt(0).toUpperCase() + label.slice(1)} отзыв #${reviewId}...`);
  try {
    const result = await fetchAdminJson(`/api/admin/reviews/${reviewId}/${action}`, { method: "POST" });
    setAdminStatus(result.message);
    await loadAdminReviews();
  } catch (error) {
    setAdminStatus(error instanceof Error ? error.message : "Ошибка соединения.", true);
  }
}

function getReviewPayload(card) {
  const nameInput = card.querySelector('input[name="name"]');
  const roleInput = card.querySelector('input[name="role"]');
  const textInput = card.querySelector('textarea[name="text"]');
  return {
    name: nameInput instanceof HTMLInputElement ? nameInput.value.trim() : "",
    role: roleInput instanceof HTMLInputElement ? roleInput.value.trim() : "",
    text: textInput instanceof HTMLTextAreaElement ? textInput.value.trim() : "",
  };
}

async function saveReview(reviewId, card) {
  setAdminStatus(`Сохраняю отзыв #${reviewId}...`);
  try {
    const payload = getReviewPayload(card);
    const result = await fetchAdminJson(`/api/admin/reviews/${reviewId}`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
    setAdminStatus(result.message);
    await loadAdminReviews();
  } catch (error) {
    setAdminStatus(error instanceof Error ? error.message : "Ошибка соединения.", true);
  }
}

async function deleteReview(reviewId) {
  const confirmed = window.confirm(`Удалить отзыв #${reviewId}? Это действие нельзя отменить.`);
  if (!confirmed) {
    return;
  }
  setAdminStatus(`Удаляю отзыв #${reviewId}...`);
  try {
    const result = await fetchAdminJson(`/api/admin/reviews/${reviewId}`, { method: "DELETE" });
    setAdminStatus(result.message);
    await loadAdminReviews();
  } catch (error) {
    setAdminStatus(error instanceof Error ? error.message : "Ошибка соединения.", true);
  }
}

function getWorkPayload() {
  if (!workAdminForm) {
    return {};
  }
  const formData = new FormData(workAdminForm);
  const payload = {
    title: String(formData.get("title") || "").trim(),
    workType: String(formData.get("workType") || "").trim(),
    subject: String(formData.get("subject") || "").trim(),
    originality: String(formData.get("originality") || "").trim(),
    tags: String(formData.get("tags") || "").trim(),
    description: String(formData.get("description") || "").trim(),
    published: Boolean(formData.get("published")),
  };
  if (pendingWorkAttachment) {
    payload.attachment = pendingWorkAttachment;
  }
  return payload;
}

function attachmentLabel(file) {
  if (!file) {
    return "Файл не выбран";
  }
  const sizeKb = Math.max(1, Math.round(file.size / 1024));
  return `${file.name} · ${sizeKb} КБ`;
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || "");
      const contentBase64 = result.includes(",") ? result.split(",")[1] : result;
      resolve({
        name: file.name,
        contentType: file.type || "application/octet-stream",
        contentBase64,
      });
    };
    reader.onerror = () => reject(new Error("Не удалось прочитать файл."));
    reader.readAsDataURL(file);
  });
}

function resetWorkForm() {
  if (!workAdminForm) {
    return;
  }
  workAdminForm.reset();
  pendingWorkAttachment = null;
  if (workFileInput instanceof HTMLInputElement) {
    workFileInput.value = "";
  }
  if (workAttachmentName) {
    workAttachmentName.textContent = attachmentLabel(null);
  }
  const idInput = workAdminForm.querySelector('input[name="id"]');
  if (idInput instanceof HTMLInputElement) {
    idInput.value = "";
  }
  const publishedInput = workAdminForm.querySelector('input[name="published"]');
  if (publishedInput instanceof HTMLInputElement) {
    publishedInput.checked = true;
  }
}

function fillWorkForm(item) {
  if (!workAdminForm) {
    return;
  }
  const fields = ["id", "title", "workType", "subject", "originality", "tags", "description"];
  fields.forEach((field) => {
    const input = workAdminForm.querySelector(`[name="${field}"]`);
    if (input instanceof HTMLInputElement || input instanceof HTMLTextAreaElement) {
      input.value = String(item[field] || "");
    }
  });
  const publishedInput = workAdminForm.querySelector('input[name="published"]');
  if (publishedInput instanceof HTMLInputElement) {
    publishedInput.checked = Boolean(item.published);
  }
  pendingWorkAttachment = null;
  if (workFileInput instanceof HTMLInputElement) {
    workFileInput.value = "";
  }
  if (workAttachmentName) {
    workAttachmentName.textContent = item.attachment?.name
      ? `Текущий файл: ${item.attachment.name}. Новый файл заменит его.`
      : attachmentLabel(null);
  }
  workAdminForm.scrollIntoView({ behavior: "smooth", block: "center" });
}

async function saveWork() {
  if (!workAdminForm) {
    return;
  }
  const idInput = workAdminForm.querySelector('input[name="id"]');
  const workId = idInput instanceof HTMLInputElement ? idInput.value.trim() : "";
  const payload = getWorkPayload();
  setAdminStatus(workId ? `Сохраняю работу #${workId}...` : "Добавляю работу...");
  try {
    const result = await fetchAdminJson(workId ? `/api/admin/works/${workId}` : "/api/admin/works", {
      method: workId ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    setAdminStatus(result.message);
    resetWorkForm();
    await loadAdminWorks();
  } catch (error) {
    setAdminStatus(error instanceof Error ? error.message : "Ошибка сохранения работы.", true);
  }
}

async function deleteWork(workId) {
  const confirmed = window.confirm(`Удалить работу #${workId}? Это действие нельзя отменить.`);
  if (!confirmed) {
    return;
  }
  setAdminStatus(`Удаляю работу #${workId}...`);
  try {
    const result = await fetchAdminJson(`/api/admin/works/${workId}`, { method: "DELETE" });
    setAdminStatus(result.message);
    await loadAdminWorks();
  } catch (error) {
    setAdminStatus(error instanceof Error ? error.message : "Ошибка удаления работы.", true);
  }
}

if (loginForm) {
  loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(loginForm);
    storeAuth(String(formData.get("username") || "").trim(), String(formData.get("password") || ""));
    await loadRequests();
    await loadAdminReviews();
    await loadAdminWorks();
  });
}

if (filtersForm) {
  filtersForm.addEventListener("submit", (event) => {
    event.preventDefault();
    loadRequests();
  });
}

if (resetFiltersButton && filtersForm) {
  resetFiltersButton.addEventListener("click", () => {
    filtersForm.reset();
    loadRequests();
  });
}

if (logoutButton) {
  logoutButton.addEventListener("click", () => {
    clearAuth();
    if (loginForm) {
      loginForm.reset();
    }
    setAuthorizedState(false);
    renderRequests([]);
    renderAdminReviews([]);
    renderAdminWorks([]);
    setAdminStatus("Авторизация очищена.");
  });
}

if (changeUserButton) {
  changeUserButton.addEventListener("click", () => {
    clearAuth();
    setAuthorizedState(false);
    renderRequests([]);
    renderAdminReviews([]);
    renderAdminWorks([]);
    setAdminStatus("Введите данные другого аккаунта.");
    if (loginForm) {
      loginForm.reset();
      const usernameInput = loginForm.querySelector('input[name="username"]');
      if (usernameInput instanceof HTMLInputElement) {
        usernameInput.focus();
      }
    }
  });
}

if (refreshButton) {
  refreshButton.addEventListener("click", () => {
    loadRequests();
  });
}

if (refreshReviewsButton) {
  refreshReviewsButton.addEventListener("click", () => {
    loadAdminReviews();
  });
}

if (refreshWorksButton) {
  refreshWorksButton.addEventListener("click", () => {
    loadAdminWorks();
  });
}

if (resetWorkFormButton) {
  resetWorkFormButton.addEventListener("click", () => {
    resetWorkForm();
  });
}

workFileInput?.addEventListener("change", async () => {
  const file = workFileInput.files?.[0] || null;
  if (!file) {
    pendingWorkAttachment = null;
    if (workAttachmentName) {
      workAttachmentName.textContent = attachmentLabel(null);
    }
    return;
  }
  if (workAttachmentName) {
    workAttachmentName.textContent = "Подготавливаю файл...";
  }
  try {
    pendingWorkAttachment = await fileToBase64(file);
    if (workAttachmentName) {
      workAttachmentName.textContent = attachmentLabel(file);
    }
    setAdminStatus("");
  } catch (error) {
    pendingWorkAttachment = null;
    workFileInput.value = "";
    if (workAttachmentName) {
      workAttachmentName.textContent = attachmentLabel(null);
    }
    setAdminStatus(error instanceof Error ? error.message : "Ошибка подготовки файла.", true);
  }
});

if (workAdminForm) {
  workAdminForm.addEventListener("submit", (event) => {
    event.preventDefault();
    saveWork();
  });
}

if (reviewStatusFilter) {
  reviewStatusFilter.addEventListener("change", () => {
    loadAdminReviews();
  });
}

if (requestList) {
  requestList.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    const button = target.closest(".request-delete");
    if (!button) {
      return;
    }
    const requestId = button.getAttribute("data-request-id");
    if (requestId) {
      deleteRequest(requestId);
    }
  });
}

if (reviewAdminList) {
  reviewAdminList.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    const card = target.closest(".request-card");
    if (!(card instanceof HTMLElement)) {
      return;
    }
    const reviewId = card.dataset.reviewId || "";
    if (!reviewId) {
      return;
    }
    const saveButton = target.closest(".review-save");
    if (saveButton) {
      saveReview(reviewId, card);
      return;
    }
    const approveButton = target.closest(".review-approve");
    if (approveButton) {
      moderateReview(reviewId, "approve");
      return;
    }
    const rejectButton = target.closest(".review-reject");
    if (rejectButton) {
      moderateReview(reviewId, "reject");
      return;
    }
    const deleteButton = target.closest(".review-delete");
    if (deleteButton) {
      deleteReview(reviewId);
    }
  });
}

if (workAdminList) {
  workAdminList.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    const card = target.closest(".request-card");
    if (!(card instanceof HTMLElement)) {
      return;
    }
    const editButton = target.closest(".work-edit");
    if (editButton) {
      try {
        fillWorkForm(JSON.parse(card.dataset.workPayload || "{}"));
      } catch (error) {
        setAdminStatus("Не удалось открыть работу для редактирования.", true);
      }
      return;
    }
    const deleteButton = target.closest(".work-delete");
    if (deleteButton) {
      const workId = deleteButton.getAttribute("data-work-id");
      if (workId) {
        deleteWork(workId);
      }
    }
  });
}

setAuthorizedState(Boolean(getStoredAuth()));
loadRequests();
loadAdminReviews();
loadAdminWorks();
