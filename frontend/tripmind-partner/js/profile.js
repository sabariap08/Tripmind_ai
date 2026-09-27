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

    function renderApplication(user) {
        var reg = P.reg(user);
        var rows = [
            row('Partner type', P.typeLabel(user.registration && user.registration.partnerType)),
            row('Business', reg.companyName),
            row('Operating area', reg.operatingArea || reg.companyAddress),
            row('GST / registration', reg.gst),
            row('Applied on', user.createdAt ? P.fmtDate(user.createdAt) : '—')
        ].join('');
        el('phApplication').innerHTML = '<ul class="ph-rows">' + rows + '</ul>' +
            '<p class="tm-2xs tm-muted" style="padding:0 1.25rem 1.25rem;margin:0">' +
            'Something wrong here? Contact the TripMind team and we will correct it.</p>';
    }

    P.boot({
        view: function (state) {
            var user = state.user;
            renderAccount(user);
            renderApplication(user);

            var reg = P.reg(user);
            if (!el('pfService').value) el('pfService').value = reg.companyName || user.name || '';

            /* The profile endpoint requires an approved provider, so a partner
             * whose account is still pending simply sees the read-only view. */
            api.transportService().then(function (res) {
                var prof = (res && res.profile) || {};
                if (prof.serviceName) el('pfService').value = prof.serviceName;
                el('pfContact').value = prof.contact || reg.contactNumber || '';
                el('pfDescription').value = prof.description || '';
            }).catch(function (e) {
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
    });
})();
