/* TripMind Partner Hub \u2014 bookings.
 *
 * GET /api/provider/bookings?type=<TYPE> is already owner-scoped and
 * customer-scoped server side, so this page only renders what the partner is
 * allowed to see. The role decides the booking type, the unit noun and which
 * listing collection supplies readable names instead of raw ids.
 *
 * There is no cancel action here: cancellations belong to the traveller,
 * exactly as they do today.
 */
(function () {
    'use strict';

    var P = TM_PARTNER;
    var listHost = document.getElementById('phBookList');
    var statHost = document.getElementById('phBookStats');
    var rows = [];
    var filter = '';
    var names = {};

    /* Per-role booking type, unit noun, and how to name each booked item. */
    var ROLE = {
        TRANSPORT_ADMIN: {
            type: 'TRANSPORT', unit: 'seat', unitLabel: 'Seats', itemLabel: 'Service', seatsLabel: 'Seats sold',
            loadNames: function () {
                return api.getTransports().then(function (r) {
                    ((r && r.transports) || []).forEach(function (v) {
                        var d = v.details || {};
                        names[v.transportId] = P.numberOf(d) + ' \u00b7 ' + P.routeLabel(d);
                    });
                });
            },
            label: function (b) { return names[b.transportId] || b.transportId || 'Service'; }
        },
        HOTEL_ADMIN: {
            type: 'HOTEL', unit: 'room', unitLabel: 'Rooms', itemLabel: 'Property', seatsLabel: 'Rooms booked',
            loadNames: function () {
                return api.getMyHotels().then(function (r) {
                    ((r && r.hotels) || []).forEach(function (h) {
                        names[h.id] = h.name || 'Property';
                    });
                });
            },
            label: function (b) { return names[b.hotelId] || b.hotelId || 'Property'; }
        },
        RESTAURANT_ADMIN: {
            type: 'RESTAURANT', unit: 'table', unitLabel: 'Tables', itemLabel: 'Restaurant', seatsLabel: 'Tables booked',
            loadNames: function () {
                return api.getMyRestaurants().then(function (r) {
                    ((r && r.restaurants) || []).forEach(function (v) {
                        names[v.id] = v.name || 'Restaurant';
                    });
                });
            },
            label: function (b) { return names[b.restaurantId] || b.restaurantId || 'Restaurant'; }
        },
        TOURIST_SPOT_ADMIN: {
            type: 'SPOT', unit: 'visit', unitLabel: 'Visits', itemLabel: 'Spot', seatsLabel: 'Visits booked',
            loadNames: function () {
                return api.getMySpots().then(function (r) {
                    ((r && r.spots) || []).forEach(function (v) {
                        names[v.id] = v.name || 'Spot';
                    });
                });
            },
            label: function (b) { return names[b.spotId] || b.spotId || 'Spot'; }
        },
        GUIDE: {
            type: 'GUIDE', unit: 'assignment', unitLabel: 'Travellers', itemLabel: 'Request', seatsLabel: 'Assignments',
            loadNames: function () { return Promise.resolve(); },
            label: function (b) {
                var d = b.details || {};
                return d.location || 'Guiding request';
            }
        }
    };

    var cfg = ROLE.TRANSPORT_ADMIN;

    function needs(snap) {
        if (!snap) return '';
        var out = (snap.requirements || []).slice();
        if (snap.accessibility) out.push(snap.accessibility);
        return out.length ? 'Needs: ' + out.join(', ') : '';
    }

    function renderStats() {
        var confirmed = rows.filter(function (b) { return b.status === 'CONFIRMED'; });
        var pending = rows.filter(function (b) { return b.status === 'PENDING' || b.status === 'PENDING_PAYMENT'; });
        var today = new Date().toISOString().slice(0, 10);
        var upcoming = confirmed.filter(function (b) { return (b.date || '') >= today; });
        var revenue = confirmed.reduce(function (n, b) { return n + (Number(b.total) || 0); }, 0);
        var units = confirmed.reduce(function (n, b) { return n + (Number(b.qty) || 1); }, 0);

        statHost.innerHTML = [
            { n: rows.length, k: 'Bookings' },
            { n: confirmed.length, k: 'Confirmed' },
            { n: pending.length, k: 'Awaiting payment' },
            { n: upcoming.length, k: 'Upcoming travel' },
            { n: units, k: cfg.seatsLabel },
            { n: P.money(revenue), k: cfg.type === 'GUIDE' ? 'Earnings' : 'Revenue' }
        ].map(function (t) {
            return '<div class="ph-stat"><b>' + P.esc(String(t.n)) + '</b><span>' + P.esc(t.k) + '</span></div>';
        }).join('');
    }

    function render() {
        var shown = filter ? rows.filter(function (b) { return b.status === filter; }) : rows;
        if (!shown.length) {
            listHost.innerHTML = P.empty(
                filter ? 'Nothing with that status' : 'No bookings yet',
                filter ? 'Try another filter to see the rest of your bookings.'
                    : 'When a traveller books with you it appears here with their name, date and party size.');
            return;
        }
        listHost.innerHTML = '<div class="ph-table-scroll"><table class="ph-table"><thead><tr>' +
            '<th>Traveller</th><th>' + P.esc(cfg.itemLabel) + '</th><th>Date</th>' +
            '<th>' + P.esc(cfg.unitLabel) + '</th>' +
            '<th>Preparation</th><th>Amount</th><th>Status</th>' +
            (cfg.type === 'GUIDE' ? '<th>Respond</th>' : '') +
            '</tr></thead><tbody>' + shown.map(function (b) {
                var who = (b.customer && b.customer.name) || 'Traveller';
                var contact = (b.customer && (b.customer.mobile || b.customer.email)) || '';
                var prep = needs(b.partySnapshot);
                return '<tr>' +
                    '<td><span class="ph-table__route">' + P.esc(who) + '</span>' +
                    (contact ? '<span class="ph-table__sub">' + P.esc(contact) + '</span>' : '') + '</td>' +
                    '<td>' + P.esc(cfg.label(b)) + '</td>' +
                    '<td>' + P.esc(P.fmtDate(b.date)) + '</td>' +
                    '<td class="ph-table__num">' + P.esc(b.qty == null ? 1 : b.qty) + '</td>' +
                    '<td><span class="ph-table__sub">' + P.esc(prep || '\u2014') + '</span></td>' +
                    '<td class="ph-table__num">' + P.esc(P.money(b.total)) + '</td>' +
                    '<td>' + P.pill(b.status) + '</td>' +
                    (cfg.type === 'GUIDE' ? '<td>' + respondCells(b) + '</td>' : '') +
                    '</tr>';
            }).join('') + '</tbody></table></div>';

        /* Guides are on the hook for a specific day's answer, so offer the
         * respond action here too, not just on the requests page. */
        if (cfg.type === 'GUIDE') {
            P.qa('[data-req-id]', listHost).forEach(function (btn) {
                btn.addEventListener('click', function () {
                    var id = btn.getAttribute('data-req-id');
                    var action = btn.getAttribute('data-req-action');
                    P.busy(btn, true);
                    apiRequest('/api/guide/requests/' + encodeURIComponent(id), {
                        method: 'POST',
                        body: { action: action, message: '' }
                    }).then(function () {
                        P.toast(action === 'ACCEPT' ? 'Accepted.' : 'Declined.', 'success');
                        return load();
                    }).catch(function (e) {
                        P.toast(e.message, 'error');
                    }).then(function () { P.busy(btn, false); });
                });
            });
        }
    }

    function respondCells(b) {
        if (cfg.type !== 'GUIDE' || b.status !== 'PENDING') return '';
        return '<span class="ph-req-actions-inline">' +
            '<button class="tm-btn tm-btn--primary tm-btn--sm" type="button" data-req-id="' + P.esc(b.id) +
            '" data-req-action="ACCEPT">Accept</button>' +
            '<button class="tm-btn tm-btn--ghost tm-btn--sm" type="button" data-req-id="' + P.esc(b.id) +
            '" data-req-action="REJECT">Decline</button></span>';
    }

    async function load() {
        listHost.innerHTML = P.loading('Loading your bookings\u2026');
        try {
            var res = await api.providerBookings(cfg.type);
            rows = (res && res.bookings) || [];
            /* Name each booked item from the partner's own catalogue so the
             * table is readable instead of a column of ids. */
            try { await cfg.loadNames(); } catch (e) { /* ids are a fine fallback */ }
            renderStats();
            render();
        } catch (e) {
            P.fail(listHost, e);
        }
    }

    P.boot({
        view: function (state) {
            cfg = ROLE[state.role] || ROLE.TRANSPORT_ADMIN;

            P.qa('[data-ph-entity-plural]').forEach(function (n) {
                n.textContent = 'Every booking taken on your own listings, newest first.';
            });
            P.qa('[data-ph-filter]').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    filter = btn.getAttribute('data-ph-filter');
                    P.qa('[data-ph-filter]').forEach(function (b) {
                        var on = b === btn;
                        b.setAttribute('aria-pressed', on ? 'true' : 'false');
                        b.classList.toggle('tm-btn--secondary', on);
                        b.classList.toggle('tm-btn--ghost', !on);
                    });
                    render();
                });
            });
            return load();
        }
    });
})();

