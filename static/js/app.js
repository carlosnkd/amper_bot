const API_BASE = '';
// No auth/session layer exists yet, so every request is scoped to this single
// hardcoded user. Replace with a real logged-in user id once auth lands.
const USER_ID = '1';
const state = {
    conversations: [],
    currentConversationId: null,
    isGenerating: false,
    // Set to { conversationId } while a plan card is shown and awaiting the user's
    // approval / edits / change-request -- the composer is locked until it resolves.
    pendingPlan: null,
    selectedFiles: [],
    theme: localStorage.getItem('agent-theme') || 'light',
};

const ICONS = {
    sun: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4.5"></circle><line x1="12" y1="2.5" x2="12" y2="5"></line><line x1="12" y1="19" x2="12" y2="21.5"></line><line x1="4.2" y1="4.2" x2="6" y2="6"></line><line x1="18" y1="18" x2="19.8" y2="19.8"></line><line x1="2.5" y1="12" x2="5" y2="12"></line><line x1="19" y1="12" x2="21.5" y2="12"></line><line x1="4.2" y1="19.8" x2="6" y2="18"></line><line x1="18" y1="6" x2="19.8" y2="4.2"></line></svg>',
    moon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5Z"></path></svg>',
    close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><line x1="6" y1="6" x2="18" y2="18"></line><line x1="18" y1="6" x2="6" y2="18"></line></svg>',
    user: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="3.4"></circle><path d="M5 20c0-3.6 3.1-6.5 7-6.5s7 2.9 7 6.5"></path></svg>',
    bot: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="8" width="16" height="11" rx="2.5"></rect><line x1="12" y1="3" x2="12" y2="8"></line><circle cx="12" cy="3" r="1.1"></circle><line x1="8" y1="13.5" x2="8" y2="15"></line><line x1="16" y1="13.5" x2="16" y2="15"></line></svg>',
};

const els = {};

function init() {
    cacheElements();
    bindEvents();
    applyTheme();
    renderEmptyState();
    loadHistory();
}

function cacheElements() {
    els.sidebar = document.querySelector('.sidebar');
    els.chatWindow = document.getElementById('chatWindow');
    els.messageInput = document.getElementById('messageInput');
    els.conversationList = document.getElementById('conversationList');
    els.searchInput = document.getElementById('conversationSearch');
    els.newChatBtn = document.getElementById('newChatBtn');
    els.themeBtn = document.getElementById('themeToggle');
    els.sendBtn = document.getElementById('sendBtn');
    els.stopBtn = document.getElementById('stopBtn');
    els.fileInput = document.getElementById('fileInput');
    els.fileList = document.getElementById('fileList');
    els.toastContainer = document.getElementById('toastContainer');
    els.emptyState = document.getElementById('emptyState');
    els.confirmModal = document.getElementById('confirmModal');
    els.confirmModalTitle = document.getElementById('confirmModalTitle');
    els.confirmModalMessage = document.getElementById('confirmModalMessage');
    els.confirmModalCancel = document.getElementById('confirmModalCancel');
    els.confirmModalConfirm = document.getElementById('confirmModalConfirm');
}

function bindEvents() {
    els.newChatBtn.addEventListener('click', startNewConversation);
    els.themeBtn.addEventListener('click', toggleTheme);
    els.sendBtn.addEventListener('click', sendMessage);
    els.stopBtn.addEventListener('click', stopGeneration);
    els.messageInput.addEventListener('keydown', handleComposerKeydown);
    els.messageInput.addEventListener('input', autoResize);
    els.fileInput.addEventListener('change', handleFileSelection);
    els.searchInput.addEventListener('input', renderConversations);
    els.confirmModalCancel.addEventListener('click', () => resolveConfirm(false));
    els.confirmModalConfirm.addEventListener('click', () => resolveConfirm(true));
    els.confirmModal.addEventListener('click', (event) => {
        if (event.target === els.confirmModal) resolveConfirm(false);
    });
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && !els.confirmModal.classList.contains('hidden')) {
            resolveConfirm(false);
        }
    });
}

// Promise-based replacement for window.confirm() -- resolves true/false
// once the user picks an option on the in-app modal, so callers can just
// `await showConfirm(...)` the same way they would `window.confirm(...)`.
let confirmResolver = null;

function showConfirm(message, { title = 'Are you sure?', confirmLabel = 'Confirm' } = {}) {
    els.confirmModalTitle.textContent = title;
    els.confirmModalMessage.textContent = message;
    els.confirmModalConfirm.textContent = confirmLabel;
    els.confirmModal.classList.remove('hidden');
    els.confirmModalConfirm.focus();

    return new Promise((resolve) => {
        confirmResolver = resolve;
    });
}

function resolveConfirm(result) {
    els.confirmModal.classList.add('hidden');
    if (confirmResolver) {
        confirmResolver(result);
        confirmResolver = null;
    }
}

function autoResize() {
    els.messageInput.style.height = 'auto';
    els.messageInput.style.height =
        Math.min(els.messageInput.scrollHeight, 180) + 'px';
}

function handleComposerKeydown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
    }
}

function applyTheme() {
    document.documentElement.classList.toggle('dark', state.theme === 'dark');
    els.themeBtn.innerHTML =
        state.theme === 'light' ? ICONS.moon : ICONS.sun;
    els.themeBtn.setAttribute(
        'aria-label',
        state.theme === 'light' ? 'Switch to dark theme' : 'Switch to light theme',
    );
}

function toggleTheme() {
    state.theme = state.theme === 'dark' ? 'light' : 'dark';
    localStorage.setItem('agent-theme', state.theme);
    applyTheme();
    showToast('Theme updated', 'success');
}

function startNewConversation() {
    state.currentConversationId = null;
    state.pendingPlan = null;
    setComposerLocked(false);
    els.chatWindow.innerHTML = '';
    els.messageInput.value = '';
    els.messageInput.focus();
    renderEmptyState();
    state.selectedFiles = [];
    renderFiles();
}

function renderEmptyState() {
    if (els.chatWindow.children.length === 0) {
        els.chatWindow.innerHTML = `
      <div class="empty-state">
        <h3>Research assistant ready</h3>
        <p>Ask anything about your data, and the CrewAI workflow will inspect the schema, build a query, and return an answer.</p>
      </div>
    `;
    }
}

async function loadHistory() {
    try {
        const response = await fetch(
            `${API_BASE}/get_history?user_id=${encodeURIComponent(USER_ID)}`,
        );
        const data = await response.json();
        state.conversations = Array.isArray(data.history) ? data.history : [];
        renderConversations();
    } catch (error) {
        console.error(error);
        showToast('Unable to load history', 'error');
    }
}

function renderConversations() {
    const query = els.searchInput.value.trim().toLowerCase();
    const filtered = state.conversations.filter((conversation) => {
        const title = (conversation.summary || 'Conversation').toLowerCase();
        return title.includes(query);
    });

    els.conversationList.innerHTML = '';
    if (!filtered.length) {
        els.conversationList.innerHTML =
            '<div class="empty-state" style="padding:8px 0;"><p>No conversations found.</p></div>';
        return;
    }

    filtered.forEach((conversation) => {
        // A <div> wrapper (not a <button>) because it now holds two
        // independently clickable buttons -- select and delete -- and a
        // <button> can't legally nest another <button> inside it.
        const item = document.createElement('div');
        item.className = `conversation-item ${conversation.conversation_id === state.currentConversationId ? 'active' : ''}`;

        const selectBtn = document.createElement('button');
        selectBtn.type = 'button';
        selectBtn.className = 'conversation-select';
        selectBtn.innerHTML = `
      <h4>${escapeHtml(conversation.summary || 'Conversation')}</h4>
      <p>${(conversation.messages || []).length} messages</p>
    `;
        selectBtn.addEventListener('click', () =>
            selectConversation(conversation.conversation_id),
        );

        const deleteBtn = document.createElement('button');
        deleteBtn.type = 'button';
        deleteBtn.className = 'conversation-delete';
        deleteBtn.innerHTML = ICONS.close;
        deleteBtn.setAttribute('aria-label', 'Delete conversation');
        deleteBtn.addEventListener('click', (event) => {
            event.stopPropagation();
            deleteConversationItem(conversation.conversation_id);
        });

        item.appendChild(selectBtn);
        item.appendChild(deleteBtn);
        els.conversationList.appendChild(item);
    });
}

async function deleteConversationItem(conversationId) {
    const confirmed = await showConfirm('This cannot be undone.', {
        title: 'Delete conversation?',
        confirmLabel: 'Delete',
    });
    if (!confirmed) {
        return;
    }

    try {
        const response = await fetch(
            `${API_BASE}/delete_conversation?user_id=${encodeURIComponent(USER_ID)}&conversation_id=${encodeURIComponent(conversationId)}`,
            { method: 'DELETE' },
        );
        if (!response.ok) throw new Error(`Request failed with ${response.status}`);

        state.conversations = state.conversations.filter(
            (conversation) => conversation.conversation_id !== conversationId,
        );

        if (state.currentConversationId === conversationId) {
            startNewConversation();
        }

        renderConversations();
        showToast('Conversation deleted', 'success');
    } catch (error) {
        console.error(error);
        showToast('Unable to delete conversation', 'error');
    }
}

async function selectConversation(conversationId) {
    state.currentConversationId = conversationId;
    renderConversations();
    const conversation = state.conversations.find(
        (item) => item.conversation_id === conversationId,
    );
    if (!conversation) return;
    els.chatWindow.innerHTML = '';
    (conversation.messages || []).forEach((message) =>
        appendMessage(message.role, message.content, message.timestamp),
    );
    if (!conversation.messages?.length) {
        renderEmptyState();
    }
}

async function sendMessage() {
    const prompt = els.messageInput.value.trim();
    if (!prompt) return;
    if (state.isGenerating || state.pendingPlan) return;

    state.isGenerating = true;
    els.sendBtn.classList.add('hidden');
    els.stopBtn.classList.remove('hidden');
    appendMessage('user', prompt, new Date().toISOString());
    els.messageInput.value = '';
    autoResize();
    showTypingIndicator('Reading your message…');

    const formData = new FormData();
    formData.append('user_id', USER_ID);
    formData.append('query', prompt);
    if (state.currentConversationId)
        formData.append('conversation_id', state.currentConversationId);
    state.selectedFiles.forEach((file) => formData.append('file', file));

    try {
        const response = await fetch(`${API_BASE}/run/stream`, {
            method: 'POST',
            body: formData,
        });
        if (!response.ok) throw new Error(`Request failed with ${response.status}`);

        // "phase" events update the typing indicator's label in place as the backend
        // moves through intent-check -> Planner/chat-reply -> summary, instead of a
        // static "Thinking…" for the whole request; the last non-phase event carries
        // the actual outcome.
        let finalEvent = null;
        await consumeEventStream(response, (event) => {
            if (event.type === 'phase') {
                showTypingIndicator(event.message);
            } else {
                finalEvent = event;
            }
        });

        removeTypingIndicator();

        if (!finalEvent) {
            throw new Error('The connection ended before a response arrived.');
        }
        if (!state.currentConversationId && finalEvent.conversation_id) {
            state.currentConversationId = finalEvent.conversation_id;
        }

        if (finalEvent.type === 'error') {
            appendMessageTyped(
                'assistant',
                finalEvent.message || 'Something went wrong.',
                new Date().toISOString(),
            );
        } else if (finalEvent.error || !finalEvent.plan) {
            // finalEvent.reply is set when the backend classified this message as
            // chit-chat rather than a ticket (see backend/services/bot/intent.py)
            // -- no plan was generated, so just show the direct reply.
            appendMessageTyped(
                'assistant',
                finalEvent.error || finalEvent.reply || 'I could not come up with a plan for that.',
                new Date().toISOString(),
            );
        } else {
            renderPlanMessage(finalEvent.plan, finalEvent.conversation_id, prompt);
        }
        await loadHistory();
    } catch (error) {
        removeTypingIndicator();
        showToast('The request could not be completed', 'error');
    } finally {
        state.isGenerating = false;
        els.sendBtn.classList.remove('hidden');
        els.stopBtn.classList.add('hidden');
    }
}

function stopGeneration() {
    state.isGenerating = false;
    state.pendingPlan = null;
    setComposerLocked(false);
    removeTypingIndicator();
    els.sendBtn.classList.remove('hidden');
    els.stopBtn.classList.add('hidden');
}

function setComposerLocked(locked, hint) {
    els.messageInput.disabled = locked;
    els.sendBtn.disabled = locked;
    els.messageInput.placeholder = locked
        ? hint || 'Respond to the plan above to continue'
        : 'Ask about your data, schema, or research question...';
}

function renderPlanMessage(plan, conversationId, ticketText) {
    const assumptions = plan.assumptions || [];
    const tasks = plan.tasks || [];

    const row = document.createElement('div');
    row.className = 'message-row';
    const card = document.createElement('div');
    card.className = 'message-card plan-card';
    card.dataset.conversationId = conversationId;
    card.dataset.ticket = ticketText;

    card.innerHTML = `
    <div class="message-card-head">
      ${ICONS.bot}
      <h4>Agent</h4>
    </div>
    <p class="plan-intro">Here's my proposed plan. Edit any task inline if you'd like, then approve to start building.</p>
    ${
        assumptions.length
            ? `<div class="plan-section">
        <h5>Assumptions</h5>
        <ul class="plan-assumptions">${assumptions.map((a) => `<li>${escapeHtml(a)}</li>`).join('')}</ul>
      </div>`
            : ''
    }
    <div class="plan-section">
      <h5>Tasks</h5>
      <ul class="plan-tasks"></ul>
    </div>
    <div class="plan-feedback hidden">
      <textarea placeholder="What should change about this plan?"></textarea>
      <div class="plan-actions">
        <button type="button" class="plan-feedback-submit">Submit changes</button>
        <button type="button" class="plan-feedback-cancel">Cancel</button>
      </div>
    </div>
    <div class="plan-actions plan-actions-main">
      <button type="button" class="plan-approve">Approve &amp; Build</button>
      <button type="button" class="plan-request-changes">Request changes</button>
    </div>
    <div class="message-meta">${new Date().toLocaleString()}</div>
  `;

    const taskList = card.querySelector('.plan-tasks');
    tasks.forEach((task) => {
        const item = document.createElement('li');
        item.className = 'plan-task';
        item.dataset.taskId = task.id || '';
        item.innerHTML = `
      <span class="plan-task-id">${escapeHtml(task.id || '')}</span>
      <div class="plan-task-desc" contenteditable="true">${escapeHtml(task.description || '')}</div>
    `;
        taskList.appendChild(item);
    });

    card
        .querySelector('.plan-approve')
        .addEventListener('click', () => approvePlan(card));
    card.querySelector('.plan-request-changes').addEventListener('click', () => {
        card.querySelector('.plan-feedback').classList.remove('hidden');
        card.querySelector('.plan-actions-main').classList.add('hidden');
        card.querySelector('.plan-feedback textarea').focus();
    });
    card.querySelector('.plan-feedback-cancel').addEventListener('click', () => {
        card.querySelector('.plan-feedback').classList.add('hidden');
        card.querySelector('.plan-actions-main').classList.remove('hidden');
    });
    card
        .querySelector('.plan-feedback-submit')
        .addEventListener('click', () => requestPlanChanges(card));

    row.appendChild(card);
    els.chatWindow.appendChild(row);
    els.chatWindow.scrollTop = els.chatWindow.scrollHeight;

    state.pendingPlan = { conversationId };
    setComposerLocked(true);
}

function lockPlanCard(card) {
    card.querySelectorAll('button').forEach((btn) => (btn.disabled = true));
    card.querySelectorAll('[contenteditable]').forEach((el) => {
        el.contentEditable = 'false';
    });
    card.classList.add('plan-resolved');
}

function collectEditedPlan(card) {
    const assumptions = Array.from(
        card.querySelectorAll('.plan-assumptions li'),
    ).map((li) => li.textContent.trim());
    const tasks = Array.from(card.querySelectorAll('.plan-task')).map((item) => ({
        id: item.dataset.taskId,
        description: item.querySelector('.plan-task-desc').textContent.trim(),
    }));
    return { assumptions, tasks };
}

async function approvePlan(card) {
    const conversationId = card.dataset.conversationId;
    const ticketText = card.dataset.ticket;
    const editedPlan = collectEditedPlan(card);

    lockPlanCard(card);
    state.isGenerating = true;

    const live = createLiveBuildMessage();

    const formData = new FormData();
    formData.append('user_id', USER_ID);
    formData.append('conversation_id', conversationId);
    formData.append('ticket', ticketText);
    formData.append('plan', JSON.stringify(editedPlan));

    try {
        const response = await fetch(`${API_BASE}/build/stream`, {
            method: 'POST',
            body: formData,
        });
        if (!response.ok) throw new Error(`Request failed with ${response.status}`);

        let sawResult = false;
        await consumeEventStream(response, (event) => {
            if (event.type === 'phase') {
                live.setStatus(event.label);
            } else if (event.type === 'file') {
                live.upsertFile(event.path, event.content);
            } else if (event.type === 'result') {
                sawResult = true;
                live.finish(event);
                showToast(
                    event.approved ? 'Build complete' : 'Build finished with open feedback',
                    event.approved ? 'success' : 'error',
                );
            } else if (event.type === 'error') {
                sawResult = true;
                live.fail(event.message);
                showToast('The build could not be completed', 'error');
            }
        });
        if (!sawResult) {
            live.fail('The connection ended before the build finished.');
        }
        await loadHistory();
    } catch (error) {
        live.fail('The build could not be completed');
        showToast('The build could not be completed', 'error');
    } finally {
        state.isGenerating = false;
        state.pendingPlan = null;
        setComposerLocked(false);
    }
}

async function requestPlanChanges(card) {
    const conversationId = card.dataset.conversationId;
    const feedback = card.querySelector('.plan-feedback textarea').value.trim();
    if (!feedback) return;

    lockPlanCard(card);
    appendMessage('user', feedback, new Date().toISOString());
    showTypingIndicator('Revising the plan…');

    const formData = new FormData();
    formData.append('user_id', USER_ID);
    formData.append('conversation_id', conversationId);
    formData.append('feedback', feedback);

    try {
        const response = await fetch(`${API_BASE}/replan`, {
            method: 'POST',
            body: formData,
        });
        const data = await response.json();
        removeTypingIndicator();
        if (data.error || !data.plan) {
            appendMessageTyped(
                'assistant',
                data.error || 'I could not revise the plan.',
                new Date().toISOString(),
            );
            state.pendingPlan = null;
            setComposerLocked(false);
        } else {
            renderPlanMessage(data.plan, conversationId, card.dataset.ticket);
        }
        await loadHistory();
    } catch (error) {
        removeTypingIndicator();
        showToast('The request could not be completed', 'error');
        state.pendingPlan = null;
        setComposerLocked(false);
    }
}

/**
 * Reads a fetch() Response whose body is a `text/event-stream` (SSE) of
 * `data: <json>\n\n` frames, calling `onEvent(parsedJson)` for each one as it arrives.
 * Not EventSource -- this endpoint is POST (form data), which EventSource can't send --
 * so the stream is parsed by hand off the response's own ReadableStream instead.
 */
async function consumeEventStream(response, onEvent) {
    if (!response.body || !response.body.getReader) {
        // No streaming support in this browser/response -- fall back to parsing
        // whatever arrived as one block, so the UI still ends up in a final state.
        const text = await response.text();
        text.split('\n\n').forEach((chunk) => parseSseChunk(chunk, onEvent));
        return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split('\n\n');
        buffer = chunks.pop();
        chunks.forEach((chunk) => parseSseChunk(chunk, onEvent));
    }
    if (buffer.trim()) parseSseChunk(buffer, onEvent);
}

function parseSseChunk(chunk, onEvent) {
    const dataLine = chunk.split('\n').find((line) => line.startsWith('data:'));
    if (!dataLine) return;
    const jsonText = dataLine.slice(5).trim();
    if (!jsonText) return;
    try {
        onEvent(JSON.parse(jsonText));
    } catch (error) {
        console.error('Malformed stream event', error, jsonText);
    }
}

/**
 * A chat bubble that fills in live as /build/stream sends events: a status line that
 * updates in place (replacing the old fixed "typing" dots for this phase), and a file
 * appearing with its code the moment the Coder writes it -- instead of the whole
 * response only showing up once the entire build finishes.
 */
function createLiveBuildMessage() {
    const row = document.createElement('div');
    row.className = 'message-row';
    const card = document.createElement('div');
    card.className = 'message-card build-live';
    card.innerHTML = `
    <div class="message-card-head">${ICONS.bot}<h4>Agent</h4></div>
    <div class="build-status">
      <span class="build-status-dot"></span>
      <span class="build-status-label">Starting…</span>
    </div>
    <div class="build-files"></div>
    <div class="build-summary hidden"></div>
    <div class="message-meta"></div>
  `;
    row.appendChild(card);
    els.chatWindow.appendChild(row);
    els.chatWindow.scrollTop = els.chatWindow.scrollHeight;

    const statusRow = card.querySelector('.build-status');
    const statusLabel = card.querySelector('.build-status-label');
    const filesEl = card.querySelector('.build-files');
    const summaryEl = card.querySelector('.build-summary');
    const metaEl = card.querySelector('.message-meta');
    const fileBlocks = new Map();

    const scrollDown = () => {
        els.chatWindow.scrollTop = els.chatWindow.scrollHeight;
    };

    return {
        setStatus(label) {
            statusLabel.textContent = label;
            scrollDown();
        },
        upsertFile(path, content) {
            let block = fileBlocks.get(path);
            if (!block) {
                block = document.createElement('div');
                block.className = 'build-file';
                block.innerHTML = `
          <div class="build-file-head"><code>${escapeHtml(path)}</code></div>
          <pre><code class="build-file-code"></code></pre>
        `;
                filesEl.appendChild(block);
                fileBlocks.set(path, block);
            }
            block.querySelector('.build-file-code').textContent = content;
            scrollDown();
        },
        finish(event) {
            card.classList.remove('build-live');
            statusRow.classList.add('hidden');
            summaryEl.classList.remove('hidden');
            summaryEl.innerHTML = formatMessage(event.result || event.error || 'No result');
            if (event.approved === false) card.classList.add('build-not-approved');
            metaEl.textContent = new Date().toLocaleString();
            scrollDown();
        },
        fail(message) {
            card.classList.remove('build-live');
            statusRow.classList.add('build-error');
            statusLabel.textContent = message || 'Build failed';
            metaEl.textContent = new Date().toLocaleString();
            scrollDown();
        },
    };
}

function appendMessage(role, content, timestamp) {
    const safeContent =
        typeof content === 'string' ? content : JSON.stringify(content);
    const row = document.createElement('div');
    row.className = `message-row ${role === 'user' ? 'user' : ''}`;
    const card = document.createElement('div');
    card.className = 'message-card';
    card.innerHTML = `
    <div class="message-card-head">
      ${role === 'user' ? ICONS.user : ICONS.bot}
      <h4>${role === 'user' ? 'You' : 'Agent'}</h4>
    </div>
    <div class="message-body">${formatMessage(safeContent)}</div>
    <div class="message-meta">${timestamp ? new Date(timestamp).toLocaleString() : 'just now'}</div>
  `;
    row.appendChild(card);
    els.chatWindow.appendChild(row);
    els.chatWindow.scrollTop = els.chatWindow.scrollHeight;
}

/**
 * Same as appendMessage(), but drip-feeds the text into the DOM instead of showing it
 * all at once -- purely a client-side reveal animation. The backend already returned the
 * complete reply (see /run/stream's "result" event) before this is ever called, so this
 * does NOT reflect real generation progress the way the phase-streaming ("Reading your
 * message…" etc.) does -- it's cosmetic, to make the answer feel like it's being typed.
 * Duration is capped so long replies (e.g. a SNIPPET's code block) don't drag the
 * animation out -- always somewhere between 400ms and 1.8s regardless of length.
 */
function appendMessageTyped(role, content, timestamp) {
    const safeContent =
        typeof content === 'string' ? content : JSON.stringify(content);
    const row = document.createElement('div');
    row.className = `message-row ${role === 'user' ? 'user' : ''}`;
    const card = document.createElement('div');
    card.className = 'message-card';
    card.innerHTML = `
    <div class="message-card-head">
      ${role === 'user' ? ICONS.user : ICONS.bot}
      <h4>${role === 'user' ? 'You' : 'Agent'}</h4>
    </div>
    <div class="message-body"></div>
    <div class="message-meta">${timestamp ? new Date(timestamp).toLocaleString() : 'just now'}</div>
  `;
    row.appendChild(card);
    els.chatWindow.appendChild(row);

    const bodyEl = card.querySelector('.message-body');
    const durationMs = Math.min(1800, Math.max(400, safeContent.length * 12));
    const startedAt = performance.now();

    function tick(now) {
        const progress = Math.min(1, (now - startedAt) / durationMs);
        const chars = Math.ceil(safeContent.length * progress);
        bodyEl.innerHTML = formatMessage(safeContent.slice(0, chars));
        els.chatWindow.scrollTop = els.chatWindow.scrollHeight;
        if (progress < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
}

function formatMessage(content) {
    const escaped = escapeHtml(content);
    const withCodeBlocks = escaped
        .replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>')
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/\*([^*]+)\*/g, '<em>$1</em>');
    return `<div>${withCodeBlocks.replace(/\n/g, '<br>')}</div>`;
}

function escapeHtml(value) {
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function showTypingIndicator(label) {
    removeTypingIndicator();
    const node = document.createElement('div');
    node.className = 'typing-indicator';
    node.id = 'typingIndicator';
    node.innerHTML = `<span></span><span></span><span></span>${
        label ? `<em>${escapeHtml(label)}</em>` : ''
    }`;
    els.chatWindow.appendChild(node);
    els.chatWindow.scrollTop = els.chatWindow.scrollHeight;
}

function removeTypingIndicator() {
    const indicator = document.getElementById('typingIndicator');
    if (indicator) indicator.remove();
}

function handleFileSelection(event) {
    const files = Array.from(event.target.files || []);
    state.selectedFiles = files;
    renderFiles();
}

function renderFiles() {
    els.fileList.innerHTML = '';
    if (!state.selectedFiles.length) {
        els.fileList.classList.add('hidden');
        return;
    }
    els.fileList.classList.remove('hidden');
    state.selectedFiles.forEach((file) => {
        const chip = document.createElement('div');
        chip.className = 'file-chip';
        chip.innerHTML = `<span>${escapeHtml(file.name)}</span><button type="button" data-name="${escapeHtml(file.name)}">${ICONS.close}</button>`;
        chip.querySelector('button').addEventListener('click', () =>
            removeFile(file.name),
        );
        els.fileList.appendChild(chip);
    });
}

function removeFile(name) {
    state.selectedFiles = state.selectedFiles.filter(
        (file) => file.name !== name,
    );
    renderFiles();
}

function showToast(message, type = 'success') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    els.toastContainer.appendChild(toast);
    setTimeout(() => toast.remove(), 2600);
}

document.addEventListener('DOMContentLoaded', init);
