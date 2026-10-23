const socket = io();
const { otherUserId } = window.CHAT_CONTEXT;

const log = document.getElementById("chat-log");
const form = document.getElementById("chat-form");
const input = document.getElementById("chat-input");

socket.on("connect", () => {
  socket.emit("join", { other_user_id: otherUserId });
});

socket.on("receive_message", (msg) => {
  appendBubble(msg.body, msg.created_at, msg.sender_id === window.CHAT_CONTEXT.myUserId);
});

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const body = input.value.trim();
  if (!body) return;
  socket.emit("send_message", { recipient_id: otherUserId, body });
  input.value = "";
});

function appendBubble(body, time, isMine) {
  const placeholder = log.querySelector(".muted");
  if (placeholder) placeholder.remove();

  const bubble = document.createElement("div");
  bubble.className = "chat-bubble" + (isMine ? " chat-bubble--mine" : "");
  bubble.innerHTML = `<span class="chat-bubble__body"></span><time>${time}</time>`;
  bubble.querySelector(".chat-bubble__body").textContent = body; // textContent avoids any HTML injection
  log.appendChild(bubble);
  log.scrollTop = log.scrollHeight;
}

log.scrollTop = log.scrollHeight;
