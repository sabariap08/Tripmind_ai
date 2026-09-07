const API_BASE = '';

async function apiRequest(url, options = {}) {
    const config = {
        headers: { 'Content-Type': 'application/json' },
        ...options,
    };
    if (config.body && typeof config.body === 'object') {
        config.body = JSON.stringify(config.body);
    }
    let response;
    try {
        response = await fetch(`${API_BASE}${url}`, config);
    } catch (e) {
        throw new Error('Network error — please try again.');
    }
    const text = await response.text();
    let data = null;
    try {
        data = text ? JSON.parse(text) : null;
    } catch (e) {
        data = { error: text.trim() ? `Server returned an invalid response (${response.status}).` : 'Server returned an empty response.' };
    }
    if (!response.ok) {
        throw new Error(data.error || ('Request failed (' + response.status + ').'));
    }
    return data;
}

const api = {
    getTrips: () => apiRequest('/api/trips'),
    adminTrips: () => apiRequest('/api/admin/trips'),
    createTrip: (data) => apiRequest('/api/trips', { method: 'POST', body: data }),
    getTrip: (id) => apiRequest(`/api/trips/${id}`),
    generatePlans: (id) => apiRequest(`/api/trips/${id}/generate`, { method: 'POST' }),
    bookTrip: (id) => apiRequest(`/api/trips/${id}/book`, { method: 'POST' }),
    getEvents: (id) => apiRequest(`/api/trips/${id}/events`),
    getItinerary: (id) => apiRequest(`/api/trips/${id}/itinerary`),
    editItineraryItems: (id, action, payload = {}) => apiRequest(`/api/trips/${id}/itinerary/items`, { method: 'POST', body: { action, ...payload } }),
    simulateDelay: (id, minutes) => apiRequest(`/api/trips/${id}/simulate-delay`, { method: 'POST', body: { delayMinutes: minutes } }),
    replan: (id, minutes) => apiRequest(`/api/trips/${id}/replan`, { method: 'POST', body: { delayMinutes: minutes } }),
    chat: (message, tripId) => apiRequest('/api/ai/chat', { method: 'POST', body: { message, tripId } }),
    getMindmapFlow: () => apiRequest('/api/mindmap/flow'),
    tripReviews: (id) => apiRequest(`/api/trips/${id}/reviews`),
    addTripReview: (id, rating, comment) => apiRequest(`/api/trips/${id}/review`, { method: 'POST', body: { rating, comment } }),
    feedbackAnalysis: () => apiRequest('/api/ai/feedback-analysis', { method: 'POST' }),
    assistantChat: (message, tripId) => apiRequest('/api/assistant/chat', { method: 'POST', body: { message, tripId } }),
    assistantAction: (type, params) => apiRequest('/api/assistant/action', { method: 'POST', body: { type, params } }),

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
    transportTypes: () => apiRequest('/api/transport/types'),

    // Tourist spots
    getSpots: (params = {}) => {
        const qs = new URLSearchParams(params).toString();
        return apiRequest(`/api/spots${qs ? `?${qs}` : ''}`);
    },
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
