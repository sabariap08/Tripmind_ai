/* TripMind Partner Hub — bookings.
 *
 * GET /api/provider/bookings?type=TRANSPORT is already owner-scoped and
 * customer-scoped server side, so this page only renders what the partner is
 * allowed to see. There is no cancel action here: cancellations belong to the
 * traveller, exactly as they do today.
 */
(function () {
    'use strict';

    var P = TM_PARTNER;
    var listHost = document.getElementById('phBookList');
    var statHost = document.getElementById('phBookStats');
    var rows = [];
    var filter = '';
    var transportNames = {};

    function serviceLabel(id) {
        return transportNames[id] || id || 'Service';
    }

    function renderStats() {
        var confirmed = rows.filter(function (b) { return b.status === 'CONFIRMED'; });
        var pending = rows.filter(function (b) { return b.status === 'PENDING' || b.status === 'PENDING_PAYMENT'; });
        var today = new Date().toISOString().slice(0, 10);
        var upcoming = confirmed.filter(function (b) { return (b.date || '') >= today; });
        var revenue = confirmed.reduce(function (n, b) { return n + (Number(b.total) || 0); }, 0);
        var seats = confirmed.reduce(function (n, b) { return n + (Number(b.qty) || 1); }, 0);

        statHost.innerHTML = [
            { n: rows.length, k: 'Bookings' },
            { n: confirmed.length, k: 'Confirmed' },
            { n: pending.length, k: 'Awaiting payment' },
            { n: upcoming.length, k: 'Upcoming travel' },
            { n: seats, k: 'Seats sold' },
            { n: P.money(revenue), k: 'Revenue' }
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
                    : 'When a traveller books one of your services it appears here with their name, date and seats.');
            return;
        }
        listHost.innerHTML = '<div class="ph-table-scroll"><table class="ph-table"><thead><tr>' +
            '<th>Traveller</th><th>Service</th><th>Travel date</th><th>Seats</th><th>Amount</th><th>Status</th>' +
            '</tr></thead><tbody>' + shown.map(function (b) {
                var who = (b.customer && b.customer.name) || 'Traveller';
                var contact = (b.customer && (b.customer.mobile || b.customer.email)) || '';
                return '<tr>' +
                    '<td><span class="ph-table__route">' + P.esc(who) + '</span>' +
                    (contact ? '<span class="ph-table__sub">' + P.esc(contact) + '</span>' : '') + '</td>' +
                    '<td>' + P.esc(serviceLabel(b.transportId)) + '</td>' +
                    '<td>' + P.esc(P.fmtDate(b.date)) + '</td>' +
                    '<td class="ph-table__num">' + P.esc(b.qty == null ? 1 : b.qty) + '</td>' +
                    '<td class="ph-table__num">' + P.esc(P.money(b.total)) + '</td>' +
                    '<td>' + P.pill(b.status) + '</td>' +
                    '</tr>';
            }).join('') + '</tbody></table></div>';
    }

    async function load() {
        listHost.innerHTML = P.loading('Loading your bookings…');
        try {
            var res = await api.providerBookings('TRANSPORT');
            rows = (res && res.bookings) || [];
            /* Name each service from the partner's own fleet so the table is
             * readable instead of a column of ids. */
            try {
                var fleet = await api.getTransports();
                ((fleet && fleet.transports) || []).forEach(function (v) {
                    var d = v.details || {};
                    transportNames[v.transportId] = P.numberOf(d) + ' · ' + P.routeLabel(d);
                });
            } catch (e) { /* ids are a fine fallback */ }
            renderStats();
            render();
        } catch (e) {
            P.fail(listHost, e);
        }
    }

    P.boot({
        view: function () {
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
