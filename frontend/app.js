const API = "";  // same origin

// ── Utility ───────────────────────────────────────────────────────────────────

async function api(path, opts = {}) {
  const res = await fetch(API + path, opts);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

function toast(msg, type = "success") {
  const el = document.getElementById("toast");
  if (!el) return;
  el.textContent = msg;
  el.className = `show ${type}`;
  setTimeout(() => { el.className = ""; }, 3500);
}

function fmt(n, decimals = 2) {
  if (n == null) return "—";
  return Number(n).toFixed(decimals);
}

function fmtPct(n) {
  if (n == null) return "—";
  return (Number(n) * 100).toFixed(1) + "%";
}

function fmtMoney(n) {
  if (n == null) return "—";
  return "$" + Number(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function pnlClass(n) {
  return Number(n) >= 0 ? "pnl-pos" : "pnl-neg";
}

function signClass(score) {
  return score > 0.05 ? "bullish" : score < -0.05 ? "bearish" : "neutral";
}

function escHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function toggleDetail(btn) {
  const panel = btn.closest(".card").querySelector(".see-more-panel");
  const open = panel.classList.toggle("hidden") === false;
  btn.textContent = open ? "See less ▴" : "See more ▾";
}

function setActive(page) {
  document.querySelectorAll("nav a[data-page]").forEach(a => {
    a.classList.toggle("active", a.dataset.page === page);
  });
}

// ── Opportunities page ────────────────────────────────────────────────────────

let _allCards = [];  // cached card elements for filter

function filterCards() {
  const container = document.getElementById("cards");
  if (!container || !_allCards.length) return;
  const val = (document.getElementById("ticker-filter")?.value || "").toUpperCase();
  container.innerHTML = "";
  const visible = val ? _allCards.filter(el => el.dataset.ticker === val) : _allCards;
  if (!visible.length) {
    container.innerHTML = `<p class="empty">No data for ${val}. Run a scan first.</p>`;
    return;
  }
  visible.forEach(el => container.appendChild(el));
}

async function loadOpportunities() {
  const container = document.getElementById("cards");
  if (!container) return;
  setActive("opportunities");

  container.innerHTML = `<p class="empty">Loading...</p>`;
  try {
    const data = await api("/opportunities");
    if (!data.length) {
      container.innerHTML = `<p class="empty">No opportunities yet. Run a scan to populate.</p>`;
      return;
    }
    _allCards = data.map(opp => {
      const el = buildCard(opp);
      el.dataset.ticker = opp.ticker;
      return el;
    });
    filterCards();
  } catch (e) {
    container.innerHTML = `<p class="empty">Error: ${e.message}</p>`;
  }
}

function buildCard(opp) {
  const dir = opp.direction;
  const conf = opp.fused_confidence;
  const confPct = Math.round(conf * 100);

  const signalDefs = [
    { key: "polymarket", label: "StockTwits" },
    { key: "gdelt",      label: "GDELT News" },
    { key: "technical",  label: "Technical" },
  ];

  const signalBars = signalDefs.map(({ key, label }) => {
    const sig = opp.signals[key];
    const score = sig?.score ?? 0;
    const cls = signClass(score);
    const pct = Math.abs(score) * 50;  // max 50% of half-track
    const sign = score >= 0 ? "+" : "";
    return `
      <div class="signal-row">
        <span class="signal-label">${label}</span>
        <div class="bar-track">
          <div class="bar-center"></div>
          <div class="bar-fill ${cls}" style="width:${pct}%"></div>
        </div>
        <span class="signal-score">${sign}${fmt(score, 2)}</span>
      </div>`;
  }).join("");

  const detail = opp.signal_detail || {};
  const posts = detail.stocktwits?.posts || [];
  const headlines = detail.gdelt?.headlines || [];
  const tech = detail.technical || {};

  const detailHtml = `
    <div class="see-more-panel hidden">
      <div class="detail-section">
        <div class="detail-title">StockTwits posts (${posts.length})</div>
        ${posts.length
          ? posts.map(p => `<div class="detail-item">${p.sentiment ? `<span class="sent-tag ${p.sentiment.toLowerCase()}">${p.sentiment}</span> ` : ""}${escHtml(p.body)}</div>`).join("")
          : `<div class="detail-item muted">No posts fetched</div>`}
      </div>
      <div class="detail-section">
        <div class="detail-title">GDELT headlines (${headlines.length})</div>
        ${headlines.length
          ? headlines.map(h => `<div class="detail-item">— ${escHtml(h)}</div>`).join("")
          : `<div class="detail-item muted">No headlines fetched</div>`}
      </div>
      <div class="detail-section">
        <div class="detail-title">Technical</div>
        <div class="detail-item">Price ${tech.price ?? "—"} · MA20 ${tech.ma20 ?? "—"} · MA50 ${tech.ma50 ?? "—"}</div>
        <div class="detail-item">RSI ${tech.rsi ?? "—"} · MACD ${tech.macd_signal ?? "—"} · MA score ${tech.ma_score ?? "—"}</div>
      </div>
    </div>`;

  const card = document.createElement("div");
  card.className = "card";
  card.dataset.id = opp.id;
  card.innerHTML = `
    <div class="card-header">
      <span class="ticker">${opp.ticker}</span>
      <span class="direction-badge ${dir}">${dir}</span>
    </div>
    <div class="signals">${signalBars}</div>
    <div class="confidence">
      <span class="conf-label">Confidence</span>
      <span class="conf-value">${confPct}%</span>
      <div class="conf-track"><div class="conf-fill" style="width:${confPct}%"></div></div>
    </div>
    <p class="explanation">${opp.llm_explanation ?? ""}</p>
    <div class="card-footer">
      <span class="scanned">Scanned ${opp.scanned_at ? new Date(opp.scanned_at).toLocaleString() : "—"}</span>
      <button class="btn-see-more" onclick="toggleDetail(this)">See more ▾</button>
    </div>
    ${detailHtml}
    ${opp.traded
      ? `<button class="btn btn-trade" disabled>Traded</button>`
      : `<button class="btn btn-trade" onclick="executeTrade(${opp.id}, this)">Trade ${dir === "bullish" ? "▲" : "▼"} ${opp.ticker}</button>`
    }`;
  return card;
}

async function executeTrade(id, btn) {
  btn.disabled = true;
  btn.textContent = "Executing…";
  try {
    const trade = await api(`/trade/${id}`, { method: "POST" });
    toast(`Trade placed: ${trade.qty} × ${trade.ticker} @ $${fmt(trade.entry_price)}`, "success");
    btn.textContent = "Traded ✓";
  } catch (e) {
    toast(`Trade failed: ${e.message}`, "error");
    btn.disabled = false;
    btn.textContent = "Retry";
  }
}

const PHASE_PCT = { 0: 0, 1: 10, 2: 40, 3: 60, 4: 80, 5: 90 };

function updateProgress(status) {
  const box = document.getElementById("scan-progress");
  const label = document.getElementById("scan-phase-label");
  const counter = document.getElementById("scan-phase-counter");
  const bar = document.getElementById("scan-progress-bar");
  const liveTickers = document.getElementById("scan-live-tickers");
  if (!box) return;

  if (!status.running) {
    box.classList.add("hidden");
    bar.style.width = "0%";
    if (liveTickers) liveTickers.innerHTML = "";
    return;
  }

  box.classList.remove("hidden");
  label.textContent = status.phase_label || "Scanning…";
  counter.textContent = status.phase === 1
    ? `${Math.min(status.tickers_fetched, status.tickers_total)} / ${status.tickers_total} tickers`
    : status.opportunities > 0 ? `${status.opportunities} opportunities` : `Phase ${status.phase} / 5`;
  bar.style.width = (PHASE_PCT[status.phase] ?? 0) + "%";

  if (liveTickers && status.live_tickers?.length) {
    liveTickers.innerHTML = status.live_tickers.map(t => `<span class="live-tick">${t}</span>`).join("");
  }
}

async function triggerScan() {
  const btn = document.getElementById("scan-btn");
  if (btn) { btn.disabled = true; btn.textContent = "Scanning…"; }

  const selectedTicker = document.getElementById("ticker-filter")?.value;
  const scanPath = selectedTicker ? `/scan?ticker=${selectedTicker}` : "/scan";
  const scanPromise = api(scanPath).catch(e => { toast(`Scan error: ${e.message}`, "error"); });

  // Poll /scan/status every 1.5s while running
  const poll = setInterval(async () => {
    try {
      const status = await api("/scan/status");
      updateProgress(status);
      if (!status.running) {
        clearInterval(poll);
        updateProgress({ running: false });
        toast("Scan complete", "success");
        await loadOpportunities();
        if (btn) { btn.disabled = false; btn.textContent = "Scan Now"; }
      }
    } catch (_) { clearInterval(poll); }
  }, 1500);

  await scanPromise;
}

// ── Portfolio page ────────────────────────────────────────────────────────────

async function loadPortfolio() {
  const tbody = document.getElementById("positions-body");
  const equity = document.getElementById("equity");
  const cash = document.getElementById("cash");
  if (!tbody) return;
  setActive("portfolio");

  tbody.innerHTML = `<tr><td colspan="7" class="empty">Loading…</td></tr>`;
  try {
    const data = await api("/portfolio");
    if (equity) equity.textContent = fmtMoney(data.equity);
    if (cash) cash.textContent = fmtMoney(data.cash);

    if (!data.positions.length) {
      tbody.innerHTML = `<tr><td colspan="7" class="empty">No open positions.</td></tr>`;
      return;
    }
    tbody.innerHTML = data.positions.map(p => `
      <tr>
        <td><strong>${p.ticker}</strong></td>
        <td>${p.side}</td>
        <td>${fmt(p.qty, 4)}</td>
        <td>${fmtMoney(p.entry_price)}</td>
        <td>${fmtMoney(p.current_price)}</td>
        <td class="${pnlClass(p.unrealised_pnl)}">${fmtMoney(p.unrealised_pnl)}</td>
        <td class="${pnlClass(p.unrealised_pnl_pct)}">${fmt(p.unrealised_pnl_pct, 2)}%</td>
      </tr>`).join("");
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="7" class="empty">Error: ${e.message}</td></tr>`;
  }
}

// ── History page ──────────────────────────────────────────────────────────────

async function loadHistory() {
  const tbody = document.getElementById("history-body");
  if (!tbody) return;
  setActive("history");

  tbody.innerHTML = `<tr><td colspan="8" class="empty">Loading…</td></tr>`;
  try {
    const data = await api("/history");
    if (!data.length) {
      tbody.innerHTML = `<tr><td colspan="8" class="empty">No closed trades yet.</td></tr>`;
      return;
    }
    tbody.innerHTML = data.map(t => {
      const pnl = t.realised_pnl;
      return `
        <tr>
          <td><strong>${t.ticker}</strong></td>
          <td>${t.direction}</td>
          <td>${fmtMoney(t.entry_price)}</td>
          <td>${fmtMoney(t.exit_price)}</td>
          <td>${fmt(t.qty, 4)}</td>
          <td class="${pnlClass(pnl)}">${fmtMoney(pnl)}</td>
          <td>${fmt(t.signal_scores?.fused, 2) ?? "—"}</td>
          <td>${t.closed_at ? new Date(t.closed_at).toLocaleDateString() : "—"}</td>
        </tr>`;
    }).join("");
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="8" class="empty">Error: ${e.message}</td></tr>`;
  }
}
