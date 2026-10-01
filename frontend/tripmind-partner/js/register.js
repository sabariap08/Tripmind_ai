/* TripMind Partner Hub \u2014 schema-driven partner registration.
 *
 * Nothing about a role is hardcoded here. The form is built entirely from
 * GET /api/partner/meta, so the district list, the fields, the weekly-hours
 * grid, the upload limits and the verification requirements all come from the
 * server's single source of truth (backend/services/partner_schema.py).
 *
 * Adding a role or changing a legal requirement is a backend change only.
 */
(function () {
    'use strict';

    var state = {
        meta: null,
        role: null,
        schema: null,
        step: 0,
        images: [],
        documents: [],
        location: null,
        busy: false,
        lastErrors: []
    };

    var MAX_IMAGE_BYTES = 400 * 1024;
    var MAX_IMAGES = 10;
    var MIN_IMAGES = 5;

    /* ------------------------------------------------------------------ */
    /* small helpers                                                        */
    /* ------------------------------------------------------------------ */
    function q(sel, root) { return (root || document).querySelector(sel); }
    function qa(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
    function esc(s) { return (typeof TM !== 'undefined' && TM.esc) ? TM.esc(s) : String(s == null ? '' : s); }
    function show(node, on) { if (node) { node.hidden = !on; } }

    function alertBox(node, message, kind) {
        if (!node) return;
        if (!message) { node.hidden = true; node.textContent = ''; return; }
        node.hidden = false;
        node.className = 'tm-alert tm-alert--' + (kind || 'error');
        node.textContent = message;
    }

    function fieldWrap(id, label, required, help, control, extraClass) {
        return '<div class="tm-field ' + (extraClass || '') + '">'
            + '<label class="tm-label" for="' + id + '">' + esc(label)
            + (required ? ' <span class="req">*</span>' : '')
            + (required ? '' : ' <span class="tm-optional">optional</span>') + '</label>'
            + control
            + (help ? '<span class="tm-help">' + esc(help) + '</span>' : '')
            + '<span class="tm-error" aria-live="polite"></span>'
            + '</div>';
    }

    /* ------------------------------------------------------------------ */
    /* role chooser                                                         */
    /* ------------------------------------------------------------------ */
    function renderRoles() {
        var grid = q('#phRoleGrid');
        if (!grid || !state.meta) return;
        grid.innerHTML = state.meta.roles.map(function (r) {
            return '<label class="ph-rolecard" data-slug="' + esc(r.slug) + '">'
                + '<input type="radio" name="partnerRole" value="' + esc(r.role) + '">'
                + '<span class="ph-rolecard__icon" aria-hidden="true">' + roleIcon(r.slug) + '</span>'
                + '<span class="ph-rolecard__body">'
                + '<strong>' + esc(r.label) + '</strong>'
                + '<small>' + esc(r.blurb) + '</small>'
                + '</span></label>';
        }).join('');
        qa('input[name="partnerRole"]', grid).forEach(function (input) {
            input.addEventListener('change', function () {
                selectRole(input.value);
            });
        });
    }

    function roleIcon(slug) {
        var paths = {
            transport: '<path d="M5 16V6a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v10M5 16h14M7 16v2M17 16v2M4 12h16"/>',
            hotel: '<path d="M3 18V8m0 10h18V8M3 12h18M7 10h3M14 10h3M3 18v-6"/>',
            restaurant: '<path d="M6 3v8a3 3 0 0 0 6 0V3M9 11v10M18 3c-1.5 2-2 4-2 6s.7 3 2 3v9"/>',
            'tourist-spot': '<path d="M12 3 3 8l9 5 9-5-9-5ZM3 8v8l9 5 9-5V8M12 13v8"/>',
            guide: '<path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM4 21a8 8 0 0 1 16 0"/>'
        };
        return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" '
            + 'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            + (paths[slug] || paths.guide) + '</svg>';
    }

    function selectRole(role) {
        if (!state.meta || !state.meta.schemas[role]) return;
        state.role = role;
        state.schema = state.meta.schemas[role];
        state.step = 0;
        state.images = [];
        state.documents = [];
        state.location = null;

        qa('.ph-rolecard').forEach(function (card) {
            var input = q('input', card);
            card.classList.toggle('is-active', !!input && input.checked);
        });

        q('#phBusinessLegend').textContent = '3. ' + (state.schema.label || 'About your service');
        buildAccount();
        buildBusiness();
        buildLocation();
        buildSchedule();
        buildImages();
        buildDocuments();
        buildReview();
        buildStepBar();
        show(q('#phRoleStep'), true);
        show(q('#phRegForm'), true);
        goTo(0);
    }

    /* ------------------------------------------------------------------ */
    /* step list                                                            */
    /* ------------------------------------------------------------------ */
    function steps() {
        var list = [
            { key: 'account', label: 'Sign-in' },
            { key: 'business', label: 'Business' }
        ];
        if (state.schema && state.schema.location) list.push({ key: 'location', label: 'Location' });
        if (state.schema && state.schema.schedule) list.push({ key: 'hours', label: 'Hours' });
        if (state.schema && state.schema.images) list.push({ key: 'photos', label: 'Photos' });
        list.push({ key: 'documents', label: 'Documents' });
        list.push({ key: 'review', label: 'Review' });
        return list;
    }

    function buildStepBar() {
        var bar = q('#phStepBar');
        if (!bar) return;
        bar.innerHTML = steps().map(function (s, i) {
            return '<li class="ph-steps__item" data-step-key="' + s.key + '">'
                + '<span class="ph-steps__n">' + (i + 2) + '</span>'
                + '<span class="ph-steps__label">' + esc(s.label) + '</span></li>';
        }).join('');
    }

    function goTo(index) {
        var list = steps();
        state.step = Math.max(0, Math.min(index, list.length - 1));
        var current = list[state.step].key;
        qa('.ph-step[data-step]').forEach(function (node) {
            show(node, node.getAttribute('data-step') === current);
        });
        qa('.ph-steps__item').forEach(function (node) {
            node.classList.toggle('is-active', node.getAttribute('data-step-key') === current);
            node.classList.toggle('is-done',
                list.findIndex(function (s) { return s.key === node.getAttribute('data-step-key'); }) < state.step);
        });
        show(q('#phBack'), state.step > 0);
        show(q('#phNext'), state.step < list.length - 1);
        show(q('#phSubmit'), state.step === list.length - 1);
        var top = q('#phApply');
        if (top && top.scrollIntoView) top.scrollIntoView({ block: 'start' });
    }

    /* ------------------------------------------------------------------ */
    /* step 1 \u2014 account                                                     */
    /* ------------------------------------------------------------------ */
    function buildAccount() {
        q('#phAccountFields').innerHTML = [
            fieldWrap('phName', 'Your name', true, '', '<input class="tm-input" id="phName" name="name" autocomplete="name" maxlength="80" data-validate="required">'),
            fieldWrap('phEmail', 'Email address', true, 'This is your sign-in email.',
                '<input class="tm-input" type="email" id="phEmail" name="email" autocomplete="email" maxlength="160" data-validate="required,email">'),
            fieldWrap('phMobile', 'Mobile number', true, '10-digit Indian mobile number.',
                '<input class="tm-input" type="tel" id="phMobile" name="mobile" inputmode="numeric" maxlength="10" placeholder="98XXXXXXXX" data-validate="required,mobile">'),
            fieldWrap('phPassword', 'Password', true, 'At least 8 characters.',
                '<input class="tm-input" type="password" id="phPassword" name="password" autocomplete="new-password" minlength="8" data-validate="required,minlen:8">'),
            fieldWrap('phIdType', 'Government ID type', true, 'We store only the type and last 4 digits.',
                '<select class="tm-input" id="phIdType" name="identityType" data-validate="required">'
                + '<option value="">Select\u2026</option>'
                + '<option value="AADHAAR">Aadhaar</option>'
                + '<option value="PAN">PAN</option>'
                + '<option value="PASSPORT">Passport</option>'
                + '<option value="DRIVING_LICENCE">Driving licence</option>'
                + '</select>'),
            fieldWrap('phIdNumber', 'Government ID number', true, 'Only the last 4 characters are stored.',
                '<input class="tm-input" id="phIdNumber" name="identityNumber" maxlength="24" data-validate="required">')
        ].join('');
    }

    /* ------------------------------------------------------------------ */
    /* step 2 \u2014 business fields (schema driven)                             */
    /* ------------------------------------------------------------------ */
    function buildBusiness() {
        var host = q('#phBusinessFields');
        if (!host) return;
        host.innerHTML = (state.schema.fields || []).map(function (f) {
            return renderField(f, 'b_' + f.id);
        }).join('');
        wireMultiSelects(host);
    }

    function renderField(f, id) {
        var help = f.help || '';
        var attrs = ' class="tm-input" id="' + id + '" data-field="' + esc(f.id) + '"'
            + (f.required ? ' data-validate="required"' : '')
            + (f.placeholder ? ' placeholder="' + esc(f.placeholder) + '"' : '');

        var control;
        if (f.type === 'select') {
            control = '<select' + attrs + '>'
                + '<option value="">Select\u2026</option>'
                + (f.options || []).map(function (o) {
                    return '<option value="' + esc(o) + '">' + esc(o) + '</option>';
                }).join('') + '</select>';
        } else if (f.type === 'multiselect') {
            control = '<div class="ph-chips" data-multi="' + esc(f.id) + '" role="group" aria-label="' + esc(f.label) + '">'
                + (f.options || []).map(function (o) {
                    return '<label class="ph-chip"><input type="checkbox" value="' + esc(o) + '"><span>' + esc(o) + '</span></label>';
                }).join('') + '</div>';
            return fieldWrap(id, f.label, f.required, help, control, 'tm-field--wide');
        } else if (f.type === 'textarea') {
            control = '<textarea' + attrs + ' rows="3" maxlength="600"></textarea>';
        } else {
            control = '<input type="' + (f.type || 'text') + '"' + attrs + '>'
                + (f.type === 'number' ? ' min="0" step="any"' : '')
                + (f.type === 'time' ? '' : ' maxlength="120"') + '>';
        }
        return fieldWrap(id, f.label, f.required, help, control);
    }

    function wireMultiSelects(root) {
        qa('[data-multi]', root).forEach(function (group) {
            qa('input[type="checkbox"]', group).forEach(function (box) {
                box.addEventListener('change', function () {
                    box.closest('.ph-chip').classList.toggle('is-on', box.checked);
                });
            });
        });
    }

    function collectMulti(root) {
        var out = {};
        qa('[data-multi]', root).forEach(function (group) {
            out[group.getAttribute('data-multi')] = qa('input:checked', group)
                .map(function (b) { return b.value; });
        });
        return out;
    }

    /* ------------------------------------------------------------------ */
    /* step 3 \u2014 location                                                    */
    /* ------------------------------------------------------------------ */
    function buildLocation() {
        var step = q('#phLocationStep');
        if (!state.schema || !state.schema.location) { show(step, false); return; }
        show(step, true);
        var districts = (state.meta && state.meta.districts) || [];
        q('#phLocationFields').innerHTML =
            fieldWrap('phPlaceSearch', 'Search your location on Google Maps', true,
                'Pick your actual premises from the search results so travellers can find you. We never guess a pin for you.',
                '<input class="tm-input" id="phPlaceSearch" autocomplete="off" placeholder="e.g. Anna Salai, Chennai">'
                + '<div id="phPlaceMap" class="ph-map" role="application" aria-label="Map of your location"></div>'
                + '<p class="tm-help" id="phPlaceStatus">Google Maps fills the address, coordinates and district for you.</p>')
            + fieldWrap('phAddress', 'Full address', true, 'Filled in from the map. You can correct the wording.',
                '<input class="tm-input" id="phAddress" data-loc="address" maxlength="240">')
            + fieldWrap('phDistrict', 'District', true, 'All ' + districts.length + ' Tamil Nadu districts. Auto-filled from the map \u2014 change it if Google picked the wrong one.',
                '<select class="tm-input" id="phDistrict" data-loc="district"><option value="">Select district\u2026</option>'
                + districts.map(function (d) {
                    return '<option value="' + esc(d) + '">' + esc(d) + '</option>';
                }).join('') + '</select>')
            + fieldWrap('phCity', 'City / town', true, 'Filled in from the map.',
                '<input class="tm-input" id="phCity" data-loc="city" maxlength="80">')
            + '<input type="hidden" id="phPlaceId" data-loc="placeId">'
            + '<input type="hidden" id="phLat" data-loc="lat">'
            + '<input type="hidden" id="phLng" data-loc="lng">';

        initPlacePicker();
    }

    function initPlacePicker() {
        if (typeof TM_MAPS === 'undefined') return;
        var status = q('#phPlaceStatus');
        TM_MAPS.init().then(function (ok) {
            if (!ok) {
                if (status) {
                    status.textContent = 'Google Maps is not configured on this server, so we cannot '
                        + 'verify your location automatically. Enter the address and district manually.';
                    status.classList.add('tm-help--warn');
                }
                return;
            }
            TM_MAPS.initPlacePicker({
                inputId: 'phPlaceSearch',
                mapId: 'phPlaceMap',
                districtSelectId: 'phDistrict',
                districts: (state.meta && state.meta.districts) || [],
                onPick: function (info) {
                    if (info.pinOnly) {
                        if (status) status.textContent = 'Pin moved. Search for your premises to confirm the address.';
                        return;
                    }
                    applyLocation(info);
                    if (status) status.textContent = 'Location confirmed from Google Maps.';
                },
                onNotAvailable: function () {
                    if (status) status.textContent = 'Google Maps is unavailable. Enter your address and district manually.';
                }
            });
        });
    }

    function applyLocation(info) {
        state.location = {
            address: info.address || '',
            city: info.city || info.locality || '',
            district: info.district || '',
            placeId: info.placeId || '',
            lat: info.latitude,
            lng: info.longitude
        };
        var set = function (id, value) { var el = q(id); if (el) el.value = value == null ? '' : value; };
        set('#phAddress', state.location.address);
        set('#phCity', state.location.city);
        set('#phDistrict', state.location.district);
        set('#phPlaceId', state.location.placeId);
        set('#phLat', state.location.lat);
        set('#phLng', state.location.lng);
    }

    function readLocation() {
        var get = function(id) { var el = q(id); return el ? el.value.trim() : ''; };
        var latRaw = get('#phLat'), lngRaw = get('#phLng');
        return {
            address: get('#phAddress'),
            city: get('#phCity'),
            district: get('#phDistrict'),
            placeId: get('#phPlaceId'),
            lat: latRaw ? Number(latRaw) : null,
            lng: lngRaw ? Number(lngRaw) : null
        };
    }

    /* ------------------------------------------------------------------ */
    /* step 4 \u2014 weekly hours                                                */
    /* ------------------------------------------------------------------ */
    function buildSchedule() {
        var step = q('#phHoursStep');
        if (!state.schema || !state.schema.schedule) { show(step, false); return; }
        show(step, true);
        var days = (state.meta && state.meta.weekDays) || [];
        q('#phScheduleFields').innerHTML =
            '<p class="tm-sm tm-muted" style="margin:0 0 1rem">' + esc(state.schema.schedule.help || '') + '</p>'
            + '<div class="ph-hours">'
            + days.map(function (day, i) {
                return '<div class="ph-hours__row" data-day="' + esc(day) + '">'
                    + '<label class="ph-hours__day"><input type="checkbox" class="ph-hours__closed">'
                    + '<span>' + esc(day) + '</span></label>'
                    + '<input class="tm-input tm-input--time" type="time" data-open aria-label="' + esc(day) + ' opening time">'
                    + '<span class="ph-hours__dash" aria-hidden="true">to</span>'
                    + '<input class="tm-input tm-input--time" type="time" data-close aria-label="' + esc(day) + ' closing time">'
                    + '</div>';
            }).join('')
            + '</div>';

        qa('.ph-hours__row').forEach(function (row) {
            var closed = q('[data-closed]', row) || q('.ph-hours__closed', row);
            var open = q('[data-open]', row);
            var close = q('[data-close]', row);
            if (!closed || !open || !close) return;
            open.value = '09:00';
            close.value = '21:00';
            var sync = function () {
                var isClosed = closed.checked;
                open.disabled = isClosed;
                close.disabled = isClosed;
                row.classList.toggle('is-closed', isClosed);
            };
            closed.addEventListener('change', sync);
            sync();
        });
    }

    function readSchedule() {
        var out = {};
        qa('.ph-hours__row').forEach(function (row) {
            var closed = q('.ph-hours__closed', row);
            var open = q('[data-open]', row);
            var close = q('[data-close]', row);
            if (closed && closed.checked) {
                out[row.getAttribute('data-day')] = { closed: true };
                return;
            }
            if (open && close && open.value && close.value) {
                out[row.getAttribute('data-day')] = { open: open.value, close: close.value };
            }
        });
        return out;
    }

    /* ------------------------------------------------------------------ */
    /* step 5 \u2014 photos                                                      */
    /* ------------------------------------------------------------------ */
    function buildImages() {
        var step = q('#phPhotosStep');
        if (!state.schema || !state.schema.images) { show(step, false); return; }
        show(step, true);
        var limits = (state.meta && state.meta.limits) || {};
        MIN_IMAGES = limits.minImages || MIN_IMAGES;
        MAX_IMAGES = limits.maxImages || MAX_IMAGES;
        MAX_IMAGE_BYTES = limits.maxImageBytes || MAX_IMAGE_BYTES;
        q('#phImageFields').innerHTML =
            '<p class="tm-sm tm-muted" style="margin:0 0 1rem">'
            + 'Upload at least <strong>' + MIN_IMAGES + '</strong> clear photos (JPEG, PNG or WebP, under '
            + Math.round(MAX_IMAGE_BYTES / 1024) + ' KB each). Show the actual premises \u2014 travellers book from these.</p>'
            + '<div class="ph-drop" id="phDrop" tabindex="0" role="button" aria-label="Add photos">'
            + '<input type="file" id="phImageInput" accept="image/jpeg,image/png,image/webp" multiple hidden>'
            + '<strong>Choose photos</strong><small>or drop them here</small></div>'
            + '<p class="tm-error" id="phImageError" aria-live="polite"></p>'
            + '<div class="ph-thumbs" id="phThumbs"></div>';

        var input = q('#phImageInput');
        var drop = q('#phDrop');
        if (input) input.addEventListener('change', function () { addFiles(input.files); input.value = ''; });
        if (drop) {
            drop.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); }
            });
            ['dragenter', 'dragover'].forEach(function (evt) {
                drop.addEventListener(evt, function (e) { e.preventDefault(); drop.classList.add('is-over'); });
            });
            ['dragleave', 'drop'].forEach(function (evt) {
                drop.addEventListener(evt, function (e) { e.preventDefault(); drop.classList.remove('is-over'); });
            });
            drop.addEventListener('drop', function (e) {
                if (e.dataTransfer && e.dataTransfer.files) addFiles(e.dataTransfer.files);
            });
        }
        renderThumbs();
    }

    function addFiles(fileList) {
        var errEl = q('#phImageError');
        if (errEl) errEl.textContent = '';
        var files = Array.prototype.slice.call(fileList || []);
        files.forEach(function (file) {
            if (state.images.length >= MAX_IMAGES) {
                if (errEl) errEl.textContent = 'You can upload at most ' + MAX_IMAGES + ' photos.';
                return;
            }
            if (['image/jpeg', 'image/png', 'image/webp'].indexOf(file.type) === -1) {
                if (errEl) errEl.textContent = file.name + ' is not a JPEG, PNG or WebP image.';
                return;
            }
            if (file.size > MAX_IMAGE_BYTES) {
                if (errEl) errEl.textContent = file.name + ' is larger than ' + Math.round(MAX_IMAGE_BYTES / 1024) + ' KB.';
                return;
            }
            var reader = new FileReader();
            reader.onload = function (event) {
                state.images.push(String(event.target.result));
                renderThumbs();
            };
            reader.readAsDataURL(file);
        });
    }

    function renderThumbs() {
        var host = q('#phThumbs');
        if (!host) return;
        host.innerHTML = state.images.map(function (src, i) {
            return '<figure class="ph-thumb">'
                + '<img src="' + esc(src) + '" alt="Uploaded photo ' + (i + 1) + '">'
                + '<button type="button" class="ph-thumb__x" data-remove="' + i + '" aria-label="Remove photo ' + (i + 1) + '">&times;</button>'
                + '</figure>';
        }).join('');
        qa('[data-remove]', host).forEach(function (btn) {
            btn.addEventListener('click', function () {
                state.images.splice(Number(btn.getAttribute('data-remove')), 1);
                renderThumbs();
            });
        });
    }

    /* ------------------------------------------------------------------ */
    /* step 6 \u2014 verification documents                                      */
    /* ------------------------------------------------------------------ */
    var REQUIREMENT_LABEL = {
        MANDATORY: 'Required',
        CONDITIONAL: 'Required in some cases',
        OPTIONAL: 'Optional',
        NOT_APPLICABLE: 'Not applicable'
    };

    function buildDocuments() {
        var docs = (state.schema && state.schema.documents) || [];
        var host = q('#phDocumentFields');
        if (!docs.length) {
            host.innerHTML = '<p class="tm-sm tm-muted">No verification documents are required for this role.</p>';
            return;
        }
        host.innerHTML =
            '<p class="tm-sm tm-muted" style="margin:0 0 1rem">'
            + 'Each item is labelled with whether it is legally required, required only in certain '
            + 'circumstances, or simply optional. Where TripMind could not verify a threshold from an '
            + 'official source we say so rather than inventing a rule \u2014 the Main Admin confirms those.</p>'
            + '<div class="ph-doclist">'
            + docs.map(function (d) {
                var badge = (d.requirement || 'OPTIONAL').toLowerCase();
                return '<div class="ph-doc" data-doc="' + esc(d.id) + '">'
                    + '<div class="ph-doc__head">'
                    + '<strong>' + esc(d.label) + '</strong>'
                    + '<span class="ph-req ph-req--' + esc(badge) + '">'
                    + esc(REQUIREMENT_LABEL[d.requirement] || d.requirement) + '</span>'
                    + '</div>'
                    + (d.condition ? '<p class="ph-doc__cond"><strong>Applies when:</strong> ' + esc(d.condition) + '</p>' : '')
                    + (d.help ? '<p class="ph-doc__help">' + esc(d.help) + '</p>' : '')
                    + (d.verified === false ? '<p class="ph-doc__flag">TripMind could not verify the exact threshold from an official source. The Main Admin will confirm this with you.</p>' : '')
                    + '<p class="ph-doc__src">Source: ' + esc(d.source) + (d.alsoWatch ? ' &middot; Watch: ' + esc(d.alsoWatch) : '') + '</p>'
                    + '<div class="tm-field"><label class="tm-label" for="doc_' + esc(d.id) + '">Upload ' + esc(d.label) + '</label>'
                    + '<input class="tm-input" type="file" id="doc_' + esc(d.id) + '" data-docinput="' + esc(d.id) + '" accept="image/*,application/pdf">'
                    + '<span class="tm-help" id="dochelp_' + esc(d.id) + '">No file chosen.</span></div>'
                    + '</div>';
            }).join('')
            + '</div>';

        qa('[data-docinput]', host).forEach(function (input) {
            input.addEventListener('change', function () {
                var file = input.files && input.files[0];
                var help = q('#dochelp_' + input.getAttribute('data-docinput'));
                if (file && help) {
                    help.textContent = file.name + ' (' + Math.round(file.size / 1024) + ' KB)';
                } else if (help) {
                    help.textContent = 'No file chosen.';
                }
                renderDocumentStatus();
            });
        });
    }

    function renderDocumentStatus() {
        var docs = (state.schema && state.schema.documents) || [];
        state.documents = docs.map(function (d) {
            var input = q('#doc_' + d.id);
            var file = (input && input.files && input.files[0]) || null;
            return { id: d.id, label: d.label, file: file };
        }).filter(function (d) { return !!d.file; });
        var missing = docs.filter(function (d) {
            if (d.requirement !== 'MANDATORY') return false;
            var input = q('#doc_' + d.id);
            return !(input && input.files && input.files[0]);
        });
        var note = q('#phDocStatus');
        if (!note) return;
        note.textContent = missing.length
            ? missing.length + ' required document' + (missing.length === 1 ? '' : 's') + ' still to upload: ' + missing.map(function (d) { return d.label; }).join(', ')
            : 'All required documents are attached.';
        note.className = missing.length ? 'tm-help tm-help--warn' : 'tm-help tm-help--ok';
    }

    /* ------------------------------------------------------------------ */
    /* step 7 \u2014 review                                                      */
    /* ------------------------------------------------------------------ */
    function buildReview() {
        q('#phReview').innerHTML =
            '<div class="ph-review" id="phReviewBody"></div>'
            + '<p class="tm-help" id="phDocStatus"></p>'
            + '<label class="ph-consent"><input type="checkbox" id="phTruth" data-validate="required">'
            + '<span>I confirm the information and documents I have provided are accurate and belong to me or my business. I understand TripMind\'s Main Admin will review this application and that I cannot publish anything until it is approved.</span></label>';
        var truth = q('#phTruth');
        if (truth) truth.addEventListener('change', renderReview);
    }

    function collectBusiness() {
        var out = {};
        qa('[data-field]').forEach(function (el) {
            var key = el.getAttribute('data-field');
            out[key] = el.value;
        });
        var multis = collectMulti(q('#phBusinessFields'));
        Object.keys(multis).forEach(function (k) { out[k] = multis[k]; });
        if (state.schema && state.schema.location) out.location = readLocation();
        if (state.schema && state.schema.schedule) out.weeklySchedule = readSchedule();
        return out;
    }

    function fileToDataUri(file) {
        return new Promise(function (resolve, reject) {
            var reader = new FileReader();
            reader.onload = function () { resolve(reader.result); };
            reader.onerror = reject;
            reader.readAsDataURL(file);
        });
    }

    async function collectAll() {
        var docs = await Promise.all(state.documents.map(function (d) {
            return fileToDataUri(d.file).then(function (dataUri) {
                return { id: d.id, data: dataUri, name: d.file.name, size: d.file.size };
            });
        }));
        return {
            role: state.role,
            name: (q('#phName') || {}).value || '',
            email: (q('#phEmail') || {}).value || '',
            mobile: (q('#phMobile') || {}).value || '',
            password: (q('#phPassword') || {}).value || '',
            identityType: (q('#phIdType') || {}).value || '',
            identityNumber: (q('#phIdNumber') || {}).value || '',
            registration: collectBusiness(),
            images: state.images,
            documents: docs
        };
    }

    function row(label, value) {
        if (value === null || value === undefined || value === '' || (Array.isArray(value) && !value.length)) return '';
        return '<div class="ph-review__row"><dt>' + esc(label) + '</dt><dd>' + esc(
            Array.isArray(value) ? value.join(', ') : value) + '</dd></div>';
    }

    function renderReview() {
        var body = q('#phReviewBody');
        if (!body) return;
        var reg = collectBusiness();
        var loc = reg.location || {};
        var html = '<dl class="ph-review__list">';
        html += row('Partner type', state.schema && state.schema.label);
        html += row('Name', (q('#phName') || {}).value);
        html += row('Email', (q('#phEmail') || {}).value);
        html += row('Mobile', (q('#phMobile') || {}).value);
        (state.schema.fields || []).forEach(function (f) {
            var value = reg[f.id];
            if (f.type === 'select' && value) {
                var opt = (f.options || []).find(function (o) { return String(o) === String(value); });
                if (opt) value = opt;
            }
            html += row(f.label, value);
        });
        if (state.schema.location) {
            html += row('Address', loc.address);
            html += row('City', loc.city);
            html += row('District', loc.district);
            html += row('Map place ID', loc.placeId ? 'Captured' : 'Not captured');
        }
        html += row('Photos uploaded', state.images.length + ' of at least ' + MIN_IMAGES);
        var schedule = reg.weeklySchedule || {};
        var openDays = Object.keys(schedule).filter(function (d) { return !schedule[d].closed; });
        html += row('Open days', openDays.length ? openDays.join(', ') : 'Not set');
        var docs = (state.schema.documents) || [];
        html += row('Documents attached', state.documents.length + ' of ' + docs.length);
        html += '</dl>';
        body.innerHTML = html;
        renderDocumentStatus();
    }

    /* ------------------------------------------------------------------ */
    /* validation + submit                                                  */
    /* ------------------------------------------------------------------ */
    function validateStep(index) {
        var list = steps();
        var key = list[index].key;
        var node = q('.ph-step[data-step="' + key + '"]');
        if (!node) return true;
        var ok = true;
        qa('[data-validate]', node).forEach(function (el) {
            var rules = (el.getAttribute('data-validate') || '').split(',');
            var errorNode = el.parentNode.querySelector('.tm-error');
            var value = (el.value || '').trim();
            var message = '';
            rules.forEach(function (rule) {
                rule = rule.trim();
                if (!rule) return;
                if (rule === 'required' && !value) message = 'This field is required.';
                else if (rule === 'email' && value && value.indexOf('@') === -1) message = 'Enter a valid email address.';
                else if (rule === 'mobile' && value && value.replace(/\D/g, '').length !== 10) message = 'Enter a 10-digit mobile number.';
                else if (rule.indexOf('minlen:') === 0 && value && value.length < Number(rule.split(':')[1])) message = 'Must be at least ' + rule.split(':')[1] + ' characters.';
            });
            el.classList.toggle('is-error', !!message);
            if (errorNode) errorNode.textContent = message;
            if (message) ok = false;
        });

        if (key === 'location' && state.schema.location) {
            var loc = readLocation();
            if (!loc.address) ok = false;
            if (!loc.district) ok = false;
            if (!loc.placeId) {
                /* Only demand a Google-Maps pick when Maps is actually
                 * available. `!x.indexOf(y) === false` is a tautology
                 * (indexOf returns a number, !number is a boolean, so this was
                 * always false) which made the manual-entry fallback unreachable. */
                var mapsReady = !!(window.TM_MAPS && TM_MAPS.ready);
                var status = q('#phPlaceStatus');
                var mapsMissing = !!(status && status.textContent
                    && status.textContent.indexOf('Google Maps is not configured') !== -1);
                if (mapsReady && !mapsMissing) {
                    var flag = q('#phPlaceError');
                    if (!flag) {
                        flag = document.createElement('p');
                        flag.id = 'phPlaceError';
                        flag.className = 'tm-error';
                        q('#phLocationFields').appendChild(flag);
                    }
                    flag.textContent = 'Select your location from the Google Maps search so we can verify the address.';
                    ok = false;
                }
            }
        }
        if (key === 'photos' && state.schema.images && state.images.length < MIN_IMAGES) {
            var errEl = q('#phImageError');
            if (errEl) errEl.textContent = 'Upload at least ' + MIN_IMAGES + ' photos.';
            ok = false;
        }
        if (key === 'documents') {
            renderDocumentStatus();
            var missing = ((state.schema.documents) || []).filter(function (d) {
                if (d.requirement !== 'MANDATORY') return false;
                var input = q('#doc_' + d.id);
                return !(input && input.files && input.files[0]);
            });
            if (missing.length) ok = false;
        }
        return ok;
    }

    function submit() {
        if (state.busy) return;
        var list = steps();
        for (var i = 0; i < list.length; i++) {
            if (!validateStep(i)) { goTo(i); return; }
        }
        state.busy = true;
        var btn = q('#phSubmit');
        if (typeof TM !== 'undefined' && TM.button) TM.button(btn, true);

        collectAll().then(function (payload) {
            return apiRequest('/api/auth/register', { method: 'POST', body: JSON.stringify(payload) });
        }).then(function (res) {
            show(q('#phRegForm'), false);
            show(q('#phRoleStep'), false);
            var done = q('#phDone');
            show(done, true);
            done.innerHTML = '<div class="ph-success">'
                + '<h2 class="tm-h3">Application received</h2>'
                + '<p>Thanks \u2014 your ' + esc(state.schema.label) + ' application is with the TripMind Main Admin.</p>'
                + '<ul class="ph-nextsteps">'
                + '<li>You can sign in now to see your pending status, but nothing goes live yet.</li>'
                + '<li>A Main Admin reviews your business details, photos and documents.</li>'
                + '<li>Once approved you can publish your listing and receive bookings.</li>'
                + '</ul>'
                + '<p class="tm-sm"><a class="tm-btn tm-btn--primary" href="/tripmind-partner/login">Go to Partner Hub sign-in</a></p>'
                + '</div>';
            done.scrollIntoView({ block: 'start' });
        }).catch(function (err) {
            state.lastErrors = (err && err.body && err.body.errors) || [];
            alertBox(q('#phMetaError'), (err && err.message) || 'Could not submit your application.', 'error');
            goTo(list.length - 1);
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }).then(function () {
            state.busy = false;
            if (typeof TM !== 'undefined' && TM.button) TM.button(btn, false);
        });
    }

    /* ------------------------------------------------------------------ */
    /* boot                                                                */
    /* ------------------------------------------------------------------ */
    function boot() {
        var next = q('#phNext'), back = q('#phBack'), form = q('#phRegForm');
        if (next) next.addEventListener('click', function () {
            if (validateStep(state.step)) goTo(state.step + 1);
        });
        if (back) back.addEventListener('click', function () { goTo(state.step - 1); });
        if (form) form.addEventListener('submit', function (e) { e.preventDefault(); submit(); });

        var metaPromise;
        try {
            metaPromise = apiRequest('/api/partner/meta');
        } catch (e) {
            /* A synchronous throw here (a missing script, a typo) must not leave
             * the page on its "Loading partner types..." placeholder: the
             * promise chain is never built, so .catch() below never fires. */
            alertBox(q('#phMetaError'),
                'The partner form could not start because a required script failed to load. '
                + 'Please refresh the page, and if it keeps happening contact support.', 'error');
            var grid = q('#phRoleGrid');
            if (grid) grid.innerHTML = '';
            return;
        }

        metaPromise.then(function (meta) {
            state.meta = meta;
            renderRoles();
            var preselect = new URLSearchParams(window.location.search).get('role');
            var wanted = preselect ? resolveRoleKey(meta, preselect) : null;
            if (wanted) {
                var input = q('input[value="' + CSS.escape(wanted) + '"]', q('#phRoleGrid'));
                if (input) { input.checked = true; selectRole(wanted); }
            }
        }).catch(function (err) {
            var grid = q('#phRoleGrid');
            if (grid) grid.innerHTML = '';
            alertBox(q('#phMetaError'),
                'We could not load the partner form (' + ((err && err.message) || 'network error') + '). '
                + 'Please refresh, or contact support if this continues.', 'error');
        });
    }

    /* ?role= is used in links as the slug ("transport") as often as the role
     * key ("TRANSPORT_ADMIN"), so accept either. */
    function resolveRoleKey(meta, wanted) {
        var schemas = (meta && meta.schemas) || {};
        if (schemas[wanted]) return wanted;
        var upper = String(wanted).toUpperCase().replace(/[^A-Z]/g, '_');
        if (schemas[upper]) return upper;
        for (var key in schemas) {
            if (!Object.prototype.hasOwnProperty.call(schemas, key)) continue;
            var slug = (schemas[key] && schemas[key].slug) || '';
            if (slug === wanted) return key;
        }
        return null;
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }
})();
