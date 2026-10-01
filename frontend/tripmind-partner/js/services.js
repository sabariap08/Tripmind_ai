/* TripMind Partner Hub \u2014 My services (add / edit fleet).
 *
 * Talks to the existing transport API only:
 *   GET  /api/transport/list    -> the partner's own documents (owner-scoped)
 *   POST /api/transport/register-> create (always starts PENDING)
 *   PUT  /api/transport/<id>    -> edit (re-validated, approval state kept)
 *
 * The service name is never asked for here: it comes from the partner's
 * service profile, exactly as the platform has always worked.
 */
(function () {
    'use strict';

    var P = TM_PARTNER;
    var f = document.getElementById('phSvcForm');
    var listHost = document.getElementById('phList');
    var note = document.getElementById('svcNote');
    var submit = document.getElementById('svcSubmit');
    var reset = document.getElementById('svcReset');
    var formTitle = document.getElementById('phFormTitle');
    var formSub = document.getElementById('phFormSub');

    var editing = null;      // full transport document while editing
    var pickerFrom = null;
    var pickerTo = null;

    function el(id) { return document.getElementById(id); }

    function say(message, kind) {
        note.textContent = message;
        note.dataset.show = 'true';
        note.className = 'tm-formnote' + (kind === 'error' ? ' tm-formnote--error' : kind === 'warn' ? ' tm-formnote--warn' : '');
    }

    function typeOf() {
        var checked = f.querySelector('input[name="svcType"]:checked');
        return checked ? checked.value : 'BUS';
    }

    function applyType() {
        var t = typeOf();
        var isBus = t === 'BUS';
        P.qa('[data-ph-only-bus]').forEach(function (n) { n.hidden = !isBus; });
        P.qa('[data-ph-only-cab]').forEach(function (n) { n.hidden = isBus; });
        var label = P.q('[data-ph-number-label]');
        if (label) label.textContent = isBus ? 'Bus number' : 'Vehicle number';
        formTitle.textContent = isBus ? 'Add a bus' : 'Add a ' + t.toLowerCase();
        el('svcFrom').required = isBus;
        el('svcTotal').required = isBus;
        el('svcFare').required = isBus;
        el('svcArea').required = !isBus;
        el('svcPerKm').required = !isBus;
        if (isBus) syncTotal();
    }

    /* The backend rejects a bus whose sleeper + seater does not equal the
     * total, so keep the three numbers consistent as the partner types. */
    function syncTotal() {
        var seater = parseInt(el('svcSeater').value, 10) || 0;
        var sleeper = parseInt(el('svcSleeper').value, 10) || 0;
        var total = parseInt(el('svcTotal').value, 10) || 0;
        if (total !== seater + sleeper) {
            var hint = P.q('[data-ph-total-hint]');
            if (hint) hint.textContent = 'Sleeper + seater must equal the total (' + (seater + sleeper) + ' right now).';
        } else {
            var h = P.q('[data-ph-total-hint]');
            if (h) h.textContent = 'Sleeper + seater must equal the total.';
        }
    }

    function coordsLine(node, lat, lng) {
        if (!node) return;
        if (lat == null || lng == null || isNaN(parseFloat(lat))) {
            node.innerHTML = '<span>No coordinates yet \u2014 travellers will see the text only.</span>';
        } else {
            node.innerHTML = '<span>Lat <b>' + P.esc(Number(lat).toFixed(4)) + '</b></span>' +
                '<span>Lng <b>' + P.esc(Number(lng).toFixed(4)) + '</b></span>';
        }
    }

    function wireMaps() {
        /* The boarding point is the one place travellers search, so it gets a
         * live picker; the dropping point stays a text field the way the
         * traveller planner treats it. */
        P.locationPicker({
            addressId: 'svcFrom', latId: 'svcFromLat', lngId: 'svcFromLng', mapId: 'svcFromMap',
            onPick: function (v) {
                coordsLine(el('svcFromCoords'), v.latitude, v.longitude);
            }
        }).then(function (controller) {
            if (!controller) {
                var map = el('svcFromMap');
                if (map) map.setAttribute('data-ready', 'false');
            }
        });
        el('svcFrom').addEventListener('input', function () {
            coordsLine(el('svcFromCoords'), el('svcFromLat').value, el('svcFromLng').value);
        });
    }

    function num(id) {
        var v = parseInt(el(id).value, 10);
        return isNaN(v) ? 0 : v;
    }

    function collect() {
        var t = typeOf();
        if (t === 'BUS') {
            return {
                type: 'BUS',
                busNumber: el('svcNumber').value.trim(),
                boardingPoint: el('svcFrom').value.trim(),
                boardingLat: el('svcFromLat').value || null,
                boardingLng: el('svcFromLng').value || null,
                droppingPoint: el('svcTo').value.trim(),
                droppingLat: el('svcToLat').value || null,
                droppingLng: el('svcToLng').value || null,
                boardingDay: num('svcDay'),
                boardingTime: el('svcTime').value || '06:00',
                droppingDay: num('svcDropDay'),
                droppingTime: el('svcDropTime').value || '09:00',
                seaterSeats: num('svcSeater'),
                sleeperSeats: num('svcSleeper'),
                totalSeats: num('svcTotal'),
                seatTypes: [el('svcSleeper').value && num('svcSleeper') > 0 ? 'SLEEPER' : null,
                            el('svcSeater').value && num('svcSeater') > 0 ? 'SEATER' : null].filter(Boolean),
                stops: (editing && editing.stops) || [],
                fare: num('svcFare'),
                images: (editing && editing.images) || [],
                documents: (editing && editing.documents) || []
            };
        }
        return {
            type: t,
            vehicleNumber: el('svcNumber').value.trim(),
            vehicleType: t,
            seatingCapacity: num('svcCapacity') || 4,
            ac: el('svcAc').value === '1',
            serviceArea: el('svcArea').value.trim(),
            baseLocation: el('svcBase').value.trim(),
            fare: {
                baseFare: parseFloat(el('svcBaseFare').value) || 0,
                pricePerKm: parseFloat(el('svcPerKm').value) || 0,
                minimum: parseFloat(el('svcBaseFare').value) || 0
            },
            driver: (editing && editing.driver) || {},
            images: (editing && editing.images) || [],
            documents: (editing && editing.documents) || []
        };
    }

    function problems(payload) {
        var out = [];
        if (!payload.busNumber && !payload.vehicleNumber) out.push('Enter the bus or vehicle number.');
        if (payload.type === 'BUS') {
            if (!payload.boardingPoint) out.push('Enter the boarding point.');
            if (!payload.droppingPoint) out.push('Enter the dropping point.');
            if (payload.sleeperSeats + payload.seaterSeats !== payload.totalSeats) {
                out.push('Sleeper + seater seats must equal the total seats.');
            }
            if (payload.totalSeats <= 0) out.push('Total seats must be more than zero.');
            if (!payload.fare) out.push('Set the fare.');
        } else {
            if (!payload.serviceArea) out.push('Enter the service area you cover.');
            if (!payload.fare.pricePerKm) out.push('Set a fare per km.');
        }
        return out;
    }

    function fillForm(view) {
        var d = (view && view.details) || {};
        editing = view;
        var type = d.type || 'BUS';
        var radio = f.querySelector('input[name="svcType"][value="' + type + '"]')
            || f.querySelector('input[name="svcType"]');
        if (radio) radio.checked = true;
        applyType();
        el('svcNumber').value = P.numberOf(d) === '\u2014' ? '' : P.numberOf(d);
        if (type === 'BUS') {
            el('svcFrom').value = d.boardingPoint || '';
            el('svcFromLat').value = d.boardingLat == null ? '' : d.boardingLat;
            el('svcFromLng').value = d.boardingLng == null ? '' : d.boardingLng;
            el('svcTo').value = d.droppingPoint || '';
            el('svcToLat').value = d.droppingLat == null ? '' : d.droppingLat;
            el('svcToLng').value = d.droppingLng == null ? '' : d.droppingLng;
            el('svcSeater').value = d.seaterSeats || 0;
            el('svcSleeper').value = d.sleeperSeats || 0;
            el('svcTotal').value = d.totalSeats || 0;
            el('svcFare').value = d.fare || '';
            el('svcDay').value = d.boardingDay == null ? 0 : d.boardingDay;
            el('svcTime').value = d.boardingTime || '06:00';
            el('svcDropDay').value = d.droppingDay == null ? 0 : d.droppingDay;
            el('svcDropTime').value = d.droppingTime || '09:00';
        } else {
            el('svcArea').value = d.serviceArea || '';
            el('svcBase').value = d.baseLocation || '';
            el('svcCapacity').value = d.seatingCapacity || 4;
            el('svcAc').value = d.ac ? '1' : '0';
            var fare = d.fare || {};
            el('svcPerKm').value = fare.pricePerKm || fare.perKm || '';
            el('svcBaseFare').value = fare.baseFare || '';
        }
        coordsLine(el('svcFromCoords'), el('svcFromLat').value, el('svcFromLng').value);
        formTitle.textContent = 'Edit service ' + P.numberOf(d);
        formSub.textContent = 'Changes keep the current approval status. What travellers see updates once you save.';
        submit.textContent = 'Save changes';
        document.getElementById('add').scrollIntoView({ behavior: P.reducedMotion() ? 'auto' : 'smooth', block: 'start' });
    }

    function clearForm() {
        editing = null;
        f.reset();
        el('svcFromLat').value = '';
        el('svcFromLng').value = '';
        el('svcToLat').value = '';
        el('svcToLng').value = '';
        applyType();
        coordsLine(el('svcFromCoords'), null, null);
        formTitle.textContent = 'Add a service';
        formSub.textContent = 'Set the route, schedule, seats and fare. The TripMind team reviews it before travellers can book it.';
        submit.textContent = 'Submit for review';
        note.dataset.show = 'false';
    }

    function renderList(views) {
        if (!views.length) {
            listHost.innerHTML = P.empty('Nothing listed yet',
                'Use the form above to add your first bus or vehicle.');
            return;
        }
        listHost.innerHTML = '<div class="ph-table-scroll"><table class="ph-table"><thead><tr>' +
            '<th>Service</th><th>Route</th><th>Schedule</th><th>Seats</th><th>Fare</th><th>Status</th><th></th>' +
            '</tr></thead><tbody>' + views.map(function (v) {
                var d = v.details || {};
                var fare = d.type === 'BUS' ? P.money(d.fare)
                    : P.money(((d.fare || {}).baseFare || 0)) + ' + ' + P.money(((d.fare || {}).pricePerKm || 0)) + '/km';
                return '<tr>' +
                    '<td><span class="ph-table__route">' + P.esc(P.numberOf(d)) + '</span>' +
                    '<span class="ph-table__sub">' + P.esc(P.typeLabelOf(d)) + ' \u00b7 ' + P.esc(v.serviceName || P.serviceName()) + '</span></td>' +
                    '<td>' + P.esc(P.routeLabel(d)) + '</td>' +
                    '<td>' + P.esc(P.fmtDayTime(d)) + '</td>' +
                    '<td class="ph-table__num">' + P.esc(P.capacityOf(d) || '\u2014') + '</td>' +
                    '<td class="ph-table__num">' + P.esc(fare) + '</td>' +
                    '<td>' + P.pill(v.status) + (v.status === 'REJECTED' && d.rejectionReason
                        ? '<span class="ph-table__sub">' + P.esc(d.rejectionReason) + '</span>' : '') + '</td>' +
                    '<td class="ph-table__num"><button class="tm-btn tm-btn--ghost tm-btn--sm" type="button" data-ph-edit="' +
                    P.esc(v.transportId) + '">Edit</button></td>' +
                    '</tr>';
            }).join('') + '</tbody></table></div>';

        P.qa('[data-ph-edit]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var id = btn.getAttribute('data-ph-edit');
                var view = views.filter(function (v) { return v.transportId === id; })[0];
                if (view) fillForm(view);
            });
        });
    }

    async function refresh() {
        try {
            var res = await api.getTransports();
            var views = (res && res.transports) || [];
            renderList(views);
            return views;
        } catch (e) {
            P.fail(listHost, e);
            return [];
        }
    }

    P.boot({
        view: function (state) {
            /* Only transport partners manage buses/cabs/autos. */
            if (state.role !== 'TRANSPORT_ADMIN') {
                P.go('dashboard');
                return;
            }
            f.querySelectorAll('input[name="svcType"]').forEach(function (r) {
                r.addEventListener('change', function () {
                    if (editing) clearForm();
                    applyType();
                });
            });
            el('svcSeater').addEventListener('input', syncTotal);
            el('svcSleeper').addEventListener('input', syncTotal);
            el('svcTotal').addEventListener('input', syncTotal);
            applyType();
            wireMaps();

            reset.addEventListener('click', function () { clearForm(); });

            f.addEventListener('submit', async function (e) {
                e.preventDefault();
                var payload = collect();
                var issues = problems(payload);
                if (issues.length) {
                    say(issues[0], 'error');
                    P.toast(issues[0], 'error');
                    return;
                }
                TM.button(submit, true);
                note.dataset.show = 'false';
                try {
                    if (editing) {
                        await api.updateTransport(editing.transportId, payload);
                        P.toast('Service updated.', 'ok');
                    } else {
                        await api.registerTransport(payload);
                        P.toast('Submitted for review. We will approve it shortly.', 'ok');
                    }
                    clearForm();
                    await refresh();
                } catch (err) {
                    say(err.message, 'error');
                    P.toast(err.message, 'error');
                } finally {
                    TM.button(submit, false);
                }
            });

            return refresh();
        }
    });
})();
