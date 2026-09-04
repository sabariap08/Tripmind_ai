const API_BASE = '';

async function apiRequest(url, options = {}) {
    const config = {
        headers: { 'Content-Type': 'application/json' },
        ...options,
    };
    if (config.body && typeof config.body === 'object') {
        config.body = JSON.stringify(config.body);
    }
    const response = await fetch(`${API_BASE}${url}`, config);
    const data = await response.json();
    if (!response.ok) {
        throw new Error(data.error || 'Request failed');
    }
    return data;
}

const api = {
    getTrips: () => apiRequest('/api/trips'),
    createTrip: (data) => apiRequest('/api/trips', { method: 'POST', body: data }),
    getTrip: (id) => apiRequest(`/api/trips/${id}`),
    generatePlans: (id) => apiRequest(`/api/trips/${id}/generate`, { method: 'POST' }),
    bookTrip: (id) => apiRequest(`/api/trips/${id}/book`, { method: 'POST' }),
    getEvents: (id) => apiRequest(`/api/trips/${id}/events`),
    getItinerary: (id) => apiRequest(`/api/trips/${id}/itinerary`),
    simulateDelay: (id, minutes) => apiRequest(`/api/trips/${id}/simulate-delay`, { method: 'POST', body: { delayMinutes: minutes } }),
    replan: (id, minutes) => apiRequest(`/api/trips/${id}/replan`, { method: 'POST', body: { delayMinutes: minutes } }),
    chat: (message, tripId) => apiRequest('/api/ai/chat', { method: 'POST', body: { message, tripId } }),
};
