let refreshTimer = null;
let refreshCountdown = 0;
const REFRESH_INTERVAL = 300;

document.addEventListener("DOMContentLoaded", () => {
    loadWatchlist();
    initResearchToggle();
    document.getElementById('searchInput').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') loadMarkets(e.target.value.trim());
    });
});

function _escapeHtml(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
}

function _apiHeaders() {
    const key = localStorage.getItem('polysint_api_key');
    const h = { 'Content-Type': 'application/json' };
    if (key) h['X-API-Key'] = key;
    return h;
}

async function _apiFetch(url, opts = {}) {
    opts.headers = { ..._apiHeaders(), ...(opts.headers || {}) };
    const res = await fetch(url, opts);
    if (res.status === 401) {
        const key = prompt('API key required. Enter your PolySINT API key:');
        if (key) {
            localStorage.setItem('polysint_api_key', key);
            opts.headers['X-API-Key'] = key;
            return fetch(url, opts);
        }
    }
    return res;
}

function _renderMarkdown(text) {
    return _escapeHtml(text)
        .replace(/\*\*(.*?)\*\*/g, '<strong class="text-white">$1</strong>')
        .replace(/\n/g, '<br>');
}

function initResearchToggle() {
    const saved = localStorage.getItem('polysint_research_enabled');
    const enabled = saved === 'true';
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

function isResearchEnabled() {
    return document.getElementById('researchToggle').checked;
}

function showIdleState() {
    const table = document.getElementById('marketsTable');
    const counter = document.getElementById('marketCounter');
    if (counter) counter.textContent = '';
    table.innerHTML = `
        <tr><td colspan="4" class="py-16 text-center">
            <div class="flex flex-col items-center space-y-4">
                <div class="text-5xl opacity-40">🕵️‍♂️</div>
                <div class="text-gray-400 text-sm font-medium">Intelligence awaiting orders.</div>
                <div class="text-gray-600 text-xs max-w-xs">Search for a specific market above and press Enter, or load all active movers.</div>
                <button onclick="loadMarkets('')"
                    class="mt-2 bg-polysint text-gray-900 font-bold px-5 py-2 rounded-lg text-sm hover:bg-emerald-400 transition-all shadow-lg shadow-emerald-900/30">
                    Load Top Markets
                </button>
            </div>
        </td></tr>`;
}

function showLoadingState() {
    const table = document.getElementById('marketsTable');
    table.innerHTML = `
        <tr><td colspan="4" class="py-16 text-center">
            <div class="flex flex-col items-center space-y-3">
                <div class="flex space-x-1">
                    <div class="w-2 h-2 bg-polysint rounded-full animate-bounce" style="animation-delay:0ms"></div>
                    <div class="w-2 h-2 bg-polysint rounded-full animate-bounce" style="animation-delay:150ms"></div>
                    <div class="w-2 h-2 bg-polysint rounded-full animate-bounce" style="animation-delay:300ms"></div>
                </div>
                <div class="text-gray-400 text-sm">Scanning intelligence feeds...</div>
            </div>
        </td></tr>`;
}

function showEmptySearchState(query) {
    const table = document.getElementById('marketsTable');
    table.innerHTML = `
        <tr><td colspan="4" class="py-16 text-center">
            <div class="flex flex-col items-center space-y-3">
                <div class="text-4xl opacity-30">🔍</div>
                <div class="text-gray-400 text-sm">No markets found for <span class="text-white font-mono">${_escapeHtml(query)}</span></div>
                <div class="text-gray-600 text-xs">Try a broader term or check the harvester has run.</div>
            </div>
        </td></tr>`;
}

function startAutoRefresh(query) {
    clearInterval(refreshTimer);
    refreshCountdown = REFRESH_INTERVAL;
    updateRefreshUI();
    refreshTimer = setInterval(() => {
        refreshCountdown -= 1;
        updateRefreshUI();
        if (refreshCountdown <= 0) loadMarkets(query, true);
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

const formatter = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });

async function loadMarkets(searchQuery = '', silent = false) {
    if (!silent) showLoadingState();
    const volMin = document.getElementById('volMin')?.value.trim();
    const volMax = document.getElementById('volMax')?.value.trim();

    try {
        const params = new URLSearchParams();
        if (searchQuery) params.set('search', searchQuery);
        if (volMin !== '') params.set('vol_min', volMin);
        if (volMax !== '') params.set('vol_max', volMax);

        const url = `/markets${params.toString() ? '?' + params.toString() : ''}`;
        const res = await _apiFetch(url);
        if (!res.ok) throw new Error(`Backend Error ${res.status}`);
        const markets = await res.json();

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
            const currentOdds = m.current_price != null ? `${Math.round(m.current_price * 100)}%` : 'N/A';

            let anomalyBadge = '';
            if (isAnomaly) {
                anomalyBadge = `<span class="ml-2 inline-flex items-center px-1.5 py-0.5 rounded text-xs font-bold bg-red-500/20 text-red-400 border border-red-500/40 animate-pulse">ANOMALY</span>`;
            } else if (isWarning) {
                anomalyBadge = `<span class="ml-2 inline-flex items-center px-1.5 py-0.5 rounded text-xs font-bold bg-amber-500/20 text-amber-400 border border-amber-500/40">WATCH</span>`;
            }

            const rowHighlight = isAnomaly ? 'bg-red-500/5 hover:bg-red-500/10' : 'hover:bg-gray-700/30';

            const tr = document.createElement('tr');
            tr.className = `transition-colors border-b border-gray-700/50 ${rowHighlight}`;

            const safeId = _escapeHtml(String(m.id));
            const safeQuestion = _escapeHtml(m.question);

            tr.innerHTML = `
                <td class="px-4 py-4 font-medium text-gray-200">
                    <div class="flex items-start flex-wrap gap-1">
                        <span>${safeQuestion}</span>
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
                    <div class="flex justify-end gap-1 flex-wrap">
                        <button onclick="analyzeMarket('${safeId}')"
                            class="bg-polysint/10 text-polysint border border-polysint/30 hover:bg-polysint hover:text-white px-2.5 py-1 rounded text-xs transition-all shadow-sm">
                            AI Analyze
                        </button>
                        <button onclick="showOrderbook('${safeId}')"
                            class="bg-gray-700/50 text-gray-400 border border-gray-600 hover:bg-gray-600 hover:text-white px-2 py-1 rounded text-xs transition-all">
                            Book
                        </button>
                    </div>
                </td>`;
            table.appendChild(tr);
        });

        startAutoRefresh(searchQuery);
    } catch (e) {
        console.error(e);
        document.getElementById('marketsTable').innerHTML = `
            <tr><td colspan="4" class="text-center py-10">
                <div class="flex flex-col items-center space-y-3">
                    <div class="text-3xl">⚠️</div>
                    <div class="text-red-400 text-sm">Failed to load markets.</div>
                    <div class="text-gray-600 text-xs">Is the backend running? Check <code>analyzer.log</code>.</div>
                    <button onclick="loadMarkets('${_escapeHtml(searchQuery)}')" class="mt-2 text-xs text-polysint underline">Retry</button>
                </div>
            </td></tr>`;
    }
}

async function analyzeMarket(marketId, forceRefresh = false) {
    const useResearch = isResearchEnabled();
    const modal = document.getElementById('aiModal');
    const content = document.getElementById('aiModalContent');
    const modalTitle = document.getElementById('aiModalTitle');

    modal.classList.remove('hidden');
    const researchNote = useResearch
        ? '<span class="text-xs bg-emerald-900/40 text-emerald-400 border border-emerald-800/50 px-2 py-0.5 rounded font-mono ml-2">+ Web Research</span>'
        : '<span class="text-xs bg-gray-800 text-gray-500 border border-gray-700 px-2 py-0.5 rounded font-mono ml-2">No Web Research</span>';
    modalTitle.innerHTML = `🤖 Market Intelligence ${researchNote}`;

    content.innerHTML = `
        <div class="flex flex-col items-center justify-center space-y-3 py-12">
            <div class="flex space-x-1">
                <div class="w-2 h-2 bg-polysint rounded-full animate-bounce" style="animation-delay:0ms"></div>
                <div class="w-2 h-2 bg-polysint rounded-full animate-bounce" style="animation-delay:150ms"></div>
                <div class="w-2 h-2 bg-polysint rounded-full animate-bounce" style="animation-delay:300ms"></div>
            </div>
            <div class="text-polysint text-sm animate-pulse">
                ${forceRefresh ? 'Forcing fresh LLM analysis...' : useResearch ? 'Scanning web + running LLM analysis...' : 'Running LLM analysis...'}
            </div>
        </div>`;

    try {
        const params = new URLSearchParams({ research: useResearch });
        if (forceRefresh) params.set('force', 'true');
        const res = await _apiFetch(`/markets/${marketId}/ai-analysis?${params.toString()}`);
        if (!res.ok) throw new Error("AI Analysis Failed");
        const data = await res.json();

        const formatted = _renderMarkdown(data.analysis);

        let cacheBadge = '';
        if (data.cached) {
            const cachedAt = data.cached_at
                ? new Date(data.cached_at + 'Z').toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                : 'recently';
            cacheBadge = `
                <div class="mb-4 flex items-center justify-between gap-3 flex-wrap">
                    <span class="inline-flex items-center gap-1.5 text-xs bg-blue-900/30 text-blue-400 border border-blue-800/50 px-2 py-1 rounded font-mono">
                        Cached from ${cachedAt}
                    </span>
                    <button onclick="analyzeMarket('${_escapeHtml(marketId)}', true)"
                        class="text-xs text-gray-500 hover:text-polysint underline transition-colors font-mono">
                        ↻ Force refresh
                    </button>
                </div>`;
        } else {
            cacheBadge = `
                <div class="mb-4">
                    <span class="inline-flex items-center gap-1.5 text-xs bg-polysint/10 text-polysint border border-polysint/20 px-2 py-1 rounded font-mono">
                        Fresh analysis — cached for 1 hour
                    </span>
                </div>`;
        }

        content.innerHTML = `${cacheBadge}<div class="p-3 border-l-4 border-polysint bg-gray-900/60 rounded-r leading-relaxed">${formatted}</div>`;
    } catch (e) {
        content.innerHTML = `
            <div class="text-red-400 bg-red-900/20 p-4 rounded border border-red-800 text-sm">
                Could not generate intelligence brief.<br>
                <span class="text-xs text-gray-500 mt-1 block">Check your LLM API key and <code>analyzer.log</code>.</span>
            </div>`;
    }
}

async function showOrderbook(marketId) {
    const modal = document.getElementById('aiModal');
    const content = document.getElementById('aiModalContent');
    const modalTitle = document.getElementById('aiModalTitle');

    modal.classList.remove('hidden');
    modalTitle.innerHTML = '📊 Orderbook Depth Analysis';
    content.innerHTML = `
        <div class="flex flex-col items-center justify-center space-y-3 py-12">
            <div class="flex space-x-1">
                <div class="w-2 h-2 bg-amber-400 rounded-full animate-bounce" style="animation-delay:0ms"></div>
                <div class="w-2 h-2 bg-amber-400 rounded-full animate-bounce" style="animation-delay:150ms"></div>
                <div class="w-2 h-2 bg-amber-400 rounded-full animate-bounce" style="animation-delay:300ms"></div>
            </div>
            <div class="text-amber-400 text-sm animate-pulse">Fetching orderbook data...</div>
        </div>`;

    try {
        const res = await _apiFetch(`/markets/${marketId}/orderbook`);
        if (!res.ok) throw new Error("Orderbook fetch failed");
        const data = await res.json();
        const d = data.depth;

        const signalColors = {
            BUYING_PRESSURE: 'text-emerald-400 bg-emerald-900/30 border-emerald-800/50',
            SELLING_PRESSURE: 'text-red-400 bg-red-900/30 border-red-800/50',
            BID_WALL_SUPPORT: 'text-blue-400 bg-blue-900/30 border-blue-800/50',
            ASK_WALL_RESISTANCE: 'text-amber-400 bg-amber-900/30 border-amber-800/50',
            NEUTRAL: 'text-gray-400 bg-gray-700/50 border-gray-600',
        };
        const sigClass = signalColors[d.signal] || signalColors.NEUTRAL;

        const barMax = Math.max(d.bid_liquidity_usd, d.ask_liquidity_usd) || 1;
        const bidPct = (d.bid_liquidity_usd / barMax * 100).toFixed(0);
        const askPct = (d.ask_liquidity_usd / barMax * 100).toFixed(0);

        content.innerHTML = `
            <div class="mb-3 text-sm text-gray-400">${_escapeHtml(data.question)}</div>

            <div class="inline-flex items-center px-3 py-1.5 rounded border text-sm font-bold mb-4 ${sigClass}">
                Signal: ${d.signal.replace(/_/g, ' ')}
            </div>

            <div class="grid grid-cols-2 gap-4 mb-4">
                <div class="bg-emerald-900/20 border border-emerald-800/40 rounded-lg p-3">
                    <div class="text-xs text-emerald-500 mb-1 font-mono">BID SIDE</div>
                    <div class="text-lg font-bold text-emerald-400">${formatter.format(d.bid_liquidity_usd)}</div>
                    <div class="text-xs text-gray-500 mt-1">${d.bid_levels} levels · ${d.bid_walls} wall(s)</div>
                    <div class="mt-2 h-2 bg-gray-700 rounded-full overflow-hidden">
                        <div class="h-full bg-emerald-500 rounded-full" style="width:${bidPct}%"></div>
                    </div>
                </div>
                <div class="bg-red-900/20 border border-red-800/40 rounded-lg p-3">
                    <div class="text-xs text-red-500 mb-1 font-mono">ASK SIDE</div>
                    <div class="text-lg font-bold text-red-400">${formatter.format(d.ask_liquidity_usd)}</div>
                    <div class="text-xs text-gray-500 mt-1">${d.ask_levels} levels · ${d.ask_walls} wall(s)</div>
                    <div class="mt-2 h-2 bg-gray-700 rounded-full overflow-hidden">
                        <div class="h-full bg-red-500 rounded-full" style="width:${askPct}%"></div>
                    </div>
                </div>
            </div>

            <div class="grid grid-cols-3 gap-3 text-center text-xs">
                <div class="bg-gray-900 rounded p-2 border border-gray-700">
                    <div class="text-gray-500">Spread</div>
                    <div class="font-mono text-white">${d.spread !== null ? d.spread : 'N/A'}</div>
                </div>
                <div class="bg-gray-900 rounded p-2 border border-gray-700">
                    <div class="text-gray-500">Imbalance</div>
                    <div class="font-mono ${d.imbalance_ratio > 0 ? 'text-emerald-400' : 'text-red-400'}">${d.imbalance_ratio > 0 ? '+' : ''}${d.imbalance_ratio}</div>
                </div>
                <div class="bg-gray-900 rounded p-2 border border-gray-700">
                    <div class="text-gray-500">Largest Order</div>
                    <div class="font-mono text-white">${formatter.format(Math.max(d.largest_bid_usd, d.largest_ask_usd))}</div>
                </div>
            </div>`;
    } catch (e) {
        content.innerHTML = `
            <div class="text-red-400 bg-red-900/20 p-4 rounded border border-red-800 text-sm">
                Could not fetch orderbook data. This market may not have a CLOB token ID.
            </div>`;
    }
}

async function unmaskWallet(address) {
    const btn = document.getElementById(`btn-${address}`);
    const realDiv = document.getElementById(`real-${address}`);

    btn.disabled = true;
    btn.innerHTML = '<span class="animate-pulse">Scanning...</span>';
    btn.classList.add("opacity-50", "cursor-not-allowed");

    try {
        const res = await _apiFetch(`/wallets/${address}/unmask/full`);
        const data = await res.json();

        realDiv.classList.remove("hidden");

        if (data.owner_chain && data.owner_chain.length > 1) {
            const chain = data.owner_chain.map((a, i) => {
                const prefix = i === 0 ? 'Proxy' : i === data.owner_chain.length - 1 ? 'EOA' : `Layer ${i}`;
                const color = i === data.owner_chain.length - 1 ? 'text-polysint' : 'text-gray-500';
                return `<span class="${color}">${prefix}: ${a.substring(0, 8)}…${a.substring(a.length - 6)}</span>`;
            }).join(' <span class="text-gray-600">→</span> ');
            realDiv.innerHTML = chain;
        } else {
            realDiv.innerHTML = `EOA: <span class="text-polysint">${data.owner || 'Unknown'}</span>`;
        }

        if (data.type) {
            const typeDiv = document.getElementById(`type-${address}`);
            if (typeDiv) {
                typeDiv.classList.remove("hidden");
                typeDiv.textContent = data.type;
            }
        }

        if (data.threshold && data.threshold > 1) {
            const thrDiv = document.getElementById(`thresh-${address}`);
            if (thrDiv) {
                thrDiv.classList.remove("hidden");
                thrDiv.textContent = `${data.threshold}-of-N multi-sig`;
            }
        }

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

async function profileEntity(address, label) {
    const modal = document.getElementById('aiModal');
    const content = document.getElementById('aiModalContent');
    const modalTitle = document.getElementById('aiModalTitle');

    modal.classList.remove('hidden');
    modalTitle.innerHTML = `🧠 Entity Profile — ${_escapeHtml(label)}`;

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
        const res = await _apiFetch(`/wallets/${address}/profile`);
        if (!res.ok) throw new Error("Profiling Failed");
        const data = await res.json();
        const formatted = _renderMarkdown(data.profile);

        content.innerHTML = `
            <div class="mb-4 p-3 bg-gray-900 rounded border border-gray-700 font-mono text-xs text-gray-400 space-y-1">
                <div><span class="text-gray-600">Proxy:</span> ${address}</div>
                <div><span class="text-gray-600">EOA:</span> <span class="text-polysint">${_escapeHtml(data.real_owner)}</span></div>
            </div>
            <div class="p-3 border-l-4 border-blue-500 bg-gray-900/60 rounded-r leading-relaxed">${formatted}</div>`;
    } catch (e) {
        content.innerHTML = `<div class="text-red-400 bg-red-900/20 p-4 rounded border border-red-800 text-sm">Could not generate entity profile.</div>`;
    }
}

function toggleEntityDetail(address) {
    const detail = document.getElementById(`detail-${address}`);
    if (!detail) return;
    const isOpen = detail.classList.contains('open');
    detail.classList.toggle('open');
    if (!isOpen) {
        loadEntityDetail(address, detail);
    }
}

async function loadEntityDetail(address, container) {
    const tabs = `
        <div class="flex gap-3 border-b border-gray-700 mb-3">
            <button class="tab-btn active text-xs pb-2 px-1 text-gray-400 hover:text-white transition-colors" onclick="loadEntityTab('${address}', 'trades', this)">Trades</button>
            <button class="tab-btn text-xs pb-2 px-1 text-gray-400 hover:text-white transition-colors" onclick="loadEntityTab('${address}', 'alerts', this)">Alerts</button>
            <button class="tab-btn text-xs pb-2 px-1 text-gray-400 hover:text-white transition-colors" onclick="loadEntityTab('${address}', 'linked', this)">Linked</button>
        </div>
        <div id="entity-tab-content-${address}" class="text-xs text-gray-400">
            <div class="flex items-center justify-center py-4 text-gray-600">Select a tab above</div>
        </div>`;
    container.innerHTML = tabs;
}

async function loadEntityTab(address, tab, btn) {
    const tabContent = document.getElementById(`entity-tab-content-${address}`);
    if (!tabContent) return;

    btn.closest('.flex').querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');

    tabContent.innerHTML = '<div class="flex items-center justify-center py-4 text-gray-600 animate-pulse">Loading...</div>';

    try {
        if (tab === 'trades') {
            const res = await _apiFetch(`/wallets/${address}/trades?limit=20`);
            if (!res.ok) throw new Error('Failed');
            const trades = await res.json();
            if (trades.length === 0) {
                tabContent.innerHTML = '<div class="text-gray-600 py-2">No recorded trades yet.</div>';
                return;
            }
            tabContent.innerHTML = trades.map(t => {
                const side = t.side || '?';
                const sideColor = side === 'BUY' ? 'text-emerald-400' : 'text-red-400';
                const size = t.size ? `$${Number(t.size).toLocaleString()}` : '';
                return `<div class="flex items-center gap-2 py-1 border-b border-gray-800">
                    <span class="${sideColor} font-mono font-bold w-10">${side}</span>
                    <span class="flex-1 truncate">${_escapeHtml(t.market_title || 'Unknown')}</span>
                    <span class="text-gray-500 font-mono">${size}</span>
                    <span class="text-gray-600 font-mono">${t.timestamp ? new Date(t.timestamp).toLocaleDateString() : ''}</span>
                </div>`;
            }).join('');
        } else if (tab === 'alerts') {
            const res = await _apiFetch(`/wallets/${address}/alerts?limit=20`);
            if (!res.ok) throw new Error('Failed');
            const alerts = await res.json();
            if (alerts.length === 0) {
                tabContent.innerHTML = '<div class="text-gray-600 py-2">No alerts recorded.</div>';
                return;
            }
            tabContent.innerHTML = alerts.map(a => {
                const typeColors = {
                    SYBIL_CLUSTER: 'text-purple-400 bg-purple-900/30',
                    LEADING_TRADE: 'text-amber-400 bg-amber-900/30',
                };
                const cls = typeColors[a.alert_type] || 'text-gray-400 bg-gray-700';
                return `<div class="py-2 border-b border-gray-800">
                    <div class="flex items-center gap-2 mb-1">
                        <span class="px-1.5 py-0.5 rounded text-xs font-mono ${cls}">${_escapeHtml(a.alert_type || 'UNKNOWN')}</span>
                        <span class="text-gray-600 font-mono">${a.created_at || ''}</span>
                    </div>
                    <div class="text-gray-500 text-xs">${_escapeHtml((a.message || '').substring(0, 150))}${(a.message || '').length > 150 ? '...' : ''}</div>
                </div>`;
            }).join('');
        } else if (tab === 'linked') {
            const res = await _apiFetch(`/wallets/${address}/linked`);
            if (!res.ok) throw new Error('Failed');
            const data = await res.json();
            if (!data.linked || data.linked.length <= 1) {
                tabContent.innerHTML = '<div class="text-gray-600 py-2">No linked wallets found.</div>';
                return;
            }
            tabContent.innerHTML = `<div class="text-gray-500 mb-2">EOA: <span class="text-polysint font-mono">${data.eoa || 'Unknown'}</span></div>` +
                data.linked.map(l => `<div class="flex items-center gap-2 py-1 border-b border-gray-800">
                    <span class="text-gray-500 font-mono">${l.proxy_wallet.substring(0, 10)}…${l.proxy_wallet.substring(l.proxy_wallet.length - 6)}</span>
                    ${l.proxy_wallet === address ? '<span class="text-xs text-polysint">(this wallet)</span>' : '<span class="text-xs text-amber-400">linked</span>'}
                </div>`).join('');
        }
    } catch (e) {
        tabContent.innerHTML = '<div class="text-red-400 py-2">Failed to load data.</div>';
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
        const res = await _apiFetch('/watchlist', {
            method: 'POST',
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

async function loadWatchlist() {
    const table = document.getElementById('watchlistTable');
    try {
        const res = await _apiFetch('/watchlist');
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

            const row = document.createElement('tr');
            row.className = "hover:bg-gray-700/30 transition-colors border-b border-gray-700/50";
            row.innerHTML = `
                <td class="px-4 py-3">
                    <div class="flex items-center justify-between">
                        <div>
                            <div class="font-semibold text-gray-200 text-sm cursor-pointer hover:text-polysint transition-colors" onclick="toggleEntityDetail('${w.address}')">
                                ${_escapeHtml(w.label)} <span class="text-gray-600 text-xs ml-1">▸</span>
                            </div>
                            <div class="text-xs font-mono text-gray-500 mt-0.5">${shortAddr}</div>
                            <div class="text-xs font-mono text-polysint mt-0.5 hidden" id="real-${w.address}"></div>
                            <div class="text-xs font-mono text-amber-400 mt-0.5 hidden" id="type-${w.address}"></div>
                            <div class="text-xs font-mono text-purple-400 mt-0.5 hidden" id="thresh-${w.address}"></div>
                        </div>
                        <div class="flex items-center gap-1 flex-wrap">
                            <button onclick="unmaskWallet('${w.address}')" id="btn-${w.address}"
                                class="bg-gray-800 border border-gray-600 text-gray-300 hover:bg-gray-700 px-2 py-1 rounded text-xs transition-all">
                                Unmask
                            </button>
                            <button onclick="profileEntity('${w.address}', '${_escapeHtml(w.label)}')"
                                class="bg-blue-900/40 text-blue-400 border border-blue-800 hover:bg-blue-800 hover:text-white px-2 py-1 rounded text-xs transition-all">
                                Profile
                            </button>
                            <button onclick="deleteTarget('${w.address}')" title="Stop Tracking"
                                class="bg-red-900/30 text-red-400 border border-red-800 hover:bg-red-800 hover:text-white px-2 py-1 rounded text-xs transition-all">
                                ✕
                            </button>
                        </div>
                    </div>
                    <div class="entity-detail mt-2 bg-gray-900/50 rounded-lg p-3" id="detail-${w.address}"></div>
                </td>`;
            table.appendChild(row);
        });
    } catch (e) {
        table.innerHTML = `<tr><td class="text-center py-8 text-red-400 text-sm">Failed to load watchlist.</td></tr>`;
    }
}

async function deleteTarget(address) {
    if (!confirm("Stop tracking this entity?")) return;
    try {
        const res = await _apiFetch(`/watchlist/${address}`, { method: 'DELETE' });
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

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeModal();
});
