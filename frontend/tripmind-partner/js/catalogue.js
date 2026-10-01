/* TripMind Partner Hub \u2014 shared catalogue manager.
 *
 * Hotels, restaurants and tourist spots all follow the same partner loop:
 * list what you own, add something new, edit it, and wait for Main Admin
 * review before it is visible to travellers. Rather than three near-identical
 * page scripts, each page supplies its resource wiring and this module handles
 * the form, validation messaging, list rendering and review state.
 */
var TM_CATALOGUE = (function () {
    'use strict';

    var P = TM_PARTNER;

    /* Field descriptors per resource. `value` reads the payload value back out
     * of a saved document so edit mode can prefill the form. */
    function text(name, label, opts) {
        return { name: name, label: label, type: 'text', value: function (d) { return d[name] || ''; },
            attrs: (opts && opts.attrs) || {} };
    }

    function num(name, label, opts) {
        opts = opts || {};
        return {
            name: name, label: label, type: 'number',
            value: function (d) { return d[name] != null ? d[name] : (opts.fallback || ''); },
            attrs: { min: opts.min != null ? opts.min : 1, step: opts.step || 1,
                inputmode: opts.step && opts.step < 1 ? 'decimal' : 'numeric' }
        };
    }

    function select(name, label, options, valueFn) {
        return {
            name: name, label: label, type: 'select', options: options,
            value: valueFn || function (d) { return d[name] || ''; }
        };
    }

    function list(name, label) {
        return {
            name: name, label: label, type: 'list',
            value: function (d) { return (d[name] || []).join(', '); },
            parse: function (raw) {
                return String(raw || '').split(',').map(function (s) { return s.trim(); })
                    .filter(Boolean);
            }
        };
    }

    /* One item per line: image URLs. */
    function lines(name, label) {
        return {
            name: name, label: label, type: 'lines',
            value: function (d) { return (d[name] || []).join('\n'); },
            parse: function (raw) {
                return String(raw || '').split('\n').map(function (s) { return s.trim(); })
                    .filter(Boolean);
            }
        };
    }

    /* Visiting slots typed as "08:00-10:00" become {from,to,note} objects,
     * which is the shape the backend slot parser expects. */
    function slots(name, label) {
        return {
            name: name, label: label, type: 'slots',
            value: function (d) {
                return (d[name] || []).map(function (s) {
                    return (s && s.from) ? s.from + '-' + (s.to || s.from) : String(s);
                }).join(', ');
            },
            parse: function (raw) {
                return String(raw || '').split(',').map(function (s) { return s.trim(); })
                    .filter(Boolean).map(function (s) {
                        var m = s.split('-');
                        if (m.length >= 2) return { from: m[0].trim(), to: m[1].trim(), note: '' };
                        return { from: s, to: s, note: '' };
                    });
            }
        };
    }

    var FIELDS = {
        hotelFields: [
            text('name', 'Property name', { attrs: { maxlength: 120, required: true, placeholder: 'e.g. Beach View Residency' } }),
            select('category', 'Category', ['Hotel', 'Resort', 'Homestay', 'Guest house', 'Hostel', 'Other'],
                function (d) { return d.category || ''; }),
            text('city', 'City', { attrs: { maxlength: 80, required: true, placeholder: 'e.g. Mahabalipuram' } }),
            text('address', 'Address', { attrs: { maxlength: 200, required: true, placeholder: 'Street and area' } }),
            num('totalRooms', 'Total rooms', { min: 1 }),
            select('starRating', 'Star rating',
                [['', 'Not classified'], ['1', '1 star'], ['2', '2 star'], ['3', '3 star'],
                    ['4', '4 star'], ['5', '5 star']],
                function (d) { return d.starRating != null && d.starRating !== '' ? String(d.starRating) : ''; }),
            { name: 'checkInTime', label: 'Check-in time', type: 'time', value: function (d) { return d.checkInTime || '12:00'; } },
            { name: 'checkOutTime', label: 'Check-out time', type: 'time', value: function (d) { return d.checkOutTime || '11:00'; } },
            text('contactNumber', 'Contact number', { attrs: { maxlength: 20, required: true, placeholder: '98765 43210' } }),
            text('email', 'Contact email', { attrs: { type: 'email', maxlength: 120, placeholder: 'frontdesk@example.com' } }),
            list('amenities', 'Amenities (comma separated)'),
            lines('images', 'Image URLs (one per line)'),
            text('description', 'Description', { type: 'textarea', value: function (d) { return d.description || ''; } })
        ],
        restaurantFields: [
            text('name', 'Restaurant name', { attrs: { maxlength: 120, required: true, placeholder: 'e.g. Saravana Bhavan' } }),
            select('restaurantType', 'Restaurant type',
                ['Vegetarian', 'Non-vegetarian', 'Pure vegetarian', 'Multi-cuisine', 'Cafe', 'Bakery', 'Food court', 'Other'],
                function (d) { return d.restaurantType || ''; }),
            text('city', 'City', { attrs: { maxlength: 80, required: true, placeholder: 'e.g. Chennai' } }),
            text('address', 'Address', { attrs: { maxlength: 200, required: true, placeholder: 'Street and area' } }),
            text('contactNumber', 'Contact number', { attrs: { maxlength: 20, required: true, placeholder: '98765 43210' } }),
            text('email', 'Contact email', { attrs: { type: 'email', maxlength: 120 } }),
            list('cuisines', 'Cuisines (comma separated)'),
            list('operatingDays', 'Operating days (comma separated, e.g. Monday, Tuesday)'),
            list('openingHours', 'Opening hours (comma separated, e.g. 11:00-22:30)'),
            lines('images', 'Image URLs (one per line)'),
            text('description', 'Description', { type: 'textarea', value: function (d) { return d.description || ''; } })
        ],
        spotFields: [
            text('name', 'Spot name', { attrs: { maxlength: 120, required: true, placeholder: 'e.g. Shore Temple' } }),
            select('category', 'Category',
                ['HISTORICAL', 'BEACH', 'HILL', 'WATERFALL', 'WILDLIFE', 'RELIGIOUS', 'MUSEUM', 'GARDEN', 'ADVENTURE', 'OTHER'],
                function (d) { return d.category || ''; }),
            text('city', 'City', { attrs: { maxlength: 80, required: true, placeholder: 'e.g. Mahabalipuram' } }),
            text('address', 'Address', { attrs: { maxlength: 200, required: true, placeholder: 'Where travellers should go' } }),
            num('entryFee', 'Entry fee (\u20b9)', { min: 0, fallback: 0 }),
            { name: 'openingTime', label: 'Opens', type: 'time', value: function (d) { return d.openingTime || '09:00'; } },
            { name: 'closingTime', label: 'Closes', type: 'time', value: function (d) { return d.closingTime || '18:00'; } },
            slots('recommendedTimes', 'Recommended visiting slots (comma separated, e.g. 08:00-10:00, 10:00-12:00)'),
            list('workingDays', 'Working days (comma separated)'),
            lines('images', 'Image URLs (one per line \u2014 at least 5)'),
            text('description', 'Description', { type: 'textarea', value: function (d) { return d.description || ''; } })
        ]
    };

    /* ---------------------------------------------------------------- rooms */

    /* The server requires exactly one room number per room, so room numbers are
     * generated here rather than asked for one at a time. They are visible and
     * editable because real properties number their rooms their own way. */
    function roomRow(rt, idx) {
        rt = rt || {};
        var prefix = rt.roomNumbers && rt.roomNumbers.length
            ? String(rt.roomNumbers[0]).replace(/\d+$/, '') : (String.fromCharCode(65 + (idx % 26)));
        return '<div class="ph-form__row" data-room-row>' +
            '<div class="tm-field" style="margin:0">' +
            '<label class="tm-label">Room type ' + (idx + 1) + ' <span class="req">*</span></label>' +
            '<input class="tm-input" data-room="name" type="text" placeholder="e.g. Deluxe Double" maxlength="60" value="' +
            P.esc(rt.name || '') + '">' +
            '</div>' +
            '<div class="tm-field" style="margin:0">' +
            '<label class="tm-label">Rooms in this type <span class="req">*</span></label>' +
            '<input class="tm-input" data-room="totalRooms" type="number" min="1" step="1" inputmode="numeric" value="' +
            P.esc(rt.totalRooms != null ? rt.totalRooms : 1) + '">' +
            '</div>' +
            '<div class="tm-field" style="margin:0">' +
            '<label class="tm-label">Rate per night (\u20b9) <span class="req">*</span></label>' +
            '<input class="tm-input" data-room="pricePerNight" type="number" min="1" step="1" inputmode="numeric" placeholder="2400" value="' +
            P.esc(rt.pricePerNight != null ? rt.pricePerNight : '') + '">' +
            '</div>' +
            '<div class="tm-field" style="margin:0">' +
            '<label class="tm-label">Beds</label>' +
            '<input class="tm-input" data-room="numberOfBeds" type="number" min="1" step="1" inputmode="numeric" value="' +
            P.esc(rt.numberOfBeds || 1) + '">' +
            '</div>' +
            '<div class="tm-field" style="margin:0">' +
            '<label class="tm-label">Sleeps</label>' +
            '<input class="tm-input" data-room="maxOccupancy" type="number" min="1" step="1" inputmode="numeric" value="' +
            P.esc(rt.maxOccupancy || 2) + '">' +
            '</div>' +
            '<div class="tm-field" style="margin:0">' +
            '<label class="tm-label">Room number prefix</label>' +
            '<input class="tm-input" data-room="prefix" type="text" maxlength="4" value="' + P.esc(prefix) + '">' +
            '</div>' +
            '<div class="tm-field" style="margin:0">' +
            '<label class="tm-label">Air conditioned</label>' +
            '<select class="tm-select" data-room="ac">' +
            '<option value="1"' + (rt.ac ? ' selected' : '') + '>Yes</option>' +
            '<option value="0"' + (rt.ac ? '' : ' selected') + '>No</option>' +
            '</select></div>' +
            '</div>';
    }

    function collectRooms() {
        var rows = P.qa('[data-room-row]');
        var out = [];
        var used = {};
        rows.forEach(function (row, idx) {
            function val(key) {
                var el = row.querySelector('[data-room="' + key + '"]');
                return el ? el.value.trim() : '';
            }
            var name = val('name');
            if (!name) return;
            var count = Math.max(0, parseInt(val('totalRooms'), 10) || 0);
            var price = parseFloat(val('pricePerNight'));
            var prefix = (val('prefix') || String.fromCharCode(65 + (idx % 26))).slice(0, 4);
            var numbers = [];
            for (var n = 1; n <= count; n += 1) {
                var num = prefix + n;
                /* Never emit a duplicate: the server rejects the whole payload
                 * if one room number is used twice, so bump it instead. */
                while (used[num]) { num += 'x'; }
                used[num] = true;
                numbers.push(num);
            }
            out.push({
                name: name,
                totalRooms: count,
                pricePerNight: isNaN(price) ? 0 : price,
                numberOfBeds: Math.max(1, parseInt(val('numberOfBeds'), 10) || 1),
                maxOccupancy: Math.max(1, parseInt(val('maxOccupancy'), 10) || 1),
                ac: val('ac') === '1',
                bedType: 'Single Bed',
                amenities: [],
                images: [],
                roomNumbers: numbers
            });
        });
        return out;
    }

    /* ---------------------------------------------------------------- mount */

    function mount(cfg) {
        var form = P.q(cfg.form);
        var listHost = P.q(cfg.list);
        if (!form) return;

        var rows = [];
        var editingId = null;
        var originalRooms = [];

        if (cfg.roomTypes) {
            var roomHost = P.q('#phRoomTypes');
            var addRoomBtn = P.q('#phAddRoom');
            rows = [roomRow(null, 0)];
            if (roomHost) roomHost.innerHTML = rows.join('');
            if (addRoomBtn) {
                addRoomBtn.addEventListener('click', function () {
                    var n = P.qa('[data-room-row]').length;
                    roomHost.insertAdjacentHTML('beforeend', roomRow(null, n));
                });
            }
        }

        function reset() {
            editingId = null;
            form.reset();
            var roomErr = P.q('#phRoomError');
            if (roomErr) roomErr.textContent = '';
            var title = P.q(cfg.title);
            var sub = P.q(cfg.sub);
            if (title) title.textContent = cfg.addTitle;
            if (sub) sub.textContent = cfg.addSub;
            if (cfg.roomTypes) {
                originalRooms = [];
                P.q('#phRoomTypes').innerHTML = roomRow(null, 0);
            }
        }

        function collect() {
            var data = {};
            (cfg.fields || []).forEach(function (f) {
                var el = form.elements[f.name];
                if (!el) return;
                if (f.type === 'list' || f.type === 'lines' || f.type === 'slots') { data[f.name] = f.parse(el.value); }
                else if (f.type === 'number') {
                    var n = parseFloat(el.value);
                    data[f.name] = isNaN(n) ? null : n;
                } else { data[f.name] = el.value.trim(); }
            });
            if (cfg.roomTypes) {
                data.roomTypes = collectRooms();
                var total = parseInt((form.elements.totalRooms || {}).value, 10) || 0;
                var sum = data.roomTypes.reduce(function (n, r) { return n + r.totalRooms; }, 0);
                var roomErr = P.q('#phRoomError');
                if (!data.roomTypes.length) {
                    if (roomErr) roomErr.textContent = 'Add at least one room type.';
                    return null;
                }
                if (total && sum !== total) {
                    if (roomErr) roomErr.textContent = 'Room types add up to ' + sum + ' but the property has ' + total + ' rooms.';
                    return null;
                }
                data.totalRooms = total || sum;
            }
            return data;
        }

        function edit(doc) {
            editingId = doc.id;
            (cfg.fields || []).forEach(function (f) {
                var el = form.elements[f.name];
                if (!el) return;
                var v = f.value(doc);
                el.value = v == null ? '' : v;
            });
            if (cfg.roomTypes) {
                originalRooms = doc.roomTypes || [];
                P.q('#phRoomTypes').innerHTML = originalRooms.map(roomRow).join('');
            }
            var title = P.q(cfg.title);
            var sub = P.q(cfg.sub);
            if (title) title.textContent = cfg.editTitle;
            if (sub) sub.textContent = cfg.editSub;
            var panel = P.q('#add');
            if (panel) panel.scrollIntoView({ behavior: P.reducedMotion() ? 'auto' : 'smooth', block: 'start' });
        }

        form.addEventListener('submit', async function (ev) {
            ev.preventDefault();
            var data = collect();
            if (!data) return;

            P.qa('.tm-error', form).forEach(function (n) { n.textContent = ''; });
            var invalid = form.querySelector(':invalid');
            if (invalid) {
                invalid.focus();
                P.toast('Fill in the highlighted fields.', 'error');
                return;
            }

            var btn = P.q(cfg.submit);
            P.busy(btn, true);
            try {
                if (editingId) {
                    var payload = data;
                    if (cfg.roomTypes) {
                        /* bookedRooms/blockedRooms are inventory the server owns.
                         * Send them back unchanged so a rate edit cannot reset
                         * live occupancy. */
                        (originalRooms || []).forEach(function (r, i) {
                            if (payload.roomTypes[i]) {
                                payload.roomTypes[i].id = r.id;
                                payload.roomTypes[i].bookedRooms = r.bookedRooms || 0;
                                payload.roomTypes[i].blockedRooms = r.blockedRooms || 0;
                            }
                        });
                    }
                    await cfg.update(editingId, payload);
                    P.toast('Saved. Your change goes back to the TripMind team for review.', 'success');
                } else {
                    await cfg.create(data);
                    P.toast('Submitted for review. We will let you know once it is live.', 'success');
                }
                reset();
                await refresh();
            } catch (e) {
                P.toast(e.message, 'error');
            } finally {
                P.busy(btn, false);
            }
        });

        function render(items) {
            if (!listHost) return;
            if (!items.length) {
                listHost.innerHTML = P.empty('No ' + cfg.entity + 's yet',
                    'Add your first ' + cfg.entity + ' and it appears here as soon as the TripMind team approves it.',
                    '<a class="tm-btn tm-btn--primary" href="#add">Add a ' + P.esc(cfg.entity) + '</a>');
                return;
            }
            var approved = items.filter(function (d) { return d.status === 'APPROVED'; }).length;
            var pending = items.filter(function (d) { return d.status === 'PENDING'; }).length;

            listHost.innerHTML = '<ul class="ph-rows">' + items.map(function (doc) {
                var r = cfg.row(doc);
                return '<li class="ph-row"><div class="ph-row__main">' +
                    '<div class="ph-row__title">' + P.esc(r.title) + ' ' + P.pill(doc.status) + '</div>' +
                    '<p class="ph-row__meta">' + P.esc(r.meta) + '</p>' +
                    (r.detail ? '<p class="ph-row__meta tm-2xs tm-muted">' + P.esc(r.detail) + '</p>' : '') +
                    '</div><div class="ph-row__side">' +
                    '<span class="tm-2xs tm-muted">' + P.esc(r.side) + '</span>' +
                    '<button class="tm-btn tm-btn--ghost tm-btn--sm" type="button" data-edit="' + P.esc(doc.id) + '">Edit</button>' +
                    '</div></li>';
            }).join('') + '</ul>' +
                '<p class="tm-2xs tm-muted" style="padding:1rem 1.25rem 0;margin:0">' +
                approved + ' live for travellers \u00b7 ' + pending + ' awaiting review</p>';

            P.qa('[data-edit]', listHost).forEach(function (btn) {
                btn.addEventListener('click', function () {
                    var id = btn.getAttribute('data-edit');
                    var doc = items.filter(function (d) { return String(d.id) === id; })[0];
                    if (doc) edit(doc);
                });
            });
        }

        async function refresh() {
            if (listHost) listHost.innerHTML = P.loading();
            try {
                var items = await cfg.load();
                render(items || []);
                if (cfg.stats) {
                    var host = P.q(cfg.stats);
                    if (host) {
                        var approved = (items || []).filter(function (d) { return d.status === 'APPROVED'; }).length;
                        var pending = (items || []).filter(function (d) { return d.status === 'PENDING'; }).length;
                        host.innerHTML = [
                            { n: (items || []).length, k: P.esc(cfg.entity + 's listed') },
                            { n: approved, k: 'Live for travellers' },
                            { n: pending, k: 'Awaiting review' }
                        ].map(function (t) {
                            return '<div class="ph-stat"><b>' + P.esc(String(t.n)) + '</b><span>' + t.k + '</span></div>';
                        }).join('');
                    }
                }
                if (cfg.pendingNote) {
                    var note = P.q(cfg.pendingNote);
                    if (note) {
                        note.hidden = !(items || []).some(function (d) { return d.status === 'PENDING'; });
                    }
                }
            } catch (e) {
                P.fail(listHost, e);
            }
        }

        refresh();
    }

    return {
        mount: mount,
        hotelFields: FIELDS.hotelFields,
        restaurantFields: FIELDS.restaurantFields,
        spotFields: FIELDS.spotFields
    };
})();
