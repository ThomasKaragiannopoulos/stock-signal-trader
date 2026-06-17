const API = "";  // same origin

// ── Utilities ─────────────────────────────────────────────────────────────────

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

function directionSymbol(direction) {
  return `<span class="direction-symbol ${direction}" title="${direction}">${tradeDirectionGlyph(direction)}</span>`;
}

function tradeDirectionGlyph(direction) {
  if (direction === "bullish") return "▲";
  if (direction === "bearish") return "▼";
  return "-";
}

function escHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function setActive(page) {
  document.querySelectorAll("nav a[data-page]").forEach(a => {
    a.classList.toggle("active", a.dataset.page === page);
  });
}

function fmtDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function fmtDateTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

// ── Charts ────────────────────────────────────────────────────────────────────

function buildLineChart(ctx, labels, data, color, yFmt) {
  return new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [{
        data,
        borderColor: color,
        backgroundColor: color.replace("rgb(", "rgba(").replace(")", ", 0.08)"),
        fill: true,
        tension: 0.3,
        pointRadius: data.length > 60 ? 0 : 3,
        pointHoverRadius: 5,
        borderWidth: 2,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => yFmt(ctx.raw) } },
      },
      scales: {
        x: { grid: { color: "rgba(80,130,200,0.08)" }, ticks: { color: "#4a6a8a", maxTicksLimit: 8, font: { family: "Inter, sans-serif", size: 10 } } },
        y: { grid: { color: "rgba(80,130,200,0.08)" }, ticks: { color: "#4a6a8a", callback: yFmt, font: { family: "Inter, sans-serif", size: 10 } } },
      },
    },
  });
}

// ── Overview ──────────────────────────────────────────────────────────────────

async function loadOverview() {
  setActive("overview");

  const [portResult, histResult, snapResult] = await Promise.allSettled([
    api("/portfolio"),
    api("/history"),
    api("/snapshots"),
  ]);

  const port   = portResult.status   === "fulfilled" ? portResult.value   : null;
  const trades = histResult.status   === "fulfilled" ? histResult.value   : [];
  const snaps  = snapResult.status   === "fulfilled" ? snapResult.value   : [];

  // Stats
  if (port) {
    document.getElementById("stat-equity").textContent = fmtMoney(port.equity);
    document.getElementById("stat-cash").textContent   = fmtMoney(port.cash);
    const openPnl = port.positions.reduce((s, p) => s + p.unrealised_pnl, 0);
    const el = document.getElementById("stat-open-pnl");
    el.textContent = fmtMoney(openPnl);
    el.className = "stat-value " + pnlClass(openPnl);
  }

  const winRateEl = document.getElementById("stat-win-rate");
  const tradesEl  = document.getElementById("stat-trades");
  if (trades.length) {
    const wins = trades.filter(t => (t.realised_pnl ?? 0) > 0).length;
    winRateEl.textContent = (wins / trades.length * 100).toFixed(0) + "%";
    tradesEl.textContent  = trades.length;
  } else {
    winRateEl.textContent = "—";
    tradesEl.textContent  = "0";
  }

  // Equity chart
  if (snaps.length >= 2) {
    buildLineChart(
      document.getElementById("equity-chart").getContext("2d"),
      snaps.map(s => fmtDate(s.recorded_at)),
      snaps.map(s => s.equity),
      "rgb(230, 230, 235)",
      v => "$" + Number(v).toLocaleString("en-US", { maximumFractionDigits: 0 }),
    );
  } else {
    document.getElementById("equity-chart").style.display = "none";
    document.getElementById("equity-empty").classList.remove("hidden");
  }

  // Open positions
  const posBody = document.getElementById("positions-body");
  if (port && port.positions.length) {
    posBody.innerHTML = port.positions.map(p => `
      <tr>
        <td><strong>${p.ticker}</strong></td>
        <td>${p.side}</td>
        <td>${fmtMoney(p.entry_price)}</td>
        <td>${fmtMoney(p.current_price)}</td>
        <td class="${pnlClass(p.unrealised_pnl)}">${fmtMoney(p.unrealised_pnl)}</td>
        <td class="${pnlClass(p.unrealised_pnl_pct)}">${fmt(p.unrealised_pnl_pct, 1)}%</td>
      </tr>`).join("");
  } else {
    posBody.innerHTML = `<tr><td colspan="6" class="empty">${port ? "No open positions." : "Could not load positions."}</td></tr>`;
  }

  // Recent trades (last 5)
  const recentBody = document.getElementById("recent-trades-body");
  const recent = trades.slice(0, 5);
  if (recent.length) {
    recentBody.innerHTML = recent.map(t => `
      <tr>
        <td><strong>${t.ticker}</strong></td>
        <td>${directionSymbol(t.direction)}</td>
        <td class="${pnlClass(t.realised_pnl)}">${fmtMoney(t.realised_pnl)}</td>
        <td>${fmtDate(t.closed_at)}</td>
        <td><a class="link-detail" href="/detail.html?id=${t.opportunity_id}">See more →</a></td>
      </tr>`).join("");
  } else {
    recentBody.innerHTML = `<tr><td colspan="5" class="empty">No closed trades yet.</td></tr>`;
  }
}

// ── Portfolio page ────────────────────────────────────────────────────────────

async function loadPortfolio() {
  setActive("portfolio");

  const [portResult, openResult] = await Promise.allSettled([
    api("/portfolio"),
    api("/trades/open"),
  ]);

  const port  = portResult.status === "fulfilled" ? portResult.value : null;
  const open  = openResult.status === "fulfilled" ? openResult.value : [];

  if (port) {
    document.getElementById("equity").textContent = fmtMoney(port.equity);
    document.getElementById("cash").textContent   = fmtMoney(port.cash);
  }

  const filledTickers = new Set((port?.positions ?? []).map(p => p.ticker));

  // Open positions (filled on Alpaca)
  const posBody = document.getElementById("positions-body");
  if (port && port.positions.length) {
    posBody.innerHTML = port.positions.map(p => `
      <tr>
        <td><strong>${p.ticker}</strong></td>
        <td>${p.side}</td>
        <td>${p.qty}</td>
        <td>${fmtMoney(p.entry_price)}</td>
        <td>${fmtMoney(p.current_price)}</td>
        <td class="${pnlClass(p.unrealised_pnl)}">${fmtMoney(p.unrealised_pnl)}</td>
        <td class="${pnlClass(p.unrealised_pnl_pct)}">${fmt(p.unrealised_pnl_pct, 1)}%</td>
        <td>${p.trade_id != null
          ? `<button class="btn-action btn-close" onclick="closePosition(${p.trade_id}, '${p.ticker}', this)">Close</button>`
          : "—"}</td>
      </tr>`).join("");
  } else {
    posBody.innerHTML = `<tr><td colspan="8" class="empty">${port ? "No open positions." : "Could not load positions."}</td></tr>`;
  }

  // Pending orders (submitted but not yet filled)
  const pending = open.filter(t => !filledTickers.has(t.ticker));
  const pendBody = document.getElementById("pending-body");
  if (pending.length) {
    pendBody.innerHTML = pending.map(t => `
      <tr>
        <td><strong>${t.ticker}</strong></td>
        <td>${directionSymbol(t.direction)}</td>
        <td>${t.qty}</td>
        <td>${fmtMoney(t.entry_price)}</td>
        <td>${fmtMoney(t.notional)}</td>
        <td>${fmtDateTime(t.executed_at)}</td>
        <td><button class="btn-action btn-cancel" onclick="cancelTrade(${t.id}, this)">Cancel</button></td>
      </tr>`).join("");
  } else {
    pendBody.innerHTML = `<tr><td colspan="7" class="empty">No pending orders.</td></tr>`;
  }
}

async function closePosition(tradeId, ticker, btn) {
  if (!confirm(`Close position in ${ticker}? This will market-sell immediately.`)) return;
  btn.disabled = true;
  btn.textContent = "Closing…";
  try {
    await api(`/trade/${tradeId}/close`, { method: "POST" });
    toast(`${ticker} position closed`, "success");
    loadPortfolio();
  } catch (e) {
    toast(`Close failed: ${e.message}`, "error");
    btn.disabled = false;
    btn.textContent = "Close";
  }
}

async function cancelTrade(tradeId, btn) {
  btn.disabled = true;
  btn.textContent = "Cancelling…";
  try {
    const t = await api(`/trade/${tradeId}`, { method: "DELETE" });
    toast(`Order cancelled: ${t.ticker}`, "success");
    loadPortfolio();
  } catch (e) {
    toast(`Cancel failed: ${e.message}`, "error");
    btn.disabled = false;
    btn.textContent = "Cancel";
  }
}

// ── Scan page ─────────────────────────────────────────────────────────────────

let _allScanCards = [];

async function loadScan() {
  setActive("scan");
  const container = document.getElementById("scan-cards");
  if (!container) return;
  container.innerHTML = `<p class="empty">Loading…</p>`;
  try {
    const data = await api("/opportunities");

    // Populate filter from live data
    const filter = document.getElementById("ticker-filter");
    if (filter && data.length) {
      const tickers = [...new Set(data.map(o => o.ticker))].sort();
      filter.innerHTML = `<option value="">All tickers</option>` +
        tickers.map(t => `<option>${t}</option>`).join("");
    }

    if (!data.length) {
      container.innerHTML = `<p class="empty">No opportunities yet. Run a scan to populate.</p>`;
      return;
    }
    _allScanCards = data.map(opp => {
      const el = buildScanCard(opp);
      el.dataset.ticker = opp.ticker;
      return el;
    });
    filterScanCards();
  } catch (e) {
    container.innerHTML = `<p class="empty">Error: ${escHtml(e.message)}</p>`;
  }
}

function buildScanCard(opp) {
  const dir     = opp.direction;
  const conf    = opp.fused_confidence;
  const confPct = Math.round(conf * 100);

  const signalDefs = [
    { key: "stocktwits", label: "StockTwits" },
    { key: "gdelt",      label: "GDELT" },
    { key: "technical",  label: "Technical" },
    { key: "nn",         label: "NN" },
  ];

  const signalBars = signalDefs.map(({ key, label }) => {
    const sig   = opp.signals[key];
    const score = sig?.score ?? 0;
    const cls   = signClass(score);
    const pct   = Math.abs(score) * 50;
    const sign  = score >= 0 ? "+" : "";
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

  const card = document.createElement("div");
  card.className = "card";
  card.dataset.id = opp.id;
  card.innerHTML = `
    <div class="card-header">
      <span class="ticker">${opp.ticker}</span>
      <span class="direction-badge ${dir}">${tradeDirectionGlyph(dir)}</span>
    </div>
    <div class="signals">${signalBars}</div>
    <div class="confidence">
      <span class="conf-label">Confidence</span>
      <span class="conf-value">${confPct}%</span>
      <div class="conf-track"><div class="conf-fill" style="width:${confPct}%"></div></div>
    </div>
    <p class="explanation">${escHtml(opp.llm_explanation ?? "")}</p>
    ${opp.judge_verdict ? `
    <div class="judge-block ${opp.judge_verdict}">
      <span class="judge-badge">${opp.judge_verdict === "trade" ? "✓ TRADE" : "✗ SKIP"}</span>
      <span class="judge-reason">${escHtml(opp.judge_reason ?? "")}</span>
    </div>` : ""}
    <div class="card-footer">
      <span class="scanned">${fmtDateTime(opp.scanned_at)}</span>
      <a class="btn-see-more" href="/detail.html?id=${opp.id}">See more →</a>
    </div>
    ${opp.traded
      ? `<button class="btn btn-trade" disabled>Traded ✓</button>`
      : `<button class="btn btn-trade" onclick="executeTrade(${opp.id}, this)">Trade ${tradeDirectionGlyph(dir)} ${opp.ticker}</button>`
    }`;
  return card;
}

function filterScanCards() {
  const container = document.getElementById("scan-cards");
  if (!container || !_allScanCards.length) return;
  const val = (document.getElementById("ticker-filter")?.value || "").toUpperCase();
  container.innerHTML = "";
  const visible = val ? _allScanCards.filter(el => el.dataset.ticker === val) : _allScanCards;
  if (!visible.length) {
    container.innerHTML = `<p class="empty">No data for ${val}.</p>`;
    return;
  }
  visible.forEach(el => container.appendChild(el));
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

const PHASE_PCT = { 0: 0, 1: 10, 2: 35, 3: 55, 4: 70, 5: 85, 6: 95 };

function updateProgress(status) {
  const box        = document.getElementById("scan-progress");
  const label      = document.getElementById("scan-phase-label");
  const counter    = document.getElementById("scan-phase-counter");
  const bar        = document.getElementById("scan-progress-bar");
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
    : status.opportunities > 0 ? `${status.opportunities} opportunities` : `Phase ${status.phase} / 6`;
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
  api(scanPath, { method: "POST" }).catch(e => toast(`Scan error: ${e.message}`, "error"));

  const poll = setInterval(async () => {
    try {
      const status = await api("/scan/status");
      updateProgress(status);
      if (!status.running) {
        clearInterval(poll);
        updateProgress({ running: false });
        toast("Scan complete", "success");
        await loadScan();
        if (btn) { btn.disabled = false; btn.textContent = "Scan Now"; }
      }
    } catch (_) { clearInterval(poll); }
  }, 1500);
}

// ── History page ──────────────────────────────────────────────────────────────

async function loadHistory() {
  setActive("history");
  const tbody = document.getElementById("history-body");
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="9" class="empty">Loading…</td></tr>`;

  try {
    const data = await api("/history");

    // Analytics
    if (data.length) {
      const wins     = data.filter(t => (t.realised_pnl ?? 0) > 0).length;
      const totalPnl = data.reduce((s, t) => s + (t.realised_pnl ?? 0), 0);
      const best     = data.reduce((m, t) => (t.realised_pnl ?? 0) > (m.realised_pnl ?? 0) ? t : m, data[0]);

      document.getElementById("h-total").textContent = data.length;
      document.getElementById("h-winrate").textContent = (wins / data.length * 100).toFixed(0) + "%";

      const totalEl = document.getElementById("h-total-pnl");
      totalEl.textContent = fmtMoney(totalPnl);
      totalEl.className   = "stat-value " + pnlClass(totalPnl);

      const avgEl = document.getElementById("h-avg-pnl");
      avgEl.textContent = fmtMoney(totalPnl / data.length);
      avgEl.className   = "stat-value " + pnlClass(totalPnl / data.length);

      const bestEl = document.getElementById("h-best");
      bestEl.textContent = `${fmtMoney(best.realised_pnl)} ${best.ticker}`;
      bestEl.className   = "stat-value pnl-pos";
    }

    // Cumulative PnL chart (data is newest-first → reverse for chronological order)
    const sorted = [...data].reverse();
    if (sorted.length >= 2) {
      let cum = 0;
      const cumData = sorted.map(t => { cum += (t.realised_pnl ?? 0); return +cum.toFixed(2); });
      buildLineChart(
        document.getElementById("pnl-chart").getContext("2d"),
        sorted.map(t => fmtDate(t.closed_at)),
        cumData,
        "rgb(0, 232, 122)",
        v => "$" + Number(v).toLocaleString("en-US", { maximumFractionDigits: 0 }),
      );
    }

    if (!data.length) {
      tbody.innerHTML = `<tr><td colspan="9" class="empty">No closed trades yet.</td></tr>`;
      return;
    }

    tbody.innerHTML = data.map(t => `
      <tr>
        <td><strong>${t.ticker}</strong></td>
        <td>${directionSymbol(t.direction)}</td>
        <td>${fmtMoney(t.entry_price)}</td>
        <td>${fmtMoney(t.exit_price)}</td>
        <td>${fmt(t.qty, 4)}</td>
        <td class="${pnlClass(t.realised_pnl)}">${fmtMoney(t.realised_pnl)}</td>
        <td>${fmt(t.signal_scores?.fused, 2)}</td>
        <td>${fmtDate(t.closed_at)}</td>
        <td><a class="link-detail" href="/detail.html?id=${t.opportunity_id}">See more →</a></td>
      </tr>`).join("");
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="9" class="empty">Error: ${escHtml(e.message)}</td></tr>`;
  }
}

// ── Settings page ─────────────────────────────────────────────────────────────

async function loadSettings() {
  setActive("settings");
  const tbody = document.getElementById("watchlist-body");
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="3" class="empty">Loading…</td></tr>`;
  try {
    const data = await api("/watchlist");
    const countEl = document.getElementById("watchlist-count");
    if (countEl) countEl.textContent = `(${data.length})`;

    if (!data.length) {
      tbody.innerHTML = `<tr><td colspan="3" class="empty">Watchlist is empty.</td></tr>`;
      return;
    }
    tbody.innerHTML = data.map(({ ticker, company }) => `
      <tr>
        <td><strong>${ticker}</strong></td>
        <td>${escHtml(company)}</td>
        <td><button class="btn-remove" onclick="removeTicker('${ticker}')">Remove</button></td>
      </tr>`).join("");
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="3" class="empty">Error: ${escHtml(e.message)}</td></tr>`;
  }
}

async function addTicker() {
  const tickerEl  = document.getElementById("new-ticker");
  const companyEl = document.getElementById("new-company");
  const ticker    = tickerEl.value.trim().toUpperCase();
  const company   = companyEl.value.trim();
  if (!ticker || !company) { toast("Enter both ticker and company name", "error"); return; }
  try {
    await api("/watchlist", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticker, company }),
    });
    toast(`${ticker} added to watchlist`, "success");
    tickerEl.value  = "";
    companyEl.value = "";
    loadSettings();
  } catch (e) {
    toast(`Failed: ${e.message}`, "error");
  }
}

async function removeTicker(ticker) {
  try {
    await api(`/watchlist/${ticker}`, { method: "DELETE" });
    toast(`${ticker} removed`, "success");
    loadSettings();
  } catch (e) {
    toast(`Failed: ${e.message}`, "error");
  }
}

// ── Detail page ───────────────────────────────────────────────────────────────

async function loadDetail() {
  const id        = new URLSearchParams(location.search).get("id");
  const container = document.getElementById("detail-content");
  if (!id || !container) return;

  container.innerHTML = `<p class="empty">Loading…</p>`;
  try {
    const opp = await api(`/opportunities/${id}`);
    container.innerHTML = buildDetailHtml(opp);
  } catch (e) {
    container.innerHTML = `<p class="empty">Error: ${escHtml(e.message)}</p>`;
  }
}

function buildDetailHtml(opp) {
  const dir   = opp.direction;
  const conf  = Math.round((opp.fused_confidence ?? 0) * 100);
  const detail = opp.signal_detail || {};
  const trade  = opp.trade;

  const signalDefs = [
    { key: "stocktwits", label: "StockTwits" },
    { key: "gdelt",      label: "GDELT News" },
    { key: "technical",  label: "Technical" },
    { key: "nn",         label: "NN Model" },
  ];

  const signalPanels = signalDefs.map(({ key, label }) => {
    const sig   = opp.signals[key] || { score: 0, confidence: 0 };
    const score = sig.score ?? 0;
    const sconf = Math.round((sig.confidence ?? 0) * 100);
    const cls   = signClass(score);
    const pct   = Math.abs(score) * 50;
    const sign  = score >= 0 ? "+" : "";

    let rawHtml = "";
    if (key === "stocktwits") {
      const posts = detail.stocktwits?.posts || [];
      rawHtml = posts.length
        ? posts.slice(0, 8).map(p =>
            `<div class="detail-item">${p.sentiment ? `<span class="sent-tag ${p.sentiment.toLowerCase()}">${p.sentiment}</span> ` : ""}${escHtml(p.body)}</div>`
          ).join("") + (posts.length > 8 ? `<div class="detail-item muted">+${posts.length - 8} more posts</div>` : "")
        : `<div class="detail-item muted">No posts fetched</div>`;
    } else if (key === "gdelt") {
      const headlines = detail.gdelt?.headlines || [];
      rawHtml = headlines.length
        ? headlines.slice(0, 8).map(h => `<div class="detail-item">— ${escHtml(h)}</div>`).join("")
          + (headlines.length > 8 ? `<div class="detail-item muted">+${headlines.length - 8} more</div>` : "")
        : `<div class="detail-item muted">No headlines fetched</div>`;
    } else if (key === "technical") {
      const tech = detail.technical || {};
      rawHtml = `
        <div class="detail-item">Price <strong>${tech.price ?? "—"}</strong> · MA20 ${tech.ma20 ?? "—"} · MA50 ${tech.ma50 ?? "—"}</div>
        <div class="detail-item">RSI <strong>${tech.rsi ?? "—"}</strong> · MACD signal ${tech.macd_signal ?? "—"} · MA score ${tech.ma_score ?? "—"}</div>`;
    } else if (key === "nn") {
      const nn = detail.nn || {};
      rawHtml = nn.status === "active"
        ? `<div class="detail-item">Trained on <strong>${nn.n_trades}</strong> trades · P(profit) = <strong>${((nn.p_profit ?? 0) * 100).toFixed(1)}%</strong></div>`
        : `<div class="detail-item muted">No model yet — ${nn.n_trades !== undefined ? `needs ${10 - nn.n_trades} more trades` : "waiting for closed trades"}</div>`;
    }

    return `
      <div class="detail-signal-panel">
        <div class="detail-signal-header">
          <span class="detail-signal-name">${label}</span>
          <div class="detail-signal-score-row">
            <div class="bar-track">
              <div class="bar-center"></div>
              <div class="bar-fill ${cls}" style="width:${pct}%"></div>
            </div>
            <span class="signal-score ${cls}">${sign}${fmt(score, 2)}</span>
            <span class="detail-conf-badge">${sconf}% conf</span>
          </div>
        </div>
        <div class="detail-signal-raw">${rawHtml}</div>
      </div>`;
  }).join("");

  const tradeBlock = trade ? `
    <div class="detail-trade-block ${trade.status}">
      <div class="detail-trade-header">
        <span class="detail-trade-title">Trade — ${trade.status.toUpperCase()}</span>
        ${trade.realised_pnl != null
          ? `<span class="detail-trade-pnl ${pnlClass(trade.realised_pnl)}">${fmtMoney(trade.realised_pnl)}</span>`
          : ""}
      </div>
      <div class="detail-trade-grid">
        <div><span class="detail-meta-label">Entry</span><span>${fmtMoney(trade.entry_price)}</span></div>
        <div><span class="detail-meta-label">Exit</span><span>${fmtMoney(trade.exit_price)}</span></div>
        <div><span class="detail-meta-label">Qty</span><span>${fmt(trade.qty, 4)}</span></div>
        <div><span class="detail-meta-label">Notional</span><span>${fmtMoney(trade.notional)}</span></div>
        <div><span class="detail-meta-label">Stop</span><span>${fmtMoney(trade.stop_price)}</span></div>
        <div><span class="detail-meta-label">Target</span><span>${fmtMoney(trade.target_price)}</span></div>
        <div class="span-2"><span class="detail-meta-label">Alpaca Order</span><span class="mono">${trade.alpaca_order_id ?? "—"}</span></div>
        <div><span class="detail-meta-label">Executed</span><span>${fmtDateTime(trade.executed_at)}</span></div>
        ${trade.closed_at ? `<div><span class="detail-meta-label">Closed</span><span>${fmtDateTime(trade.closed_at)}</span></div>` : ""}
      </div>
    </div>` : "";

  const execBtn = (!opp.traded && opp.judge_verdict === "trade" && dir !== "neutral")
    ? `<button class="btn btn-trade detail-exec-btn" onclick="executeTradeFromDetail(${opp.id}, this)">
         Trade ${tradeDirectionGlyph(dir)} ${opp.ticker}
       </button>`
    : "";

  const fusedSign = (opp.fused_score ?? 0) >= 0 ? "+" : "";

  return `
    <div class="detail-header">
      <div class="detail-title-row">
        <span class="detail-ticker">${opp.ticker}</span>
        <span class="direction-badge ${dir}">${tradeDirectionGlyph(dir)}</span>
        ${opp.judge_verdict
          ? `<span class="judge-badge-sm ${opp.judge_verdict}">${opp.judge_verdict === "trade" ? "✓ TRADE" : "✗ SKIP"}</span>`
          : ""}
      </div>
      <div class="detail-meta">
        <span class="detail-meta-item">Scanned ${fmtDateTime(opp.scanned_at)}</span>
        <span class="detail-meta-item">Fused <strong class="${signClass(opp.fused_score)}">${fusedSign}${fmt(opp.fused_score, 3)}</strong></span>
        <span class="detail-meta-item">Confidence <strong>${conf}%</strong></span>
      </div>
    </div>

    ${opp.llm_explanation ? `
    <div class="detail-section-block">
      <div class="detail-section-title">Analysis</div>
      <p class="detail-explanation">${escHtml(opp.llm_explanation)}</p>
    </div>` : ""}

    ${opp.judge_verdict ? `
    <div class="judge-block ${opp.judge_verdict} detail-judge">
      <span class="judge-badge">${opp.judge_verdict === "trade" ? "✓ TRADE" : "✗ SKIP"}</span>
      <span class="judge-reason">${escHtml(opp.judge_reason ?? "")}</span>
    </div>` : ""}

    ${execBtn}
    ${tradeBlock}

    <div class="detail-section-block">
      <div class="detail-section-title">Signal Breakdown</div>
      <div class="detail-signals-grid">${signalPanels}</div>
    </div>`;
}

async function executeTradeFromDetail(id, btn) {
  btn.disabled = true;
  btn.textContent = "Executing…";
  try {
    const trade = await api(`/trade/${id}`, { method: "POST" });
    toast(`Trade placed: ${trade.qty} × ${trade.ticker} @ $${fmt(trade.entry_price)}`, "success");
    loadDetail();  // Reload to show trade block
  } catch (e) {
    toast(`Trade failed: ${e.message}`, "error");
    btn.disabled = false;
    btn.textContent = "Retry";
  }
}
