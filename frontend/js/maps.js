/* TripMind AI — Google Maps integration (lazy).
 *
 * boots only when the backend reports a GOOGLE_MAPS_API_KEY. If no key is set,
 * nothing loads and the app keeps using plain manual lat/lng/address inputs.
 *
 * Usage:
 *   await window.TM_MAPS.init();
 *   if (window.TM_MAPS.ready) window.TM_MAPS.initLocationPicker({...});
 */
(function () {
    const state = { ready: false, key: null, maps: null };

    function inject(key) {
        return new Promise((resolve, reject) => {
            if (window.google && window.google.maps) { resolve(); return; }
            window.__tmMapsReady = () => resolve();
            const s = document.createElement('script');
            s.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(key)}&libraries=places&loading=async&callback=__tmMapsReady`;
            s.onerror = () => {
                state.ready = false;
                reject(new Error('Failed to load Google Maps (check your API key and billing).'));
            };
            document.head.appendChild(s);
        });
    }

    async function init() {
        if (state.ready) return true;
        let cfg = null;
        try {
            cfg = await apiRequest('/api/auth/roles');
        } catch (e) {
            return false;
        }
        if (!cfg.mapsEnabled || !cfg.mapsKey) { state.ready = false; return false; }
        try {
            await inject(cfg.mapsKey);
            state.ready = true;
            state.key = cfg.mapsKey;
        } catch (e) {
            state.ready = false;
        }
        return state.ready;
    }

    /* Address autocomplete + draggable marker bound to lat/lng (+ hidden map id).
     *
     * opts:
     *   addressId, latId, lngId  — input/hidden ids (existing fields are filled)
     *   mapId                    — optional div id to host the map canvas
     *   required                 — when true the picker is mandatory (validator)
     *   onPick({address, latitude, longitude}) — callback in the reusable form
     *
     * Returns a controller: { fill(lat, lng, name), getValue() }.
     */
    function initLocationPicker(opts) {
        if (!state.ready || !window.google || !google.maps) return null;
        const { addressId, latId, lngId, mapId, required, onPick } = opts;
        const addrEl = document.getElementById(addressId);
        const latEl = document.getElementById(latId);
        const lngEl = document.getElementById(lngId);
        if (!addrEl || !latEl || !lngEl) return null;

        const start = new google.maps.LatLng(
            parseFloat(latEl.value) || 20.5937, parseFloat(lngEl.value) || 78.9629);

        let mapEl = null;
        if (mapId && document.getElementById(mapId)) {
            mapEl = new google.maps.Map(document.getElementById(mapId), {
                center: { lat: start.lat(), lng: start.lng() },
                zoom: 10,
            });
        }

        const marker = new google.maps.Marker({
            position: start, map: mapEl || null, draggable: true,
        });
        if (mapEl) marker.setMap(mapEl);

        const autocomplete = new google.maps.places.Autocomplete(addrEl, { types: ['establishment', 'geocode'] });
        autocomplete.bindTo('bounds', mapEl || new google.maps.Map(document.createElement('div')));

        const emit = () => {
            if (typeof onPick !== 'function') return;
            onPick({ address: addrEl.value, latitude: latEl.value, longitude: lngEl.value });
        };

        const fill = (lat, lng, name) => {
            latEl.value = lat.toFixed(6);
            lngEl.value = lng.toFixed(6);
            if (name) addrEl.value = name;
            if (mapEl) mapEl.setCenter({ lat, lng });
            marker.setPosition({ lat, lng });
            emit();
        };

        autocomplete.addListener('place_changed', () => {
            const place = autocomplete.getPlace();
            if (place && place.geometry) {
                fill(place.geometry.location.lat(), place.geometry.location.lng(), addrEl.value || place.name || '');
            }
        });
        marker.addListener('dragend', () => {
            const p = marker.getPosition();
            fill(p.lat(), p.lng());
        });
        if (mapEl) {
            mapEl.addListener('click', (e) => fill(e.latLng.lat(), e.latLng.lng()));
        }

        const getValue = () => {
            if (required && !(latEl.value && lngEl.value)) return null;
            return { address: addrEl.value, latitude: latEl.value, longitude: lngEl.value };
        };
        return { fill, getValue };
    }

    window.TM_MAPS = {
        init, initLocationPicker,
        hasLocation: () => !!state.ready && !!window.google,
        get ready() { return state.ready; },
    };
})();