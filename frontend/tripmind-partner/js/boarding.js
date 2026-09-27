/* TripMind Partner Hub — boarding points.
 *
 * A boarding point is a field on the service document, not a separate entity,
 * so this page edits the live document through PUT /api/transport/<id> with the
 * partner's own coordinates. The payload is the full existing document with only
 * the boarding fields replaced, so approval state, seats sold, stops, fares and
 * every booking on the service are untouched.
 */
(function () {
    'use strict';

    var P = TM_PARTNER;
    var listHost = document.getElementById('phPoints');
    var editor = document.getElementById('phEditor');
    var form = document.getElementById('phPointForm');
    var note = document.getElementById('ptNote');
    var submitBtn = document.getElementById('ptSubmit');

    var target = null;   // { transportId, doc }
    var picker = null;

    function el(id) { return document.getElementById(id); }

    function say(message, kind) {
        note.textContent = message;
        note.dataset.show = 'true';
        note.className = 'tm-formnote' + (kind === 'error' ? ' tm-formnote--error' : kind === 'warn' ? ' tm-formnote--warn' : '');
    }

    function coordsLine() {
        var host = el('ptCoords');
        var lat = el('ptLat').value;
        var lng = el('ptLng').value;
        if (!lat && !lng) {
            host.innerHTML = '<span>No coordinates set yet.</span>';
        } else {
            host.innerHTML = '<span>Lat <b>' + P.esc(lat || '—') + '</b></span><span>Lng <b>' +
                P.esc(lng || '—') + '</b></span>';
        }
    }

    function render(views) {
        var buses = views.filter(function (v) { return v.type === 'BUS'; });
        if (!buses.length) {
            listHost.innerHTML = P.empty('No bus services yet',
                'Boarding points belong to a bus, so add a bus service first.',
                '<a class="tm-btn tm-btn--primary" href="/tripmind-partner/buses#add">Add a bus</a>');
            return;
        }
        listHost.innerHTML = '<ul class="ph-rows">' + buses.map(function (v) {
            var d = v.details || {};
            var pinned = d.boardingLat != null && d.boardingLng != null;
            return '<li class="ph-row">' +
                '<div class="ph-row__main">' +
                '<div class="ph-row__title">' + P.esc(P.numberOf(d)) + ' ' + P.pill(v.status) + '</div>' +
                '<p class="ph-row__meta">' + P.esc(d.boardingPoint || 'No boarding point set') +
                (pinned ? ' · ' + P.esc(Number(d.boardingLat).toFixed(4)) + ', ' + P.esc(Number(d.boardingLng).toFixed(4)) : ' · not pinned') +
                '</p></div>' +
                '<div class="ph-row__side">' +
                '<span class="ph-pill ' + (pinned ? 'ph-pill--ok' : 'ph-pill--wait') + '">' + (pinned ? 'On the map' : 'Text only') + '</span>' +
                '<button class="tm-btn tm-btn--ghost tm-btn--sm" type="button" data-ph-edit="' + P.esc(v.transportId) + '">Edit point</button>' +
                '</div></li>';
        }).join('') + '</ul>';

        P.qa('[data-ph-edit]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var id = btn.getAttribute('data-ph-edit');
                var view = buses.filter(function (v) { return v.transportId === id; })[0];
                if (view) openEditor(view);
            });
        });
    }

    function openEditor(view) {
        target = view;
        var d = view.details || {};
        el('phEditorTitle').textContent = 'Boarding point for ' + P.numberOf(d);
        el('ptName').value = d.boardingPoint || '';
        el('ptAddress').value = d.boardingPoint || '';
        el('ptLat').value = d.boardingLat == null ? '' : d.boardingLat;
        el('ptLng').value = d.boardingLng == null ? '' : d.boardingLng;
        coordsLine();
        editor.hidden = false;
        note.dataset.show = 'false';
        /* Fill the map with the current pin so the partner starts where the
         * service already points instead of at a default city. */
        P.locationPicker({
            addressId: 'ptAddress', latId: 'ptLat', lngId: 'ptLng', mapId: 'ptMap',
            onPick: function (v) { coordsLine(); }
        }).then(function (controller) {
            picker = controller;
            if (controller && d.boardingLat != null && d.boardingLng != null) {
                controller.fill(Number(d.boardingLat), Number(d.boardingLng), d.boardingPoint || '');
            }
        });
        editor.scrollIntoView({ behavior: P.reducedMotion() ? 'auto' : 'smooth', block: 'start' });
        el('ptName').focus();
    }

    function closeEditor() {
        editor.hidden = true;
        target = null;
        picker = null;
    }

    async function refresh() {
        try {
            var res = await api.getTransports({ type: 'BUS' });
            var views = (res && res.transports) || [];
            render(views);
            return views;
        } catch (e) {
            P.fail(listHost, e);
            return [];
        }
    }

    P.boot({
        view: function () {
            ['ptLat', 'ptLng'].forEach(function (id) {
                el(id).addEventListener('input', function () {
                    el(id).value = el(id).value.replace(/[^\d.-]/g, '');
                    coordsLine();
                });
            });
            el('ptAddress').addEventListener('input', function () {
                el('ptName').value = el('ptAddress').value.trim();
            });
            el('ptCancel').addEventListener('click', closeEditor);

            form.addEventListener('submit', async function (e) {
                e.preventDefault();
                if (!target) return;
                var name = el('ptName').value.trim();
                if (!name) {
                    TM.fieldError(el('ptName'), 'This field is required.');
                    el('ptName').focus();
                    return;
                }
                TM.fieldError(el('ptName'), '');
                var lat = parseFloat(el('ptLat').value);
                var lng = parseFloat(el('ptLng').value);
                if ((el('ptLat').value || el('ptLng').value) && (isNaN(lat) || isNaN(lng))) {
                    TM.fieldError(el('ptLat'), 'Use a valid number, or clear both boxes.');
                    el('ptLat').focus();
                    return;
                }
                TM.fieldError(el('ptLat'), '');

                var doc = target.details || {};
                /* Full document + the three boarding fields. PUT re-validates the
                 * service, so a boarding point can never quietly corrupt it. */
                var payload = Object.assign({}, doc, {
                    boardingPoint: name,
                    boardingLat: isNaN(lat) ? null : lat,
                    boardingLng: isNaN(lng) ? null : lng
                });

                TM.button(submitBtn, true);
                note.dataset.show = 'false';
                try {
                    await api.updateTransport(target.transportId, payload);
                    say('Boarding point saved. Travellers now see the updated pickup.', 'ok');
                    P.toast('Boarding point saved.', 'ok');
                    await refresh();
                } catch (err) {
                    say(err.message, 'error');
                    P.toast(err.message, 'error');
                } finally {
                    TM.button(submitBtn, false);
                }
            });

            return refresh();
        }
    });
})();
