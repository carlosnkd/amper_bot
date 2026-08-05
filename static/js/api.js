const api = {
    // userId is required (not defaulted) so this module stays independent of
    // whatever global holds the current user id in whichever page loads it.
    async getHistory(userId) {
        const response = await fetch(
            `${API_BASE}/get_history?user_id=${encodeURIComponent(userId)}`,
        );
        return response.json();
    },
    async runQuery(payload) {
        // Phase 1 only: runs the Planner and returns { conversation_id, plan, error }.
        // No code is written yet -- see buildTicket() for phase 2.
        const response = await fetch(`${API_BASE}/run`, {
            method: 'POST',
            body: payload,
        });
        return response.json();
    },
    async replanTicket(payload) {
        // "Request changes" on a plan the user already saw.
        const response = await fetch(`${API_BASE}/replan`, {
            method: 'POST',
            body: payload,
        });
        return response.json();
    },
    async buildTicket(payload) {
        // Phase 2: runs Coder -> Reviewer against an approved (optionally edited) plan.
        const response = await fetch(`${API_BASE}/build`, {
            method: 'POST',
            body: payload,
        });
        return response.json();
    },
    async deleteConversation(conversationId, userId) {
        const response = await fetch(
            `${API_BASE}/delete_conversation?user_id=${encodeURIComponent(userId)}&conversation_id=${encodeURIComponent(conversationId)}`,
            {method: 'DELETE'},
        );
        return response.json();
    },
};
