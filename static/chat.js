const userName = document.querySelector("#user-name");
const userLogoutButton = document.querySelector("#user-logout-button");
const userChatMessages = document.querySelector("#user-chat-messages");
const userChatForm = document.querySelector("#user-chat-form");
const chatStatus = document.querySelector("#chat-status");
const chatFileInput = document.querySelector("#chat-file-input");
const attachmentName = document.querySelector("#attachment-name");

let chatPollTimer = null;
let pendingAttachment = null;

function setStatus(node, message, isError = false) {
  if (!node) {
    return;
  }
  node.textContent = message;
  node.classList.toggle("is-error", isError);
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
  const parsedDate = new Date(value);
  if (Number.isNaN(parsedDate.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsedDate);
}

function attachmentLabel(file) {
  if (!file) {
    return "Файл не выбран";
  }
  const sizeKb = Math.max(1, Math.round(file.size / 1024));
  return `${file.name} · ${sizeKb} КБ`;
}

function renderAttachment(attachment) {
  if (!attachment?.path || !attachment?.name) {
    return "";
  }
  return `
    <a class="chat-attachment" href="${escapeHtml(attachment.path)}" target="_blank" rel="noopener noreferrer">
      <span>Вложение</span>
      <strong>${escapeHtml(attachment.name)}</strong>
    </a>
  `;
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    credentials: "same-origin",
    ...options,
    headers: {
      ...(options.headers || {}),
    },
  });
  const result = await response.json();
  if (!response.ok) {
    throw new Error(result.message || "Не удалось выполнить запрос.");
  }
  return result;
}

function renderMessages(items) {
  if (!userChatMessages) {
    return;
  }
  if (!items.length) {
    userChatMessages.innerHTML = `<div class="chat-empty">Сообщений пока нет. Напишите администратору первым.</div>`;
    return;
  }
  userChatMessages.innerHTML = items.map((item) => `
    <article class="chat-message chat-message-${escapeHtml(item.sender)}">
      <div class="chat-message-meta">
        <span>${item.sender === "admin" ? "Администратор" : "Вы"}</span>
        <span>${escapeHtml(formatDate(item.createdAt))}</span>
      </div>
      ${item.text ? `<p>${escapeHtml(item.text)}</p>` : ""}
      ${renderAttachment(item.attachment)}
    </article>
  `).join("");
  userChatMessages.scrollTop = userChatMessages.scrollHeight;
}

async function ensureAuthorizedUser() {
  try {
    const result = await fetchJson("/api/auth/me");
    if (userName) {
      userName.textContent = result.user?.name || "Пользователь";
    }
  } catch (error) {
    window.location.replace("/");
  }
}

async function loadMessages() {
  try {
    const result = await fetchJson("/api/chat/messages");
    renderMessages(result.items || []);
  } catch (error) {
    if (error instanceof Error && (error.message.includes("авториза") || error.message.includes("Сессия"))) {
      window.location.replace("/");
      return;
    }
    setStatus(chatStatus, error instanceof Error ? error.message : "Ошибка загрузки сообщений.", true);
  }
}

function startPolling() {
  stopPolling();
  chatPollTimer = window.setInterval(loadMessages, 4000);
}

function stopPolling() {
  if (chatPollTimer) {
    window.clearInterval(chatPollTimer);
    chatPollTimer = null;
  }
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

chatFileInput?.addEventListener("change", async () => {
  const file = chatFileInput.files?.[0] || null;
  if (!file) {
    pendingAttachment = null;
    if (attachmentName) {
      attachmentName.textContent = attachmentLabel(null);
    }
    return;
  }
  if (attachmentName) {
    attachmentName.textContent = "Подготавливаю файл...";
  }
  try {
    pendingAttachment = await fileToBase64(file);
    if (attachmentName) {
      attachmentName.textContent = attachmentLabel(file);
    }
    setStatus(chatStatus, "");
  } catch (error) {
    pendingAttachment = null;
    chatFileInput.value = "";
    if (attachmentName) {
      attachmentName.textContent = attachmentLabel(null);
    }
    setStatus(chatStatus, error instanceof Error ? error.message : "Ошибка подготовки файла.", true);
  }
});

userChatForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(userChatForm);
  const text = String(formData.get("text") || "").trim();
  if (!text && !pendingAttachment) {
    setStatus(chatStatus, "Введите сообщение или прикрепите файл.", true);
    return;
  }
  setStatus(chatStatus, "Отправляю сообщение...");
  try {
    await fetchJson("/api/chat/messages", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        text,
        attachment: pendingAttachment,
      }),
    });
    userChatForm.reset();
    pendingAttachment = null;
    if (attachmentName) {
      attachmentName.textContent = attachmentLabel(null);
    }
    setStatus(chatStatus, "Сообщение отправлено.");
    await loadMessages();
  } catch (error) {
    setStatus(chatStatus, error instanceof Error ? error.message : "Ошибка отправки сообщения.", true);
  }
});

userLogoutButton?.addEventListener("click", async () => {
  try {
    await fetchJson("/api/auth/logout", { method: "POST" });
  } catch (error) {
    // Ignore and continue with redirect.
  } finally {
    stopPolling();
    window.location.replace("/");
  }
});

ensureAuthorizedUser();
loadMessages();
startPolling();
