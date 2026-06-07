/* Sports Arbitrage Detector — dashboard */

// ── DOM refs ─────────────────────────────────────────────────────────────────
const grid        = document.getElementById('opp-grid');
const emptyState  = document.getElementById('empty-state');
const oppCount    = document.getElementById('opp-count');
const bestMargin  = document.getElementById('best-margin');
const lastUpdate  = document.getElementById('last-update');
const statusDot   = document.getElementById('status-dot');
const statusText  = document.getElementById('status-text');
const capitalInput   = document.getElementById('capital-input');
const bookChips      = document.getElementById('book-chips');
const btnForce       = document.getElementById('btn-force-refresh');
const refreshHint    = document.getElementById('refresh-hint');

// ── State ─────────────────────────────────────────────────────────────────────
const cards = new Map();   // event_id -> card element
const opps  = new Map();   // event_id -> opportunity data (latest from server)
let currentCapital = null; // null = use server's total_stake
let capitalDebounce = null;
let ws = null;

// ── Helpers ───────────────────────────────────────────────────────────────────
function setStatus(state) {
  statusDot.className = 'status-dot ' + state;
  statusText.textContent =
    state === 'connected' ? 'Conectado en vivo' :
    state === 'error'     ? 'Sin conexión — reconectando…' :
                            'Conectando…';
}

function fmtTime(iso) {
  return new Date(iso).toLocaleTimeString('es', {
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
}

function fmtMoney(n) {
  return n.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

function effectiveCapital(opp) {
  return currentCapital || opp.total_stake;
}

// ── Capital live recalculation ────────────────────────────────────────────────
capitalInput.addEventListener('input', () => {
  const val = parseFloat(capitalInput.value);
  currentCapital = val > 0 ? val : null;
  // Re-render all cards instantly (client-side math, no server roundtrip)
  for (const [id, opp] of opps.entries()) {
    const existing = cards.get(id);
    if (existing) {
      const updated = renderCard(opp, false);
      grid.replaceChild(updated, existing);
      cards.set(id, updated);
    }
  }
  updateSummary();
  // Notify server (debounced, so it can filter future scans correctly)
  clearTimeout(capitalDebounce);
  capitalDebounce = setTimeout(sendPrefs, 400);
});

// ── Bookmaker chips ───────────────────────────────────────────────────────────
async function loadBookmakers() {
  try {
    const res = await fetch('/api/bookmakers');
    const books = await res.json();
    renderBookChips(books);
  } catch (_) {
    bookChips.innerHTML = '<span class="book-chips__loading">No se pudieron cargar las casas.</span>';
  }
}

function renderBookChips(books) {
  if (!books.length) {
    bookChips.innerHTML = '<span class="book-chips__loading">Sin datos de casas aún — espera el primer scan.</span>';
    return;
  }
  bookChips.innerHTML = '';
  books.forEach(book => {
    const label = document.createElement('label');
    label.className = 'book-chip active';
    label.title = book;

    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.value = book;
    cb.checked = true;
    cb.setAttribute('aria-label', book);
    cb.addEventListener('change', () => {
      label.classList.toggle('active', cb.checked);
      sendPrefs();
    });

    const span = document.createElement('span');
    span.textContent = book;

    label.appendChild(cb);
    label.appendChild(span);
    bookChips.appendChild(label);
  });
}

document.getElementById('select-all-books').addEventListener('click', () => {
  bookChips.querySelectorAll('input[type=checkbox]').forEach(cb => {
    cb.checked = true;
    cb.closest('.book-chip').classList.add('active');
  });
  sendPrefs();
});

document.getElementById('select-none-books').addEventListener('click', () => {
  bookChips.querySelectorAll('input[type=checkbox]').forEach(cb => {
    cb.checked = false;
    cb.closest('.book-chip').classList.remove('active');
  });
  sendPrefs();
});

// ── Send preferences to server ────────────────────────────────────────────────
function sendPrefs() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  const selectedBooks = [...bookChips.querySelectorAll('input:checked')].map(cb => cb.value);
  ws.send(JSON.stringify({
    type: 'prefs',
    capital: currentCapital,
    bookmakers: selectedBooks,
  }));
}

// ── Card rendering ────────────────────────────────────────────────────────────
function renderCard(opp, isNew) {
  const capital = effectiveCapital(opp);
  const profit  = opp.profit_margin_pct / 100 * capital;
  const guaranteed = capital * (1 + opp.profit_margin_pct / 100);

  const stepsHtml = opp.bets.map((b, i) => {
    const stake  = b.stake_pct / 100 * capital;
    const ret    = stake * b.price;
    return `
      <div class="bet-step">
        <div class="bet-step__num">Paso ${i + 1}</div>
        <div class="bet-step__body">
          <div class="bet-step__book">Ve a <strong>${b.bookmaker}</strong></div>
          <div class="bet-step__row">
            <span>Apuesta: <strong>${b.outcome}</strong></span>
            <span class="bet-step__price">@ ${b.price.toFixed(2)}</span>
          </div>
          <div class="bet-step__row">
            <span>Monto: <strong>$${fmtMoney(stake)}</strong>
              <em class="bet-step__pct">(${b.stake_pct.toFixed(1)}%)</em></span>
            <span class="bet-step__return">→ $${fmtMoney(ret)}</span>
          </div>
        </div>
      </div>`;
  }).join('');

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
        <div class="card__profit">+$${fmtMoney(profit)} de $${fmtMoney(capital)}</div>
      </div>
    </div>
    <div class="bets">${stepsHtml}</div>
    <div class="card__guaranteed">
      <span>✓ Retorno mínimo garantizado:</span>
      <strong>$${fmtMoney(guaranteed)}</strong>
    </div>
    <footer class="card__footer">Detectado: ${fmtTime(opp.detected_at)}</footer>`;
  return card;
}

// ── Grid management ───────────────────────────────────────────────────────────
function handleRefresh(opportunities) {
  // Remove cards no longer present
  const newIds = new Set(opportunities.map(o => o.event_id));
  for (const [id, card] of cards) {
    if (!newIds.has(id)) {
      if (card.parentNode === grid) grid.removeChild(card);
      cards.delete(id);
      opps.delete(id);
    }
  }
  // Upsert each opportunity
  opportunities.forEach(opp => {
    opps.set(opp.event_id, opp);
    const existing = cards.get(opp.event_id);
    const isNew    = !existing;
    const card     = renderCard(opp, isNew);
    if (existing) {
      grid.replaceChild(card, existing);
    } else {
      if (emptyState.parentNode === grid) grid.removeChild(emptyState);
      grid.prepend(card);
    }
    cards.set(opp.event_id, card);
  });

  if (cards.size === 0 && emptyState.parentNode !== grid) grid.appendChild(emptyState);
  lastUpdate.textContent = fmtTime(new Date().toISOString());
  updateSummary();
}

function updateSummary() {
  oppCount.textContent = cards.size;
  if (cards.size === 0) { bestMargin.textContent = '—'; return; }
  const margins = [...opps.values()].map(o => o.profit_margin_pct);
  bestMargin.textContent = Math.max(...margins).toFixed(2) + '%';
}

// ── Initial REST load (fallback before WS connects) ───────────────────────────
async function loadInitial() {
  try {
    const res  = await fetch('/api/opportunities');
    const data = await res.json();
    if (data.length) handleRefresh(data);
  } catch (_) { /* WS will handle it */ }
  if (cards.size === 0 && emptyState.parentNode !== grid) grid.appendChild(emptyState);
}

// ── WebSocket ─────────────────────────────────────────────────────────────────
function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onopen = () => {
    setStatus('connected');
    // Send current prefs so server applies them on first refresh
    sendPrefs();
  };
  ws.onclose = () => { setStatus('error'); setTimeout(connectWS, 3000); };
  ws.onerror = () => setStatus('error');
  ws.onmessage = ({ data }) => {
    try {
      const msg = JSON.parse(data);
      if (msg.type === 'refresh') handleRefresh(msg.opportunities);
    } catch (_) {}
  };
}

// ── Force refresh button ──────────────────────────────────────────────────────
let cooldownTimer = null;

function setRefreshState(state, extra) {
  const icon  = btnForce.querySelector('.btn-refresh__icon');
  const label = btnForce.querySelector('.btn-refresh__label');
  btnForce.disabled = state !== 'idle';

  if (state === 'idle') {
    btnForce.className = 'btn-refresh';
    icon.textContent  = '🔄';
    label.textContent = 'Actualizar ahora';
    refreshHint.textContent = 'Salta la caché y consulta el API en este momento.';
  } else if (state === 'loading') {
    btnForce.className = 'btn-refresh btn-refresh--loading';
    icon.textContent  = '⏳';
    label.textContent = 'Consultando API…';
    refreshHint.textContent = '';
  } else if (state === 'success') {
    btnForce.className = 'btn-refresh btn-refresh--success';
    icon.textContent  = '✓';
    label.textContent = `Actualizado — ${extra} oportunidad${extra !== 1 ? 'es' : ''}`;
    refreshHint.textContent = '';
    setTimeout(() => setRefreshState('idle'), 4000);
  } else if (state === 'cooldown') {
    btnForce.className = 'btn-refresh btn-refresh--cooldown';
    let secs = extra;
    icon.textContent  = '⏱';
    label.textContent = `Espera ${secs}s`;
    refreshHint.textContent = 'Demasiadas solicitudes — aguardá un momento.';
    clearInterval(cooldownTimer);
    cooldownTimer = setInterval(() => {
      secs -= 1;
      if (secs <= 0) {
        clearInterval(cooldownTimer);
        setRefreshState('idle');
      } else {
        label.textContent = `Espera ${secs}s`;
      }
    }, 1000);
  } else if (state === 'error') {
    btnForce.className = 'btn-refresh btn-refresh--error';
    icon.textContent  = '✗';
    label.textContent = 'Error — intentá de nuevo';
    refreshHint.textContent = extra || '';
    setTimeout(() => setRefreshState('idle'), 4000);
  }
}

btnForce.addEventListener('click', async () => {
  setRefreshState('loading');
  try {
    const res  = await fetch('/api/scan/force', { method: 'POST' });
    const data = await res.json();
    if (res.status === 429) {
      setRefreshState('cooldown', data.cooldown || 30);
    } else if (data.ok) {
      setRefreshState('success', data.opportunities);
    } else {
      setRefreshState('error', data.error);
    }
  } catch (_) {
    setRefreshState('error', 'Sin conexión con el servidor');
  }
});

// ── Boot ──────────────────────────────────────────────────────────────────────
loadInitial();
loadBookmakers();
connectWS();
