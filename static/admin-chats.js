const chatUserList = document.querySelector("#chat-user-list");
const refreshChatListButton = document.querySelector("#refresh-chat-list-button");
const adminChatTitle = document.querySelector("#chat-admin-title");
const adminChatSubtitle = document.querySelector("#chat-admin-subtitle");
const adminChatMessages = document.querySelector("#admin-chat-messages");
const adminChatForm = document.querySelector("#admin-chat-form");
const adminChatStatus = document.querySelector("#admin-chat-status");
const adminChatFileInput = document.querySelector("#admin-chat-file-input");
const adminAttachmentName = document.querySelector("#admin-attachment-name");

let selectedUserId = "";
let adminChatPollTimer = null;
let lastChatsSnapshot = [];
const defaultTitle = document.title;
let pendingAttachment = null;

function getAdminAuth() {
  return window.localStorage.getItem("adminAuth") || "";
}

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

function getLastMessagePreview(message) {
  if (!message) {
    return "Сообщений пока нет";
  }
  if (message.text) {
    return message.text;
  }
  if (message.attachment?.name) {
    return `Файл: ${message.attachment.name}`;
  }
  return "Новое сообщение";
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

async function adminFetch(url, options = {}) {
  const auth = getAdminAuth();
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

function updateDocumentTitle(items) {
  const unreadTotal = items.reduce((sum, item) => sum + Number(item.unreadCount || 0), 0);
  document.title = unreadTotal > 0 ? `(${unreadTotal}) ${defaultTitle}` : defaultTitle;
}

function renderAdminMessages(items) {
  if (!adminChatMessages) {
    return;
  }
  if (!items.length) {
    adminChatMessages.innerHTML = `<div class="chat-empty">В этом чате пока нет сообщений.</div>`;
    return;
  }
  adminChatMessages.innerHTML = items.map((item) => `
    <article class="chat-message chat-message-${escapeHtml(item.sender)}">
      <div class="chat-message-meta">
        <span>${item.sender === "admin" ? "Администратор" : "Пользователь"}</span>
        <span>${escapeHtml(formatDate(item.createdAt))}</span>
      </div>
      ${item.text ? `<p>${escapeHtml(item.text)}</p>` : ""}
      ${renderAttachment(item.attachment)}
    </article>
  `).join("");
  adminChatMessages.scrollTop = adminChatMessages.scrollHeight;
}

async function loadChatList() {
  if (!getAdminAuth()) {
    if (chatUserList) {
      chatUserList.innerHTML = `<div class="chat-empty">Сначала войдите в админку на странице /admin.</div>`;
    }
    updateDocumentTitle([]);
    return;
  }
  try {
    const result = await adminFetch("/api/admin/chats");
    const items = result.items || [];
    lastChatsSnapshot = items;
    updateDocumentTitle(items);
    if (!chatUserList) {
      return;
    }
    if (!items.length) {
      chatUserList.innerHTML = `<div class="chat-empty">Пока нет зарегистрированных пользователей с чатами.</div>`;
      return;
    }
    chatUserList.innerHTML = items.map((item) => `
      <button class="chat-user-item ${selectedUserId === String(item.user.id) ? "is-active" : ""}" type="button" data-user-id="${escapeHtml(item.user.id)}">
        <div class="chat-user-item-head">
          <strong>${escapeHtml(item.user.name)}</strong>
          ${Number(item.unreadCount || 0) > 0 ? `<span class="chat-unread-badge">${escapeHtml(item.unreadCount)}</span>` : ""}
        </div>
        <span>${escapeHtml(item.user.email)}</span>
        <small>${escapeHtml(getLastMessagePreview(item.lastMessage))}</small>
      </button>
    `).join("");
  } catch (error) {
    updateDocumentTitle([]);
    if (chatUserList) {
      chatUserList.innerHTML = `<div class="chat-empty">${escapeHtml(error instanceof Error ? error.message : "Ошибка загрузки чатов.")}</div>`;
    }
  }
}

async function loadSelectedChat() {
  if (!selectedUserId) {
    renderAdminMessages([]);
    return;
  }
  try {
    const result = await adminFetch(`/api/admin/chats/${selectedUserId}/messages`);
    renderAdminMessages(result.items || []);
    await loadChatList();
  } catch (error) {
    setStatus(adminChatStatus, error instanceof Error ? error.message : "Ошибка загрузки сообщений.", true);
  }
}

function selectUser(userId) {
  selectedUserId = userId;
  const selectedChat = lastChatsSnapshot.find((item) => String(item.user.id) === String(userId));
  if (adminChatTitle) {
    adminChatTitle.textContent = selectedChat?.user?.name || "Пользователь";
  }
  if (adminChatSubtitle) {
    adminChatSubtitle.textContent = selectedChat?.user?.email || "";
  }
  if (adminChatForm) {
    adminChatForm.classList.remove("is-hidden");
  }
  loadChatList();
  loadSelectedChat();
}

function startAdminChatPolling() {
  stopAdminChatPolling();
  adminChatPollTimer = window.setInterval(() => {
    loadChatList();
    loadSelectedChat();
  }, 4000);
}

function stopAdminChatPolling() {
  if (adminChatPollTimer) {
    window.clearInterval(adminChatPollTimer);
    adminChatPollTimer = null;
  }
}

if (chatUserList) {
  chatUserList.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    const button = target.closest(".chat-user-item");
    if (!button) {
      return;
    }
    selectUser(button.getAttribute("data-user-id") || "");
  });
}

if (refreshChatListButton) {
  refreshChatListButton.addEventListener("click", () => {
    loadChatList();
    loadSelectedChat();
  });
}

adminChatFileInput?.addEventListener("change", async () => {
  const file = adminChatFileInput.files?.[0] || null;
  if (!file) {
    pendingAttachment = null;
    if (adminAttachmentName) {
      adminAttachmentName.textContent = attachmentLabel(null);
    }
    return;
  }
  if (adminAttachmentName) {
    adminAttachmentName.textContent = "Подготавливаю файл...";
  }
  try {
    pendingAttachment = await fileToBase64(file);
    if (adminAttachmentName) {
      adminAttachmentName.textContent = attachmentLabel(file);
    }
    setStatus(adminChatStatus, "");
  } catch (error) {
    pendingAttachment = null;
    adminChatFileInput.value = "";
    if (adminAttachmentName) {
      adminAttachmentName.textContent = attachmentLabel(null);
    }
    setStatus(adminChatStatus, error instanceof Error ? error.message : "Ошибка подготовки файла.", true);
  }
});

if (adminChatForm) {
  adminChatForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!selectedUserId) {
      setStatus(adminChatStatus, "Сначала выберите пользователя.", true);
      return;
    }
    const formData = new FormData(adminChatForm);
    const text = String(formData.get("text") || "").trim();
    if (!text && !pendingAttachment) {
      setStatus(adminChatStatus, "Введите сообщение или прикрепите файл.", true);
      return;
    }
    setStatus(adminChatStatus, "Отправляю ответ...");
    try {
      await adminFetch(`/api/admin/chats/${selectedUserId}/messages`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          text,
          attachment: pendingAttachment,
        }),
      });
      adminChatForm.reset();
      pendingAttachment = null;
      if (adminAttachmentName) {
        adminAttachmentName.textContent = attachmentLabel(null);
      }
      setStatus(adminChatStatus, "Ответ отправлен.");
      await loadSelectedChat();
    } catch (error) {
      setStatus(adminChatStatus, error instanceof Error ? error.message : "Ошибка отправки.", true);
    }
  });
}

loadChatList();
startAdminChatPolling();
