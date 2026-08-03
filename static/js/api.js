const api = {
    async getHistory() {
        const response = await fetch(`${API_BASE}/get_history`);
        return response.json();
    },
    async runQuery(payload) {
        const response = await fetch(`${API_BASE}/run`, {
            method: 'POST',
            body: payload,
        });
        return response.json();
    },
    async deleteConversation(conversationId) {
        const response = await fetch(
            `${API_BASE}/delete_conversation?conversation_id=${conversationId}`,
            {method: 'DELETE'},
        );
        return response.json();
    },
};
