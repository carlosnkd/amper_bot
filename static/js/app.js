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

// Single source of truth for every generated file's content -- both the compact rows
// in the chat and the file pane's detail view render from lookups into this same store,
// so content is never duplicated in the DOM. Keyed by a build-scoped id (not just the
// file path) so the same path in two different builds/messages doesn't collide.
const fileStore = new Map(); // id -> { id, path, content, language }
let openFileIds = []; // ids currently open as tabs in the file pane, in tab order
let activeFileId = null;

const ICONS = {
    sun: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4.5"></circle><line x1="12" y1="2.5" x2="12" y2="5"></line><line x1="12" y1="19" x2="12" y2="21.5"></line><line x1="4.2" y1="4.2" x2="6" y2="6"></line><line x1="18" y1="18" x2="19.8" y2="19.8"></line><line x1="2.5" y1="12" x2="5" y2="12"></line><line x1="19" y1="12" x2="21.5" y2="12"></line><line x1="4.2" y1="19.8" x2="6" y2="18"></line><line x1="18" y1="6" x2="19.8" y2="4.2"></line></svg>',
    moon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5Z"></path></svg>',
    close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><line x1="6" y1="6" x2="18" y2="18"></line><line x1="18" y1="6" x2="6" y2="18"></line></svg>',
    user: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="3.4"></circle><path d="M5 20c0-3.6 3.1-6.5 7-6.5s7 2.9 7 6.5"></path></svg>',
    bot: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="8" width="16" height="11" rx="2.5"></rect><line x1="12" y1="3" x2="12" y2="8"></line><circle cx="12" cy="3" r="1.1"></circle><line x1="8" y1="13.5" x2="8" y2="15"></line><line x1="16" y1="13.5" x2="16" y2="15"></line></svg>',
    // Same paperclip glyph as the composer's upload button (index.html) -- reused on the
    // read-only attachment chips appendMessage() renders under a sent user message.
    file: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M21.44 11.05 12.25 20.24a5.5 5.5 0 0 1-7.78-7.78l9.19-9.19a3.67 3.67 0 0 1 5.19 5.19l-9.2 9.19a1.83 1.83 0 0 1-2.59-2.59l8.49-8.48"></path></svg>',
};

const els = {};

function init() {
    cacheElements();
    bindEvents();
    applyTheme();
    renderEmptyState();
    loadHistory();
    initTabs();
    showWelcomeModal();
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
    els.filePane = document.getElementById('filePane');
    els.filePaneTabs = document.getElementById('filePaneTabs');
    els.filePaneFilename = document.getElementById('filePaneFilename');
    els.filePaneCode = document.getElementById('filePaneCode');
    els.filePaneClose = document.getElementById('filePaneClose');
    els.filePaneCopy = document.getElementById('filePaneCopy');
    els.filePaneDownload = document.getElementById('filePaneDownload');
    els.traceToggle = document.getElementById('traceToggle');
    els.tracePane = document.getElementById('tracePane');
    els.tracePaneClose = document.getElementById('tracePaneClose');
    els.tracePaneBody = document.getElementById('tracePaneBody');

    els.tabBtns = Array.from(document.querySelectorAll('.tab-btn'));
    els.tabPanels = {
        chat: document.getElementById('tabPanelChat'),
        about: document.getElementById('tabPanelAbout'),
        retro: document.getElementById('tabPanelRetro'),
    };
    els.aboutContent = document.getElementById('aboutContent');
    els.retroContent = document.getElementById('retroContent');

    els.welcomeModal = document.getElementById('welcomeModal');
    els.welcomeModalOk = document.getElementById('welcomeModalOk');
    els.welcomeModalClose = document.getElementById('welcomeModalClose');
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
    els.filePaneClose.addEventListener('click', closeFilePane);
    els.filePaneCopy.addEventListener('click', copyActiveFile);
    els.filePaneDownload.addEventListener('click', downloadActiveFile);
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && els.filePane.classList.contains('open')) {
            closeFilePane();
        }
    });
    els.traceToggle.addEventListener('click', toggleTracePane);
    els.tracePaneClose.addEventListener('click', closeTracePane);
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && els.tracePane.classList.contains('open')) {
            closeTracePane();
        }
    });
    // Delegated on chatWindow (not per-button) since code blocks get inserted/replaced
    // dynamically -- freshly on every message, and repeatedly per frame during
    // appendMessageTyped()'s reveal animation -- so there's no single stable moment to
    // attach a direct listener to any given button.
    els.chatWindow.addEventListener('click', handleCodeBlockClick);

    // Both buttons just dismiss the welcome modal -- it's purely informational, there's
    // no "don't show again" state to persist, so either one does exactly the same thing.
    els.welcomeModalOk.addEventListener('click', closeWelcomeModal);
    els.welcomeModalClose.addEventListener('click', closeWelcomeModal);
}

/** Shown once at the start of every session (called once from init()) -- a plain-text
 * intro to what the assistant does and how to use it. No "don't show again" checkbox by
 * design: it reappears on every fresh page load. */
function showWelcomeModal() {
    els.welcomeModal.classList.remove('hidden');
}

function closeWelcomeModal() {
    els.welcomeModal.classList.add('hidden');
}

function handleCodeBlockClick(event) {
    const copyBtn = event.target.closest('.code-block-copy');
    if (copyBtn) {
        copySnippet(copyBtn);
        return;
    }
    const downloadBtn = event.target.closest('.code-block-download');
    if (downloadBtn) {
        downloadSnippet(downloadBtn);
    }
}

async function copySnippet(button) {
    const snippet = codeSnippets.get(button.dataset.codeId);
    if (!snippet) return;
    try {
        await navigator.clipboard.writeText(snippet.code);
        const original = button.textContent;
        button.textContent = 'Copied!';
        button.classList.add('copied');
        setTimeout(() => {
            button.textContent = original;
            button.classList.remove('copied');
        }, 1500);
    } catch (error) {
        showToast('Could not copy to clipboard', 'error');
    }
}

function downloadSnippet(button) {
    const snippet = codeSnippets.get(button.dataset.codeId);
    if (!snippet) return;
    const blob = new Blob([snippet.code], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = suggestSnippetFilename(snippet.language);
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
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

/**
 * Tab bar (Chat / About / What I'd Do Differently). Chat is the pre-existing UI, wired
 * up exactly as it was before -- these three functions only add the tab chrome around
 * it. About/Retro fetch README.md lazily (on first visit to either tab, not on page
 * load) and cache it in `readmeState`, so switching tabs back and forth never re-fetches.
 */
// About and Retro are two independent files/endpoints (README.md and
// WHAT_I_WOULD_DO_DIFFERENTLY.md) -- each gets its own cache slot rather than one shared
// state, since there's no single document to split client-side anymore.
const readmeState = {
    markdown: null, // cached raw markdown once fetched successfully
    error: null, // set instead of `markdown` if the fetch/parse failed
    fetchPromise: null, // in-flight fetch, so a rapid double-click can't fire it twice
};
const retroState = {
    markdown: null,
    error: null,
    fetchPromise: null,
};

function initTabs() {
    els.tabBtns.forEach((btn) => {
        btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });
}

function switchTab(tabName) {
    if (!els.tabPanels[tabName]) return;

    els.tabBtns.forEach((btn) => {
        const active = btn.dataset.tab === tabName;
        btn.classList.toggle('active', active);
        btn.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    Object.entries(els.tabPanels).forEach(([name, panel]) => {
        panel.classList.toggle('hidden', name !== tabName);
    });

    if (tabName === 'about') {
        loadMarkdownDoc(readmeState, `${API_BASE}/api/readme`, els.aboutContent, 'README.md');
    } else if (tabName === 'retro') {
        loadMarkdownDoc(
            retroState,
            `${API_BASE}/api/retro`,
            els.retroContent,
            'WHAT_I_WOULD_DO_DIFFERENTLY.md',
        );
    }
}

/** Fetches + caches a markdown doc's raw content into `state` (one of readmeState /
 * retroState), rendering it -- or its error, or a "Loading…" placeholder in the meantime
 * -- into `targetEl` via marked.js. Safe to call repeatedly: a cache hit renders
 * immediately with no request, and a second call while a fetch is already in flight is a
 * no-op (targetEl is already showing "Loading…" from the first call). */
function loadMarkdownDoc(state, url, targetEl, label) {
    if (state.error !== null) {
        targetEl.innerHTML = `<p class="readme-fallback">${escapeHtml(state.error)}</p>`;
        return;
    }
    if (state.markdown !== null) {
        targetEl.innerHTML = renderMarkdown(state.markdown);
        return;
    }
    if (state.fetchPromise) return;

    targetEl.textContent = 'Loading…';

    state.fetchPromise = fetch(url)
        .then(async (response) => {
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data.error || `Request failed with ${response.status}`);
            }
            state.markdown = data.content || '';
            targetEl.innerHTML = renderMarkdown(state.markdown);
        })
        .catch((error) => {
            console.error(error);
            state.error = `Unable to load ${label} right now -- ${error.message || 'the request failed'}.`;
            targetEl.innerHTML = `<p class="readme-fallback">${escapeHtml(state.error)}</p>`;
        })
        .finally(() => {
            state.fetchPromise = null;
        });
}

/** marked.js is loaded from a CDN (see index.html) -- fails soft to escaped plain text
 * if that request was blocked/failed, instead of leaving the tab blank. */
function renderMarkdown(markdown) {
    if (typeof marked === 'undefined') {
        return `<pre class="readme-fallback">${escapeHtml(markdown)}</pre>`;
    }
    return marked.parse(markdown);
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
    loadTrace();
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

// The empty-state placeholder is a real node inside chatWindow (see renderEmptyState()),
// not a CSS-only overlay -- so it has to be explicitly torn down once real messages start
// arriving, or it just sits there above/alongside them. Called from every entry point that
// adds a message to an conversation that might still be showing it.
function clearEmptyState() {
    const emptyState = els.chatWindow.querySelector('.empty-state');
    if (emptyState) emptyState.remove();
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
    (conversation.messages || []).forEach((message, index) => {
        const content = message.content;
        // A structured plan payload (see backend/api/routes.py's
        // _plan_message_payload()) -- rebuild the real plan card instead of dumping
        // its flattened `text` fallback as a plain message.
        if (content && typeof content === 'object' && content.type === 'plan' && content.plan) {
            renderPlanMessage(content.plan, conversationId, content.ticket || '', {
                readOnly: true,
                timestamp: message.timestamp,
            });
        } else if (message.role === 'assistant' && message.files && message.files.length) {
            appendBuildMessage(content, message.timestamp, message.files, conversationId);
        } else {
            const attachments = registerHistoryAttachments(conversationId, index, message.attachments);
            appendMessage(message.role, content, message.timestamp, attachments);
        }
    });
    if (!conversation.messages?.length) {
        renderEmptyState();
    }
    loadTrace();
}

async function sendMessage() {
    const prompt = els.messageInput.value.trim();
    if (!prompt) return;
    if (state.isGenerating || state.pendingPlan) return;

    state.isGenerating = true;
    els.sendBtn.classList.add('hidden');
    els.stopBtn.classList.remove('hidden');

    // Snapshot the attached files before the composer's list is cleared below -- this is
    // what gets built into the request AND (via registerSentAttachment) what renders as
    // the read-only, clickable attachment chips on the message bubble, so the two never
    // disagree about what was actually sent.
    const sentFiles = state.selectedFiles;
    const sentAttachments = await Promise.all(sentFiles.map(registerSentAttachment));

    appendMessage('user', prompt, new Date().toISOString(), sentAttachments);
    els.messageInput.value = '';
    autoResize();
    showTypingIndicator('Reading your message…');

    // Clear the composer's attachment chips now that they've moved to the message bubble
    // above -- otherwise they sit there looking attached to nothing ("frozen") until a
    // full conversation reset, and would silently get re-sent with every message after.
    state.selectedFiles = [];
    renderFiles();

    const formData = new FormData();
    formData.append('user_id', USER_ID);
    formData.append('query', prompt);
    if (state.currentConversationId)
        formData.append('conversation_id', state.currentConversationId);
    sentFiles.forEach((file) => formData.append('file', file));

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
        await loadTrace();
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

// Plans are usually tight now (the Planner's prompt asks for ~3-5 real assumptions and
// ~5-8 coherent tasks), but a genuinely large ticket can still legitimately produce more --
// rather than ever dumping a wall of text, anything past these counts starts collapsed
// behind a "show more" toggle. The extra items are still rendered (just hidden), not
// omitted, so approving the plan still submits all of them -- see collectEditedPlan().
const VISIBLE_ASSUMPTIONS = 4;
const VISIBLE_TASKS = 7;

function renderPlanMessage(plan, conversationId, ticketText, options = {}) {
    // readOnly is set when replaying a saved conversation (selectConversation()) --
    // the plan card looks the same, but Approve/Request changes don't make sense
    // against a reload: plan_cache and any pending in-memory state are long gone, and
    // the composer shouldn't lock up over a conversation the user is just reviewing.
    const { readOnly = false, timestamp = null } = options;
    const assumptions = plan.assumptions || [];
    const tasks = plan.tasks || [];
    const extraAssumptionsCount = Math.max(0, assumptions.length - VISIBLE_ASSUMPTIONS);
    const extraTasksCount = Math.max(0, tasks.length - VISIBLE_TASKS);

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
        <ul class="plan-assumptions">
          ${assumptions
              .map(
                  (a, i) =>
                      `<li${i >= VISIBLE_ASSUMPTIONS ? ' class="plan-extra hidden"' : ''}>${escapeHtml(a)}</li>`,
              )
              .join('')}
        </ul>
        ${
            extraAssumptionsCount
                ? `<button type="button" class="plan-show-more" data-section="assumptions">Show ${extraAssumptionsCount} more assumption${extraAssumptionsCount > 1 ? 's' : ''}</button>`
                : ''
        }
      </div>`
            : ''
    }
    <div class="plan-section">
      <h5>Tasks</h5>
      <ul class="plan-tasks"></ul>
      ${
          extraTasksCount
              ? `<button type="button" class="plan-show-more" data-section="tasks">Show ${extraTasksCount} more task${extraTasksCount > 1 ? 's' : ''}</button>`
              : ''
      }
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
    <div class="message-meta">${timestamp ? new Date(timestamp).toLocaleString() : new Date().toLocaleString()}</div>
  `;

    const taskList = card.querySelector('.plan-tasks');
    tasks.forEach((task, i) => {
        const item = document.createElement('li');
        item.className = i >= VISIBLE_TASKS ? 'plan-task plan-extra hidden' : 'plan-task';
        item.dataset.taskId = task.id || '';
        item.innerHTML = `
      <span class="plan-task-id">${escapeHtml(task.id || '')}</span>
      <div class="plan-task-desc" contenteditable="true">${escapeHtml(task.description || '')}</div>
    `;
        taskList.appendChild(item);
    });

    card.querySelectorAll('.plan-show-more').forEach((btn) => {
        btn.addEventListener('click', () => {
            const section = btn.closest('.plan-section');
            section.querySelectorAll('.plan-extra').forEach((el) => el.classList.remove('hidden'));
            btn.remove();
        });
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

    if (readOnly) {
        // Same muted, non-interactive look as a plan that was already resolved in a
        // live session (buttons disabled, tasks no longer editable) -- reuses
        // lockPlanCard() rather than duplicating that styling logic.
        lockPlanCard(card);
    } else {
        state.pendingPlan = { conversationId };
        setComposerLocked(true);
    }
}

function lockPlanCard(card) {
    // Excludes .plan-show-more -- those just reveal already-rendered list items and
    // aren't part of the plan's editable/submittable state, so they should stay
    // clickable even on a resolved/read-only card (otherwise revisiting a past
    // conversation leaves "Show N more..." looking clickable but dead).
    card.querySelectorAll('button:not(.plan-show-more)').forEach((btn) => (btn.disabled = true));
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

    const live = createLiveBuildMessage(conversationId);

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
        await loadTrace();
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
        await loadTrace();
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

const LANGUAGE_BY_EXTENSION = {
    js: 'javascript',
    jsx: 'javascript',
    ts: 'typescript',
    tsx: 'typescript',
    py: 'python',
    json: 'json',
    css: 'css',
    html: 'html',
    md: 'markdown',
    sql: 'sql',
    sh: 'bash',
    yml: 'yaml',
    yaml: 'yaml',
};

function inferLanguage(path) {
    const ext = (path.split('.').pop() || '').toLowerCase();
    return LANGUAGE_BY_EXTENSION[ext] || 'text';
}

function countLines(content) {
    return content ? content.split('\n').length : 0;
}

// Mirrors backend/api/routes.py's MAX_ATTACHMENT_CHARS / binary-format sniffing -- kept in
// sync by hand since this is only a client-side preview convenience, not what the model
// actually sees (that's decoded server-side, more robustly -- see _extract_attachment()).
const MAX_ATTACHMENT_PREVIEW_CHARS = 20_000;
const UNREADABLE_ATTACHMENT_TYPES = /^image\/|^application\/pdf$|officedocument|^application\/zip$/;

function looksBinary(file) {
    if (file.type) return UNREADABLE_ATTACHMENT_TYPES.test(file.type);
    // Some OS/browser combos don't report a MIME type at all -- fall back to extension.
    const ext = (file.name.split('.').pop() || '').toLowerCase();
    return ['pdf', 'png', 'jpg', 'jpeg', 'gif', 'docx', 'xlsx', 'pptx', 'zip'].includes(ext);
}

/**
 * Registers a just-selected File into fileStore under a fresh id so its composer chip
 * (rendered on the just-sent message, see sendMessage()) is clickable immediately,
 * without waiting on a server round-trip. Reads the file client-side (best-effort, UTF-8
 * only via File.text() -- unlike the backend's multi-encoding fallback in
 * _extract_attachment(), so a rare non-UTF-8 text file may preview with minor mojibake
 * here even though the model/DB got it decoded correctly). Recognized binary types get a
 * placeholder instead of raw garbage bytes.
 */
async function registerSentAttachment(file) {
    const fileId = `sent-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    let content;
    if (looksBinary(file)) {
        const ext = (file.name.split('.').pop() || 'file').toUpperCase();
        content = `Preview not available for this file type (${ext}).`;
    } else {
        try {
            const text = await file.text();
            content =
                text.length > MAX_ATTACHMENT_PREVIEW_CHARS
                    ? `${text.slice(0, MAX_ATTACHMENT_PREVIEW_CHARS)}\n\n[...truncated]`
                    : text;
        } catch (error) {
            content = 'Preview not available for this file.';
        }
    }
    fileStore.set(fileId, { id: fileId, path: file.name, content, language: inferLanguage(file.name) });
    return { name: file.name, fileId };
}

/**
 * Registers a past conversation's persisted attachments (see backend/api/routes.py's
 * _extract_attachment()/record_message()) into fileStore so their chips are clickable on
 * history replay too -- same fileStore/openFilePane mechanism as a just-sent message's,
 * just sourced from the server's more robust decode instead of a fresh browser File.
 * `msgIndex` namespaces the ids so the same filename in two different messages (or two
 * different conversations) never collides in fileStore.
 */
function registerHistoryAttachments(conversationId, msgIndex, rawAttachments) {
    if (!rawAttachments || !rawAttachments.length) return null;
    return rawAttachments.map((attachment, attIndex) => {
        const fileId = `hist-${conversationId}-${msgIndex}-${attIndex}`;
        const content = attachment.readable
            ? `${attachment.text || ''}${attachment.truncated ? '\n\n[...truncated]' : ''}`
            : `Preview not available for this file${attachment.kind ? ` (${attachment.kind})` : ''}.`;
        fileStore.set(fileId, {
            id: fileId,
            path: attachment.name,
            content,
            language: attachment.readable ? inferLanguage(attachment.name) : 'text',
        });
        return { name: attachment.name, fileId };
    });
}

/**
 * Opens the file pane on `fileId` (adding it as a tab if it isn't already open) and
 * makes it the active tab. Safe to call repeatedly for the same file -- e.g. a retry
 * rewriting a file that's already open just refreshes its content in place.
 */
function openFilePane(fileId) {
    if (!openFileIds.includes(fileId)) openFileIds.push(fileId);
    activeFileId = fileId;
    renderFilePane();
}

function closeFilePane() {
    openFileIds = [];
    activeFileId = null;
    els.filePane.classList.remove('open');
    els.filePane.setAttribute('aria-hidden', 'true');
    renderFileRowActiveStates();
}

/** Closes just one tab -- unlike closeFilePane() (the pane's own "x", which closes
 * everything), this leaves the rest of openFileIds untouched. Falls back to
 * closeFilePane() when the closed tab was the last one open, since an empty pane isn't
 * a meaningful state to render. If the closed tab was the active one, activates
 * whichever tab now sits in the same slot -- the next tab over, or the new last tab if
 * it was the rightmost. */
function closeFileTab(fileId) {
    const index = openFileIds.indexOf(fileId);
    if (index === -1) return;
    openFileIds.splice(index, 1);

    if (!openFileIds.length) {
        closeFilePane();
        return;
    }

    if (activeFileId === fileId) {
        activeFileId = openFileIds[Math.min(index, openFileIds.length - 1)];
    }
    renderFilePane();
}

function switchFileTab(fileId) {
    activeFileId = fileId;
    renderFilePane();
}

async function copyActiveFile() {
    const file = fileStore.get(activeFileId);
    if (!file) return;
    try {
        await navigator.clipboard.writeText(file.content);
        const original = els.filePaneCopy.textContent;
        els.filePaneCopy.textContent = 'Copied!';
        els.filePaneCopy.classList.add('copied');
        setTimeout(() => {
            els.filePaneCopy.textContent = original;
            els.filePaneCopy.classList.remove('copied');
        }, 1500);
    } catch (error) {
        showToast('Could not copy to clipboard', 'error');
    }
}

function downloadActiveFile() {
    const file = fileStore.get(activeFileId);
    if (!file) return;
    const blob = new Blob([file.content], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = file.path.split('/').pop() || 'file.txt';
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
}

/** Re-renders the pane's tabs + content from fileStore/openFileIds/activeFileId -- the
 * only place that reads file content for display, so it's never duplicated elsewhere. */
function renderFilePane() {
    const file = fileStore.get(activeFileId);
    if (!file) return;

    els.filePane.classList.add('open');
    els.filePane.removeAttribute('aria-hidden');

    els.filePaneTabs.innerHTML = '';
    if (openFileIds.length > 1) {
        openFileIds.forEach((id) => {
            const tabFile = fileStore.get(id);
            if (!tabFile) return;

            const tab = document.createElement('div');
            tab.className = `file-pane-tab ${id === activeFileId ? 'active' : ''}`;
            tab.title = tabFile.path;

            const selectBtn = document.createElement('button');
            selectBtn.type = 'button';
            selectBtn.className = 'file-pane-tab-select';
            selectBtn.textContent = tabFile.path.split('/').pop();
            selectBtn.addEventListener('click', () => switchFileTab(id));

            const closeBtn = document.createElement('button');
            closeBtn.type = 'button';
            closeBtn.className = 'file-pane-tab-close';
            closeBtn.innerHTML = ICONS.close;
            closeBtn.setAttribute('aria-label', `Close ${tabFile.path}`);
            closeBtn.addEventListener('click', (event) => {
                event.stopPropagation();
                closeFileTab(id);
            });

            tab.appendChild(selectBtn);
            tab.appendChild(closeBtn);
            els.filePaneTabs.appendChild(tab);
        });
    }

    els.filePaneFilename.textContent = file.path;
    els.filePaneCode.textContent = file.content;
    els.filePaneCode.className = `language-${file.language}`;
    renderFileRowActiveStates();
}

/** Highlights whichever chat row(s) match the file pane's currently active file, across
 * every build message rendered so far -- not just the one that opened the pane. */
function renderFileRowActiveStates() {
    document.querySelectorAll('.build-file-row').forEach((row) => {
        row.classList.toggle('active', row.dataset.fileId === activeFileId);
    });
}

/**
 * Renders one clickable row per file into `container` -- the single code path for
 * "files a build touched, shown as compact chips", shared by the live build message
 * (createLiveBuildMessage()'s upsertFile(), called again on every new "file" SSE event)
 * and history replay (selectConversation(), called once off a message's persisted
 * `files` list). Always re-renders `container` from scratch off `files`; callers own
 * the array itself.
 *
 * Each entry is either:
 *   - { path, fileId, lines } -- content already sitting in fileStore under fileId (the
 *     live case), so a click just opens the pane straight from there, or
 *   - { path } alone -- a replayed file whose content hasn't been fetched yet; a click
 *     lazily loads it from GET /workspace_file (see openWorkspaceFile()) instead.
 */
function renderFileChips(container, files, { conversationId } = {}) {
    container.innerHTML = '';
    files.forEach(({ path, fileId, lines }) => {
        const row = document.createElement('button');
        row.type = 'button';
        row.className = 'build-file-row';
        row.dataset.fileId = fileId || '';
        row.innerHTML = `
      <code class="build-file-row-path">${escapeHtml(path)}</code>
      ${typeof lines === 'number' ? `<span class="build-file-row-meta">${lines} line${lines === 1 ? '' : 's'}</span>` : ''}
    `;
        row.addEventListener('click', () => {
            if (fileId && fileStore.has(fileId)) {
                openFilePane(fileId);
            } else {
                openWorkspaceFile(conversationId, path);
            }
        });
        container.appendChild(row);
    });
}

/**
 * Lazily fetches a replayed build file's current content from the backend the first
 * time its chip is clicked (GET /workspace_file, backend/api/routes.py), caches it into
 * fileStore under a stable id keyed by conversation+path, then opens it in the same
 * file pane a live build's chip would. Safe to call repeatedly for the same file -- a
 * second click just finds it already in fileStore and opens straight from there, no
 * second request.
 */
async function openWorkspaceFile(conversationId, path) {
    const fileId = `ws-${conversationId}-${path}`;
    if (fileStore.has(fileId)) {
        openFilePane(fileId);
        return;
    }
    try {
        const response = await fetch(
            `${API_BASE}/workspace_file?conversation_id=${encodeURIComponent(conversationId)}&path=${encodeURIComponent(path)}`,
        );
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || `Request failed with ${response.status}`);
        fileStore.set(fileId, { id: fileId, path, content: data.content, language: inferLanguage(path) });
        openFilePane(fileId);
    } catch (error) {
        console.error(error);
        showToast('Unable to load this file', 'error');
    }
}

/**
 * The "agent trace" panel -- WHY each agent decided what it decided this conversation,
 * grouped by chat turn (GET /trace, backed by agent_traces; see
 * agents/ticket_pipeline/flow.py's TicketState.trace and backend/services/research.py
 * for what gets recorded). Deliberately separate from the chat transcript, and
 * deliberately short per step -- the actual chat/build response text lives in the
 * transcript already, this never duplicates it. Opened from the panel-heading button,
 * not from within any message, and only ever fetched while open.
 */
async function toggleTracePane() {
    if (els.tracePane.classList.contains('open')) {
        closeTracePane();
    } else {
        openTracePane();
    }
}

function closeTracePane() {
    els.tracePane.classList.remove('open');
    els.tracePane.setAttribute('aria-hidden', 'true');
    els.traceToggle.classList.remove('active');
}

async function openTracePane() {
    els.tracePane.classList.add('open');
    els.tracePane.removeAttribute('aria-hidden');
    els.traceToggle.classList.add('active');
    await loadTrace();
}

/** Refetches and re-renders the trace, but only when the panel is actually open -- safe
 * to call after every turn completes (see sendMessage()/approvePlan()/requestPlanChanges())
 * without wasting a request when nobody's looking at it. */
async function loadTrace() {
    if (!els.tracePane.classList.contains('open')) return;

    if (!state.currentConversationId) {
        els.tracePaneBody.innerHTML =
            '<div class="trace-empty">Send a message first -- the trace fills in as the Planner, Coder, and Reviewer make decisions.</div>';
        return;
    }

    try {
        const response = await fetch(
            `${API_BASE}/trace?user_id=${encodeURIComponent(USER_ID)}&conversation_id=${encodeURIComponent(state.currentConversationId)}`,
        );
        const data = await response.json();
        renderTrace(data.turns || []);
    } catch (error) {
        console.error(error);
        els.tracePaneBody.innerHTML =
            '<div class="trace-empty">Unable to load the agent trace.</div>';
    }
}

/**
 * Renders the trace grouped by chat turn (GET /trace already groups it server-side --
 * see backend/services/chat.py's get_trace()). Each turn renders as either:
 *   - a compact one-line row, for a CHAT/SNIPPET turn that never left the Intent
 *     classifier (identified by its ROUTER marker step), or
 *   - an expanded set of per-agent step cards, for a TICKET turn (Planner, then
 *     Coder/Reviewer -- possibly repeated across retry rounds -- then SYSTEM if retries
 *     were exhausted).
 */
function renderTrace(turns) {
    if (!turns.length) {
        els.tracePaneBody.innerHTML =
            '<div class="trace-empty">No agent activity recorded yet for this conversation.</div>';
        return;
    }
    els.tracePaneBody.innerHTML = turns.map(renderTraceTurn).join('');
}

function renderTraceTurn(turn) {
    const steps = turn.steps || [];
    const isDirectResponse = steps.some((step) => step.agent === 'ROUTER');
    return isDirectResponse ? renderCompactTurn(steps) : renderExpandedTurn(steps);
}

/** CHAT/SNIPPET turn: the Intent classifier's decision was the whole story -- one small,
 * visually muted row (badge + one-line reasoning), signaling "nothing more happened
 * here" rather than competing for attention with an actual TICKET turn's step cards. */
function renderCompactTurn(steps) {
    const intentStep = steps.find((step) => step.agent === 'INTENT');
    if (!intentStep) return '';
    return `
    <div class="trace-turn trace-turn-compact">
      <span class="trace-badge trace-badge-intent">${escapeHtml(intentStep.decision || 'INTENT')}</span>
      <span class="trace-compact-reasoning">${escapeHtml(intentStep.reasoning || '')}</span>
      <span class="trace-step-time">${escapeHtml(formatTraceTime(intentStep.timestamp))}</span>
    </div>
  `;
}

/**
 * TICKET turn: one card per step, in the order they were recorded (INTENT, PLANNER,
 * then CODER/REVIEWER, then SYSTEM if present). A CODER step and the REVIEWER step that
 * immediately follows it are rendered together as one numbered "round" -- rounds increment
 * per CODER step encountered, which is how a Reviewer-rejected retry loop shows up without
 * the backend having to name the round number explicitly.
 */
function renderExpandedTurn(steps) {
    const cards = [];
    let round = 0;

    for (let i = 0; i < steps.length; i++) {
        const step = steps[i];
        if (step.agent === 'CODER') {
            round += 1;
            const next = steps[i + 1];
            const reviewerStep = next && next.agent === 'REVIEWER' ? next : null;
            cards.push(renderRound(round, step, reviewerStep));
            if (reviewerStep) i += 1; // already rendered as part of this round
        } else {
            cards.push(renderStepCard(step));
        }
    }

    return `<div class="trace-turn trace-turn-expanded">${cards.join('')}</div>`;
}

function renderRound(roundNumber, coderStep, reviewerStep) {
    return `
    <div class="trace-round">
      <div class="trace-round-label">Round ${roundNumber}</div>
      <div class="trace-round-steps">
        ${renderStepCard(coderStep)}
        ${reviewerStep ? '<span class="trace-round-arrow">&rarr;</span>' + renderStepCard(reviewerStep) : ''}
      </div>
    </div>
  `;
}

const AGENT_BADGE_CLASS = {
    INTENT: 'trace-badge-intent',
    ROUTER: 'trace-badge-router',
    PLANNER: 'trace-badge-planner',
    CODER: 'trace-badge-coder',
    REVIEWER: 'trace-badge-reviewer',
    SYSTEM: 'trace-badge-system',
};

const DECISION_CLASS = {
    approved: 'approved',
    rejected: 'rejected',
    max_retries_reached: 'warning',
};

function renderStepCard(step) {
    const badgeClass = AGENT_BADGE_CLASS[step.agent] || 'trace-badge-default';
    const decisionClass = DECISION_CLASS[step.decision] || '';
    return `
    <div class="trace-step-card">
      <div class="trace-step-card-head">
        <span class="trace-badge ${badgeClass}">${escapeHtml(step.agent || 'AGENT')}</span>
        <span class="trace-decision ${decisionClass}">${escapeHtml(step.decision || '')}</span>
        <span class="trace-step-time">${escapeHtml(formatTraceTime(step.timestamp))}</span>
      </div>
      <p class="trace-reasoning">${escapeHtml(step.reasoning || '')}</p>
    </div>
  `;
}

function formatTraceTime(timestamp) {
    return timestamp ? new Date(timestamp).toLocaleString() : '';
}

/**
 * A chat bubble that fills in live as /build/stream sends events: a status line that
 * updates in place (replacing the old fixed "typing" dots for this phase), and a compact,
 * clickable row appearing the moment the Coder writes a file -- full content lives only in
 * the file pane (see openFilePane()/renderFilePane()), so a build with dozens of files
 * stays scannable instead of turning the chat into an unusable code dump.
 */
function createLiveBuildMessage(conversationId) {
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
    // This build's files so far, in first-written order -- re-rendered via
    // renderFileChips() on every new "file" event rather than patched incrementally, so
    // live and replay share the exact same rendering path.
    const filesSoFar = [];
    // Namespaces this build's file ids so the same path from a different build (e.g. an
    // earlier turn, or a different conversation) never collides with this one in fileStore.
    const buildId = `build-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

    const scrollDown = () => {
        els.chatWindow.scrollTop = els.chatWindow.scrollHeight;
    };

    // Starts ticking immediately under "Starting…", same as every later setStatus() call --
    // so the countup is live from the moment this card appears, not just once the first
    // "phase" event arrives.
    startPhaseTimer('Starting…', (text) => {
        statusLabel.textContent = text;
    });

    return {
        setStatus(label) {
            startPhaseTimer(label, (text) => {
                statusLabel.textContent = text;
            });
            scrollDown();
        },
        upsertFile(path, content) {
            const fileId = `${buildId}:${path}`;
            fileStore.set(fileId, { id: fileId, path, content, language: inferLanguage(path) });

            const lines = countLines(content);
            const existing = filesSoFar.find((f) => f.path === path);
            if (existing) {
                existing.lines = lines;
            } else {
                filesSoFar.push({ path, fileId, lines });
            }
            renderFileChips(filesEl, filesSoFar, { conversationId });

            // A retry can rewrite a file that's already open in the pane -- keep it live
            // instead of leaving a stale view up.
            if (activeFileId === fileId) renderFilePane();

            scrollDown();
        },
        finish(event) {
            stopPhaseTimer();
            card.classList.remove('build-live');
            statusRow.classList.add('hidden');
            summaryEl.classList.remove('hidden');
            const summaryText = event.result || event.error || 'No result';
            // event.error's text is a friendly failure message, never a fenced block --
            // only the success path (event.result, the Coder's own summary) needs
            // stripping, but running both through it is harmless either way.
            summaryEl.innerHTML = formatMessage(stripCodeFences(summaryText));
            if (event.approved === false) card.classList.add('build-not-approved');
            metaEl.textContent = new Date().toLocaleString();
            scrollDown();
        },
        fail(message) {
            stopPhaseTimer();
            card.classList.remove('build-live');
            statusRow.classList.add('build-error');
            statusLabel.textContent = message || 'Build failed';
            metaEl.textContent = new Date().toLocaleString();
            scrollDown();
        },
    };
}

/**
 * Replay counterpart to createLiveBuildMessage() -- renders a past build turn's file
 * chips + summary in one shot from a persisted message, instead of filling in live over
 * an SSE stream. Used by selectConversation() whenever a saved assistant message
 * carries a `files` list (see backend/api/routes.py's /build/stream, which is what
 * persists it). Chips start as `{ path }` only -- content isn't stored in the DB, so
 * each one's content is fetched from GET /workspace_file lazily, on click (see
 * renderFileChips()/openWorkspaceFile()), exactly like a live build's chips are already
 * clickable from content it has in hand.
 */
function appendBuildMessage(content, timestamp, files, conversationId) {
    clearEmptyState();
    const row = document.createElement('div');
    row.className = 'message-row';
    const card = document.createElement('div');
    card.className = 'message-card';
    card.innerHTML = `
    <div class="message-card-head">${ICONS.bot}<h4>Agent</h4></div>
    <div class="build-files"></div>
    <div class="build-summary">${formatMessage(stripCodeFences(typeof content === 'string' ? content : JSON.stringify(content)))}</div>
    <div class="message-meta">${timestamp ? new Date(timestamp).toLocaleString() : ''}</div>
  `;
    row.appendChild(card);
    els.chatWindow.appendChild(row);

    const filesEl = card.querySelector('.build-files');
    renderFileChips(filesEl, files.map((path) => ({ path })), { conversationId });

    els.chatWindow.scrollTop = els.chatWindow.scrollHeight;
}

/**
 * Read-only "N file(s) attached to this turn" chip row, rendered under a sent user
 * message so the attachment isn't just a fire-and-forget -- see appendMessage()'s
 * `attachments` param. Unlike the composer's own .file-chip (which has a remove button),
 * each chip here is itself a button that opens the file pane on click -- clickability
 * requires the entry to already be registered in fileStore under `fileId` (see
 * registerSentAttachment() for a just-sent message, registerHistoryAttachments() for one
 * loaded from a past conversation) BEFORE this renders, since wireMessageAttachments()
 * below only wires up the click, it doesn't create the fileStore entry itself.
 */
function renderMessageAttachments(attachments) {
    if (!attachments || !attachments.length) return '';
    const chips = attachments
        .map(
            ({ name, fileId }) =>
                `<button type="button" class="file-chip message-attachment-chip" data-file-id="${escapeHtml(fileId)}">${ICONS.file}<span>${escapeHtml(name)}</span></button>`,
        )
        .join('');
    return `<div class="file-list message-attachments">${chips}</div>`;
}

/** Wires each attachment chip's click -> openFilePane(fileId) -- separate from
 * renderMessageAttachments() because innerHTML-inserted markup carries no listeners. */
function wireMessageAttachments(card) {
    card.querySelectorAll('.message-attachment-chip').forEach((chip) => {
        chip.addEventListener('click', () => openFilePane(chip.dataset.fileId));
    });
}

function appendMessage(role, content, timestamp, attachments) {
    clearEmptyState();
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
    ${renderMessageAttachments(attachments)}
    <div class="message-meta">${timestamp ? new Date(timestamp).toLocaleString() : 'just now'}</div>
  `;
    row.appendChild(card);
    wireMessageAttachments(card);
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
    clearEmptyState();
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

// Raw (un-escaped) code behind every rendered code block, keyed by an id embedded in
// the block's Copy/Download buttons -- so those actions always get back exactly what
// the model wrote, never the HTML-escaped display text. Not scoped per-message since
// ids are unique across the whole session; stale entries from replaced/re-rendered
// blocks (e.g. every frame of appendMessageTyped()'s reveal animation) just sit unused,
// which is harmless at chat-app scale.
const codeSnippets = new Map(); // id -> { code, language }
let codeSnippetCounter = 0;

const FILE_EXTENSION_BY_LANGUAGE = {
    python: 'py',
    py: 'py',
    javascript: 'js',
    js: 'js',
    jsx: 'jsx',
    typescript: 'ts',
    ts: 'ts',
    tsx: 'tsx',
    json: 'json',
    css: 'css',
    html: 'html',
    markdown: 'md',
    md: 'md',
    bash: 'sh',
    sh: 'sh',
    shell: 'sh',
    sql: 'sql',
    yaml: 'yml',
    yml: 'yml',
    go: 'go',
    java: 'java',
    c: 'c',
    cpp: 'cpp',
    rust: 'rs',
    ruby: 'rb',
    php: 'php',
};

/**
 * Strips fenced code blocks (```…```) out of a build's summary text before it's
 * rendered in the chat bubble. The Coder's task asks for a short plain-text summary
 * (see agents/ticket_pipeline/tasks.py's build_code_task expected_output), but the LLM
 * doesn't always follow that -- it sometimes still wraps a one-line-per-file rundown (or
 * worse, real content) in a fenced block, which formatMessage() would otherwise render
 * as a full code block with its own Copy/Download toolbar, duplicating exactly what the
 * .build-files chips + file pane already show, just less usably. Only ever applied to
 * build-result text (createLiveBuildMessage().finish() / appendBuildMessage()) -- never
 * to chat/snippet replies, which have no chips backing them and are expected to show
 * real code inline.
 */
function stripCodeFences(text) {
    const stripped = text.replace(/```[\s\S]*?```/g, '').trim();
    return stripped || 'Done -- see the files above.';
}

function suggestSnippetFilename(language) {
    const ext = FILE_EXTENSION_BY_LANGUAGE[(language || '').toLowerCase()] || 'txt';
    return `snippet.${ext}`;
}

/** Renders one fenced code block as a toolbar (language label + Copy/Download) over a
 * <pre><code> -- `code` is the RAW, not-yet-escaped block content. */
function renderCodeBlock(code, language) {
    const id = `code-${codeSnippetCounter++}`;
    codeSnippets.set(id, { code, language: language || '' });
    return `
    <div class="code-block">
      <div class="code-block-toolbar">
        <span class="code-block-lang">${escapeHtml(language || 'text')}</span>
        <div class="code-block-actions">
          <button type="button" class="code-block-btn code-block-copy" data-code-id="${id}">Copy</button>
          <button type="button" class="code-block-btn code-block-download" data-code-id="${id}">Download</button>
        </div>
      </div>
      <pre><code>${escapeHtml(code)}</code></pre>
    </div>
  `;
}

function formatMessage(content) {
    // Fenced code blocks are pulled out of the RAW text first (before HTML-escaping or
    // the newline -> <br> pass below run on everything else), both so Copy/Download get
    // pristine code and so a code block's internal newlines never get corrupted into
    // <br> tags. A null-byte-delimited placeholder holds each block's place until the
    // rest of the message has been escaped/formatted, then it's swapped back in.
    const blocks = [];
    const withPlaceholders = content.replace(
        /```(\w+)?\n?([\s\S]*?)```/g,
        (_match, lang, code) => {
            const index = blocks.length;
            blocks.push(renderCodeBlock(code.replace(/\n$/, ''), lang));
            return ` CODEBLOCK${index} `;
        },
    );

    const escaped = escapeHtml(withPlaceholders);
    const withInline = escaped
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/\*([^*]+)\*/g, '<em>$1</em>')
        .replace(/\n/g, '<br>');

    const restored = withInline.replace(
        / CODEBLOCK(\d+) /g,
        (_match, index) => blocks[Number(index)],
    );

    return `<div>${restored}</div>`;
}

function escapeHtml(value) {
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// Ticks "<label> · Ns" once a second, restarting from 0s every time a new phase begins --
// reassures the user that a long-running phase (an LLM call, a file write) is still
// moving, not frozen. Only one phase indicator (typing indicator or live build status) is
// ever on screen at a time, so a single module-level interval is enough; starting a new
// one always tears down whatever was running before.
let phaseTimerId = null;

function stopPhaseTimer() {
    if (phaseTimerId !== null) {
        clearInterval(phaseTimerId);
        phaseTimerId = null;
    }
}

function startPhaseTimer(label, onTick) {
    stopPhaseTimer();
    const startedAt = Date.now();
    const tick = () => onTick(`${label} · ${Math.floor((Date.now() - startedAt) / 1000)}s`);
    tick();
    phaseTimerId = setInterval(tick, 1000);
}

function showTypingIndicator(label) {
    removeTypingIndicator();
    const node = document.createElement('div');
    node.className = 'typing-indicator';
    node.id = 'typingIndicator';
    node.innerHTML = `<span></span><span></span><span></span>${label ? '<em></em>' : ''}`;
    els.chatWindow.appendChild(node);
    els.chatWindow.scrollTop = els.chatWindow.scrollHeight;

    if (label) {
        const labelEl = node.querySelector('em');
        startPhaseTimer(label, (text) => {
            labelEl.textContent = text;
        });
    }
}

function removeTypingIndicator() {
    stopPhaseTimer();
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
