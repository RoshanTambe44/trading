// State
let appState = {
  status: null,
  profile: null,
  funds: null,
  holdings: [],
  positions: [],
  orders: [],
  chartInstance: null,
};

// Currency formatter for INR
function formatINR(val) {
  if (val === undefined || val === null || isNaN(val)) return "₹0.00";
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  }).format(val);
}

// Toast helper
function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
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

// Tab switcher
function switchTab(tabId) {
  document.querySelectorAll(".tab-content").forEach((el) => el.classList.add("hidden"));
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.classList.remove("active", "border-brand-500", "text-brand-500");
    btn.classList.add("border-transparent", "text-gray-400");
  });

  const activeContent = document.getElementById(tabId);
  if (activeContent) activeContent.classList.remove("hidden");

  const activeBtn = document.getElementById(`btn-${tabId}`);
  if (activeBtn) {
    activeBtn.classList.add("active", "border-brand-500", "text-brand-500");
    activeBtn.classList.remove("border-transparent", "text-gray-400");
  }

  // Trigger chart resize if holdings tab
  if (tabId === "tab-holdings" && appState.chartInstance) {
    appState.chartInstance.resize();
  }
}

// Initial fetch on page load
document.addEventListener("DOMContentLoaded", () => {
  refreshDashboard();
});

// Full Dashboard Sync
async function refreshDashboard() {
  const icon = document.getElementById("refresh-icon");
  if (icon) icon.classList.add("animate-spin");

  try {
    const res = await fetch("/api/dashboard-data");
    const data = await res.json();

    appState.status = data.status || {};
    updateConnectionUI(appState.status);

    if (data.profile) {
      appState.profile = data.profile;
      renderProfile(data.profile);
    }

    if (data.funds) {
      appState.funds = data.funds;
      renderFunds(data.funds);
    }

    if (data.holdings && data.holdings.holdings) {
      appState.holdings = data.holdings.holdings;
      renderHoldings(appState.holdings, data.holdings.total_invested);
    }

    if (data.positions && data.positions.positions) {
      appState.positions = data.positions.positions;
      renderPositions(appState.positions);
    }

    if (data.orders && data.orders.orders) {
      appState.orders = data.orders.orders;
      renderOrders(appState.orders);
    }

    lucide.createIcons();
  } catch (err) {
    console.error("Dashboard refresh error:", err);
    showToast("Failed to sync dashboard data: " + err.message, "error");
  } finally {
    if (icon) icon.classList.remove("animate-spin");
  }
}

// Update Header Status UI
function updateConnectionUI(status) {
  const connPill = document.getElementById("conn-pill");
  const connText = document.getElementById("conn-text");
  const uccPill = document.getElementById("ucc-pill");
  const uccVal = document.getElementById("ucc-val");
  const btnOpenConnect = document.getElementById("btn-open-connect");
  const btnDisconnect = document.getElementById("btn-disconnect");

  if (status.is_connected) {
    connPill.className = "flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs font-medium";
    connPill.innerHTML = `<span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span><span>Connected</span>`;
    
    if (status.ucc) {
      uccPill.classList.remove("hidden");
      uccVal.textContent = status.ucc;
    }
    
    btnOpenConnect.classList.add("hidden");
    btnDisconnect.classList.remove("hidden");
    btnDisconnect.classList.add("flex");
  } else {
    connPill.className = "flex items-center gap-2 px-3 py-1.5 rounded-full bg-red-500/10 border border-red-500/30 text-red-400 text-xs font-medium";
    connPill.innerHTML = `<span class="w-2 h-2 rounded-full bg-red-500"></span><span>Disconnected</span>`;
    
    uccPill.classList.add("hidden");
    btnOpenConnect.classList.remove("hidden");
    btnDisconnect.classList.add("hidden");
    btnDisconnect.classList.remove("flex");
  }

  const keyPreview = document.getElementById("modal-saved-key-preview");
  if (keyPreview) {
    keyPreview.textContent = status.masked_api_key || (status.has_saved_keys ? "Ready in keys.txt" : "Not Found");
  }
}

// Render Profile
function renderProfile(profile) {
  if (!profile) return;

  document.getElementById("prof-ucc").textContent = profile.ucc || "--";
  const vendorEl = document.getElementById("prof-vendor-id");
  vendorEl.textContent = profile.vendor_user_id || "--";
  vendorEl.title = profile.vendor_user_id || "";

  // NSE
  const nseEl = document.getElementById("prof-nse");
  if (profile.nse_enabled) {
    nseEl.innerHTML = `<span class="w-2 h-2 rounded-full bg-emerald-400"></span><span class="text-emerald-400">Enabled</span>`;
  } else {
    nseEl.innerHTML = `<span class="w-2 h-2 rounded-full bg-gray-500"></span><span class="text-gray-400">Disabled</span>`;
  }

  // BSE
  const bseEl = document.getElementById("prof-bse");
  if (profile.bse_enabled) {
    bseEl.innerHTML = `<span class="w-2 h-2 rounded-full bg-emerald-400"></span><span class="text-emerald-400">Enabled</span>`;
  } else {
    bseEl.innerHTML = `<span class="w-2 h-2 rounded-full bg-gray-500"></span><span class="text-gray-400">Disabled</span>`;
  }

  // DDPI
  document.getElementById("prof-ddpi").textContent = profile.ddpi_enabled ? "Enabled" : "Disabled (PIN Required for selling)";

  // Synced at
  document.getElementById("prof-synced-at").textContent = new Date().toLocaleTimeString();

  // Active Segments
  const segs = profile.active_segments || [];
  document.getElementById("prof-segments-inline").textContent = segs.join(", ") || "None";

  const segmentsContainer = document.getElementById("stat-segments");
  if (segmentsContainer) {
    if (segs.length > 0) {
      segmentsContainer.innerHTML = segs
        .map(
          (s) =>
            `<span class="px-2 py-0.5 rounded bg-purple-500/10 border border-purple-500/20 text-purple-300 text-xs font-mono font-medium">${s}</span>`
        )
        .join("");
    } else {
      segmentsContainer.innerHTML = `<span class="px-2 py-0.5 rounded bg-gray-800 text-gray-400 text-xs font-mono">None</span>`;
    }
  }

  // Exchanges
  const exchs = [];
  if (profile.nse_enabled) exchs.push("NSE");
  if (profile.bse_enabled) exchs.push("BSE");
  document.getElementById("stat-exchanges").textContent = exchs.join(", ") || "--";
}

// Render Funds
function renderFunds(funds) {
  if (!funds) return;

  const clearCash = funds.clear_cash || 0.0;
  const marginUsed = funds.net_margin_used || 0.0;
  const collateral = funds.collateral_available || 0.0;

  // Stat cards
  document.getElementById("stat-cash").textContent = formatINR(clearCash);
  document.getElementById("stat-margin-used").textContent = formatINR(marginUsed);

  // Tab 2 detail fields
  document.getElementById("funds-clear-cash").textContent = formatINR(clearCash);
  document.getElementById("funds-margin-used").textContent = formatINR(marginUsed);
  document.getElementById("funds-collateral").textContent = formatINR(collateral);

  // Equity details
  const eq = funds.equity_margin_details || {};
  document.getElementById("eq-cnc-bal").textContent = formatINR(eq.cnc_balance_available);
  document.getElementById("eq-mis-bal").textContent = formatINR(eq.mis_balance_available);
  document.getElementById("eq-cnc-used").textContent = formatINR(eq.cnc_margin_used);
  document.getElementById("eq-mis-used").textContent = formatINR(eq.mis_margin_used);

  // F&O details
  const fno = funds.fno_margin_details || {};
  document.getElementById("fno-fut-bal").textContent = formatINR(fno.future_balance_available);
  document.getElementById("fno-opt-buy-bal").textContent = formatINR(fno.option_buy_balance_available);
  document.getElementById("fno-span-used").textContent = formatINR(fno.span_margin_used);
  document.getElementById("fno-exp-used").textContent = formatINR(fno.exposure_margin_used);
}

// Render Holdings
function renderHoldings(holdings, totalInvested) {
  const tbody = document.getElementById("holdings-tbody");
  const countBadge = document.getElementById("badge-holdings-count");
  const statCount = document.getElementById("stat-holdings-count");
  const statInvested = document.getElementById("stat-invested");

  const total = totalInvested || holdings.reduce((sum, h) => sum + (h.invested_value || 0), 0);

  if (countBadge) countBadge.textContent = holdings.length;
  if (statCount) statCount.textContent = holdings.length;
  if (statInvested) statInvested.textContent = formatINR(total);

  if (!holdings || holdings.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" class="py-6 text-center text-gray-500">No holdings found in Demat.</td></tr>`;
    updateHoldingsChart([], []);
    return;
  }

  tbody.innerHTML = holdings
    .map((item) => {
      const exchanges = (item.tradable_exchanges || ["NSE"])
        .map(
          (ex) =>
            `<span class="px-1.5 py-0.5 rounded text-[10px] bg-dark-base border border-dark-border text-gray-300">${ex}</span>`
        )
        .join(" ");

      return `
        <tr class="hover:bg-dark-hover/50 transition">
          <td class="py-3 px-3">
            <div class="font-bold text-white tracking-wide">${item.trading_symbol}</div>
            <div class="text-[11px] text-gray-400 font-mono">${item.isin}</div>
          </td>
          <td class="py-3 px-3 text-right font-mono font-medium text-white">${item.quantity}</td>
          <td class="py-3 px-3 text-right font-mono text-gray-300">${formatINR(item.average_price)}</td>
          <td class="py-3 px-3 text-right font-mono font-bold text-emerald-400">${formatINR(item.invested_value)}</td>
          <td class="py-3 px-3 text-right font-mono text-gray-400">${item.allocation_pct}%</td>
          <td class="py-3 px-3 text-center">${exchanges}</td>
        </tr>
      `;
    })
    .join("");

  // Update Donut Chart
  const labels = holdings.map((h) => h.trading_symbol);
  const dataVals = holdings.map((h) => h.invested_value);
  updateHoldingsChart(labels, dataVals);
}

// Chart.js instance for Holdings
function updateHoldingsChart(labels, data) {
  const ctx = document.getElementById("holdingsChart");
  if (!ctx) return;

  if (appState.chartInstance) {
    appState.chartInstance.destroy();
  }

  if (labels.length === 0) {
    return;
  }

  const colors = ["#00d09c", "#3b82f6", "#8b5cf6", "#ec4899", "#f59e0b", "#14b8a6"];

  appState.chartInstance = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: labels,
      datasets: [
        {
          data: data,
          backgroundColor: colors.slice(0, labels.length),
          borderWidth: 2,
          borderColor: "#111827",
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: function (context) {
              const val = context.raw || 0;
              return ` ${context.label}: ${formatINR(val)}`;
            },
          },
        },
      },
      cutout: "70%",
    },
  });

  // Render HTML legend
  const legendEl = document.getElementById("chart-legend");
  if (legendEl) {
    legendEl.innerHTML = labels
      .map((label, idx) => {
        const val = data[idx];
        const color = colors[idx % colors.length];
        return `
          <div class="flex items-center justify-between text-gray-300">
            <div class="flex items-center gap-2">
              <span class="w-2.5 h-2.5 rounded-full" style="background-color: ${color}"></span>
              <span class="font-medium">${label}</span>
            </div>
            <span class="font-mono text-gray-400">${formatINR(val)}</span>
          </div>
        `;
      })
      .join("");
  }
}

// Filter holdings
function filterHoldings() {
  const query = (document.getElementById("holding-search").value || "").toLowerCase();
  const filtered = appState.holdings.filter(
    (h) =>
      h.trading_symbol.toLowerCase().includes(query) ||
      (h.isin && h.isin.toLowerCase().includes(query))
  );
  renderHoldings(filtered);
}

// Render Positions
function renderPositions(positions) {
  const tbody = document.getElementById("positions-tbody");
  if (!positions || positions.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" class="py-6 text-center text-gray-500">No open positions currently.</td></tr>`;
    return;
  }

  tbody.innerHTML = positions
    .map((p) => {
      const pnl = p.unrealized_pnl || 0.0;
      const pnlColor = pnl >= 0 ? "text-emerald-400" : "text-red-400";
      return `
        <tr class="hover:bg-dark-hover/50 transition">
          <td class="py-3 px-3 font-bold text-white">${p.trading_symbol}</td>
          <td class="py-3 px-3 text-gray-400">${p.segment || "CASH"}</td>
          <td class="py-3 px-3 text-right font-mono">${p.net_quantity || 0}</td>
          <td class="py-3 px-3 text-right font-mono">${formatINR(p.buy_avg_price)}</td>
          <td class="py-3 px-3 text-right font-mono">${formatINR(p.sell_avg_price)}</td>
          <td class="py-3 px-3 text-right font-mono font-bold ${pnlColor}">${formatINR(pnl)}</td>
        </tr>
      `;
    })
    .join("");
}

// Render Orders
function renderOrders(orders) {
  const tbody = document.getElementById("orders-tbody");
  if (!orders || orders.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" class="py-6 text-center text-gray-500">No orders placed today.</td></tr>`;
    return;
  }

  tbody.innerHTML = orders
    .map((o) => {
      const statusColor =
        o.status === "COMPLETED"
          ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30"
          : o.status === "REJECTED" || o.status === "CANCELLED"
          ? "bg-red-500/10 text-red-400 border-red-500/30"
          : "bg-amber-500/10 text-amber-400 border-amber-500/30";

      return `
        <tr class="hover:bg-dark-hover/50 transition">
          <td class="py-3 px-3 font-mono text-[11px] text-gray-400">${o.order_id || "--"}</td>
          <td class="py-3 px-3 font-bold text-white">${o.trading_symbol || "--"}</td>
          <td class="py-3 px-3 text-gray-300 font-mono">${o.order_type || "--"}</td>
          <td class="py-3 px-3 font-bold ${o.transaction_type === "BUY" ? "text-emerald-400" : "text-red-400"}">${o.transaction_type}</td>
          <td class="py-3 px-3 text-right font-mono">${o.quantity || 0}</td>
          <td class="py-3 px-3 text-right font-mono">${formatINR(o.price)}</td>
          <td class="py-3 px-3 text-center">
            <span class="px-2 py-0.5 rounded-full text-[10px] font-semibold border ${statusColor}">${o.status}</span>
          </td>
        </tr>
      `;
    })
    .join("");
}

// Modal controls
function openConnectModal() {
  document.getElementById("connect-modal").classList.remove("hidden");
  document.getElementById("modal-error").classList.add("hidden");
  lucide.createIcons();
}

function closeConnectModal() {
  document.getElementById("connect-modal").classList.add("hidden");
}

function switchModalMode(mode) {
  const btnSaved = document.getElementById("modal-tab-saved");
  const btnTotp = document.getElementById("modal-tab-totp");
  const divSaved = document.getElementById("modal-mode-saved");
  const divTotp = document.getElementById("modal-mode-totp");

  if (mode === "saved") {
    btnSaved.className = "py-1.5 px-3 rounded-lg bg-brand-500 text-gray-950 font-bold transition";
    btnTotp.className = "py-1.5 px-3 rounded-lg text-gray-400 hover:text-white transition";
    divSaved.classList.remove("hidden");
    divTotp.classList.add("hidden");
  } else {
    btnTotp.className = "py-1.5 px-3 rounded-lg bg-brand-500 text-gray-950 font-bold transition";
    btnSaved.className = "py-1.5 px-3 rounded-lg text-gray-400 hover:text-white transition";
    divTotp.classList.remove("hidden");
    divSaved.classList.add("hidden");
  }
}

// Connect Actions
async function loginWithSavedKeys() {
  const btn = document.getElementById("btn-modal-saved-connect");
  const errDiv = document.getElementById("modal-error");
  errDiv.classList.add("hidden");
  btn.disabled = true;
  btn.innerHTML = `<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i><span>Connecting...</span>`;
  lucide.createIcons();

  try {
    const res = await fetch("/api/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Connected to Groww (${data.ucc || "Success"})`, "success");
      closeConnectModal();
      refreshDashboard();
    } else {
      errDiv.textContent = data.error || "Connection failed";
      errDiv.classList.remove("hidden");
    }
  } catch (err) {
    errDiv.textContent = err.message;
    errDiv.classList.remove("hidden");
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<i data-lucide="zap" class="w-4 h-4"></i><span>Connect Now</span>`;
    lucide.createIcons();
  }
}

async function loginWithTotpCode() {
  const code = (document.getElementById("modal-totp-input").value || "").trim();
  const btn = document.getElementById("btn-modal-totp-connect");
  const errDiv = document.getElementById("modal-error");

  if (!code || code.length !== 6) {
    errDiv.textContent = "Please enter a valid 6-digit TOTP code.";
    errDiv.classList.remove("hidden");
    return;
  }

  errDiv.classList.add("hidden");
  btn.disabled = true;
  btn.innerHTML = `<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i><span>Verifying TOTP...</span>`;
  lucide.createIcons();

  try {
    const res = await fetch("/api/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ totp_code: code }),
    });
    const data = await res.json();
    if (data.success) {
      showToast(`TOTP Verified! Connected to Groww (${data.ucc})`, "success");
      closeConnectModal();
      refreshDashboard();
    } else {
      errDiv.textContent = data.error || "TOTP verification failed";
      errDiv.classList.remove("hidden");
    }
  } catch (err) {
    errDiv.textContent = err.message;
    errDiv.classList.remove("hidden");
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<i data-lucide="shield-check" class="w-4 h-4"></i><span>Verify & Connect</span>`;
    lucide.createIcons();
  }
}

async function disconnectGroww() {
  if (!confirm("Are you sure you want to disconnect from Groww?")) return;
  try {
    const res = await fetch("/api/disconnect", { method: "POST" });
    const data = await res.json();
    if (data.success) {
      showToast("Disconnected from Groww", "info");
      refreshDashboard();
    }
  } catch (err) {
    showToast("Error disconnecting: " + err.message, "error");
  }
}

// Save Keys from Settings Tab
async function saveKeys(e) {
  e.preventDefault();
  const apiKey = (document.getElementById("input-api-key").value || "").trim();
  const apiSecret = (document.getElementById("input-api-secret").value || "").trim();
  const totpSecret = (document.getElementById("input-totp-secret").value || "").trim();

  if (!apiKey) {
    showToast("API Key cannot be empty.", "error");
    return;
  }

  try {
    const res = await fetch("/api/save-keys", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        api_key: apiKey,
        api_secret: apiSecret,
        totp_secret: totpSecret,
      }),
    });
    const data = await res.json();
    if (data.success) {
      showToast("Keys saved to keys.txt. Re-authenticating...", "success");
      await loginWithSavedKeys();
    } else {
      showToast(data.error || "Failed to save keys", "error");
    }
  } catch (err) {
    showToast("Error saving keys: " + err.message, "error");
  }
}

function testConnectionWithSavedKeys() {
  loginWithSavedKeys();
}

function copyUCC() {
  const ucc = document.getElementById("ucc-val").textContent;
  if (ucc && ucc !== "--") {
    navigator.clipboard.writeText(ucc);
    showToast(`Copied UCC: ${ucc}`, "info");
  }
}

function copySnippet() {
  const code = document.getElementById("code-snippet").textContent;
  navigator.clipboard.writeText(code);
  showToast("Code copied to clipboard!", "info");
}
