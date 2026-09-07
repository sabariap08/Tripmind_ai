function formatCurrency(amount, currency = 'INR') {
    if (amount == null) return '₹0';
    return new Intl.NumberFormat('en-IN', {
        style: 'currency', currency: currency, maximumFractionDigits: 0
    }).format(amount);
}

function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function money(n) {
    if (n == null) return '₹0';
    return '₹' + Number(n || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 });
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
    return '';
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

/* Login-first entry guard --------------------------------------------------- */

async function guardLogin() {
    try {
        const res = await api.me();
        const u = res && res.user;
        if (!u) return redirectToLogin();
        window.__user = u;
        return u;
    } catch (e) {
        return redirectToLogin();
    }
}

function redirectToLogin() {
    location.href = '/login.html?next=' + encodeURIComponent(location.pathname + location.search);
    return null;
}

function roleLanding(user) {
    return '/portal.html';
}

/* Live duplicate-data check (Phase 1). Resolves to true when the value is
 * available, false when already taken or invalid. Errors resolve to true so a
 * failed availability probe never blocks form submission by itself. */
async function checkAvailable(field, value) {
    if (!value) return true;
    try {
        const res = await api.checkAvailability(field, value);
        return !!(res && res.available !== false);
    } catch (e) {
        return true;
    }
}

/* Role-specific provider registration fields ---------------------------------
 * Used by register.html to render the account-type form, and by the Admin
 * approval detail viewer to label each submitted value. */
const REGISTRABLE_ROLES = [
    { value: 'USER', label: 'Normal User / Passenger', approval: 'No approval required' },
    { value: 'TRANSPORT_ADMIN', label: 'Transport Admin', approval: 'Admin approval required' },
    { value: 'HOTEL_ADMIN', label: 'Hotel Admin', approval: 'Admin approval required' },
    { value: 'RESTAURANT_ADMIN', label: 'Restaurant Admin', approval: 'Admin approval required' },
    { value: 'TOURIST_SPOT_ADMIN', label: 'Travel Spot Admin', approval: 'Admin approval required' },
    { value: 'GUIDE', label: 'Guide', approval: 'Admin approval required' },
];

const DAYS_OF_WEEK = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

/* Returns [{ id, label, type, options?, placeholder?, required? }] used to
 * collect role-specific registration data that the Main Admin inspects during
 * approval. */
function regFieldDefs(role) {
    const defs = {
        TRANSPORT_ADMIN: [
            { id: 'companyName', label: 'Company Name', type: 'text', required: true },
            { id: 'ownerName', label: 'Company Owner Name', type: 'text', required: true },
            { id: 'companyRegDate', label: 'Organization / Registration Date', type: 'date' },
            { id: 'partners', label: 'Number of Partners (if applicable)', type: 'number' },
            { id: 'contactNumber', label: 'Company Contact Number', type: 'text', required: true },
            { id: 'companyEmail', label: 'Company Email', type: 'email', required: true },
            { id: 'gst', label: 'GST Number', type: 'text' },
            { id: 'companyAddress', label: 'Company Address', type: 'textarea', required: true },
        ],
        HOTEL_ADMIN: [
            { id: 'hotelName', label: 'Hotel / Property Name', type: 'text', required: true },
            { id: 'ownerName', label: 'Owner / Admin Name', type: 'text', required: true },
            { id: 'contactNumber', label: 'Contact Number', type: 'text', required: true },
            { id: 'email', label: 'Email', type: 'email', required: true },
            { id: 'gst', label: 'GST Number', type: 'text' },
            { id: 'address', label: 'Address', type: 'textarea', required: true },
            { id: 'registrationInfo', label: 'Business / Registration Information', type: 'textarea' },
        ],
        RESTAURANT_ADMIN: [
            { id: 'restaurantName', label: 'Restaurant Name', type: 'text', required: true },
            { id: 'ownerName', label: 'Owner / Admin Name', type: 'text', required: true },
            { id: 'contactNumber', label: 'Contact Number', type: 'text', required: true },
            { id: 'email', label: 'Email', type: 'email', required: true },
            { id: 'gst', label: 'GST Number', type: 'text' },
            { id: 'address', label: 'Address', type: 'textarea', required: true },
            { id: 'businessRegInfo', label: 'Business / Registration Information', type: 'textarea' },
        ],
        TOURIST_SPOT_ADMIN: [
            { id: 'spotName', label: 'Travel Spot Name', type: 'text', required: true },
            { id: 'adminName', label: 'Travel Spot Admin Name', type: 'text', required: true },
            { id: 'contactNumber', label: 'Contact Number', type: 'text', required: true },
            { id: 'email', label: 'Email', type: 'email', required: true },
            { id: 'idType', label: 'Admin Identification Type', type: 'text', required: true },
            { id: 'idNumber', label: 'Admin Identification Number', type: 'text', required: true },
            { id: 'govtApproval', label: 'Government / Authority Approval Information', type: 'textarea' },
            { id: 'locationAddress', label: 'Location Address', type: 'textarea', required: true },
            { id: 'city', label: 'City', type: 'text', required: true },
            { id: 'district', label: 'District', type: 'text' },
            { id: 'state', label: 'State', type: 'text' },
            { id: 'optimalTimes', label: 'Optimal Visiting Times (min 5, comma separated)', type: 'text', required: true },
            { id: 'entryFee', label: 'Entry Fee (0 for free)', type: 'number' },
            { id: 'workingDays', label: 'Working Days (e.g. Mon,Tue,Wed,Thu,Fri,Sat)', type: 'text', required: true },
        ],
        GUIDE: [
            { id: 'dob', label: 'Date of Birth', type: 'date', required: true },
            { id: 'contactNumber', label: 'Contact Number', type: 'text', required: true },
            { id: 'address', label: 'Address', type: 'textarea', required: true },
            { id: 'idType', label: 'Identification Type', type: 'text', required: true },
            { id: 'idNumber', label: 'Identification Number', type: 'text', required: true },
            { id: 'qualification', label: 'Qualification / Approval Information', type: 'textarea' },
            { id: 'experience', label: 'Experience (years)', type: 'number' },
            { id: 'languages', label: 'Languages (comma separated)', type: 'text' },
        ],
    };
    return defs[role] || [];
}
