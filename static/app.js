// ─── State ────────────────────────────────────────────────────────────────────
let hasLoadedOnce = false;
let refreshTimer = null;
let refreshCountdown = 0;
const REFRESH_INTERVAL = 300; // 5 minutes

// ─── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    loadWatchlist();
    initResearchToggle();

    // Search only fires on Enter — no debounce, no auto-fire on input
    document.getElementById('searchInput').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            const q = e.target.value.trim();
            loadMarkets(q);
        }
    });
});

// ─── Research Toggle ──────────────────────────────────────────────────────────
function initResearchToggle() {
    const saved = localStorage.getItem('polysint_research_enabled');
    const enabled = saved === 'true'; // default false
    document.getElementById('researchToggle').checked = enabled;
    updateToggleLabel(enabled);
}

function onResearchToggle() {
    const enabled = document.getElementById('researchToggle').checked;
    localStorage.setItem('polysint_research_enabled', enabled);
    updateToggleLabel(enabled);
}

function updateToggleLabel(enabled) {
    const label = document.getElementById('researchToggleLabel');
    if (enabled) {
        label.textContent = 'Web Research: ON';
        label.className = 'text-xs text-emerald-400 font-mono';
    } else {
        label.textContent = 'Web Research: OFF';
        label.className = 'text-xs text-gray-500 font-mono';
    }
}

// Always read at click time — never at render time
function isResearchEnabled() {
    return document.getElementById('researchToggle').checked;
}

// ─── Idle / Empty States ──────────────────────────────────────────────────────
function showIdleState() {
    const table = document.getElementById('marketsTable');
    const counter = document.getElementById('marketCounter');
    if (counter) counter.textContent = '';

    table.innerHTML = `
        <tr>
            <td colspan="4" class="py-16 text-center">
                <div class="flex flex-col items-center space-y-4">
                    <div class="text-5xl opacity-40">🕵️‍♂️</div>
                    <div class="text-gray-400 text-sm font-medium">Intelligence awaiting orders.</div>
                    <div class="text-gray-600 text-xs max-w-xs">Search for a specific market above and press Enter, or load all active movers.</div>
                    <button onclick="loadMarkets('')"
                        class="mt-2 bg-polysint text-gray-900 font-bold px-5 py-2 rounded-lg text-sm hover:bg-emerald-400 transition-all shadow-lg shadow-emerald-900/30">
                        Load Top Markets
                    </button>
                </div>
            </td>
        </tr>`;
}

function showLoadingState() {
    const table = document.getElementById('marketsTable');
    table.innerHTML = `
        <tr>
            <td colspan="4" class="py-16 text-center">
                <div class="flex flex-col items-center space-y-3">
                    <div class="flex space-x-1">
                        <div class="w-2 h-2 bg-polysint rounded-full animate-bounce" style="animation-delay:0ms"></div>
                        <div class="w-2 h-2 bg-polysint rounded-full animate-bounce" style="animation-delay:150ms"></div>
                        <div class="w-2 h-2 bg-polysint rounded-full animate-bounce" style="animation-delay:300ms"></div>
                    </div>
                    <div class="text-gray-400 text-sm">Scanning intelligence feeds...</div>
                </div>
            </td>
        </tr>`;
}

function showEmptySearchState(query) {
    const table = document.getElementById('marketsTable');
    table.innerHTML = `
        <tr>
            <td colspan="4" class="py-16 text-center">
                <div class="flex flex-col items-center space-y-3">
                    <div class="text-4xl opacity-30">🔍</div>
                    <div class="text-gray-400 text-sm">No markets found for <span class="text-white font-mono">"${query}"</span></div>
                    <div class="text-gray-600 text-xs">Try a broader term or check the harvester has run.</div>
                </div>
            </td>
        </tr>`;
}

// ─── Auto-Refresh ─────────────────────────────────────────────────────────────
function startAutoRefresh(query) {
    clearInterval(refreshTimer);
    refreshCountdown = REFRESH_INTERVAL;
    updateRefreshUI();

    refreshTimer = setInterval(() => {
        refreshCountdown -= 1;
        updateRefreshUI();
        if (refreshCountdown <= 0) {
            loadMarkets(query, true); // silent refresh
        }
    }, 1000);
}

function updateRefreshUI() {
    const el = document.getElementById('refreshCountdown');
    if (!el) return;
    if (refreshCountdown > 0) {
        const mins = Math.floor(refreshCountdown / 60);
        const secs = refreshCountdown % 60;
        el.textContent = `Auto-refresh in ${mins}:${secs.toString().padStart(2, '0')}`;
    } else {
        el.textContent = 'Refreshing...';
    }
}

// ─── Core: Load Markets ───────────────────────────────────────────────────────
const formatter = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });

async function loadMarkets(searchQuery = '', silent = false) {
    if (!silent) showLoadingState();

    // Read volume filter values — empty means no bound applied
    const volMin = document.getElementById('volMin')?.value.trim();
    const volMax = document.getElementById('volMax')?.value.trim();

    try {
        const params = new URLSearchParams();
        if (searchQuery) params.set('search', searchQuery);
        if (volMin !== '') params.set('vol_min', volMin);
        if (volMax !== '') params.set('vol_max', volMax);

        const url = `/markets${params.toString() ? '?' + params.toString() : ''}`;
        const res = await fetch(url);
        if (!res.ok) throw new Error(`Backend Error ${res.status}`);

        const markets = await res.json();
        hasLoadedOnce = true;

        const counter = document.getElementById('marketCounter');
        if (counter) counter.textContent = markets.length > 0 ? `${markets.length} markets` : '';

        const table = document.getElementById('marketsTable');
        table.innerHTML = '';

        if (markets.length === 0) {
            showEmptySearchState(searchQuery || 'active markets');
            return;
        }

        markets.forEach((m, i) => {
            const shift = m.shift || 0;
            const absShift = Math.abs(shift);
            const shiftColor = shift > 0 ? 'text-emerald-400' : (shift < 0 ? 'text-red-400' : 'text-gray-500');
            const shiftIcon = shift > 0 ? '↑' : (shift < 0 ? '↓' : '–');
            const isAnomaly = absShift >= 10.0;
            const isWarning = absShift >= 5.0 && absShift < 10.0;

            const currentOdds = m.current_price != null
                ? `${Math.round(m.current_price * 100)}%`
                : 'N/A';

            let anomalyBadge = '';
            if (isAnomaly) {
                anomalyBadge = `<span class="ml-2 inline-flex items-center px-1.5 py-0.5 rounded text-xs font-bold bg-red-500/20 text-red-400 border border-red-500/40 animate-pulse">⚡ ANOMALY</span>`;
            } else if (isWarning) {
                anomalyBadge = `<span class="ml-2 inline-flex items-center px-1.5 py-0.5 rounded text-xs font-bold bg-amber-500/20 text-amber-400 border border-amber-500/40">⚠ WATCH</span>`;
            }

            const rowHighlight = isAnomaly
                ? 'bg-red-500/5 hover:bg-red-500/10'
                : 'hover:bg-gray-700/30';

            const tr = document.createElement('tr');
            tr.className = `transition-colors border-b border-gray-700/50 ${rowHighlight}`;
            tr.style.animationDelay = `${i * 30}ms`;

            // analyzeMarket reads isResearchEnabled() at click time — not baked in at render time
            tr.innerHTML = `
                <td class="px-4 py-4 font-medium text-gray-200">
                    <div class="flex items-start flex-wrap gap-1">
                        <span>${m.question}</span>
                        ${anomalyBadge}
                    </div>
                    <div class="text-xs text-blue-400 mt-1 font-mono">Odds: ${currentOdds}</div>
                </td>
                <td class="px-4 py-4 font-mono ${shiftColor} font-bold text-sm">
                    ${shiftIcon} ${absShift}%
                    <div class="text-xs text-gray-600 font-normal">24h shift</div>
                </td>
                <td class="px-4 py-4 text-gray-400 text-xs">${formatter.format(m.volume)}</td>
                <td class="px-4 py-4 text-right">
                    <button onclick="analyzeMarket('${m.id}')"
                        class="bg-polysint/10 text-polysint border border-polysint/30 hover:bg-polysint hover:text-white px-3 py-1 rounded text-xs transition-all shadow-sm whitespace-nowrap">
                        🤖 Analyze
                    </button>
                </td>
            `;
            table.appendChild(tr);
        });

        startAutoRefresh(searchQuery);

    } catch (e) {
        console.error(e);
        const table = document.getElementById('marketsTable');
        table.innerHTML = `
            <tr><td colspan="4" class="text-center py-10">
                <div class="flex flex-col items-center space-y-3">
                    <div class="text-3xl">⚠️</div>
                    <div class="text-red-400 text-sm">Failed to load markets.</div>
                    <div class="text-gray-600 text-xs">Is the backend running? Check <code>analyzer.log</code>.</div>
                    <button onclick="loadMarkets('${searchQuery}')" class="mt-2 text-xs text-polysint underline">Retry</button>
                </div>
            </td></tr>`;
    }
}

// ─── AI Analysis Modal ────────────────────────────────────────────────────────
// useResearch is read live from the toggle at click time — not passed from render time
async function analyzeMarket(marketId) {
    const useResearch = isResearchEnabled();

    const modal = document.getElementById('aiModal');
    const content = document.getElementById('aiModalContent');
    const modalTitle = document.getElementById('aiModalTitle');

    modal.classList.remove('hidden');

    const researchNote = useResearch
        ? '<span class="text-xs bg-emerald-900/40 text-emerald-400 border border-emerald-800/50 px-2 py-0.5 rounded font-mono ml-2">+ Web Research</span>'
        : '<span class="text-xs bg-gray-800 text-gray-500 border border-gray-700 px-2 py-0.5 rounded font-mono ml-2">No Web Research</span>';

    modalTitle.innerHTML = `🤖 PolySINT Intelligence ${researchNote}`;

    content.innerHTML = `
        <div class="flex flex-col items-center justify-center space-y-3 py-12">
            <div class="flex space-x-1">
                <div class="w-2 h-2 bg-polysint rounded-full animate-bounce" style="animation-delay:0ms"></div>
                <div class="w-2 h-2 bg-polysint rounded-full animate-bounce" style="animation-delay:150ms"></div>
                <div class="w-2 h-2 bg-polysint rounded-full animate-bounce" style="animation-delay:300ms"></div>
            </div>
            <div class="text-polysint text-sm animate-pulse">
                ${useResearch ? 'Scanning web + running LLM analysis...' : 'Running LLM analysis...'}
            </div>
            ${!useResearch ? '<div class="text-gray-600 text-xs">Enable Web Research in the toolbar for news context.</div>' : ''}
        </div>`;

    try {
        const url = `/markets/${marketId}/ai-analysis?research=${useResearch}`;
        const res = await fetch(url);
        if (!res.ok) throw new Error("AI Analysis Failed");
        const data = await res.json();

        const formatted = data.analysis
            .replace(/\*\*(.*?)\*\*/g, '<strong class="text-white">$1</strong>')
            .replace(/\n/g, '<br>');

        content.innerHTML = `<div class="p-3 border-l-4 border-polysint bg-gray-900/60 rounded-r leading-relaxed">${formatted}</div>`;
    } catch (e) {
        content.innerHTML = `
            <div class="text-red-400 bg-red-900/20 p-4 rounded border border-red-800 text-sm">
                ⚠️ Could not generate intelligence brief.<br>
                <span class="text-xs text-gray-500 mt-1 block">Check your LLM API key and <code>analyzer.log</code>.</span>
            </div>`;
    }
}

// ─── Wallet / Entity ──────────────────────────────────────────────────────────
async function profileEntity(address, label) {
    const modal = document.getElementById('aiModal');
    const content = document.getElementById('aiModalContent');
    const modalTitle = document.getElementById('aiModalTitle');

    modal.classList.remove('hidden');
    modalTitle.innerHTML = `🧠 Entity Profile — ${label}`;

    content.innerHTML = `
        <div class="flex flex-col items-center justify-center space-y-3 py-12">
            <div class="flex space-x-1">
                <div class="w-2 h-2 bg-blue-400 rounded-full animate-bounce" style="animation-delay:0ms"></div>
                <div class="w-2 h-2 bg-blue-400 rounded-full animate-bounce" style="animation-delay:150ms"></div>
                <div class="w-2 h-2 bg-blue-400 rounded-full animate-bounce" style="animation-delay:300ms"></div>
            </div>
            <div class="text-blue-400 text-sm animate-pulse">Fetching on-chain history & profiling...</div>
        </div>`;

    try {
        const res = await fetch(`/wallets/${address}/profile`);
        if (!res.ok) throw new Error("Profiling Failed");
        const data = await res.json();

        const formatted = data.profile
            .replace(/\*\*(.*?)\*\*/g, '<strong class="text-white">$1</strong>')
            .replace(/\n/g, '<br>');

        content.innerHTML = `
            <div class="mb-4 p-3 bg-gray-900 rounded border border-gray-700 font-mono text-xs text-gray-400 space-y-1">
                <div><span class="text-gray-600">Proxy:</span> ${address}</div>
                <div><span class="text-gray-600">EOA:</span> <span class="text-polysint">${data.real_owner}</span></div>
            </div>
            <div class="p-3 border-l-4 border-blue-500 bg-gray-900/60 rounded-r leading-relaxed">${formatted}</div>`;
    } catch (e) {
        content.innerHTML = `<div class="text-red-400 bg-red-900/20 p-4 rounded border border-red-800 text-sm">⚠️ Could not generate entity profile.</div>`;
    }
}

async function unmaskWallet(address) {
    const btn = document.getElementById(`btn-${address}`);
    const realDiv = document.getElementById(`real-${address}`);

    btn.disabled = true;
    btn.innerHTML = '<span class="animate-pulse">Scanning...</span>';
    btn.classList.add("opacity-50", "cursor-not-allowed");

    try {
        const res = await fetch(`/wallets/${address}/unmask`);
        const data = await res.json();

        realDiv.classList.remove("hidden");
        realDiv.innerHTML = `EOA: <span class="text-polysint">${data.real_owner}</span>`;
        btn.textContent = "✓ Unmasked";
        btn.classList.remove("border-gray-600", "text-gray-300", "hover:bg-gray-700");
        btn.classList.add("bg-gray-700", "text-gray-500", "border-transparent", "cursor-default");
    } catch (e) {
        btn.disabled = false;
        btn.textContent = "Retry";
        btn.classList.remove("opacity-50", "cursor-not-allowed");
        alert("Failed to unmask wallet. Check RPC configuration.");
    }
}

// ─── Watchlist ────────────────────────────────────────────────────────────────
async function addTarget() {
    const addressInput = document.getElementById('newAddress');
    const labelInput = document.getElementById('newLabel');
    const address = addressInput.value.trim();
    const label = labelInput.value.trim();

    if (!address || !label) {
        showInlineError('addError', 'Both address and label are required.');
        return;
    }

    try {
        const res = await fetch('/watchlist', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ address, label })
        });

        const data = await res.json();
        if (res.ok) {
            addressInput.value = '';
            labelInput.value = '';
            clearInlineError('addError');
            loadWatchlist();
        } else {
            showInlineError('addError', data.detail || 'Failed to add target.');
        }
    } catch (e) {
        showInlineError('addError', 'Network error. Is the backend running?');
    }
}

function showInlineError(id, msg) {
    const el = document.getElementById(id);
    if (el) { el.textContent = msg; el.classList.remove('hidden'); }
}

function clearInlineError(id) {
    const el = document.getElementById(id);
    if (el) { el.textContent = ''; el.classList.add('hidden'); }
}

async function loadWatchlist() {
    const table = document.getElementById('watchlistTable');
    try {
        const res = await fetch('/watchlist');
        const watchlist = await res.json();

        table.innerHTML = '';
        if (watchlist.length === 0) {
            table.innerHTML = `
                <tr><td class="text-center py-10 text-gray-600 text-sm italic px-4">
                    Watchlist empty.<br>
                    <span class="text-xs">Add a target's 0x proxy address above.</span>
                </td></tr>`;
            return;
        }

        watchlist.forEach(w => {
            const shortAddr = w.address.substring(0, 6) + '…' + w.address.substring(w.address.length - 4);
            const tr = document.createElement('tr');
            tr.className = "hover:bg-gray-700/30 transition-colors border-b border-gray-700/50";
            tr.innerHTML = `
                <td class="px-4 py-3">
                    <div class="font-semibold text-gray-200 text-sm">${w.label}</div>
                    <div class="text-xs font-mono text-gray-500 mt-0.5">${shortAddr}</div>
                    <div class="text-xs font-mono text-polysint mt-0.5 hidden" id="real-${w.address}"></div>
                </td>
                <td class="px-4 py-3 text-right">
                    <div class="flex justify-end items-center gap-1 flex-wrap">
                        <button onclick="unmaskWallet('${w.address}')" id="btn-${w.address}"
                            class="bg-gray-800 border border-gray-600 text-gray-300 hover:bg-gray-700 px-2 py-1 rounded text-xs transition-all">
                            Unmask
                        </button>
                        <button onclick="profileEntity('${w.address}', '${w.label}')"
                            class="bg-blue-900/40 text-blue-400 border border-blue-800 hover:bg-blue-800 hover:text-white px-2 py-1 rounded text-xs transition-all">
                            AI Profile
                        </button>
                        <button onclick="deleteTarget('${w.address}')" title="Stop Tracking"
                            class="bg-red-900/30 text-red-400 border border-red-800 hover:bg-red-800 hover:text-white px-2 py-1 rounded text-xs transition-all">
                            ✕
                        </button>
                    </div>
                </td>`;
            table.appendChild(tr);
        });
    } catch (e) {
        table.innerHTML = `<tr><td class="text-center py-8 text-red-400 text-sm">Failed to load watchlist.</td></tr>`;
    }
}

async function deleteTarget(address) {
    if (!confirm("Stop tracking this entity?")) return;
    try {
        const res = await fetch(`/watchlist/${address}`, { method: 'DELETE' });
        if (res.ok) loadWatchlist();
        else alert("Failed to delete target.");
    } catch (e) { console.error(e); }
}

function closeModal() {
    document.getElementById('aiModal').classList.add('hidden');
}

document.addEventListener('click', (e) => {
    const modal = document.getElementById('aiModal');
    if (e.target === modal) closeModal();
});
