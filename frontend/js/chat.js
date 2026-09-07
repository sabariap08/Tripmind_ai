function initChat(tripId) {
    const toggle = document.getElementById('chatToggle');
    const panel = document.getElementById('chatPanel');
    const input = document.getElementById('chatInput');
    const sendBtn = document.getElementById('chatSend');
    const messages = document.getElementById('chatMessages');
    const suggestions = document.getElementById('chatSuggestions');

    if (!toggle) return;
    let isOpen = false;
    let pendingAction = null;

    toggle.addEventListener('click', () => {
        isOpen = !isOpen;
        panel.classList.toggle('active', isOpen);
        if (isOpen) input.focus();
    });

    function appendMessage(role, text) {
        const div = document.createElement('div');
        div.className = `chat-msg ${role}`;
        div.textContent = text;
        messages.appendChild(div);
        messages.scrollTop = messages.scrollHeight;
    }

    function appendAction(action) {
        if (!action || !action.type || !action.label) return;
        pendingAction = action;
        const row = document.createElement('div');
        row.className = 'chat-action';
        const btn = document.createElement('button');
        btn.className = 'btn btn-primary btn-sm';
        btn.textContent = action.label;
        btn.onclick = () => runAction(action);
        row.appendChild(btn);
        messages.appendChild(row);
        messages.scrollTop = messages.scrollHeight;
    }

    async function runAction(action) {
        const btn = messages.querySelector('.chat-action button');
        if (btn) { btn.disabled = true; btn.textContent = 'Working…'; }
        try {
            const res = await api.assistantAction(action.type, action.params);
            pendingAction = null;
            appendMessage('assistant', res.message || 'Done.');
            input.focus();
        } catch (e) {
            appendMessage('assistant', e.message || 'Action failed. Please try again.');
        }
    }

    async function sendMessage(text) {
        if (!text.trim()) return;
        appendMessage('user', text);
        input.value = '';
        suggestions.innerHTML = '';

        // A new message supersedes any un-confirmed proposal.
        pendingAction = null;
        messages.querySelector('.chat-action')?.remove();

        try {
            const data = await api.assistantChat(text, tripId);
            appendMessage('assistant', data.response);
            if (data.response && data.response.includes('\n') && !data.action) {
                appendMessage('assistant', 'You can use the buttons above, or ask me to book, switch transport, pay, or plan.');
            }
            if (data.action && data.action.label) {
                appendAction(data.action);
            }
            if (data.suggestions && data.suggestions.length && !data.action) {
                suggestions.innerHTML = data.suggestions.map(s =>
                    `<button class="chat-suggestion" onclick="sendChatMsg('${s.replace(/'/g, "\\'")}')">${s}</button>`
                ).join('');
            }
        } catch (e) {
            appendMessage('assistant', 'Sorry, something went wrong. Please try again.');
        }
    }

    sendBtn.addEventListener('click', () => sendMessage(input.value));
    input.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') sendMessage(input.value);
    });

    window.sendChatMsg = sendMessage;
    window.confirmChatAction = runAction;
}