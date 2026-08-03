const API_BASE = '';
const state = {
    conversations: [],
    currentConversationId: null,
    activePanel: true,
    isGenerating: false,
    selectedFiles: [],
    theme: localStorage.getItem('agent-theme') || 'dark',
};

const els = {};

function init() {
    cacheElements();
    bindEvents();
    applyTheme();
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
    els.agentPanel = document.getElementById('agentPanel');
    els.panelToggle = document.getElementById('panelToggle');
    els.agentStatus = document.getElementById('agentStatus');
    els.taskStatus = document.getElementById('taskStatus');
    els.toolStatus = document.getElementById('toolStatus');
    els.sqlStatus = document.getElementById('sqlStatus');
    els.timeline = document.getElementById('timeline');
    els.toastContainer = document.getElementById('toastContainer');
    els.emptyState = document.getElementById('emptyState');
}

function bindEvents() {
    els.newChatBtn.addEventListener('click', startNewConversation);
    els.themeBtn.addEventListener('click', toggleTheme);
    els.sendBtn.addEventListener('click', sendMessage);
    els.stopBtn.addEventListener('click', stopGeneration);
    els.messageInput.addEventListener('keydown', handleComposerKeydown);
    els.messageInput.addEventListener('input', autoResize);
    els.fileInput.addEventListener('change', handleFileSelection);
    els.panelToggle.addEventListener('click', toggleAgentPanel);
    els.searchInput.addEventListener('input', renderConversations);
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
    document.documentElement.classList.toggle('light', state.theme === 'light');
    els.themeBtn.textContent = state.theme === 'light' ? '☀️ Light' : '🌙 Dark';
}

function toggleTheme() {
    state.theme = state.theme === 'dark' ? 'light' : 'dark';
    localStorage.setItem('agent-theme', state.theme);
    applyTheme();
    showToast('Theme updated', 'success');
}

function startNewConversation() {
    state.currentConversationId = null;
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
        const response = await fetch(`${API_BASE}/get_history`);
        const data = await response.json();
        state.conversations = Array.isArray(data.history) ? data.history : [];
        renderConversations();
        if (!state.currentConversationId && state.conversations.length) {
            selectConversation(state.conversations[0].conversation_id);
        }
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
        const item = document.createElement('button');
        item.className = `conversation-item ${conversation.conversation_id === state.currentConversationId ? 'active' : ''}`;
        item.innerHTML = `
      <span style="text-align:left; flex:1;">
        <h4>${escapeHtml(conversation.summary || 'Conversation')}</h4>
        <p>${(conversation.messages || []).length} messages</p>
      </span>
    `;
        item.addEventListener('click', () =>
            selectConversation(conversation.conversation_id),
        );
        els.conversationList.appendChild(item);
    });
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
    if (state.isGenerating) return;

    state.isGenerating = true;
    els.sendBtn.classList.add('hidden');
    els.stopBtn.classList.remove('hidden');
    appendMessage('user', prompt, new Date().toISOString());
    els.messageInput.value = '';
    showTypingIndicator();
    updateAgentTimeline('Research workflow started', 'active');
    updatePanel('agentStatus', 'Active agent', 'Intent Classifier');
    updatePanel(
        'taskStatus',
        'Current task',
        'Classifying intent and routing the request',
    );
    updatePanel('toolStatus', 'Tools', 'Schema inspection • Query planning');
    updatePanel('sqlStatus', 'SQL status', 'Preparing execution plan');

    const formData = new FormData();
    formData.append('user_id', '1');
    formData.append('query', prompt);
    if (state.currentConversationId)
        formData.append('conversation_id', state.currentConversationId);
    state.selectedFiles.forEach((file) => formData.append('file', file));

    try {
        const response = await fetch(`${API_BASE}/run`, {
            method: 'POST',
            body: formData,
        });
        const data = await response.json();
        removeTypingIndicator();
        appendMessage(
            'assistant',
            data.result || data.summary || 'No answer available',
            new Date().toISOString(),
        );
        if (!state.currentConversationId) {
            state.currentConversationId = data.conversation_id;
        }
        await loadHistory();
        updateAgentTimeline('Research workflow completed', 'done');
        updatePanel('agentStatus', 'Active agent', 'Completed');
        updatePanel('taskStatus', 'Current task', 'Final answer returned');
        showToast('Response ready', 'success');
    } catch (error) {
        removeTypingIndicator();
        updateAgentTimeline('Research workflow failed', 'error');
        showToast('The request could not be completed', 'error');
    } finally {
        state.isGenerating = false;
        els.sendBtn.classList.remove('hidden');
        els.stopBtn.classList.add('hidden');
    }
}

function stopGeneration() {
    state.isGenerating = false;
    removeTypingIndicator();
    els.sendBtn.classList.remove('hidden');
    els.stopBtn.classList.add('hidden');
    updateAgentTimeline('Generation stopped by user', 'error');
}

function appendMessage(role, content, timestamp) {
    const safeContent =
        typeof content === 'string' ? content : JSON.stringify(content);
    const row = document.createElement('div');
    row.className = `message-row ${role === 'user' ? 'user' : ''}`;
    const card = document.createElement('div');
    card.className = 'message-card';
    card.innerHTML = `
    <h4>${role === 'user' ? 'You' : 'Agent'}</h4>
    <div class="message-body">${formatMessage(safeContent)}</div>
    <div class="message-meta">${timestamp ? new Date(timestamp).toLocaleString() : 'just now'}</div>
  `;
    row.appendChild(card);
    els.chatWindow.appendChild(row);
    els.chatWindow.scrollTop = els.chatWindow.scrollHeight;
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

function showTypingIndicator() {
    removeTypingIndicator();
    const node = document.createElement('div');
    node.className = 'typing-indicator';
    node.id = 'typingIndicator';
    node.innerHTML = '<span></span><span></span><span></span>';
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
        chip.innerHTML = `<span>${escapeHtml(file.name)}</span><button type="button" data-name="${escapeHtml(file.name)}">✕</button>`;
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

function toggleAgentPanel() {
    state.activePanel = !state.activePanel;
    els.agentPanel.classList.toggle('collapsed', !state.activePanel);
    els.panelToggle.textContent = state.activePanel
        ? 'Hide agent trace'
        : 'Show agent trace';
}

function updatePanel(containerId, title, value) {
    const element = document.getElementById(containerId);
    if (element)
        element.innerHTML = `<h4>${escapeHtml(title)}</h4><p>${escapeHtml(value)}</p>`;
}

function updateAgentTimeline(message, stateValue) {
    const item = document.createElement('li');
    item.className = `timeline-item ${stateValue}`;
    item.innerHTML = `<span class="dot"></span><span>${escapeHtml(message)}</span>`;
    els.timeline.prepend(item);
}

function showToast(message, type = 'success') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    els.toastContainer.appendChild(toast);
    setTimeout(() => toast.remove(), 2600);
}

document.addEventListener('DOMContentLoaded', init);
