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

    /* A retry affordance for failures that are ours, not the traveller's.
       Deliberately takes the handler as an argument rather than assuming
       reload: the right recovery differs (a failed regeneration just needs the
       page re-fetched, a failed action may need to be re-sent). The button
       disables itself on click so a double-tap cannot fire it twice, and any
       earlier retry row is removed so they never stack up. */
    function appendRetry(onRetry, label) {
        const existing = messages.querySelector('.chat-retry');
        if (existing) existing.remove();
        const row = document.createElement('div');
        row.className = 'chat-retry';
        const btn = document.createElement('button');
        btn.className = 'btn btn-outline btn-sm';
        btn.type = 'button';
        btn.textContent = label || 'Try again';
        btn.onclick = () => {
            btn.disabled = true;
            btn.textContent = 'Working\u2026';
            try {
                onRetry();
            } catch (e) {
                // The recovery itself failed. Say so rather than leaving a
                // permanently dead button on screen.
                btn.disabled = false;
                btn.textContent = label || 'Try again';
                appendMessage('assistant', 'Still not working: '
                    + (e.message || 'please try again in a moment.'));
            }
        };
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
        summary.textContent = 'Proposed change \u2014 ' + change.summary;
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
            appendMessage('assistant', 'Change applied to your trip inputs. Regenerating your plans \u2014 this can take about half a minute\u2026');
            // /generate answers 503 when the AI planner is unreachable, and the
            // server's explanation is in the error message (api.js promotes it).
            // That is a retryable dependency failure, not a rejected change, so
            // it gets its own message and a real retry button instead of the
            // generic "could not apply the change", which sent the user looking
            // for a mistake in their input that was never there.
            let gen;
            try {
                gen = await api.generatePlans(tripId);
            } catch (e) {
                if (e.retryable) {
                    pendingChange = null;
                    appendMessage('assistant', 'Your change was saved, but the AI planner did not respond'
                        + (e.message ? ': ' + e.message : '.')
                        + ' This is a temporary problem on our side, not with your trip.');
                    appendRetry(() => { window.location.reload(); }, 'Try again');
                    return;
                }
                throw e;
            }
            if (!gen || !gen.selectedPlan) {
                throw new Error((gen && (gen.message || gen.aiExplanation)) ||
                    'The AI planner did not return a new plan.');
            }
            pendingChange = null;
            appendMessage('assistant', 'Done \u2014 your updated itinerary is ready. Refreshing\u2026');
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
        appendMessage('assistant', 'Kept your current plan \u2014 nothing was changed.');
        input.focus();
    }

    async function runAction(action) {
        const btn = messages.querySelector('.chat-action button');
        if (btn) { btn.disabled = true; btn.textContent = 'Working\u2026'; }
        try {
            const res = await api.assistantAction(action.type, action.params);
            pendingAction = null;
            appendMessage('assistant', res.message || 'Done.');

            // Item-level itinerary edits and transport changes rewrite the plan
            // on disk: reload the page so the timeline, cost ledger and
            // QR/ticket show the result.
            if (action.type === 'edit_itinerary' || action.type === 'remove_place'
                || action.type === 'change_transport') {
                appendMessage('assistant', 'Refreshing your updated itinerary\u2026');
                setTimeout(() => window.location.reload(), 900);
            }
            input.focus();
        } catch (e) {
            if (btn) { btn.disabled = false; btn.textContent = action.label; }
            // A 503/429 means our side is unavailable, not that the request was
            // bad, so the traveller is offered a retry rather than being told
            // the action failed as though they had got it wrong.
            if (e.retryable) {
                appendMessage('assistant', 'TripMind is temporarily unavailable'
                    + (e.message ? ': ' + e.message : '.')
                    + ' Nothing was changed.');
                appendRetry(() => runAction(action), 'Try again');
                return;
            }
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
            if (e.retryable) {
                appendMessage('assistant', 'TripMind is temporarily unavailable'
                    + (e.message ? ': ' + e.message : '.'));
                appendRetry(() => sendMessage(text), 'Try again');
                return;
            }
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