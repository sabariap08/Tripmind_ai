/* TripMind AI \u2014 Google Maps integration (lazy).
 *
 * boots only when the backend reports a GOOGLE_MAPS_API_KEY. If no key is set,
 * nothing loads and the app keeps using plain manual lat/lng/address inputs.
 * No coordinate or address is ever invented: if the Maps API is unavailable the
 * partner form shows an explicit "location not configured" state instead of
 * guessing a position.
 *
 * Usage:
 *   await window.TM_MAPS.init();
 *   if (window.TM_MAPS.ready) window.TM_MAPS.initLocationPicker({...});
 *
 *   // Richer partner picker (place id + address components + district)
 *   const picker = window.TM_MAPS.initPlacePicker({
 *       inputId, mapId, districtSelectId, onPick(payload)
 *   });
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

    /* ------------------------------------------------------------------ *
     * Address component helpers
     * ------------------------------------------------------------------ */
    function componentMap(place) {
        const map = {};
        const components = (place && place.address_components) || [];
        components.forEach((c) => {
            (c.types || []).forEach((t) => {
                if (!map[t]) map[t] = c.long_name || c.short_name || '';
            });
        });
        return map;
    }

    /* Pick the most specific locality name Google gives us. */
    function resolveLocality(components) {
        return components.locality
            || components.postal_town
            || components.sublocality_level_1
            || components.sublocality
            || components.administrative_area_level_2
            || components.administrative_area_level_3
            || '';
    }

    /* Google returns "Tamil Nadu" for administrative_area_level_1. Map it onto
     * the server's district list by best-effort string match, handling the
     * official spellings ("Thoothukudi" vs "Thoothukudi", "The Nilgiris" etc).
     * Returns '' when we genuinely cannot tell - the user then picks the
     * district manually. We never guess. */
    function normaliseDistrict(text) {
        return String(text || '')
            .toLowerCase()
            .replace(/^the\s+/, '')
            .replace(/\s+district$/, '')
            .replace(/[^a-z]/g, '');
    }

    function matchDistrict(place, districts) {
        const list = districts || [];
        if (!list.length) return '';
        const components = componentMap(place);
        const candidates = [
            components.administrative_area_level_2,
            components.administrative_area_level_1,
            components.locality,
            components.postal_town,
            resolveLocality(components),
        ].filter(Boolean);
        for (const raw of candidates) {
            const needle = normaliseDistrict(raw);
            if (!needle) continue;
            // Exact match on any candidate.
            for (const d of list) {
                if (normaliseDistrict(d) === needle) return d;
            }
            // Containment either way (e.g. "Nilgiris" inside "The Nilgiris").
            for (const d of list) {
                const dn = normaliseDistrict(d);
                if (dn && (dn.includes(needle) || needle.includes(dn))) return d;
            }
        }
        return '';
    }

    function describePlace(place, districts) {
        const components = componentMap(place);
        const location = place && place.geometry && place.geometry.location;
        return {
            placeId: (place && place.id) || '',
            address: (place && (place.formatted_address || place.name)) || '',
            name: (place && place.name) || '',
            locality: resolveLocality(components),
            city: components.locality || components.postal_town || '',
            state: components.administrative_area_level_1 || '',
            district: matchDistrict(place, districts),
            postalCode: components.postal_code || '',
            country: components.country || '',
            latitude: location ? location.lat() : null,
            longitude: location ? location.lng() : null,
            // Raw components are exposed so a future server-side re-verification
            // step can use them; they are not sent to any AI provider.
            addressComponents: components,
        };
    }

    /* ------------------------------------------------------------------ *
     * Original lightweight picker (kept for backward compatibility)
     * ------------------------------------------------------------------ */
    /* Address autocomplete + draggable marker bound to lat/lng (+ hidden map id).
     *
     * opts:
     *   addressId, latId, lngId  \u2014 input/hidden ids (existing fields are filled)
     *   mapId                    \u2014 optional div id to host the map canvas
     *   required                 \u2014 when true the picker is mandatory (validator)
     *   onPick({address, latitude, longitude}) \u2014 callback in the reusable form
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

    /* ------------------------------------------------------------------ *
     * Rich place picker used by the Partner Hub registration form
     * ------------------------------------------------------------------ */
    /* opts:
     *   inputId          \u2014 the visible search input
     *   mapId            \u2014 optional map canvas
     *   districtSelectId \u2014 optional <select> to auto-fill from the TN list
     *   districts        \u2014 array of official district names to match against
     *   onPick(describePlaceResult) \u2014 receives placeId/lat/lng/district/...
     *   onNotAvailable() \u2014 called when Maps is not configured
     *
     * Returns a controller: { getValue(), setValue(payload), clear() } or null.
     */
    function initPlacePicker(opts) {
        if (!state.ready || !window.google || !google.maps) {
            if (typeof opts.onNotAvailable === 'function') opts.onNotAvailable();
            return null;
        }
        const { inputId, mapId, districtSelectId, districts, onPick, onNotAvailable } = opts;
        const inputEl = document.getElementById(inputId);
        if (!inputEl) {
            if (typeof onNotAvailable === 'function') onNotAvailable();
            return null;
        }

        const defaultCenter = { lat: 11.1271, lng: 78.6561 };   // Tamil Nadu
        let mapEl = null;
        if (mapId && document.getElementById(mapId)) {
            mapEl = new google.maps.Map(document.getElementById(mapId), {
                center: defaultCenter, zoom: 7, mapTypeControl: false,
            });
        }

        const autocomplete = new google.maps.places.Autocomplete(inputEl, {
            types: ['establishment', 'geocode', 'address'],
            componentRestrictions: { country: 'in' },
            fields: ['place_id', 'name', 'formatted_address', 'geometry',
                'address_components'],
        });
        if (mapEl) autocomplete.bindTo('bounds', mapEl);

        let lastPlace = null;

        const applyPlace = (place) => {
            if (!place || !place.geometry || !place.geometry.location) {
                if (typeof onNotAvailable === 'function') onNotAvailable();
                return;
            }
            const info = describePlace(place, districts);
            lastPlace = info;
            inputEl.value = info.address || inputEl.value;
            if (mapEl) {
                mapEl.setCenter({ lat: info.latitude, lng: info.longitude });
                mapEl.setZoom(15);
            }
            // Auto-select the district when we can match it confidently.
            if (districtSelectId && info.district) {
                const sel = document.getElementById(districtSelectId);
                if (sel && Array.from(sel.options).some((o) => o.value === info.district)) {
                    sel.value = info.district;
                    sel.dispatchEvent(new Event('change', { bubbles: true }));
                }
            }
            if (typeof onPick === 'function') onPick(info);
        };

        autocomplete.addListener('place_changed', () => {
            applyPlace(autocomplete.getPlace());
        });

        if (mapEl) {
            mapEl.addListener('click', (e) => {
                // A map click is only a pin, not a verified place. We do NOT
                // fabricate a place id here; the address must come from search.
                if (typeof onPick === 'function') {
                    onPick({
                        placeId: '',
                        address: inputEl.value,
                        latitude: e.latLng.lat(),
                        longitude: e.latLng.lng(),
                        district: '',
                        pinOnly: true,
                    });
                }
            });
        }

        const getValue = () => {
            if (!lastPlace) return null;
            return {
                placeId: lastPlace.placeId || '',
                address: lastPlace.address || inputEl.value || '',
                city: lastPlace.city || lastPlace.locality || '',
                district: lastPlace.district || '',
                lat: lastPlace.latitude,
                lng: lastPlace.longitude,
                postalCode: lastPlace.postalCode || '',
            };
        };

        const setValue = (payload) => {
            if (!payload) return;
            if (payload.address) inputEl.value = payload.address;
            if (mapEl && payload.lat && payload.lng) {
                mapEl.setCenter({ lat: Number(payload.lat), lng: Number(payload.lng) });
                mapEl.setZoom(15);
            }
            lastPlace = {
                placeId: payload.placeId || '',
                address: payload.address || '',
                city: payload.city || '',
                district: payload.district || '',
                latitude: payload.lat != null ? Number(payload.lat) : null,
                longitude: payload.lng != null ? Number(payload.lng) : null,
            };
        };

        const clear = () => { inputEl.value = ''; lastPlace = null; };

        return { getValue, setValue, clear };
    }

    window.TM_MAPS = {
        init, initLocationPicker, initPlacePicker,
        describePlace, matchDistrict, componentMap, resolveLocality,
        hasLocation: () => !!state.ready && !!window.google,
        get ready() { return state.ready; },
    };
})();
