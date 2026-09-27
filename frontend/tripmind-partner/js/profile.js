/* TripMind Partner Hub — profile.
 *
 * Two existing endpoints, no new API:
 *   GET/POST /api/transport/services  -> the service profile (name, contact,
 *                                        description) that fleet documents read
 *   PATCH  /api/users/me             -> the partner's own name and phone
 * The application details are shown read-only: they are what the TripMind team
 * reviewed, so they are not editable from the provider side.
 */
(function () {
    'use strict';

    var P = TM_PARTNER;
    var form = document.getElementById('phProfileForm');
    var save = document.getElementById('pfSave');
    var status = document.getElementById('pfStatus');

    function el(id) { return document.getElementById(id); }

    function row(key, value) {
        return '<li class="ph-row"><div class="ph-row__main">' +
            '<p class="ph-row__meta" style="text-transform:uppercase;letter-spacing:.1em;font-weight:700;font-size:var(--tm-f-2xs)">' +
            P.esc(key) + '</p>' +
            '<div class="ph-row__title" style="font-weight:600">' + P.esc(value || '—') + '</div></div></li>';
    }

    function renderAccount(user) {
        var approval = user.approvalStatus || (user.approved ? 'APPROVED' : 'PENDING');
        var host = el('phAccount');
        host.innerHTML = '<ul class="ph-rows">' +
            row('Name', user.name) +
            row('Email', user.email) +
            row('Mobile', user.mobile || user.phone) +
            '<li class="ph-row"><div class="ph-row__main">' +
            '<p class="ph-row__meta" style="text-transform:uppercase;letter-spacing:.1em;font-weight:700;font-size:var(--tm-f-2xs)">Status</p>' +
            '<div class="ph-row__title">' + P.pill(approval) + '</div></div></li>' +
            '</ul>';

        if (approval !== 'APPROVED') {
            host.insertAdjacentHTML('beforeend',
                '<div class="ph-note ph-note--wait" style="margin:1.25rem">' +
                '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm1 15h-2v-2h2v2Zm0-4h-2V7h2v6Z"/></svg>' +
                '<div>' + (user.approvalReason
                    ? P.esc(user.approvalReason)
                    : 'Your account is still being reviewed. You will be able to list services once it is approved.') +
                '</div></div>');
        }
    }

    /* The reviewed application is different per role, so each role lists the
     * fields the Main Admin actually looked at. These stay read-only. */
    function applicationRows(user) {
        var r = P.reg(user);
        var role = user.role;
        var rows = [row('Role', P.roleMeta(role).label)];

        if (role === 'GUIDE') {
            rows.push(row('Guide name', r.guideName));
            rows.push(row('Base city', r.baseCity));
            rows.push(row('Experience', r.experienceYears ? r.experienceYears + ' years' : ''));
            rows.push(row('Languages', (r.languages || []).join(', ')));
            rows.push(row('Phone', r.phone || r.contactNumber));
        } else if (role === 'HOTEL_ADMIN') {
            rows.push(row('Property name', r.propertyName));
            rows.push(row('Business', r.companyName));
            rows.push(row('City', r.baseCity || r.city));
            rows.push(row('Property type', r.propertyType));
        } else if (role === 'RESTAURANT_ADMIN') {
            rows.push(row('Restaurant name', r.restaurantName));
            rows.push(row('Business', r.companyName));
            rows.push(row('City', r.baseCity || r.city));
            rows.push(row('Restaurant type', r.restaurantType));
        } else if (role === 'TOURIST_SPOT_ADMIN') {
            rows.push(row('Spot name', r.spotName));
            rows.push(row('Business', r.companyName));
            rows.push(row('District', r.baseDistrict));
            rows.push(row('Category', r.spotCategory));
        } else {
            rows.push(row('Partner type', P.partnerTypeOf(user) === 'DRIVER' ? 'Driver / vehicle owner' : 'Bus or travel operator'));
            rows.push(row('Business', r.companyName));
            rows.push(row('Operating area', r.operatingArea || r.companyAddress));
        }

        /* GST and the remaining registered details are shared, so they are
         * appended for every role when the partner supplied them. */
        if (r.gst) rows.push(row('GST / registration', r.gst));
        if (r.registrationNumber) rows.push(row('Registration number', r.registrationNumber));
        if (r.fssaiLicence) rows.push(row('FSSAI licence', r.fssaiLicence));
        if (r.guideIdProof) rows.push(row('Guide ID reference', r.guideIdProof));
        rows.push(row('Applied on', user.createdAt ? P.fmtDate(user.createdAt) : '—'));
        return rows.join('');
    }

    function renderApplication(user) {
        el('phApplication').innerHTML = '<ul class="ph-rows">' + applicationRows(user) + '</ul>' +
            '<p class="tm-2xs tm-muted" style="padding:0 1.25rem 1.25rem;margin:0">' +
            'Something wrong here? Contact the TripMind team and we will correct it.</p>';
    }

    /* Only a transport partner has a fleet-level service profile
     * (/api/transport/services). Every other role edits its listings on its own
     * catalogue page, so this form is swapped for a pointer to that page. */
    function renderServicePanel(state) {
        var panel = el('phServicePanel');
        if (!panel) return;

        if (state.role !== 'TRANSPORT_ADMIN') {
            var href = { HOTEL_ADMIN: 'hotels', RESTAURANT_ADMIN: 'restaurants',
                TOURIST_SPOT_ADMIN: 'spots', GUIDE: 'guide-requests' }[state.role];
            panel.innerHTML = '<h2>' + P.esc(P.roleMeta(state.role).entityPlural || 'Your listings') + '</h2>' +
                '<p>Your ' + P.esc(P.roleMeta(state.role).entityPlural) + ', contact details and rates are edited on ' +
                'your own page.</p>' +
                '<a class="tm-btn tm-btn--primary" href="/tripmind-partner/' + href + '">Open my ' +
                P.esc(P.roleMeta(state.role).entityPlural) + '</a>';
            return;
        }

        panel.innerHTML = panel.innerHTML; // transport form markup stays as authored
        var reg = P.reg(state.user);
        if (!el('pfService').value) el('pfService').value = reg.companyName || state.user.name || '';

        /* The profile endpoint requires an approved provider, so a partner whose
         * account is still pending simply sees the read-only view. */
        api.transportService().then(function (res) {
            var prof = (res && res.profile) || {};
            if (prof.serviceName) el('pfService').value = prof.serviceName;
            el('pfContact').value = prof.contact || reg.contactNumber || '';
            el('pfDescription').value = prof.description || '';
        }).catch(function () {
            status.textContent = 'Your service profile becomes editable once your account is approved.';
            status.className = 'ph-actions__note';
            save.disabled = true;
        });

        form.addEventListener('submit', async function (e) {
            e.preventDefault();
            var serviceName = el('pfService').value.trim();
            if (!serviceName) {
                TM.fieldError(el('pfService'), 'This field is required.');
                el('pfService').focus();
                return;
            }
            TM.fieldError(el('pfService'), '');
            TM.button(save, true);
            status.textContent = 'Saving…';
            try {
                await api.saveTransportService({
                    serviceName: serviceName,
                    contact: el('pfContact').value.trim(),
                    description: el('pfDescription').value.trim()
                });
                status.textContent = 'Saved.';
                P.toast('Service profile saved.', 'ok');
                P.renderUser();
            } catch (err) {
                status.textContent = err.message;
                P.toast(err.message, 'error');
            } finally {
                TM.button(save, false);
            }
        });
    }

    P.boot({
        view: function (state) {
            renderAccount(state.user);
            renderApplication(state.user);
            renderServicePanel(state);
        }
    });
})();
