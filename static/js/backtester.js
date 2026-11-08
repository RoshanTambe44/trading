// Backtester & Live Bot State
let backtestState = {
  runId: null,
  allTrades: [],
  filteredTrades: [],
  selectedIndex: 0,
  chart: null,
  candleSeries: null,
  ema9Series: null,
  ema21Series: null,
  isDarkTheme: true,
  tradeChartCache: {},
  // Bot state
  isPaperMode: true,
  botPollingInterval: null,
};

// Format currency in INR
function formatINR(val) {
  if (val === undefined || val === null || isNaN(val)) return "₹0.00";
  const sign = val > 0 ? "+" : "";
  return (
    sign +
    new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: "INR",
      maximumFractionDigits: 2,
    }).format(val)
  );
}

function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  if (!container) return;
  const toast = document.createElement("div");
  const bgClass =
    type === "success"
      ? "bg-emerald-950/90 border-emerald-500/40 text-emerald-200"
      : type === "error"
      ? "bg-red-950/90 border-red-500/40 text-red-200"
      : "bg-gray-900/90 border-gray-700 text-gray-200";

  toast.className = `flex items-center gap-2 px-4 py-3 rounded-xl border shadow-xl text-xs backdrop-blur-md transition-all duration-300 transform translate-y-2 opacity-0 ${bgClass}`;
  toast.innerHTML = `
    <i data-lucide="${type === "success" ? "check-circle" : type === "error" ? "alert-circle" : "info"}" class="w-4 h-4 flex-shrink-0"></i>
    <span>${message}</span>
  `;
  container.appendChild(toast);
  lucide.createIcons();

  requestAnimationFrame(() => {
    toast.classList.remove("translate-y-2", "opacity-0");
  });

  setTimeout(() => {
    toast.classList.add("opacity-0", "translate-y-2");
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// Initialize on page load
document.addEventListener("DOMContentLoaded", () => {
  initChart();
  triggerBacktest();
  setupKeyboardNavigation();
  fetchDataSummary();
  startBotPolling();
});

// Fetch database candle summary
async function fetchDataSummary() {
  try {
    const res = await fetch("/api/backtest/data-summary");
    const data = await res.json();
    if (data.count) {
      const el = document.getElementById("db-candles-count");
      if (el) el.textContent = Number(data.count).toLocaleString();
    }
  } catch (err) {
    console.error("Error fetching data summary:", err);
  }
}

// Initialize TradingView Lightweight Chart
function initChart() {
  const container = document.getElementById("chart-container");
  if (!container) return;

  const isDark = backtestState.isDarkTheme;

  backtestState.chart = LightweightCharts.createChart(container, {
    layout: {
      background: { color: isDark ? "#0B0F19" : "#FFFFFF" },
      textColor: isDark ? "#9CA3AF" : "#374151",
    },
    grid: {
      vertLines: { color: isDark ? "#1F2937" : "#F3F4F6" },
      horzLines: { color: isDark ? "#1F2937" : "#F3F4F6" },
    },
    crosshair: {
      mode: LightweightCharts.CrosshairMode.Normal,
    },
    rightPriceScale: {
      borderColor: isDark ? "#374151" : "#E5E7EB",
    },
    timeScale: {
      borderColor: isDark ? "#374151" : "#E5E7EB",
      timeVisible: true,
      secondsVisible: false,
    },
  });

  // Candlestick Series
  backtestState.candleSeries = backtestState.chart.addCandlestickSeries({
    upColor: "#10B981",
    downColor: "#EF4444",
    borderUpColor: "#10B981",
    borderDownColor: "#EF4444",
    wickUpColor: "#10B981",
    wickDownColor: "#EF4444",
  });

  // 9 EMA Series (Cyan)
  backtestState.ema9Series = backtestState.chart.addLineSeries({
    color: "#06B6D4",
    lineWidth: 2,
    title: "9 EMA",
  });

  // 21 EMA Series (Amber)
  backtestState.ema21Series = backtestState.chart.addLineSeries({
    color: "#F59E0B",
    lineWidth: 2,
    title: "21 EMA",
  });

  // Handle Resize
  window.addEventListener("resize", () => {
    if (backtestState.chart && container) {
      backtestState.chart.applyOptions({
        width: container.clientWidth,
        height: container.clientHeight,
      });
    }
  });
}

// Trigger Backtest
async function triggerBacktest(forceNotification = false) {
  const btn = document.getElementById("btn-run-backtest");
  const icon = document.getElementById("run-icon");
  if (btn) btn.disabled = true;
  if (icon) icon.classList.add("animate-spin");

  const timeframe = document.getElementById("filter-timeframe").value;
  const mode = document.getElementById("filter-mode").value;
  const startTime = document.getElementById("filter-start-time").value;
  const cutoffTime = document.getElementById("filter-cutoff-time").value;

  document.getElementById("chart-timeframe-tag").textContent = `Timeframe: ${timeframe}`;

  try {
    const res = await fetch("/api/backtest/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        timeframe: timeframe,
        mode: mode,
        start_time: startTime,
        cutoff_time: cutoffTime,
      }),
    });

    const data = await res.json();
    if (!data.success) {
      showToast(data.error || "Failed to execute backtest", "error");
      return;
    }

    backtestState.runId = data.run_id;
    backtestState.allTrades = data.trades || [];
    renderKPIs(data.summary);
    applyClientFilters();

    if (forceNotification) {
      showToast(`Backtest completed! ${data.trades.length} trades evaluated.`, "success");
    }
  } catch (err) {
    console.error("Backtest execution error:", err);
    showToast("Error running backtest: " + err.message, "error");
  } finally {
    if (btn) btn.disabled = false;
    if (icon) icon.classList.remove("animate-spin");
  }
}

// Apply Client Filters (Outcome & Cross Number)
function applyClientFilters() {
  const outcome = document.getElementById("filter-outcome").value;
  const cross = document.getElementById("filter-cross").value;

  backtestState.filteredTrades = backtestState.allTrades.filter((t) => {
    if (outcome === "WINS" && t.net_pnl <= 0) return false;
    if (outcome === "LOSSES" && t.net_pnl > 0) return false;

    if (cross === "1" && t.cross_number !== 1) return false;
    if (cross === "2" && t.cross_number !== 2) return false;
    if (cross === "3+" && (t.cross_number || 1) < 3) return false;

    return true;
  });

  document.getElementById("trades-filtered-count").textContent = backtestState.filteredTrades.length;
  renderTradesList();

  if (backtestState.filteredTrades.length > 0) {
    selectTrade(0);
  } else {
    clearTradeDetails();
  }
}

// Render KPI Row
function renderKPIs(summary) {
  if (!summary) return;

  document.getElementById("kpi-trades").textContent = summary.total_trades || 0;
  document.getElementById("kpi-winloss").textContent = `${summary.winning_trades || 0} W / ${summary.losing_trades || 0} L`;

  const winRateEl = document.getElementById("kpi-winrate");
  winRateEl.textContent = `${summary.win_rate || 0}%`;

  const netPnlEl = document.getElementById("kpi-net-pnl");
  netPnlEl.textContent = formatINR(summary.net_pnl);
  netPnlEl.className = `text-xl font-bold font-mono mt-1 ${summary.net_pnl >= 0 ? "text-emerald-400" : "text-red-400"}`;

  document.getElementById("kpi-gross-pnl").textContent = `Gross: ${formatINR(summary.gross_pnl)}`;
  document.getElementById("kpi-friction").textContent = formatINR(summary.total_friction);
  document.getElementById("kpi-pf").textContent = summary.profit_factor || "--";
  document.getElementById("kpi-payoff").textContent = summary.payoff_ratio || "--";
  document.getElementById("kpi-max-dd").textContent = formatINR(summary.max_drawdown_amount);
  document.getElementById("kpi-max-dd-pct").textContent = `${summary.max_drawdown_pct}% of Capital`;
}

// Render Scrollable Trades List
function renderTradesList() {
  const container = document.getElementById("trades-list-container");
  const trades = backtestState.filteredTrades;

  if (trades.length === 0) {
    container.innerHTML = `
      <div class="py-16 text-center text-gray-500 text-xs">
        <i data-lucide="inbox" class="w-8 h-8 text-gray-600 mx-auto mb-2"></i>
        <span>No trades matched the selected filters.</span>
      </div>
    `;
    lucide.createIcons();
    return;
  }

  container.innerHTML = trades
    .map((t, idx) => {
      const isWin = t.net_pnl > 0;
      const pnlColor = isWin ? "text-emerald-400" : "text-red-400";
      const dirColor = t.direction === "LONG" ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30" : "bg-red-500/10 text-red-400 border-red-500/30";

      return `
        <div id="trade-row-${idx}" onclick="selectTrade(${idx})" class="trade-item p-3 rounded-xl border border-dark-border bg-dark-base/60 hover:bg-dark-hover cursor-pointer transition flex items-center justify-between text-xs">
          <div class="space-y-1">
            <div class="flex items-center gap-2">
              <span class="px-1.5 py-0.5 rounded text-[10px] font-bold border ${dirColor}">${t.direction}</span>
              <span class="font-bold text-white tracking-wide">${t.strike} ${t.option_type}</span>
              <span class="text-[10px] text-gray-500">Cross #${t.cross_number || 1}</span>
            </div>
            <div class="text-[11px] text-gray-400 font-mono">
              ${t.date_str} • ${t.entry_time_str.split(" ")[1]} → ${t.exit_time_str.split(" ")[1]}
            </div>
          </div>

          <div class="text-right space-y-0.5">
            <div class="font-bold font-mono text-sm ${pnlColor}">${formatINR(t.net_pnl)}</div>
            <div class="text-[10px] text-gray-400">${t.exit_reason === "OPPOSITE_CROSSOVER" ? "Opposite Cross" : t.exit_reason === "MANDATORY_1500" ? "15:00 Square-off" : "Cutoff"}</div>
          </div>
        </div>
      `;
    })
    .join("");

  lucide.createIcons();
}

// Select a Trade (loads chart, metadata, and costs)
async function selectTrade(index) {
  const trades = backtestState.filteredTrades;
  if (!trades || index < 0 || index >= trades.length) return;

  backtestState.selectedIndex = index;
  const trade = trades[index];

  document.querySelectorAll(".trade-item").forEach((el) => el.classList.remove("border-brand-500", "bg-brand-500/10"));
  const activeRow = document.getElementById(`trade-row-${index}`);
  if (activeRow) {
    activeRow.classList.add("border-brand-500", "bg-brand-500/10");
    activeRow.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  // 1. Update Selected Trade KPI
  const pnlEl = document.getElementById("kpi-selected-trade-pnl");
  pnlEl.textContent = formatINR(trade.net_pnl);
  pnlEl.className = `text-xl font-black font-mono mt-1 ${trade.net_pnl >= 0 ? "text-emerald-400" : "text-red-400"}`;
  document.getElementById("kpi-selected-trade-info").textContent = `Trade #${trade.trade_number} (${trade.direction} ${trade.strike} ${trade.option_type})`;

  // 2. Update Metadata Bar
  const dirBadge = document.getElementById("meta-direction-badge");
  dirBadge.textContent = trade.direction;
  dirBadge.className = `px-2.5 py-1 rounded-md text-xs font-bold uppercase tracking-wider ${
    trade.direction === "LONG"
      ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30"
      : "bg-red-500/10 text-red-400 border border-red-500/30"
  }`;

  document.getElementById("meta-symbol").textContent = `NIFTY ${trade.strike} ${trade.option_type}`;

  const whipsawBadge = document.getElementById("meta-whipsaw-badge");
  if (trade.is_whipsaw) {
    whipsawBadge.classList.remove("hidden");
  } else {
    whipsawBadge.classList.add("hidden");
  }

  document.getElementById("meta-nifty-in").textContent = trade.nifty_entry || "--";
  document.getElementById("meta-nifty-out").textContent = trade.nifty_exit || "--";
  document.getElementById("meta-opt-in").textContent = `₹${trade.entry_premium}`;
  document.getElementById("meta-opt-out").textContent = `₹${trade.exit_premium}`;
  document.getElementById("meta-dte").textContent = `${trade.dte || 0}d`;
  document.getElementById("meta-exit-reason").textContent = trade.exit_reason;

  const netPnlBadge = document.getElementById("meta-net-pnl");
  netPnlBadge.textContent = formatINR(trade.net_pnl);
  netPnlBadge.className = `px-3 py-1 rounded-lg text-xs font-mono font-bold ${
    trade.net_pnl >= 0
      ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30"
      : "bg-red-500/10 text-red-400 border border-red-500/30"
  }`;

  // 3. Update Cost Card
  document.getElementById("cost-gross").textContent = formatINR(trade.gross_pnl);
  document.getElementById("cost-slippage").textContent = `₹${trade.slippage || 0}`;
  document.getElementById("cost-brokerage").textContent = `₹${trade.brokerage || 40}`;
  document.getElementById("cost-stt").textContent = `₹${trade.stt || 0}`;
  document.getElementById("cost-exchange").textContent = `₹${trade.exchange_charges || 0}`;
  document.getElementById("cost-sebi").textContent = `₹${trade.sebi_charges || 0}`;
  document.getElementById("cost-stamp").textContent = `₹${trade.stamp_duty || 0}`;
  document.getElementById("cost-gst").textContent = `₹${trade.gst || 0}`;

  const costNetEl = document.getElementById("cost-net");
  costNetEl.textContent = formatINR(trade.net_pnl);
  costNetEl.className = `font-mono font-black text-xs mt-0.5 block ${trade.net_pnl >= 0 ? "text-emerald-300" : "text-red-300"}`;

  // 4. Load & Render Candlestick Chart
  await loadTradeChart(trade.id);
}

// Fetch & Render Chart Data for Selected Trade
async function loadTradeChart(tradeId) {
  const loading = document.getElementById("chart-loading");
  if (loading) loading.classList.remove("hidden");

  const timeframe = document.getElementById("filter-timeframe").value;
  const cacheKey = `${tradeId}_${timeframe}`;

  try {
    let chartData = backtestState.tradeChartCache[cacheKey];
    if (!chartData) {
      const res = await fetch(`/api/backtest/trade-chart/${tradeId}?timeframe=${timeframe}`);
      chartData = await res.json();
      if (chartData.success) {
        backtestState.tradeChartCache[cacheKey] = chartData;
      }
    }

    if (chartData && chartData.success) {
      backtestState.candleSeries.setData(chartData.candles || []);
      backtestState.ema9Series.setData(chartData.ema9 || []);
      backtestState.ema21Series.setData(chartData.ema21 || []);
      backtestState.candleSeries.setMarkers(chartData.markers || []);
      backtestState.chart.timeScale().fitContent();
    }
  } catch (err) {
    console.error("Error loading trade chart:", err);
  } finally {
    if (loading) loading.classList.add("hidden");
  }
}

// Setup Keyboard Navigation (Up/Down Arrow keys)
function setupKeyboardNavigation() {
  window.addEventListener("keydown", (e) => {
    if (["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName)) return;

    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (backtestState.selectedIndex < backtestState.filteredTrades.length - 1) {
        selectTrade(backtestState.selectedIndex + 1);
      }
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (backtestState.selectedIndex > 0) {
        selectTrade(backtestState.selectedIndex - 1);
      }
    }
  });
}

function clearTradeDetails() {
  document.getElementById("kpi-selected-trade-pnl").textContent = "--";
  document.getElementById("kpi-selected-trade-info").textContent = "No trade selected";
  document.getElementById("meta-symbol").textContent = "--";
  document.getElementById("meta-nifty-in").textContent = "--";
  document.getElementById("meta-nifty-out").textContent = "--";
  document.getElementById("meta-opt-in").textContent = "--";
  document.getElementById("meta-opt-out").textContent = "--";
  document.getElementById("meta-net-pnl").textContent = "₹0.00";

  if (backtestState.candleSeries) backtestState.candleSeries.setData([]);
  if (backtestState.ema9Series) backtestState.ema9Series.setData([]);
  if (backtestState.ema21Series) backtestState.ema21Series.setData([]);
}

function toggleTheme() {
  backtestState.isDarkTheme = !backtestState.isDarkTheme;
  const html = document.documentElement;
  const icon = document.getElementById("theme-icon");

  if (backtestState.isDarkTheme) {
    html.classList.add("dark");
    if (icon) icon.setAttribute("data-lucide", "sun");
    if (backtestState.chart) {
      backtestState.chart.applyOptions({
        layout: { background: { color: "#0B0F19" }, textColor: "#9CA3AF" },
        grid: { vertLines: { color: "#1F2937" }, horzLines: { color: "#1F2937" } },
      });
    }
  } else {
    html.classList.remove("dark");
    if (icon) icon.setAttribute("data-lucide", "moon");
    if (backtestState.chart) {
      backtestState.chart.applyOptions({
        layout: { background: { color: "#FFFFFF" }, textColor: "#374151" },
        grid: { vertLines: { color: "#F3F4F6" }, horzLines: { color: "#F3F4F6" } },
      });
    }
  }
  lucide.createIcons();
}


// ==========================================
// LIVE & PAPER TRADING ENGINE CONTROLLER
// ==========================================

function setTradingMode(isPaper) {
  backtestState.isPaperMode = isPaper;
  const btnPaper = document.getElementById("btn-mode-paper");
  const btnLive = document.getElementById("btn-mode-live");

  if (isPaper) {
    btnPaper.className = "px-3 py-1 rounded-lg bg-brand-500 text-gray-950 shadow-sm transition";
    btnLive.className = "px-3 py-1 rounded-lg text-gray-400 hover:text-white transition";
    showToast("Trading Mode: Paper Trading (Simulation - Safe)", "info");
  } else {
    if (!confirm("⚠️ Switch to LIVE BROKER ACCOUNT? Real orders will be placed directly in your Groww account!")) {
      return;
    }
    btnLive.className = "px-3 py-1 rounded-lg bg-red-500 text-white shadow-sm transition";
    btnPaper.className = "px-3 py-1 rounded-lg text-gray-400 hover:text-white transition";
    showToast("Trading Mode: LIVE BROKER ACCOUNT ENABLED", "error");
  }
}

async function startLiveBot() {
  const timeframe = document.getElementById("filter-timeframe").value;
  const mode = document.getElementById("filter-mode").value;
  const startTime = document.getElementById("filter-start-time").value;
  const cutoffTime = document.getElementById("filter-cutoff-time").value;

  try {
    const res = await fetch("/api/bot/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        timeframe: timeframe,
        mode: mode,
        start_time: startTime,
        cutoff_time: cutoffTime,
        is_paper: backtestState.isPaperMode,
      }),
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Strategy Bot Started (${backtestState.isPaperMode ? "Paper" : "Live"})`, "success");
      updateBotUIState(true);
      pollBotStatus();
    } else {
      showToast(data.error || "Failed to start bot", "error");
    }
  } catch (err) {
    showToast("Error starting bot: " + err.message, "error");
  }
}

async function stopLiveBot() {
  try {
    const res = await fetch("/api/bot/stop", { method: "POST" });
    const data = await res.json();
    if (data.success) {
      showToast("Strategy Bot Stopped", "info");
      updateBotUIState(false);
      pollBotStatus();
    }
  } catch (err) {
    showToast("Error stopping bot: " + err.message, "error");
  }
}

async function panicSquareOff() {
  if (!confirm("Are you sure you want to SQUARE OFF the open position immediately?")) return;
  try {
    const res = await fetch("/api/bot/squareoff", { method: "POST" });
    const data = await res.json();
    if (data.success) {
      showToast(`Position squared off! Realized Gross PnL: ${formatINR(data.gross_pnl)}`, "success");
      pollBotStatus();
    } else {
      showToast(data.error || "Square-off failed", "error");
    }
  } catch (err) {
    showToast("Error executing square-off: " + err.message, "error");
  }
}

function toggleBotLog() {
  const panel = document.getElementById("bot-log-panel");
  if (panel) panel.classList.toggle("hidden");
}

function startBotPolling() {
  pollBotStatus();
  backtestState.botPollingInterval = setInterval(pollBotStatus, 3000);
}

async function pollBotStatus() {
  try {
    const res = await fetch("/api/bot/status");
    const data = await res.json();

    updateBotUIState(data.is_running, data.status);

    if (data.latest_spot) {
      document.getElementById("live-spot").textContent = formatINR(data.latest_spot);
      document.getElementById("live-ema9").textContent = data.latest_ema9 ? data.latest_ema9.toFixed(1) : "--";
      document.getElementById("live-ema21").textContent = data.latest_ema21 ? data.latest_ema21.toFixed(1) : "--";
    }

    if (data.last_check_time) {
      document.getElementById("live-last-check").textContent = data.last_check_time;
    }

    // Position Details
    const posDesc = document.getElementById("live-pos-desc");
    const pnlEl = document.getElementById("live-unrealized-pnl");
    const squareOffBtn = document.getElementById("btn-bot-squareoff");

    if (data.current_position) {
      posDesc.textContent = `${data.current_position.action} ${data.current_position.trading_symbol}`;
      posDesc.className = "text-xs font-bold text-brand-400 mt-0.5 truncate";

      pnlEl.textContent = formatINR(data.unrealized_pnl);
      pnlEl.className = `text-sm font-bold font-mono mt-0.5 ${data.unrealized_pnl >= 0 ? "text-emerald-400" : "text-red-400"}`;

      if (squareOffBtn) squareOffBtn.classList.remove("hidden");
    } else {
      posDesc.textContent = "No open position";
      posDesc.className = "text-xs font-bold text-gray-500 mt-0.5";

      pnlEl.textContent = "₹0.00";
      pnlEl.className = "text-sm font-bold font-mono text-gray-500 mt-0.5";

      if (squareOffBtn) squareOffBtn.classList.add("hidden");
    }

    // Render Event Logs
    if (data.logs && data.logs.length > 0) {
      const stream = document.getElementById("bot-log-stream");
      if (stream) {
        stream.innerHTML = data.logs
          .map((l) => `<div class="text-[11px]"><span class="text-gray-500">[${l.timestamp}]</span> <span class="${l.level === "ERROR" ? "text-red-400 font-bold" : l.message.includes("Opened") ? "text-brand-400 font-bold" : "text-gray-300"}">${l.message}</span></div>`)
          .join("");
      }
    }
  } catch (err) {
    // Silent polling error
  }
}

function updateBotUIState(isRunning, status = "IDLE") {
  const pill = document.getElementById("bot-status-pill");
  const btnStart = document.getElementById("btn-bot-start");
  const btnStop = document.getElementById("btn-bot-stop");

  if (isRunning) {
    btnStart.classList.add("hidden");
    btnStop.classList.remove("hidden");
    btnStop.classList.add("flex");

    if (status === "IN_POSITION") {
      pill.className = "px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider bg-blue-500/20 text-blue-300 border border-blue-500/40 animate-pulse";
      pill.textContent = "🔵 In Position";
    } else {
      pill.className = "px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider bg-emerald-500/20 text-emerald-400 border border-emerald-500/40 animate-pulse";
      pill.textContent = "🟢 Monitoring";
    }
  } else {
    btnStart.classList.remove("hidden");
    btnStop.classList.add("hidden");
    btnStop.classList.remove("flex");

    pill.className = "px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider bg-gray-800 text-gray-400 border border-gray-700";
    pill.textContent = "⚪ Idle";
  }
}

// ==========================================
// CSV EXPORT & EQUITY CURVE
// ==========================================

let equityChartInstance = null;

async function exportTradesCSV() {
  const trades = backtestState.filteredTrades;
  if (!trades || trades.length === 0) {
    showToast("No trades available to export.", "error");
    return;
  }

  try {
    const res = await fetch("/api/backtest/export-csv", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ trades: trades }),
    });

    if (!res.ok) throw new Error("Export failed");

    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `nifty_9_21_ema_trades_${Date.now()}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    showToast("CSV export downloaded successfully!", "success");
  } catch (err) {
    showToast("Error exporting CSV: " + err.message, "error");
  }
}

function toggleEquityCurveModal() {
  const modal = document.getElementById("equity-modal");
  if (!modal) return;
  modal.classList.toggle("hidden");
  if (!modal.classList.contains("hidden")) {
    renderEquityCurve();
  }
}

function renderEquityCurve() {
  const ctx = document.getElementById("equityChart");
  if (!ctx) return;

  const trades = backtestState.filteredTrades;
  if (!trades || trades.length === 0) return;

  // Sort trades chronologically
  const sorted = [...trades].sort((a, b) => (a.entry_timestamp || 0) - (b.entry_timestamp || 0));

  let cumNet = 0.0;
  const labels = ["Start"];
  const equityData = [0.0];
  const drawdownData = [0.0];

  let peak = 0.0;
  sorted.forEach((t, i) => {
    cumNet += t.net_pnl || 0.0;
    labels.push(`T#${t.trade_number} (${t.date_str})`);
    equityData.push(Math.round(cumNet * 100) / 100);

    if (cumNet > peak) peak = cumNet;
    const dd = cumNet - peak;
    drawdownData.push(Math.round(dd * 100) / 100);
  });

  if (equityChartInstance) {
    equityChartInstance.destroy();
  }

  equityChartInstance = new Chart(ctx, {
    type: "line",
    data: {
      labels: labels,
      datasets: [
        {
          label: "Cumulative Net PnL (₹)",
          data: equityData,
          borderColor: "#00d09c",
          backgroundColor: "rgba(0, 208, 156, 0.1)",
          borderWidth: 2.5,
          fill: true,
          tension: 0.2,
          yAxisID: "y",
        },
        {
          label: "Drawdown (₹)",
          data: drawdownData,
          borderColor: "#ef4444",
          backgroundColor: "rgba(239, 68, 68, 0.2)",
          borderWidth: 1.5,
          fill: true,
          tension: 0.1,
          yAxisID: "y1",
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          labels: { color: "#9ca3af" },
        },
        tooltip: {
          callbacks: {
            label: function (context) {
              return ` ${context.dataset.label}: ${formatINR(context.raw)}`;
            },
          },
        },
      },
      scales: {
        x: {
          ticks: { color: "#6b7280" },
          grid: { color: "#1f2937" },
        },
        y: {
          position: "left",
          ticks: { color: "#00d09c" },
          grid: { color: "#1f2937" },
        },
        y1: {
          position: "right",
          ticks: { color: "#ef4444" },
          grid: { drawOnChartArea: false },
        },
      },
    },
  });
}

