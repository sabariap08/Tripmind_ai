const API_BASE = '';

/* Mojibake guard.
 * TripMind renders en-dashes (U+2013), middle dots (U+00B7) and rupee signs
 * (U+20B9). If any hop between us and the API decodes those UTF-8 bytes as
 * Windows-1252 they arrive as "a-circumflex, euro, en-dash" instead of the real
 * character. `response.text()` already decodes as UTF-8, so this only fires in
 * the rare case that something upstream already mangled the payload.
 *
 * It is deliberately narrow: it only touches a string when every character is
 * a single byte AND re-decoding those bytes as UTF-8 yields a different string.
 * Correct English and Tamil Nadu place names are never altered by it. */
const MOJIBAKE = /(?:\u00e2[\u0080-\u00bf\u20ac]|\u00c2[\u0080-\u00bf]|\u00e3\u0083)/;
function repairEncoding(text) {
    if (!text || !MOJIBAKE.test(text)) return text;
    try {
        const bytes = new Uint8Array(text.length);
        for (let i = 0; i < text.length; i++) {
            const code = text.charCodeAt(i);
            if (code > 0xff) return text;      // real multi-byte text: leave it alone
            bytes[i] = code;
        }
        const fixed = new TextDecoder('utf-8', { fatal: false }).decode(bytes);
        return fixed !== text ? fixed : text;
    } catch (e) {
        return text;
    }
}

async function apiRequest(url, options = {}) {
    const config = {
        headers: { 'Content-Type': 'application/json; charset=utf-8', 'Accept': 'application/json' },
        ...options,
    };
    if (config.body && typeof config.body === 'object') {
        config.body = JSON.stringify(config.body);
    }
    let response;
    try {
        response = await fetch(`${API_BASE}${url}`, config);
    } catch (e) {
        throw new Error('Network error \u2014 please try again.');
    }
    const text = repairEncoding(await response.text());
    let data = null;
    try {
        data = text ? JSON.parse(text) : null;
    } catch (e) {
        data = { error: text.trim() ? `Server returned an invalid response (${response.status}).` : 'Server returned an empty response.' };
    }
    if (!response.ok) {
        let msg = data.error || ('Request failed (' + response.status + ').');
        if (data.hint) msg += ' ' + data.hint;
        if (Array.isArray(data.unavailable) && data.unavailable.length) {
            msg += ' ' + data.unavailable
                .map(u => [u.title, u.reason].filter(Boolean).join(' \u2014 '))
                .join('; ');
        }
        const err = new Error(msg);
        err.status = response.status;
        err.data = data;
        // Some endpoints return a well-formed body alongside a non-2xx status
        // because the caller genuinely needs that body: /generate answers 503
        // with the planner's own explanation when the AI backend is down. The
        // message is the server's, not a generic "Request failed (503)", and
        // `retryable` says a plain retry is worth offering.
        if (!data.error && data.message) {
            err.message = data.message;
        }
        err.retryable = response.status === 503 || response.status === 429
            || data.retryable === true;
        throw err;
    }
    return data;
}

const api = {
    getTrips: () => apiRequest('/api/trips'),
    adminTrips: () => apiRequest('/api/admin/trips'),
    createTrip: (data) => apiRequest('/api/trips', { method: 'POST', body: data }),
    getTrip: (id) => apiRequest(`/api/trips/${id}`),
    /* Budget utilisation, per-category breakdown and headroom, computed
       server-side. Separate from getTrip so the trip page can refresh the money
       after a booking or an itinerary edit without re-fetching and
       re-rendering the whole itinerary. */
    getBudget: (id) => apiRequest(`/api/trips/${id}/budget`),
    generatePlans: (id, clarifications = {}) => apiRequest(`/api/trips/${id}/generate`, { method: 'POST', body: { clarifications } }),
    bookTrip: (id) => apiRequest(`/api/trips/${id}/book`, { method: 'POST' }),
    confirmBookTrip: (id, payFromWallet) => apiRequest(`/api/trips/${id}/confirm-book`, { method: 'POST', body: { payFromWallet }}),
    getEvents: (id) => apiRequest(`/api/trips/${id}/events`),
    getItinerary: (id) => apiRequest(`/api/trips/${id}/itinerary`),
    editItineraryItems: (id, action, payload = {}) => apiRequest(`/api/trips/${id}/itinerary/items`, { method: 'POST', body: { action, ...payload } }),
    simulateDelay: (id, minutes) => apiRequest(`/api/trips/${id}/simulate-delay`, { method: 'POST', body: { delayMinutes: minutes } }),
    /* Two-phase. The first call (confirm omitted/false) returns a proposal and
       writes nothing; the second applies it. `reason` is passed through so the
       server can label the change. */
    replan: (id, minutes, options = {}) => apiRequest(`/api/trips/${id}/replan`, { method: 'POST', body: { delayMinutes: minutes, confirm: !!options.confirm, reason: options.reason } }),
    chat: (message, tripId, pendingAction) => apiRequest('/api/ai/chat', { method: 'POST', body: { message, tripId, pendingAction } }),
    chatConfirm: (message, tripId, pendingAction) => apiRequest('/api/ai/chat', { method: 'POST', body: { message, tripId, pendingAction, confirm: true } }),
    tripReviews: (id) => apiRequest(`/api/trips/${id}/reviews`),
    addTripReview: (id, rating, comment) => apiRequest(`/api/trips/${id}/review`, { method: 'POST', body: { rating, comment } }),
    feedbackAnalysis: () => apiRequest('/api/ai/feedback-analysis', { method: 'POST' }),
    assistantChat: (message, tripId) => apiRequest('/api/assistant/chat', { method: 'POST', body: { message, tripId } }),
    assistantAction: (type, params) => apiRequest('/api/assistant/action', { method: 'POST', body: { type, params } }),
    modifyTrip: (id, updates) => apiRequest(`/api/trips/${id}/modify`, { method: 'POST', body: { updates } }),

    // Smart Packing / Digital Twin / Voice
    voiceNormalize: (text) => apiRequest('/api/ai/voice-normalize', { method: 'POST', body: { text } }),
    tripPacking: (id, force) => apiRequest(`/api/trips/${id}/packing`, { method: 'POST', body: { force: !!force } }),
    tripTwin: (id) => apiRequest(`/api/trips/${id}/twin`),

    // Auth
    me: () => apiRequest('/api/auth/me'),
    login: (data) => apiRequest('/api/auth/login', { method: 'POST', body: data }),
    register: (data) => apiRequest('/api/auth/register', { method: 'POST', body: data }),
    logout: () => apiRequest('/api/auth/logout', { method: 'POST' }),
    updateProfile: (data) => apiRequest('/api/users/me', { method: 'PATCH', body: data }),
    checkAvailability: (field, value, extra = {}) => {
        const qs = new URLSearchParams({ field, value: value || '', ...extra });
        return apiRequest(`/api/auth/check-availability?${qs.toString()}`);
    },
    registrationFields: (role) => apiRequest(`/api/auth/registration-fields?role=${encodeURIComponent(role)}`),

    // Transport catalogue
    getTransports: (params = {}) => {
        const qs = new URLSearchParams(params).toString();
        return apiRequest(`/api/transport/list${qs ? `?${qs}` : ''}`);
    },
    registerTransport: (data) => apiRequest('/api/transport/register', { method: 'POST', body: data }),
    getTransport: (id) => apiRequest(`/api/transport/${id}`),
    updateTransport: (id, data) => apiRequest(`/api/transport/${id}`, { method: 'PUT', body: data }),
    transportStatus: (id, status, reason) => apiRequest(`/api/transport/${id}/status`, { method: 'POST', body: { status, reason } }),
    transportSearch: (params = {}) => {
        const qs = new URLSearchParams(params).toString();
        return apiRequest(`/api/transport/search${qs ? `?${qs}` : ''}`);
    },
    transportService: () => apiRequest('/api/transport/services'),
    saveTransportService: (data) => apiRequest('/api/transport/services', { method: 'POST', body: data }),
    transportTypes: () => apiRequest('/api/transport/types'),

    // Tourist spots
    getSpots: (params = {}) => {
        const qs = new URLSearchParams(params).toString();
        return apiRequest(`/api/spots${qs ? `?${qs}` : ''}`);
    },
    getMySpots: () => apiRequest('/api/spots/mine'),
    createSpot: (data) => apiRequest('/api/spots', { method: 'POST', body: data }),
    getGuideLocations: () => apiRequest('/api/guide-locations'),
    addGuideLocation: (data) => apiRequest('/api/guide-locations', { method: 'POST', body: data }),

    // Tours
    getTours: (params = {}) => {
        const qs = new URLSearchParams(params).toString();
        return apiRequest(`/api/tours${qs ? `?${qs}` : ''}`);
    },
    createTour: (data) => apiRequest('/api/tours', { method: 'POST', body: data }),

    // Hotels
    searchHotels: (params = {}) => {
        const qs = new URLSearchParams(params).toString();
        return apiRequest(`/api/hotels/search${qs ? `?${qs}` : ''}`);
    },
    createHotel: (data) => apiRequest('/api/hotels', { method: 'POST', body: data }),
    getMyHotels: () => apiRequest('/api/hotels/mine'),
    getHotel: (id) => apiRequest(`/api/hotels/${id}`),
    getOccupancy: (id) => apiRequest(`/api/hotels/${id}/occupancy`),
    blockRooms: (hid, rtid, blocked) => apiRequest(`/api/hotels/${hid}/room-types/${rtid}/block`, { method: 'POST', body: { blocked } }),
    addHotelRoom: (hid, room) => apiRequest(`/api/hotels/${hid}/rooms`, { method: 'POST', body: room }),
    getHotelBookings: () => apiRequest('/api/hotels/bookings'),

    // Restaurants
    getRestaurants: (params = {}) => {
        const qs = new URLSearchParams(params).toString();
        return apiRequest(`/api/restaurants${qs ? `?${qs}` : ''}`);
    },
    createRestaurant: (data) => apiRequest('/api/restaurants', { method: 'POST', body: data }),
    getMyRestaurants: () => apiRequest('/api/restaurants/mine'),
    getRestaurant: (id) => apiRequest(`/api/restaurants/${id}`),
    updateRestaurant: (id, data) => apiRequest(`/api/restaurants/${id}`, { method: 'PUT', body: data }),
    getFoodItems: (rid) => apiRequest(`/api/restaurants/${rid}/food-items`),
    createFoodItem: (rid, data) => apiRequest(`/api/restaurants/${rid}/food-items`, { method: 'POST', body: data }),
    updateFoodItem: (rid, fid, data) => apiRequest(`/api/restaurants/${rid}/food-items/${fid}`, { method: 'PUT', body: data }),
    deleteFoodItem: (rid, fid) => apiRequest(`/api/restaurants/${rid}/food-items/${fid}`, { method: 'DELETE' }),

    // Railway lounges (RAILWAY_ADMIN)
    getLounges: () => apiRequest('/api/lounge'),
    getLounge: (id) => apiRequest(`/api/lounge/${id}`),
    createLounge: (data) => apiRequest('/api/lounge', { method: 'POST', body: data }),
    updateLounge: (id, data) => apiRequest(`/api/lounge/${id}`, { method: 'PUT', body: data }),
    deleteLounge: (id) => apiRequest(`/api/lounge/${id}`, { method: 'DELETE' }),
    setLoungeStatus: (id, status) => apiRequest(`/api/lounge/${id}/status`, { method: 'POST', body: { status } }),

    // Guides
    getGuideProfile: () => apiRequest('/api/guide/profile'),
    guidePricing: (data) => apiRequest('/api/guide/pricing', { method: 'POST', body: data }),
    guideAvailability: (data) => apiRequest('/api/guide/availability', { method: 'POST', body: data }),
    browseGuides: (params = {}) => {
        const qs = new URLSearchParams(params).toString();
        return apiRequest(`/api/guides${qs ? `?${qs}` : ''}`);
    },
    guideRequests: () => apiRequest('/api/guide/requests'),
    guideRespond: (id, action, message) => apiRequest(`/api/guide/requests/${id}`, { method: 'POST', body: { action, message } }),
    guideAssignments: () => apiRequest('/api/guide/assignments'),

    // Passenger profiles (owner-only, masked proof, consent-gated health)
    passengers: () => apiRequest('/api/passengers'),
    passenger: (id) => apiRequest(`/api/passengers/${encodeURIComponent(id)}`),
    createPassenger: (data) => apiRequest('/api/passengers', { method: 'POST', body: data }),
    updatePassenger: (id, data) => apiRequest(`/api/passengers/${encodeURIComponent(id)}`, { method: 'PUT', body: data }),
    deletePassenger: (id) => apiRequest(`/api/passengers/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    setDefaultPassenger: (id) => apiRequest(`/api/passengers/${encodeURIComponent(id)}/default`, { method: 'POST' }),
    passengerPartyPreview: (ids, travellers = 1) => apiRequest('/api/passengers/party', { method: 'POST', body: { passengerIds: ids || [], travellers } }),

    // Pre-trip checklist (AI assisted, persisted per booking)
    checklists: () => apiRequest('/api/checklists'),
    checklist: (bookingId) => apiRequest(`/api/checklists/${encodeURIComponent(bookingId)}`),
    generateChecklist: (bookingId, data = {}) => apiRequest(`/api/checklists/${encodeURIComponent(bookingId)}`, { method: 'POST', body: data }),
    regenerateChecklist: (bookingId) => apiRequest(`/api/checklists/${encodeURIComponent(bookingId)}`, { method: 'POST', body: { regenerate: true } }),
    addChecklistItem: (bookingId, text, category, dueOffsetDays) => apiRequest(
        `/api/checklists/${encodeURIComponent(bookingId)}/items`,
        { method: 'POST', body: { text, category, dueOffsetDays } }),
    setChecklistItem: (bookingId, itemId, done) => apiRequest(
        `/api/checklists/${encodeURIComponent(bookingId)}/items/${encodeURIComponent(itemId)}`,
        { method: 'PATCH', body: { done: !!done } }),
    deleteChecklistItem: (bookingId, itemId) => apiRequest(
        `/api/checklists/${encodeURIComponent(bookingId)}/items/${encodeURIComponent(itemId)}`, { method: 'DELETE' }),

    // Notifications (in-app; email only when a partner has opted in)
    notifications: () => apiRequest('/api/notifications'),
    readNotification: (id) => apiRequest(`/api/notifications/${encodeURIComponent(id)}/read`, { method: 'POST' }),
    readAllNotifications: () => apiRequest('/api/notifications/read-all', { method: 'POST' }),

    // Bookings
    getBookings: () => apiRequest('/api/bookings'),
    providerBookings: (type) => apiRequest(`/api/provider/bookings?type=${encodeURIComponent(type)}`),
    createBooking: (data) => apiRequest('/api/bookings', { method: 'POST', body: data }),
    cancelBooking: (id) => apiRequest(`/api/bookings/${id}`, { method: 'DELETE' }),
    downloadTicket: async (id) => {
        const response = await fetch(`/api/bookings/${id}/ticket`);
        if (!response.ok) {
            let message = 'Could not download the ticket.';
            try { message = (await response.json()).error || message; } catch (e) { /* ignore */ }
            throw new Error(message);
        }
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'TripMind-ticket.pdf';
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 4000);
    },
    verifyTicket: (token) => apiRequest(`/api/tickets/verify/${encodeURIComponent(token)}`),
    bookingToken: (id) => apiRequest(`/api/bookings/${id}/token`),
    tripToken: (id) => apiRequest(`/api/trips/${id}/token`),
    downloadTripTicket: async (id, name) => {
        const response = await fetch(`/api/trips/${id}/ticket`);
        if (!response.ok) {
            let message = 'Could not download the trip ticket.';
            try { message = (await response.json()).error || message; } catch (e) { /* ignore */ }
            throw new Error(message);
        }
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = name || 'TripMind-trip.pdf';
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 4000);
    },

    // Wallet
    getWallet: () => apiRequest('/api/wallet'),
    walletDeposit: (amount) => apiRequest('/api/wallet/deposit', { method: 'POST', body: { amount } }),
    tripPay: (id) => apiRequest(`/api/trips/${id}/pay`, { method: 'POST' }),
    payBooking: (id) => apiRequest(`/api/bookings/${id}/pay`, { method: 'POST' }),

    // Admin
    adminStats: () => apiRequest('/api/admin/stats'),
    adminBookings: () => apiRequest('/api/bookings/all'),
    adminUsers: (params = {}) => {
        const qs = new URLSearchParams(params).toString();
        return apiRequest(`/api/admin/users${qs ? `?${qs}` : ''}`);
    },
    adminSetApproval: (id, status, reason) => apiRequest(`/api/admin/users/${id}/approval`, { method: 'POST', body: { status, reason } }),
    // Role-aware Partner Hub approval queue (all five operational roles)
    adminPartners: ({ status = 'PENDING', role = 'ALL' } = {}) => apiRequest(
        `/api/admin/partners?status=${encodeURIComponent(status)}&role=${encodeURIComponent(role)}`),
    partnerDecision: (id, action, reason) => apiRequest(
        `/api/admin/partners/${encodeURIComponent(id)}/decision`,
        { method: 'POST', body: { action, reason } }),
    partnerSchema: (role) => apiRequest(`/api/partner/schema/${encodeURIComponent(role)}`),
    partnerMeta: () => apiRequest('/api/partner/meta'),
    partnerMe: () => apiRequest('/api/partner/me'),
    contentReview: () => apiRequest('/api/admin/content-review'),
    reviewContent: (kind, id, action, reason) => apiRequest(`/api/admin/content/${kind}/${id}/review`, { method: 'POST', body: { action, reason } }),
    adminAvailability: () => apiRequest('/api/admin/availability'),

    // ML layer
    mlStatus: () => apiRequest('/api/ml/status'),
    mlTrain: () => apiRequest('/api/admin/ml/train', { method: 'POST' }),
    mlRecommendSpots: (params = {}) => {
        const qs = new URLSearchParams(params).toString();
        return apiRequest(`/api/ml/recommend/spots${qs ? `?${qs}` : ''}`);
    },
    mlRecommendHotels: (params = {}) => {
        const qs = new URLSearchParams(params).toString();
        return apiRequest(`/api/ml/recommend/hotels${qs ? `?${qs}` : ''}`);
    },
    mlRecommendTransports: (params = {}) => {
        const qs = new URLSearchParams(params).toString();
        return apiRequest(`/api/ml/recommend/transports${qs ? `?${qs}` : ''}`);
    },
    mlRecommendGuides: (params = {}) => {
        const qs = new URLSearchParams(params).toString();
        return apiRequest(`/api/ml/recommend/guides${qs ? `?${qs}` : ''}`);
    },
    mlSimilar: (params = {}) => {
        const qs = new URLSearchParams(params).toString();
        return apiRequest(`/api/ml/similar${qs ? `?${qs}` : ''}`);
    },
    mlPredictCost: (params = {}) => {
        const qs = new URLSearchParams(params).toString();
        return apiRequest(`/api/ml/predict/cost${qs ? `?${qs}` : ''}`);
    },
    mlPredictTime: (params = {}) => {
        const qs = new URLSearchParams(params).toString();
        return apiRequest(`/api/ml/predict/time${qs ? `?${qs}` : ''}`);
    },
    mlClusters: () => apiRequest('/api/ml/clusters'),
    mlSegments: () => apiRequest('/api/ml/segments'),
    mlAffinity: (params = {}) => {
        const qs = new URLSearchParams(params).toString();
        return apiRequest(`/api/ml/affinity${qs ? `?${qs}` : ''}`);
    },
    mlDemand: (params = {}) => {
        const qs = new URLSearchParams(params).toString();
        return apiRequest(`/api/ml/demand${qs ? `?${qs}` : ''}`);
    },
    mlAnomalies: (params = {}) => {
        const qs = new URLSearchParams(params).toString();
        return apiRequest(`/api/ml/anomalies${qs ? `?${qs}` : ''}`);
    },
    mlVisitTimes: (spotId) => apiRequest(`/api/ml/visit-times?spotId=${encodeURIComponent(spotId)}`),
    mlRankTrip: (plans, requestData) => apiRequest('/api/ml/trip-rank', { method: 'POST', body: { plans, requestData } }),

    // Ratings
    ratingEligible: () => apiRequest('/api/ratings/eligible'),
    myRatings: () => apiRequest('/api/ratings'),
    addRating: (data) => apiRequest('/api/ratings', { method: 'POST', body: data }),
    serviceRating: (type, id) => apiRequest(`/api/ratings/service?type=${encodeURIComponent(type)}&id=${encodeURIComponent(id)}`),

    // Provider dashboards
    providerStats: () => apiRequest('/api/provider/stats'),
};

/* Publish the client on the shared namespace.
 *
 * `const api = {...}` is a module-scoped binding, not a global, so pages that
 * reached for `TM.api.*` got `undefined` and threw a TypeError on the first
 * call. pages/passengers.html did exactly that (TM.api.passengers()), so the
 * whole passenger page failed to load while every other page - which uses the
 * bare `api` identifier - worked fine, which is what made it look like a
 * data-layer problem rather than a namespace one.
 *
 * This mirrors how TM.esc and TM.statusBadge are already exposed from ui.js.
 * TM is created defensively so loading api.js before ui.js is not an error. */
if (typeof window !== 'undefined') {
    window.TM = window.TM || {};
    window.TM.api = api;
}
