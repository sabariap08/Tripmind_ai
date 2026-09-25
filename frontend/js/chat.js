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
    let pendingChange = null;

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

    /* Modification chatbot: the AI PROPOSES a change; nothing is applied
       until the traveller presses Confirm Change. Keep Current Plan leaves
       the trip exactly as it is. */
    function appendChange(change) {
        if (!change || !change.updates || !Object.keys(change.updates).length) return;
        pendingChange = change;
        const row = document.createElement('div');
        row.className = 'chat-action chat-change';
        const summary = document.createElement('div');
        summary.className = 'chat-msg assistant';
        summary.style.fontStyle = 'italic';
        summary.textContent = 'Proposed change — ' + change.summary;
        row.appendChild(summary);

        const confirmBtn = document.createElement('button');
        confirmBtn.className = 'btn btn-primary btn-sm';
        confirmBtn.textContent = 'Confirm Change';
        confirmBtn.onclick = applyChange;
        row.appendChild(confirmBtn);

        const keepBtn = document.createElement('button');
        keepBtn.className = 'btn btn-outline btn-sm';
        keepBtn.style.marginLeft = '0.4rem';
        keepBtn.textContent = 'Keep Current Plan';
        keepBtn.onclick = keepCurrentPlan;
        row.appendChild(keepBtn);

        messages.appendChild(row);
        messages.scrollTop = messages.scrollHeight;
    }

    async function applyChange() {
        const change = pendingChange;
        if (!change) return;
        const row = messages.querySelector('.chat-change');
        if (row) row.querySelectorAll('button').forEach(b => b.disabled = true);
        try {
            await api.modifyTrip(tripId, change.updates);
            appendMessage('assistant', 'Change applied to your trip inputs. Regenerating your plans — this can take about half a minute…');
            const gen = await api.generatePlans(tripId);
            if (!gen || !gen.selectedPlan) {
                throw new Error((gen && (gen.message || gen.aiExplanation)) ||
                    'The AI planner did not return a new plan.');
            }
            pendingChange = null;
            appendMessage('assistant', 'Done — your updated itinerary is ready. Refreshing…');
            setTimeout(() => window.location.reload(), 900);
        } catch (e) {
            if (row) row.querySelectorAll('button').forEach(b => b.disabled = false);
            appendMessage('assistant', 'Could not apply the change: ' + (e.message || 'please try again.'));
        }
    }

    function keepCurrentPlan() {
        pendingChange = null;
        const row = messages.querySelector('.chat-change');
        if (row) row.remove();
        appendMessage('assistant', 'Kept your current plan — nothing was changed.');
        input.focus();
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
        pendingChange = null;
        messages.querySelector('.chat-action')?.remove();

        try {
            const data = await api.assistantChat(text, tripId);
            appendMessage('assistant', data.response);
            if (data.response && data.response.includes('\n') && !data.action && !data.change) {
                appendMessage('assistant', 'You can use the buttons above, or ask me to book, switch transport, pay, or plan.');
            }
            if (data.action && data.action.label) {
                appendAction(data.action);
            }
            if (data.change && data.change.updates) {
                appendChange(data.change);
            }
            if (data.suggestions && data.suggestions.length && !data.action && !data.change) {
                suggestions.innerHTML = data.suggestions.map(s =>
                    `<button class="chat-suggestion" onclick="sendChatMsg('${s.replace(/'/g, "\\'")}')">${s}</button>`
                ).join('');
            }
        } catch (e) {
            appendMessage('assistant', 'Sorry, something went wrong: ' + (e.message || 'please try again.'));
        }
    }

    sendBtn.addEventListener('click', () => sendMessage(input.value));
    input.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') sendMessage(input.value);
    });

    window.sendChatMsg = sendMessage;
    window.confirmChatAction = runAction;
}