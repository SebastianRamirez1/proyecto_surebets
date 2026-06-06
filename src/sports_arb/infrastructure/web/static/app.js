/* Sports Arbitrage Detector — dashboard */

const grid      = document.getElementById('opp-grid');
const emptyState = document.getElementById('empty-state');
const oppCount  = document.getElementById('opp-count');
const bestMargin = document.getElementById('best-margin');
const lastUpdate = document.getElementById('last-update');
const statusDot  = document.getElementById('status-dot');
const statusText = document.getElementById('status-text');

const cards = new Map(); // event_id -> card element

function setStatus(state) {
  statusDot.className = 'status-dot ' + state;
  statusText.textContent =
    state === 'connected' ? 'Conectado en vivo' :
    state === 'error'     ? 'Sin conexión' :
                            'Conectando…';
}

function fmtTime(iso) {
  return new Date(iso).toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function renderCard(opp, isNew) {
  const betsHtml = opp.bets.map(b => `
    <div class="bet">
      <span class="bet__outcome">${b.outcome}</span>
      <span class="bet__price">@${b.price.toFixed(2)}</span>
      <span class="bet__book">${b.bookmaker}</span>
      <span class="bet__stake">${b.stake.toFixed(0)} (${b.stake_pct.toFixed(1)}%)</span>
    </div>`).join('');

  const card = document.createElement('article');
  card.className = 'card' + (isNew ? ' new' : '');
  card.setAttribute('role', 'listitem');
  card.setAttribute('aria-label', `Arbitraje: ${opp.label}, margen ${opp.profit_margin_pct}%`);
  card.innerHTML = `
    <header class="card__header">
      <h2 class="card__title">${opp.label}</h2>
      <span class="card__sport">${opp.sport}</span>
    </header>
    <div class="card__margin">
      <span class="card__margin-label">Margen garantizado</span>
      <div>
        <span class="card__margin-value">${opp.profit_margin_pct.toFixed(2)}%</span>
        <div class="card__profit">+${opp.profit_amount.toFixed(2)} sobre ${opp.total_stake.toFixed(0)}</div>
      </div>
    </div>
    <div class="bets">${betsHtml}</div>
    <footer class="card__footer">Detectado: ${fmtTime(opp.detected_at)}</footer>`;
  return card;
}

function updateSummary() {
  oppCount.textContent = cards.size;
  if (cards.size === 0) {
    bestMargin.textContent = '—';
    return;
  }
  const best = Math.max(...[...cards.values()].map(c =>
    parseFloat(c.querySelector('.card__margin-value').textContent)));
  bestMargin.textContent = best.toFixed(2) + '%';
}

function upsertCard(opp) {
  const existing = cards.get(opp.event_id);
  const isNew = !existing;
  const card = renderCard(opp, isNew);

  if (existing) {
    grid.replaceChild(card, existing);
  } else {
    if (emptyState.parentNode === grid) grid.removeChild(emptyState);
    grid.prepend(card);
  }
  cards.set(opp.event_id, card);
  lastUpdate.textContent = fmtTime(new Date().toISOString());
  updateSummary();
}

/* Load existing opportunities on page load */
async function loadInitial() {
  try {
    const res = await fetch('/api/opportunities');
    const opps = await res.json();
    opps.forEach(o => upsertCard(o));
    if (cards.size === 0) grid.appendChild(emptyState);
  } catch (_) {
    grid.appendChild(emptyState);
  }
}

/* WebSocket for real-time updates */
function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onopen  = () => setStatus('connected');
  ws.onclose = () => { setStatus('error'); setTimeout(connectWS, 3000); };
  ws.onerror = () => setStatus('error');
  ws.onmessage = ({ data }) => {
    try { upsertCard(JSON.parse(data)); } catch (_) {}
  };
}

loadInitial().then(() => connectWS());
