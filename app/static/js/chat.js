/**
 * Air Compressor Management - Diagnostic Chatbot Controller
 * Handles slide-out drawer, streaming token responses, prompt chips, and Markdown rendering.
 */

document.addEventListener("DOMContentLoaded", () => {
  initChatDrawer();
  initSuggestedPrompts();
  initChatForm();
});

function initChatDrawer() {
  const drawer = document.getElementById("chatDrawer");
  const btnToggle = document.getElementById("btnToggleChat");
  const btnClose = document.getElementById("btnCloseChat");

  btnToggle.addEventListener("click", () => {
    drawer.classList.toggle("open");
    if (drawer.classList.contains("open")) {
      document.getElementById("chatInput").focus();
    }
  });

  btnClose.addEventListener("click", () => {
    drawer.classList.remove("open");
  });

  // Close with Escape key
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && drawer.classList.contains("open")) {
      drawer.classList.remove("open");
    }
  });
}

async function initSuggestedPrompts() {
  const container = document.getElementById("suggestionsScroll");
  try {
    const res = await fetch("/api/chat/suggestions");
    const suggestions = await res.json();
    container.innerHTML = "";

    suggestions.forEach(item => {
      const chip = document.createElement("button");
      chip.className = "prompt-chip";
      chip.type = "button";
      chip.innerHTML = `<span>${item.icon}</span><span>${item.label}</span>`;
      chip.addEventListener("click", () => {
        const input = document.getElementById("chatInput");
        input.value = item.prompt;
        document.getElementById("chatForm").dispatchEvent(new Event("submit"));
      });
      container.appendChild(chip);
    });

    // Update status text
    document.getElementById("botStatusText").textContent = "AI Reliability Agent Ready";
  } catch (err) {
    console.warn("Could not load prompt suggestions:", err);
  }
}

function initChatForm() {
  const form = document.getElementById("chatForm");
  const input = document.getElementById("chatInput");
  const messagesContainer = document.getElementById("chatMessages");
  const btnSend = document.getElementById("btnSendChat");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const query = input.value.trim();
    if (!query) return;

    input.value = "";
    input.disabled = true;
    btnSend.disabled = true;

    // 1. Append User Message Bubble
    appendMessage("user", query);

    // 2. Prepare Bot Message Bubble with Streaming Cursor
    const botMsgId = "bot-msg-" + Date.now();
    const botContentEl = appendBotPlaceholder(botMsgId);

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: query })
      });

      if (!response.ok) {
        throw new Error(`Server returned ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let fullText = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        fullText += chunk;

        // Render Markdown into bubble
        botContentEl.innerHTML = parseSimpleMarkdown(fullText) + '<span class="cursor-blink"></span>';
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
      }

      // Final render without cursor
      botContentEl.innerHTML = parseSimpleMarkdown(fullText);
      messagesContainer.scrollTop = messagesContainer.scrollHeight;

    } catch (err) {
      console.error("Streaming error:", err);
      botContentEl.innerHTML = `<p style="color: var(--accent-rose);">⚠️ Diagnostic agent connection error: ${err.message}</p>`;
    } finally {
      input.disabled = false;
      btnSend.disabled = false;
      input.focus();
    }
  });
}

function appendMessage(role, text) {
  const container = document.getElementById("chatMessages");
  const bubble = document.createElement("div");
  bubble.className = `chat-bubble ${role}-message`;

  const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const senderTitle = role === "user" ? "Plant Operator" : "Diagnostic AI";

  bubble.innerHTML = `
    <div class="bubble-header">
      <strong>${senderTitle}</strong>
      <span class="msg-time">${timeStr}</span>
    </div>
    <div class="bubble-content">
      <p>${escapeHtml(text)}</p>
    </div>
  `;

  container.appendChild(bubble);
  container.scrollTop = container.scrollHeight;
}

function appendBotPlaceholder(msgId) {
  const container = document.getElementById("chatMessages");
  const bubble = document.createElement("div");
  bubble.className = "chat-bubble bot-message";
  bubble.id = msgId;

  const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  bubble.innerHTML = `
    <div class="bubble-header">
      <strong>Compressor Diagnostic Agent</strong>
      <span class="msg-time">${timeStr}</span>
    </div>
    <div class="bubble-content" id="${msgId}-content">
      <span class="cursor-blink"></span>
    </div>
  `;

  container.appendChild(bubble);
  container.scrollTop = container.scrollHeight;
  return document.getElementById(`${msgId}-content`);
}

function parseSimpleMarkdown(md) {
  let html = md;

  // Headings
  html = html.replace(/^### (.*$)/gim, '<h3>$1</h3>');
  html = html.replace(/^#### (.*$)/gim, '<h4>$1</h4>');

  // Bold & Italic
  html = html.replace(/\*\*(.*?)\*\*/gim, '<strong>$1</strong>');
  html = html.replace(/\*(.*?)\*/gim, '<em>$1</em>');

  // Inline Code
  html = html.replace(/`([^`]+)`/gim, '<code style="background: rgba(255,255,255,0.1); padding: 2px 4px; border-radius: 4px; font-family: monospace;">$1</code>');

  // Unordered list items
  html = html.replace(/^\s*-\s+(.*$)/gim, '<li>$1</li>');
  html = html.replace(/(<li>.*<\/li>)/gims, '<ul>$1</ul>');

  // Clean empty p tags around lists
  html = html.split("\n\n").map(para => {
    para = para.trim();
    if (!para) return "";
    if (para.startsWith("<h") || para.startsWith("<ul")) return para;
    return `<p>${para}</p>`;
  }).join("");

  return html;
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}
