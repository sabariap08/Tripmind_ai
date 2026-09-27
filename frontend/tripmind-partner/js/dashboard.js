/* TripMind Partner Hub — role-aware dashboard.
 *
 * One dashboard serves all five operational roles. The signed-in role decides
 * which listing collection is loaded, what the entity is called, which
 * management page the call-to-action points at, and which booking type is
 * queried. Nothing here assumes transport.
 */
(function () {
    'use strict';

    var P = TM_PARTNER;

    /* Per-role data wiring. `load` returns the partner's own listings;
     * `bookings` names the provider booking type; `entity` is the noun used
     * in every heading so the copy always matches the role. */
    var VIEW = {
        TRANSPORT_ADMIN: {
            entity: 'service', entityPlural: 'services',
            manageHref: 'buses', manageLabel: 'Manage services',
            addHref: 'buses#add', addLabel: 'Add a service',
            bookingType: 'TRANSPORT',
            load: function () { return api.getTransports().then(function (r) { return r.transports || []; }); },
            statTiles: function (s, rows) {
                return [
                    { n: s.fleet || 0, k: 'Services listed' },
                    { n: s.approvedFleet || 0, k: 'Live for travellers' },
                    { n: s.pendingFleet || 0, k: 'Awaiting review' },
                    { n: s.bookings || 0, k: 'All bookings' },
                    { n: s.confirmedBookings || 0, k: 'Confirmed' },
                    { n: s.upcomingBookings || 0, k: 'Upcoming' },
                    { n: s.seatsBooked || 0, k: 'Seats sold' },
                    { n: s.fleetCapacity || 0, k: 'Total capacity' }
                ];
            },
            rows: function (v) {
                var d = v.details || {};
                var cap = P.capacityOf(d);
                return {
                    title: P.numberOf(d),
                    meta: [P.typeLabelOf(d), P.routeLabel(d)].join(' · '),
                    side: cap ? cap + ' seats' : 'Capacity not set'
                };
            }
        },
        HOTEL_ADMIN: {
            entity: 'property', entityPlural: 'properties',
            manageHref: 'hotels', manageLabel: 'Manage properties',
            addHref: 'hotels#add', addLabel: 'Add a property',
            bookingType: 'HOTEL',
            load: function () { return api.getMyHotels().then(function (r) { return r.hotels || []; }); },
            statTiles: function (s) {
                return [
                    { n: s.hotels || 0, k: 'Properties listed' },
                    { n: s.approvedHotels || 0, k: 'Live for travellers' },
                    { n: s.pendingHotels || 0, k: 'Awaiting review' },
                    { n: s.totalRooms || 0, k: 'Rooms on TripMind' },
                    { n: s.roomsOccupied || 0, k: 'Rooms booked' },
                    { n: s.occupancyPct || 0, k: 'Occupancy %' },
                    { n: s.bookings || 0, k: 'All bookings' },
                    { n: s.confirmedBookings || 0, k: 'Confirmed' }
                ];
            },
            rows: function (v) {
                return {
                    title: v.name || 'Property',
                    meta: [v.category, v.starRating ? v.starRating + ' star' : '', v.city]
                        .filter(Boolean).join(' · '),
                    side: v.totalRooms ? v.totalRooms + ' rooms' : 'Rooms not set'
                };
            }
        },
        RESTAURANT_ADMIN: {
            entity: 'restaurant', entityPlural: 'restaurants',
            manageHref: 'restaurants', manageLabel: 'Manage restaurants',
            addHref: 'restaurants#add', addLabel: 'Add a restaurant',
            bookingType: 'RESTAURANT',
            load: function () { return api.getMyRestaurants().then(function (r) { return r.restaurants || []; }); },
            statTiles: function (s) {
                return [
                    { n: s.restaurants || 0, k: 'Restaurants listed' },
                    { n: s.foodItems || 0, k: 'Menu items' },
                    { n: s.availableItems || 0, k: 'Items available' },
                    { n: s.orders || 0, k: 'Food orders' },
                    { n: s.confirmedOrders || 0, k: 'Confirmed orders' },
                    { n: s.bookings || 0, k: 'Table bookings' },
                    { n: s.confirmedBookings || 0, k: 'Confirmed tables' }
                ];
            },
            rows: function (v) {
                return {
                    title: v.name || 'Restaurant',
                    meta: [v.restaurantType, (v.cuisines || []).join(', '), v.city]
                        .filter(Boolean).join(' · '),
                    side: (v.operatingDays || []).length
                        ? v.operatingDays.length + ' days a week'
                        : 'Hours not set'
                };
            }
        },
        TOURIST_SPOT_ADMIN: {
            entity: 'spot', entityPlural: 'spots',
            manageHref: 'spots', manageLabel: 'Manage spots',
            addHref: 'spots#add', addLabel: 'Add a spot',
            bookingType: 'SPOT',
            load: function () { return api.getMySpots().then(function (r) { return r.spots || []; }); },
            statTiles: function (s) {
                return [
                    { n: s.spots || 0, k: 'Spots listed' },
                    { n: s.approvedSpots || 0, k: 'Live for travellers' },
                    { n: s.pendingSpots || 0, k: 'Awaiting review' },
                    { n: s.tours || 0, k: 'Tours listed' },
                    { n: s.spotVisits || 0, k: 'Visits booked' },
                    { n: s.spotBookings || 0, k: 'Spot bookings' },
                    { n: s.tourBookings || 0, k: 'Tour bookings' },
                    { n: s.revenue || 0, k: 'Confirmed revenue', money: true }
                ];
            },
            rows: function (v) {
                return {
                    title: v.name || 'Spot',
                    meta: [v.category, v.city, v.address].filter(Boolean).join(' · '),
                    side: v.entryFee ? P.money(v.entryFee) + ' entry' : 'Free entry'
                };
            }
        },
        GUIDE: {
            entity: 'guide profile', entityPlural: 'profiles',
            manageHref: 'guide-requests', manageLabel: 'Guide requests',
            addHref: 'profile', addLabel: 'Edit my profile',
            bookingType: 'GUIDE',
            load: function () { return Promise.resolve([P.state.user]); },
            statTiles: function (s, rows, requests) {
                return [
                    { n: s.pendingRequests || 0, k: 'Requests to answer' },
                    { n: s.assignments || 0, k: 'Confirmed assignments' },
                    { n: s.completed || 0, k: 'Completed' },
                    { n: s.upcoming || 0, k: 'Upcoming' },
                    { n: s.availableDays || 0, k: 'Days available' },
                    { n: s.pricingPerHour || 0, k: 'Your hourly rate', money: true },
                    { n: s.specialty || '—', k: 'Specialty', text: true },
                    { n: s.earnings || 0, k: 'Earnings', money: true }
                ];
            },
            rows: function (v) {
                var me = v || {};
                var r = P.reg(me);
                return {
                    title: r.guideName || me.name || 'Your guide profile',
                    meta: [r.baseCity, r.experienceYears ? r.experienceYears + ' yrs experience' : '']
                        .filter(Boolean).join(' · '),
                    side: me.approvalStatus || 'PENDING'
                };
            }
        }
    };

    function status(row) {
        return String((row && (row.status || row.approvalStatus)) || '').toUpperCase();
    }

    function view(state) {
        var role = state.role;
        var cfg = VIEW[role] || VIEW.TRANSPORT_ADMIN;

        P.boot({
            view: function (st) {
                var first = String((st.user && st.user.name) || '').trim().split(/\s+/)[0];
                P.qa('[data-ph-firstname]').forEach(function (n) { n.textContent = first || 'partner'; });
                P.qa('[data-ph-entity]').forEach(function (n) { n.textContent = cfg.entityPlural; });
                P.qa('[data-ph-entity-singular]').forEach(function (n) { n.textContent = cfg.entity; });
                P.qa('[data-ph-manage-href]').forEach(function (n) { n.href = P.PARTNER_PREFIX + '/' + cfg.manageHref; });
                P.qa('[data-ph-manage-label]').forEach(function (n) { n.textContent = cfg.manageLabel; });
                P.qa('[data-ph-add-href]').forEach(function (n) { n.href = P.PARTNER_PREFIX + '/' + cfg.addHref; });
                P.qa('[data-ph-add-label]').forEach(function (n) { n.textContent = cfg.addLabel; });

                // The "next departures" panel is transport vocabulary. A hotel
                // wants its next arrival day, a guide their open requests, so
                // the panel is swapped per role rather than mislabelled.
                var nextPanel = P.q('#phNextPanel');
                if (nextPanel) {
                    if (role === 'TRANSPORT_ADMIN') { nextPanel.hidden = false; }
                    else { nextPanel.hidden = true; }
                }

                var jobs = [
                    api.providerStats().catch(function () { return {}; }),
                    cfg.load().catch(function (e) { P.toast(e.message, 'error'); return []; }),
                    api.providerBookings(cfg.bookingType).catch(function () { return { bookings: [] }; }),
                    role === 'GUIDE'
                        ? api.guideRequests().catch(function () { return { requests: [] }; })
                        : Promise.resolve({ requests: [] })
                ];

                return Promise.all(jobs).then(function (res) {
                    var stats = res[0] || {};
                    var rows = res[1] || [];
                    var bookings = (res[2] && res[2].bookings) || [];
                    var requests = (res[3] && res[3].requests) || [];

                    renderStats(cfg, stats, rows, requests);
                    renderListings(cfg, rows);
                    if (role === 'TRANSPORT_ADMIN') renderNext(rows);
                    renderRequests(role, requests);
                    renderBookings(bookings, cfg);
                });
            }
        });
    }

    function renderStats(cfg, stats, rows) {
        var tiles = cfg.statTiles(stats, rows);
        var host = P.q('#phStats');
        if (host) {
            host.innerHTML = tiles.map(function (t) {
                var value = t.money ? P.money(t.n) : P.esc(String(t.n));
                return '<div class="ph-stat"><b>' + value + '</b><span>' + P.esc(t.k) + '</span></div>';
            }).join('');
        }

        var revenue = P.q('#phRevenue');
        if (revenue) {
            var money = stats.revenue != null ? stats.revenue : (stats.earnings || 0);
            revenue.textContent = P.money(money || 0);
        }

        var pendingNote = P.q('#phPendingNote');
        if (pendingNote) {
            var pendingKeys = ['pendingFleet', 'pendingHotels', 'pendingSpots'];
            var pendingCount = 0;
            pendingKeys.forEach(function (k) { pendingCount += (stats[k] || 0); });
            pendingNote.hidden = !pendingCount;
        }
    }

    function renderListings(cfg, rows) {
        var host = P.q('#phFleet');
        if (!host) return;
        if (!rows.length) {
            host.innerHTML = P.empty('Nothing listed yet',
                'Add your first ' + cfg.entity + ' and it appears here as soon as the TripMind team approves it.',
                '<a class="tm-btn tm-btn--primary" href="' + P.PARTNER_PREFIX + '/' + cfg.addHref + '">' +
                P.esc(cfg.addLabel) + '</a>');
            return;
        }
        host.innerHTML = '<ul class="ph-rows">' + rows.slice(0, 6).map(function (v) {
            var r = cfg.rows(v);
            return '<li class="ph-row"><div class="ph-row__main">' +
                '<div class="ph-row__title">' + P.esc(r.title) + ' ' + P.pill(status(v)) + '</div>' +
                '<p class="ph-row__meta">' + P.esc(r.meta) + '</p></div>' +
                '<div class="ph-row__side"><span class="tm-2xs tm-muted">' + P.esc(r.side) + '</span>' +
                '<a class="tm-btn tm-btn--ghost tm-btn--sm" href="' + P.PARTNER_PREFIX + '/' +
                cfg.manageHref + '">Edit</a></div></li>';
        }).join('') + '</ul>';
    }

    function renderNext(rows) {
        var host = P.q('#phNext');
        if (!host) return;
        var live = rows.filter(function (v) { return status(v) === 'APPROVED'; });
        if (!live.length) {
            host.innerHTML = P.empty('Nothing scheduled yet',
                'Once a service is approved, its boarding day, time and stop show up here.');
            return;
        }
        host.innerHTML = '<ul class="ph-rows">' + live.slice(0, 5).map(function (v) {
            var d = v.details || {};
            return '<li class="ph-row"><div class="ph-row__main">' +
                '<div class="ph-row__title">' + P.esc(P.numberOf(d)) + '</div>' +
                '<p class="ph-row__meta">' + P.esc(P.fmtDayTime(d)) + ' · from ' +
                P.esc(d.boardingPoint || d.baseLocation || '—') + '</p></div>' +
                '<div class="ph-row__side"><span class="tm-2xs tm-muted">' +
                P.esc(P.typeLabelOf(d)) + '</span></div></li>';
        }).join('') + '</ul>';
    }

    function renderRequests(role, requests) {
        var host = P.q('#phRequests');
        if (!host) return;
        if (role !== 'GUIDE') { host.closest('.ph-panel').hidden = true; return; }
        if (!requests.length) {
            host.innerHTML = P.empty('No open requests',
                'When a traveller asks for your guiding on a date, it arrives here for you to accept or decline.');
            return;
        }
        host.innerHTML = '<ul class="ph-rows">' + requests.slice(0, 6).map(function (r) {
            var d = r.details || {};
            return '<li class="ph-row"><div class="ph-row__main">' +
                '<div class="ph-row__title">' + P.esc(r.reference || 'Request') + ' ' + P.pill(r.status) + '</div>' +
                '<p class="ph-row__meta">' + P.esc(P.fmtDate(r.date)) +
                (d.startTime ? ' · ' + P.esc(d.startTime) + '–' + P.esc(d.endTime || '') : '') +
                (d.location ? ' · ' + P.esc(d.location) : '') + '</p></div>' +
                '<div class="ph-row__side"><span class="tm-sm">' + P.esc(P.money(r.total)) + '</span></div></li>';
        }).join('') + '</ul>';
    }

    function renderBookings(bookings, cfg) {
        var host = P.q('#phBookings');
        if (!host) return;
        if (!bookings.length) {
            host.innerHTML = P.empty('No bookings yet',
                'When a traveller books one of your ' + cfg.entityPlural + ' it shows up here with their date.');
            return;
        }
        host.innerHTML = '<ul class="ph-rows">' + bookings.slice(0, 6).map(function (b) {
            var who = (b.customer && b.customer.name) || 'Traveller';
            var party = b.partySnapshot && b.partySnapshot.count
                ? ' · party of ' + b.partySnapshot.count : '';
            var flags = (b.partySnapshot && b.partySnapshot.requirements || []).join(', ');
            return '<li class="ph-row"><div class="ph-row__main">' +
                '<div class="ph-row__title">' + P.esc(who) + ' ' + P.pill(b.status) + '</div>' +
                '<p class="ph-row__meta">' + P.esc(P.fmtDate(b.date)) +
                (b.qty ? ' · ' + P.esc(b.qty) + ' ' + P.esc(cfg.entity) + (Number(b.qty) > 1 ? 's' : '') : '') +
                party + (flags ? ' · ' + P.esc(flags) : '') +
                '</p></div><div class="ph-row__side"><span class="tm-sm">' +
                P.esc(P.money(b.total)) + '</span></div></li>';
        }).join('') + '</ul>';
    }

    view();
})();
