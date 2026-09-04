function formatCurrency(amount, currency = 'INR') {
    if (amount == null) return '₹0';
    return new Intl.NumberFormat('en-IN', {
        style: 'currency', currency: currency, maximumFractionDigits: 0
    }).format(amount);
}

function formatDate(dateStr) {
    if (!dateStr) return '';
    const d = new Date(dateStr);
    return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
}

function formatTime(dateStr) {
    if (!dateStr) return '';
    const d = new Date(dateStr);
    return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: true });
}

function getSeverityBadge(severity) {
    const map = {
        'INFO': 'badge-info', 'LOW': 'badge-warning', 'MEDIUM': 'badge-warning', 'HIGH': 'badge-destructive'
    };
    return `<span class="badge ${map[severity] || 'badge-default'}">${severity}</span>`;
}

function getStatusBadge(status) {
    const map = {
        'DRAFT': 'badge-default', 'PLANNED': 'badge-info', 'BOOKED': 'badge-success',
        'REPLANNING': 'badge-warning', 'COMPLETED': 'badge-success',
        'SELECTED': 'badge-success', 'AVAILABLE': 'badge-secondary', 'SUPERSEDED': 'badge-destructive',
    };
    return `<span class="badge ${map[status] || 'badge-default'}">${status}</span>`;
}

function getTypeColor(type) {
    const map = {
        'FLIGHT': 'flight', 'HOTEL': 'hotel', 'FOOD': 'food',
        'ACTIVITY': 'activity', 'TRANSFER': 'transfer', 'TRANSPORT': 'transfer',
    };
    return map[type] || '';
}

function getTypeIcon(type) {
    const map = {
        'FLIGHT': '✈️', 'HOTEL': '🏨', 'FOOD': '🍽️',
        'ACTIVITY': '🎯', 'TRANSFER': '🚗', 'TRANSPORT': '🚕',
    };
    return map[type] || '📌';
}

function getCostBarColor(category) {
    const map = {
        'flights': '#3b82f6', 'hotel': '#8b5cf6', 'transport': '#64748b',
        'activities': '#10b981', 'food': '#f59e0b',
    };
    return map[category] || '#94a3b8';
}

function parseNaturalInput(text) {
    const result = {
        origin: '', destination: '', travelers: 1,
        budget: 50000, days: 3, travelStyle: 'BALANCED', foodPreference: ''
    };
    const lower = text.toLowerCase();

    const cities = ['coimbatore', 'chennai', 'mumbai', 'delhi', 'bangalore', 'bengaluru',
        'new york', 'london', 'dubai', 'singapore', 'tokyo', 'paris', 'bangkok', 'sydney',
        'goa', 'jaipur', 'kolkata', 'hyderabad'];
    const found = cities.filter(c => lower.includes(c));
    if (found.length >= 2) { result.origin = found[0]; result.destination = found[1]; }
    else if (found.length === 1) { result.destination = found[0]; }

    const dayMatch = lower.match(/(\d+)\s*day/);
    if (dayMatch) result.days = parseInt(dayMatch[1]);

    const pplMatch = lower.match(/(\d+)\s*(people|person|ppl|traveller|traveler)/);
    if (pplMatch) result.travelers = parseInt(pplMatch[1]);

    const budgetMatch = lower.match(/(\d+)\s*(lakh|lac)/);
    if (budgetMatch) result.budget = parseInt(budgetMatch[1]) * 100000;
    else {
        const numBudget = lower.match(/(\d+)/);
        if (numBudget && parseInt(numBudget[1]) > 1000) result.budget = parseInt(numBudget[1]);
    }

    if (lower.includes('budget') || lower.includes('cheap')) result.travelStyle = 'BUDGET';
    else if (lower.includes('premium') || lower.includes('luxury')) result.travelStyle = 'PREMIUM';
    else result.travelStyle = 'BALANCED';

    if (lower.includes('vegetarian') || lower.includes('veg')) result.foodPreference = 'vegetarian';

    return result;
}
