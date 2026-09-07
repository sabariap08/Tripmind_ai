/* TripMind AI — account-type-first registration wizard (Phase 2/3).

 * Workflow: Account Type -> Basic Details -> Identity & Contact -> Review.
 * Every role-specific provider detail is collected here (nothing is deferred
 * to a "create profile" page inside the dashboard), and duplicate data is
 * rejected live via /api/auth/check-availability before submission.
 */
(function () {
    const $ = (id) => document.getElementById(id);
    const IDENTITY_TYPES = ['AADHAAR', 'PAN', 'PASSPORT', 'DRIVING_LICENCE', 'VOTER_ID', 'OTHER'];
    const IDENTITY_LABELS = {
        AADHAAR: 'Aadhaar', PAN: 'PAN', PASSPORT: 'Passport',
        DRIVING_LICENCE: 'Driving Licence', VOTER_ID: 'Voter ID', OTHER: 'Other',
    };

    const state = {
        step: 'type',
        role: '',                 // selected account type
        values: {},               // collected field -> value (canonical)
        regRoleFields: [],        // provider-specific registration fields
        regValues: {},            // provider registration label -> value
        regLocation: {},          // {address, lat, lng} from business map picker
        regHours: {},             // day -> {open, close} weekly working hours
        documents: [],            // data: URIs
        images: [],               // data: URIs
    };

    const steps = ['type', 'basic', 'identity', 'summary'];
    const STEP_TITLES = {
        type: 'Account Type', basic: 'Basic Details',
        identity: 'Identity & Contact', summary: 'Review & Confirm',
    };

    const roleInfo = {
        USER: {
            title: 'Passenger',
            desc: 'Plan trips and book across transport, stays, food and experiences.',
            icon: '<circle cx="12" cy="8" r="4"></circle><path d="M4 20c0-4 4-6 8-6s8 2 8 6"></path>',
        },
        TRANSPORT_ADMIN: {
            title: 'Transport Admin',
            desc: 'Run a fleet of buses, trains, flights, cabs and autos.',
            icon: '<rect x="5" y="4" width="14" height="12" rx="2"></rect><path d="M5 10h14"></path><path d="M8 16v3"></path><path d="M16 16v3"></path>',
        },
        HOTEL_ADMIN: {
            title: 'Hotel Admin',
            desc: 'Add your hotel, rooms and amenities for travellers to book.',
            icon: '<path d="M3 19V9a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v10"></path><path d="M3 15h18"></path><path d="M7 12v-2"></path><path d="M17 12v3"></path>',
        },
        RESTAURANT_ADMIN: {
            title: 'Restaurant Admin',
            desc: 'Register your restaurant and manage its food menu.',
            icon: '<path d="M7 3v18"></path><path d="M5 3v5a2 2 0 0 0 4 0V3"></path><path d="M7 15v6"></path><path d="M15 3c0 4 3 5 3 9"></path><path d="M18 3v18"></path>',
        },
        GUIDE: {
            title: 'Guide',
            desc: 'Offer local guiding services and manage your availability.',
            icon: '<circle cx="12" cy="12" r="9"></circle><path d="M15.5 8.5l-2.5 6-6 2.5 2.5-6z"></path>',
        },
    };

    let emailChecked = null;

    /* ---- helpers ---------------------------------------------------------- */

    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, c => (
            { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    }
    function setMsg(text, isError) {
        const el = $('authMsg');
        el.textContent = text || '';
        el.style.color = isError ? 'var(--danger,#dc2626)' : 'var(--success,#16a34a)';
    }
    function fieldHtml(id, label, inner, hint) {
        return `<div class="form-group">
            <label class="form-label" for="${id}">${label}</label>
            ${inner}
            ${hint ? `<div class="hint" id="${id}_hint">${hint}</div>` : ''}
        </div>`;
    }
    function inputEl(id, type, placeholder, extra) {
        return `<input id="${id}" type="${type}" class="form-input" placeholder="${esc(placeholder || '')}" ${extra || ''}>`;
    }
    function fileToDataUrl(file) {
        return new Promise((resolve, reject) => {
            if (!file) return resolve('');
            const r = new FileReader();
            r.onload = () => resolve(r.result);
            r.onerror = reject;
            r.readAsDataURL(file);
        });
    }
    function live(hintId, ok, fail) {
        const h = $(hintId);
        if (!h) return;
        h.textContent = ok ? 'Looks good.' : fail;
        h.style.color = ok ? 'var(--success,#16a34a)' : 'var(--danger,#dc2626)';
    }

    /* ---- step rendering ---------------------------------------------------- */

    function renderType() {
        const cards = ['USER', 'TRANSPORT_ADMIN', 'HOTEL_ADMIN', 'RESTAURANT_ADMIN', 'GUIDE'].map(r => {
                const info = roleInfo[r] || {};
                return `<button type="button" class="role-card ${state.role === r ? 'selected' : ''}" data-role="${r}">
                    <span class="role-card-icon">${info.icon || ''}</span>
                    <div class="role-card-title">${esc(info.title || r)}</div>
                    <div class="role-card-desc">${esc(info.desc || '')}</div>
                </button>`;
            }).join('');
        $('wizContent').innerHTML = `<div class="role-grid">${cards}</div>`;
        document.querySelectorAll('.role-card').forEach(btn => btn.addEventListener('click', () => {
            document.querySelectorAll('.role-card').forEach(b => b.classList.remove('selected'));
            btn.classList.add('selected');
            state.role = btn.dataset.role;
            loadRegFields(state.role);
            syncTypeFooter();
        }));
        setMsg(state.role ? `Selected: ${roleInfo[state.role].title}` : '', false);
    }

    /* Provider business details are declared at registration (read-only in the
       portal afterwards). Load the field definitions for the chosen role. */
    function loadRegFields(role) {
        if (role === 'USER' || !role) { state.regRoleFields = []; state.weekDays = []; return; }
        api.registrationFields(role)
            .then(res => {
                const fields = res.fields || [];
                state.regRoleFields = fields;
                const gst = res.gst;
                if (gst) state.regRoleFields.push({ id: 'gst', label: gst.label, required: false, placeholder: gst.placeholder });
                state.weekDays = res.weekDays || state.weekDays || [];
            })
            .catch(() => { state.regRoleFields = []; });
    }

    function syncTypeFooter() {
        const nextBtn = $('wizNext');
        if (nextBtn) {
            nextBtn.textContent = 'Continue';
            nextBtn.disabled = !state.role;
        }
        setMsg(state.role ? `Selected: ${roleInfo[state.role].title}` : '', false);
    }

    function renderBasic() {
        const v = state.values;
        $('wizContent').innerHTML = `
            ${fieldHtml('name', 'Full name', inputEl('name', 'text', 'Your full name'), 'As it appears on your identification.')}
            ${fieldHtml('email', 'Email address', inputEl('email', 'email', 'you@example.com'), 'We will never share your email.')}
            <div class="form-row">
                ${fieldHtml('password', 'Password', inputEl('password', 'password', 'Min 8 characters'))}
                ${fieldHtml('confirm', 'Confirm password', inputEl('confirm', 'password', 'Repeat password'))}
            </div>
            <p class="hint" id="emailLive"></p>`;
        $('name').value = v.name || '';
        $('email').value = v.email || '';
        $('password').value = v.password || '';
        $('confirm').value = v.confirm || '';
        bindEmailLive();
    }

    function bindEmailLive() {
        const email = $('email');
        if (!email) return;
        const check = async () => {
            const value = (email.value || '').trim();
            const liveEl = $('emailLive');
            if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(value)) { emailChecked = null; liveEl.textContent = ''; return; }
            const res = await api.checkAvailability('email', value);
            if (value !== (email.value || '').trim()) return;
            emailChecked = res.available !== false;
            if (emailChecked) {
                liveEl.textContent = 'Email is available.';
                liveEl.style.color = 'var(--success,#16a34a)';
            } else {
                liveEl.textContent = 'This email is already registered.';
                liveEl.style.color = 'var(--danger,#dc2626)';
            }
        };
        email.addEventListener('blur', check);
        email.addEventListener('input', check);
    }

    function renderIdentity() {
        const isUser = state.role === 'USER';
        const v = state.values;
        const identityOptions = IDENTITY_TYPES.map(t =>
            `<option value="${t}" ${v.identityType === t ? 'selected' : ''}>${IDENTITY_LABELS[t]}</option>`).join('');

        let html = `<div class="form-row">
            ${fieldHtml('mobile', 'Mobile number', inputEl('mobile', 'tel', '10-digit mobile'), 'Verified for identity & OTPs.')}
        </div>
        <div class="form-row">
            ${fieldHtml('identityType', 'Identification type',
                `<select id="identityType" class="form-select">${identityOptions}</select>`)}
            ${fieldHtml('identityNumber', 'Identification number',
                inputEl('identityNumber', 'text', 'e.g. Aadhaar / PAN number'), 'Used for identity verification.')}
        </div>`;

        if (isUser) {
            html += `<div class="form-row">
                ${fieldHtml('diet', 'Dietary preference',
                    `<select id="diet" class="form-select">
                        <option value="vegetarian" ${v.diet === 'vegetarian' ? 'selected' : ''}>Vegetarian</option>
                        <option value="non_veg" ${v.diet === 'non_veg' ? 'selected' : ''}>Non-Vegetarian</option>
                        <option value="vegan" ${v.diet === 'vegan' ? 'selected' : ''}>Vegan</option>
                    </select>`)}
                ${fieldHtml('travelStyle', 'Travel style',
                    `<select id="travelStyle" class="form-select">
                        <option value="BUDGET" ${v.travelStyle === 'BUDGET' ? 'selected' : ''}>Budget</option>
                        <option value="BALANCED" ${v.travelStyle === 'BALANCED' ? 'selected' : ''}>Comfort</option>
                        <option value="PREMIUM" ${v.travelStyle === 'PREMIUM' ? 'selected' : ''}>Premium</option>
                    </select>`)}
            </div>`;
        } else {
            const gst = state.regRoleFields.find(d => d.id === 'gst');
            if (gst) {
                html += fieldHtml('gst', gst.label,
                    inputEl('gst', 'text', '15-character GST number (optional)'),
                    'Checked live against existing accounts.');
            }
            html += `<div class="reg-section-title">Registration details (reviewed by the Main Admin)</div>`;
            const defs = state.regRoleFields.filter(d => d.id !== 'gst');
            html += defs.map(d => {
                const id = 'reg_' + d.id;
                let inner;
                if (d.type === 'textarea') {
                    inner = `<textarea id="${id}" class="form-input" rows="2" placeholder="${esc(d.placeholder || '')}"></textarea>`;
                } else if (d.type === 'select') {
                    inner = `<select id="${id}" class="form-select">
                        ${(d.options || []).map(o => `<option value="${esc(String(o))}">${esc(String(o))}</option>`).join('')}
                    </select>`;
                } else {
                    const typeMap = { number: 'number', time: 'time', date: 'date', email: 'email' };
                    inner = `<input id="${id}" type="${typeMap[d.type] || 'text'}"
                            class="form-input" ${d.type === 'number' ? 'step="any"' : ''}
                            ${d.placeholder ? `placeholder="${esc(d.placeholder)}"` : ''}>`;
                }
                return fieldHtml(id, d.label + (d.required ? ' *' : ''), inner);
            }).join('');
            html += `<div class="form-row">
                ${fieldHtml('reg_docs', 'Supporting documents',
                    `<input id="reg_docs" type="file" class="form-input" multiple accept=".pdf,.jpg,.jpeg,.png">
                    <div class="hint2">Registration certificates, ID, GST. Optional.</div>`)}
                ${fieldHtml('reg_images', 'Photographs',
                    `<input id="reg_images" type="file" class="form-input" multiple accept=".jpg,.jpeg,.png">
                    <div class="hint2">Property / vehicles / spot / ID photos.</div>`)}
            </div>`;
            const days = (state.weekDays && state.weekDays.length ? state.weekDays : ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'])
                .map(d => {
                    const h = state.regHours[d] || {};
                    const on = h.enabled ? 'checked' : '';
                    return `<th>
                        <label><input type="checkbox" class="wh_en" value="${esc(d)}" ${on}> ${esc(d)}</label>
                        <div class="form-row" style="gap:.25rem;margin-top:.25rem;">
                            <input type="time" class="form-input wh_open" value="${esc(h.open || '09:00')}" style="flex:1;">
                            <span class="text-muted">–</span>
                            <input type="time" class="form-input wh_close" value="${esc(h.close || '17:00')}" style="flex:1;">
                        </div>
                    </th>`;
                }).join('');
            html += `
            <div class="reg-section-title">Weekly working hours</div>
            <p class="hint" style="margin:.25rem 0 .6rem;">Tick a day to include it and set its open / close times.</p>
            <div style="overflow-x:auto;">
                <table class="row-table" style="width:100%;min-width:640px;">
                    <tr>${days}</tr>
                </table>
            </div>`;
            html += `
            <div class="reg-section-title">Business location (map picker)</div>
            ${fieldHtml('pocAddress', 'Business address',
                inputEl('pocAddress', 'text', 'Search or type the full address'), 'Select a place or drag the marker to capture coordinates.')}
            <input type="hidden" id="pocLat" value="">
            <input type="hidden" id="pocLng" value="">
            <div id="pocMap" class="poc-map" style="display:none; height:220px; border-radius:.75rem; border:1px solid var(--slate-200,#e2e8f0);"></div>
            <p class="hint2" id="pocMapNote">Map loads automatically when available.</p>`;
        }

        $('wizContent').innerHTML = html;

        // prefill collected values
        ['mobile', 'identityNumber', 'gst'].forEach(k => { if ($(k) && v[k]) $(k).value = state.values[k]; });
        const prefill = (id, key) => { const el = $(id); if (el && v[key]) el.value = v[key]; };
        prefill('diet', 'diet'); prefill('travelStyle', 'travelStyle');
        state.regRoleFields.filter(d => d.id !== 'gst').forEach(d => {
            const el = $('reg_' + d.id);
            if (el && state.regValues[d.label]) el.value = state.regValues[d.label];
        });
        if (state.role !== 'USER') {
            if (state.regLocation) {
                const pa = $('pocAddress'); if (pa) pa.value = state.regLocation.address || '';
                const pl = $('pocLat'); if (pl) pl.value = state.regLocation.lat || '';
                const pg = $('pocLng'); if (pg) pg.value = state.regLocation.lng || '';
            }
            initPocMap();
        }
        bindIdentityLive();
    }

    function initPocMap() {
        const mapEl = $('pocMap');
        const note = $('pocMapNote');
        if (!mapEl || !window.TM_MAPS) { if (note) note.textContent = 'Map unavailable.'; return; }
        window.TM_MAPS.init().then(() => {
            if (!window.TM_MAPS.ready) { if (note) note.textContent = 'Map unavailable (no maps key configured).'; return; }
            mapEl.style.display = '';
            if (note) note.textContent = 'Search for a place, then drag the marker to fine-tune.';
            window.TM_MAPS.initLocationPicker({
                addressId: 'pocAddress', latId: 'pocLat', lngId: 'pocLng', mapId: 'pocMap',
            });
        });
    }

    function bindIdentityLive() {
        const bind = (field, el, extra = {}) => {
            if (!el) return;
            const run = async () => {
                const value = (el.value || '').trim();
                const hint = $(el.id + '_hint');
                if (!value) { if (hint) hint.textContent = ''; return; }
                if (field === 'mobile' && !/^[6-9]\d{9}$/.test(value.replace(/\D/g, ''))) {
                    live(el.id + '_hint', false, 'Enter a valid 10-digit mobile number.');
                    return;
                }
                const res = await api.checkAvailability(field, value, extra);
                if (value !== (el.value || '').trim()) return;
                if (field === 'gst' && !/^[0-9A-Z]{15}$/i.test(value.replace(/[^0-9A-Z]/ig, ''))) {
                    live(el.id + '_hint', false, 'GST must be 15 characters (letters + digits).');
                    return;
                }
                if (res && res.available === false) live(el.id + '_hint', false, 'Already in use.');
                else live(el.id + '_hint', true, 'Available.');
            };
            el.addEventListener('blur', run);
            el.addEventListener('input', run);
        };
        bind('mobile', $('mobile'));
        const identityNumber = $('identityNumber');
        const identityType = $('identityType');
        const idCheck = async () => {
            const value = (identityNumber.value || '').trim();
            const type = (identityType.value || '');
            const hint = $('identityNumber_hint');
            if (!value) { if (hint) hint.textContent = ''; return; }
            const res = await api.checkAvailability('identityNumber', value, { identityType: type });
            if (value !== (identityNumber.value || '').trim()) return;
            if (res && res.available === false) live('identityNumber_hint', false, 'This identification is already registered.');
            else live('identityNumber_hint', true, 'Available.');
        };
        identityNumber.addEventListener('blur', idCheck);
        identityNumber.addEventListener('input', idCheck);
        if (identityType) identityType.addEventListener('change', idCheck);
        bind('gst', $('gst'));
    }

    function renderSummary() {
        const isUser = state.role === 'USER';
        const rows = [];
        const push = (k, v) => { if (v !== undefined && v !== null && String(v).trim() !== '') rows.push([k, v]); };

        push('Account type', roleInfo[state.role]?.title || state.role);
        push('Full name', state.values.name);
        push('Email', state.values.email);
        push('Mobile', state.values.mobile);
        push('Identification', state.values.identityType ? `${IDENTITY_LABELS[state.values.identityType] || state.values.identityType} · ${state.values.identityNumber}` : '');
        push('GST number', state.values.gst);
        if (isUser) {
            push('Dietary preference', state.values.diet === 'vegetarian' ? 'Vegetarian' : state.values.diet === 'vegan' ? 'Vegan' : 'Non-Vegetarian');
            push('Travel style', state.values.travelStyle);
        }
        state.regRoleFields.filter(d => d.id !== 'gst').forEach(d => push(d.label, state.regValues[d.label]));
        if (state.role !== 'USER') {
            const hours = Object.keys(state.regHours).length
                ? Object.keys(state.regHours).map(d =>
                    `${d} ${state.regHours[d].open}–${state.regHours[d].close}`).join(', ')
                : '';
            push('Weekly working hours', hours || undefined);
            const rl = state.regLocation;
            if (rl && rl.lat && rl.lng) push('Location (lat, lng)', `${rl.address || ''} · ${rl.lat}, ${rl.lng}`);
        }

        const detailRows = rows.map(([k, v]) =>
            `<div class="detail-item"><span class="k">${esc(k)}</span><span class="v">${esc(v)}</span></div>`).join('');

        $('wizContent').innerHTML = `<p class="wiz-sub">Review everything below — all provider details are sent with this registration.</p>
            <div class="detail-list">${detailRows || '<p class="text-muted">Nothing to review.</p>'}</div>
            ${
            state.documents.length
                ? `<div class="summary-note">${state.documents.length} supporting document(s) attached.</div>` : ''
            }${
            state.images.length
                ? `<div class="summary-note">${state.images.length} photograph(s) attached.</div>` : ''
            }`;
    }

    /* ---- validation & navigation ------------------------------------------- */

    function validate() {
        const v = state.values;
        if (state.step === 'type') {
            if (!state.role) { setMsg('Please choose an account type.', true); return false; }
        }
        if (state.step === 'basic') {
            const name = $('name').value.trim();
            const email = $('email').value.trim();
            const password = $('password').value;
            const confirm = $('confirm').value;
            if (!name) { setMsg('Enter your full name.', true); return false; }
            if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) { setMsg('Enter a valid email address.', true); return false; }
            if (emailChecked === false) { setMsg('This email is already registered.', true); return false; }
            if (password.length < 8) { setMsg('Password must be at least 8 characters.', true); return false; }
            if (password !== confirm) { setMsg('Passwords do not match.', true); return false; }
            Object.assign(v, { name, email, password, confirm });
        }
        if (state.step === 'identity') {
            const mobile = ($('mobile').value || '').replace(/\D/g, '');
            if (!/^[6-9]\d{9}$/.test(mobile)) { setMsg('Enter a valid 10-digit mobile number.', true); return false; }
            const identityType = $('identityType').value;
            const identityNumber = ($('identityNumber').value || '').trim();
            if (!identityType || !identityNumber) { setMsg('Identification type and number are required.', true); return false; }
            const gst = ($('gst') ? $('gst').value.trim() : '') || v.gst || '';
            if (gst && !/^[0-9A-Z]{15}$/i.test(gst.replace(/[^0-9A-Z]/ig, ''))) { setMsg('Enter a valid 15-character GST number.', true); return false; }
            Object.assign(v, {
                mobile, identityType, identityNumber,
                gst: gst.replace(/[^0-9A-Z]/ig, '').toUpperCase() || '',
                diet: $('diet') ? $('diet').value : v.diet,
                travelStyle: $('travelStyle') ? $('travelStyle').value : v.travelStyle,
            });
            if (state.role !== 'USER') {
                const fail = state.regRoleFields.filter(d => d.id !== 'gst' && d.required &&
                    !(($(`reg_${d.id}`) ? $(`reg_${d.id}`).value : '').trim()));
                if (fail.length) { setMsg(`Please complete: ${fail[0].label}`, true); return false; }
                state.regRoleFields.filter(d => d.id !== 'gst').forEach(d => {
                    const el = $(`reg_${d.id}`);
                    if (el) state.regValues[d.label] = el.value.trim();
                });
                if (gst && !v.gst) v.gst = '';
                if (v.gst) state.regValues[(state.regRoleFields.find(d => d.id === 'gst') || {}).label || 'GST Number'] = v.gst;

                // weekly working hours -> structured day list stored as JSON
                const hours = {};
                document.querySelectorAll('.wh_en').forEach(cb => {
                    if (!cb.checked) return;
                    const row = cb.closest('th');
                    hours[cb.value] = {
                        open: (row.querySelector('.wh_open').value || '09:00'),
                        close: (row.querySelector('.wh_close').value || '17:00'),
                    };
                });
                const entries = Object.keys(hours).length
                    ? Object.keys(hours).map(d => ({ day: d, open: hours[d].open, close: hours[d].close }))
                    : [];
                state.regHours = hours;
                state.regValues['Weekly Working Hours'] = JSON.stringify(entries);
                const pocAddress = ($('pocAddress') ? $('pocAddress').value : '').trim();
                const pocLat = ($('pocLat') ? $('pocLat').value : '').trim();
                const pocLng = ($('pocLng') ? $('pocLng').value : '').trim();
                state.regLocation = { address: pocAddress, lat: pocLat, lng: pocLng };
                if (pocLat && pocLng) {
                    state.regValues['Latitude'] = pocLat;
                    state.regValues['Longitude'] = pocLng;
                }
                const alreadyHasAddress = Object.keys(state.regValues).some(k => /address/i.test(k));
                if (pocAddress && !alreadyHasAddress) state.regValues['Location Address'] = pocAddress;
            }
        }
        return true;
    }

    async function submit() {
        const v = state.values;
        setMsg('Creating your account…');
        const payload = {
            name: v.name, email: v.email, password: v.password, role: state.role,
            mobile: v.mobile, identityType: v.identityType, identityNumber: v.identityNumber,
        };
        if (v.gst) payload.gst = v.gst;
        if (state.role === 'USER') {
            payload.preferences = { dietary: v.diet || 'vegetarian', travelStyle: v.travelStyle || 'BALANCED' };
        } else {
            payload.registration = state.regValues;
            payload.documents = state.documents;
            payload.images = state.images;
        }
        try {
            const res = await api.register(payload);
            setMsg(res.message || 'Account created.');
            setTimeout(() => { location.href = '/login.html'; }, 1400);
        } catch (err) {
            setMsg(err.message, true);
        }
        return false;
    }

    async function handleNext() {
        if (state.step === 'identity' && state.role !== 'USER') {
            const docs = $('reg_docs');
            const images = $('reg_images');
            if (docs && docs.files && docs.files.length) state.documents = await Promise.all(Array.from(docs.files).map(fileToDataUrl));
            if (images && images.files && images.files.length) state.images = await Promise.all(Array.from(images.files).map(fileToDataUrl));
        }
        if (!validate()) return;
        const idx = steps.indexOf(state.step);
        if (idx >= steps.length - 1) { submit(); return; }
        state.step = steps[idx + 1];
        renderStep();
    }

    function renderStep() {
        setMsg('');
        if (state.step === 'type') renderType(); else if (state.step === 'basic') renderBasic();
        else if (state.step === 'identity') renderIdentity(); else renderSummary();

        const idx = steps.indexOf(state.step);
        document.querySelectorAll('.wiz-step').forEach((el, i) => {
            el.classList.toggle('active', i === idx);
            el.classList.toggle('done', i < idx);
        });
        const title = $('wizTitle');
        if (title) title.textContent = STEP_TITLES[state.step];
        const backBtn = $('wizBack');
        const nextBtn = $('wizNext');
        if (backBtn) backBtn.style.display = idx === 0 ? 'none' : '';
        if (nextBtn) {
            nextBtn.textContent = idx >= steps.length - 1 ? 'Create Account' : 'Continue';
            nextBtn.disabled = state.step === 'type' && !state.role;
        }
        $('wizContent').scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    function init() {
        const start = () => {
            state.step = 'type';
            renderStep();
        };
        /* account type grid interaction — the role select is the first step */
        const next = $('wizNext'); if (next) next.addEventListener('click', handleNext);
        const back = $('wizBack');
        if (back) back.addEventListener('click', () => {
            const idx = steps.indexOf(state.step);
            if (idx > 0) { state.step = steps[idx - 1]; renderStep(); }
        });
        start();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();