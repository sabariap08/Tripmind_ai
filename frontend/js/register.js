/* TripMind AI \u2014 passenger-first registration wizard (Phase 2/3).
 *
 * Workflow: Basic Details -> Identity & Contact -> Review.
 *
 * Passenger-first: this page IS the traveller account form. It opens straight on
 * the traveller details, creates a USER account immediately and never asks a
 * visitor to pick an account type.
 *
 * All provider applications are handled through the TripMind Partner Hub
 * (/tripmind-partner/register). This page is for passenger accounts only.
 *
 * Duplicate data is rejected live via /api/auth/check-availability before
 * submission, exactly as before.
 */
(function () {
    'use strict';
    const $ = (id) => document.getElementById(id);
    const IDENTITY_TYPES = ['AADHAAR', 'PAN', 'PASSPORT', 'DRIVING_LICENCE', 'VOTER_ID', 'OTHER'];
    const IDENTITY_LABELS = {
        AADHAAR: 'Aadhaar', PAN: 'PAN', PASSPORT: 'Passport',
        DRIVING_LICENCE: 'Driving Licence', VOTER_ID: 'Voter ID', OTHER: 'Other',
    };

    const state = {
        step: 'basic',
        values: {},
    };

    function steps() {
        return ['basic', 'identity', 'summary'];
    }
    const STEP_TITLES = {
        basic: 'Basic Details',
        identity: 'Identity & Contact',
        summary: 'Review & Confirm',
    };

    function fileToDataUrl(file) {
        return new Promise(function (resolve, reject) {
            var reader = new FileReader();
            reader.onload = function () { resolve(String(reader.result)); };
            reader.onerror = function () { reject(new Error('Could not read ' + file.name)); };
            reader.readAsDataURL(file);
        });
    }

    function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
        return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]); }); }
    function cls(node, name, on) { if (node) node.classList.toggle(name, on); }
    function msg(text, kind) { var n = $('wizMsg'); if (!n) return; n.textContent = text; n.className = 'wiz-msg' + (kind === 'error' ? ' wiz-msg--err' : ''); }
    function setMsg(t) { var n = $('wizMsg'); if (n) n.textContent = t || ''; }

    function renderType() { /* not used in passenger flow */ }
    function renderBasic() {
        var name = ($('wizName') || {}).value || '';
        var email = ($('wizEmail') || {}).value || '';
        var mobile = ($('wizMobile') || {}).value || '';
        $('wizContent').innerHTML =
            '<p class="wiz-sub">Welcome to TripMind. We only need a few details to create your traveller account.</p>' +
            '<div class="wiz-field">' +
            '<label class="wiz-label" for="wizName">Full name <span class="req">*</span></label>' +
            '<input class="wiz-input" type="text" id="wizName" name="name" value="' + esc(name) +
            '" autocomplete="name" maxlength="80" required>' +
            '<span class="wiz-hint">As it appears on your ID</span>' +
            '</div>' +
            '<div class="wiz-field">' +
            '<label class="wiz-label" for="wizEmail">Email <span class="req">*</span></label>' +
            '<input class="wiz-input" type="email" id="wizEmail" name="email" value="' + esc(email) +
            '" autocomplete="email" maxlength="160" required>' +
            '<span class="wiz-hint">We will send a verification link</span>' +
            '</div>' +
            '<div class="wiz-field">' +
            '<label class="wiz-label" for="wizMobile">Mobile number <span class="req">*</span></label>' +
            '<input class="wiz-input" type="tel" id="wizMobile" name="mobile" value="' + esc(mobile) +
            '" inputmode="numeric" maxlength="10" placeholder="98XXXXXXXX" autocomplete="tel" required>' +
            '<span class="wiz-hint">10 digits, for OTP login</span>' +
            '</div>' +
            '<div class="wiz-field">' +
            '<label class="wiz-label" for="wizPwd">Password <span class="req">*</span></label>' +
            '<input class="wiz-input" type="password" id="wizPwd" name="password" autocomplete="new-password" minlength="8" required>' +
            '<span class="wiz-hint">At least 8 characters</span>' +
            '</div>';
        ['wizName', 'wizEmail', 'wizMobile', 'wizPwd'].forEach(function (id) {
            var el = $(id);
            if (el) {
                el.addEventListener('input', function () {
                    state.values[id] = el.value;
                });
                if (state.values[id]) el.value = state.values[id];
            }
        });
    }

    function renderIdentity() {
        var idType = ($('wizIdType') || {}).value || '';
        var idNum = ($('wizIdNum') || {}).value || '';
        $('wizContent').innerHTML =
            '<p class="wiz-sub">We store only the type and last 4 digits of your government ID. The full number never leaves your device.</p>' +
            '<div class="wiz-field">' +
            '<label class="wiz-label" for="wizIdType">Government ID type <span class="req">*</span></label>' +
            '<select class="wiz-input" id="wizIdType" name="identityType" required>' +
            '<option value="">Select\u2026</option>' +
            IDENTITY_TYPES.map(function (t) {
                return '<option value="' + esc(t) + '"' + (idType === t ? ' selected' : '') + '>' + esc(IDENTITY_LABELS[t]) + '</option>';
            }).join('') + '</select>' +
            '</div>' +
            '<div class="wiz-field">' +
            '<label class="wiz-label" for="wizIdNum">Government ID number <span class="req">*</span></label>' +
            '<input class="wiz-input" type="text" id="wizIdNum" name="identityNumber" value="' + esc(idNum) +
            '" maxlength="24" required>' +
            '<span class="wiz-hint">Only the last 4 characters are stored</span>' +
            '</div>';
        ['wizIdType', 'wizIdNum'].forEach(function (id) {
            var el = $(id);
            if (el) {
                el.addEventListener('input', function () { state.values[id] = el.value; });
                if (state.values[id]) el.value = state.values[id];
            }
        });
    }

    function renderSummary() {
        var name = state.values.wizName || '';
        var email = state.values.wizEmail || '';
        var mobile = state.values.wizMobile || '';
        var idType = state.values.wizIdType || '';
        var idNum = state.values.wizIdNum || '';
        var idDisp = idType ? (IDENTITY_LABELS[idType] || idType) + ': ' + (idNum ? '\u2022\u2022\u2022\u2022' + idNum.slice(-4) : '') : 'Not provided';
        $('wizContent').innerHTML =
            '<p class="wiz-sub">Review everything below. Your password is not shown.</p>' +
            '<dl class="wiz-summary">' +
            '<dt>Name</dt><dd>' + esc(name) + '</dd>' +
            '<dt>Email</dt><dd>' + esc(email) + '</dd>' +
            '<dt>Mobile</dt><dd>' + esc(mobile) + '</dd>' +
            '<dt>ID</dt><dd>' + esc(idDisp) + '</dd>' +
            '<dt>Account type</dt><dd>Passenger (traveller)</dd>' +
            '</dl>';
    }

    function validate() {
        var list = steps();
        var idx = list.indexOf(state.step);
        var key = list[idx];
        var el, v;
        if (key === 'basic') {
            var req = ['wizName', 'wizEmail', 'wizMobile', 'wizPwd'];
            for (var i = 0; i < req.length; i++) {
                el = $(req[i]); v = (el && el.value || '').trim();
                if (!v) { msg('Please fill in ' + req[i].replace('wiz', '').toLowerCase() + '.', 'error'); if (el) el.focus(); return false; }
            }
            if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(state.values.wizEmail)) { msg('Enter a valid email.', 'error'); return false; }
            if (!/^\d{10}$/.test(state.values.wizMobile)) { msg('Mobile must be 10 digits.', 'error'); return false; }
            if (state.values.wizPwd.length < 8) { msg('Password must be at least 8 characters.', 'error'); return false; }
        }
        if (key === 'identity') {
            if (!state.values.wizIdType) { msg('Select your government ID type.', 'error'); return false; }
            if (!state.values.wizIdNum || state.values.wizIdNum.trim().length < 4) { msg('Enter your ID number (at least 4 digits).', 'error'); return false; }
        }
        return true;
    }

    function collectAll() {
        return {
            role: 'USER',
            name: (state.values.wizName || '').trim(),
            email: (state.values.wizEmail || '').trim().toLowerCase(),
            mobile: (state.values.wizMobile || '').trim(),
            password: state.values.wizPwd || '',
            identityType: state.values.wizIdType || '',
            identityNumber: (state.values.wizIdNum || '').trim(),
        };
    }

    async function submit() {
        if (!validate()) return;
        var btn = $('wizNext'); if (btn) { btn.disabled = true; btn.textContent = 'Creating\u2026'; }
        try {
            var payload = collectAll();
            var res = await apiRequest('/api/auth/register', {
                method: 'POST',
                body: JSON.stringify(payload)
            });
            if (res && res.user) {
                location.href = '/login.html?verified=1';
            } else {
                msg(res?.message || 'Registration succeeded. You can now sign in.', 'success');
                setTimeout(function () { location.href = '/login.html'; }, 1500);
            }
        } catch (e) {
            msg(e.message || 'Registration failed.', 'error');
            if (btn) { btn.disabled = false; btn.textContent = 'Create Account'; }
        }
    }

    function handleNext() {
        var list = steps();
        var idx = list.indexOf(state.step);
        if (idx >= list.length - 1) { submit(); return; }
        if (!validate()) return;
        state.step = list[idx + 1];
        renderStep();
    }

    function renderStep() {
        setMsg('');
        if (state.step === 'basic') renderBasic();
        else if (state.step === 'identity') renderIdentity();
        else renderSummary();

        var list = steps();
        var idx = list.indexOf(state.step);
        var strip = Array.prototype.filter.call(document.querySelectorAll('.wiz-step'), function (el) {
            return true; // no provider step in passenger flow
        });
        strip.forEach(function (el, i) {
            el.classList.toggle('active', i === idx);
            el.classList.toggle('done', i < idx);
        });
        var title = $('wizTitle');
        if (title) title.textContent = STEP_TITLES[state.step];
        var backBtn = $('wizBack');
        var nextBtn = $('wizNext');
        if (backBtn) backBtn.style.display = idx === 0 ? 'none' : '';
        if (nextBtn) {
            nextBtn.textContent = idx >= list.length - 1 ? 'Create Account' : 'Continue';
            nextBtn.disabled = false;
        }
        var content = $('wizContent');
        if (content) content.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    function init() {
        document.body.setAttribute('data-reg-flow', 'passenger');
        state.role = 'USER';
        state.step = 'basic';
        renderStep();

        var next = $('wizNext');
        if (next) next.addEventListener('click', handleNext);
        var back = $('wizBack');
        if (back) back.addEventListener('click', function () {
            var list = steps();
            var idx = list.indexOf(state.step);
            if (idx > 0) { state.step = list[idx - 1]; renderStep(); }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();