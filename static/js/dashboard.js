const state = {
  currentPage: 1,
  currentCategory: "All",
  currentQuery: "",
  totalPages: 1,
  debounceTimer: null,
};

const els = {
  grid:        document.getElementById("dealsGrid"),
  emptyState:  document.getElementById("emptyState"),
  pagination:  document.getElementById("pagination"),
  pagePrev:    document.getElementById("pagePrev"),
  pageNext:    document.getElementById("pageNext"),
  pageInfo:    document.getElementById("pageInfo"),
  searchInput: document.getElementById("searchInput"),
  clearSearch: document.getElementById("clearSearch"),
  filterPills: document.getElementById("filterPills"),
  btnRefresh:  document.getElementById("btnRefresh"),
  lastUpdated: document.getElementById("lastUpdated"),
  toast:       document.getElementById("toast"),
  // stats
  statTotal:   document.getElementById("statTotal"),
  statNewLow:  document.getElementById("statNewLow"),
  statDrop:    document.getElementById("statDrop"),
  statGreat:   document.getElementById("statGreat"),
};

let toastTimer;
function showToast(msg, type = "") {
  clearTimeout(toastTimer);
  els.toast.textContent = msg;
  els.toast.className = `toast show ${type}`;
  toastTimer = setTimeout(() => {
    els.toast.classList.remove("show");
  }, 3500);
}

function fmtTime(ts) {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

//  Render deals 
function statusBadge(deal) {
  if (deal.status === "NEW LOW") return `<span class="badge badge-new-low">★ New Low</span>`;
  if (deal.status === "PRICE DROP") return `<span class="badge badge-price-drop">↓ Price Drop</span>`;
  return `<span class="badge badge-great">✦ Great Deal</span>`;
}

function renderDeals(deals) {
  if (!deals.length) {
    els.grid.innerHTML = "";
    els.emptyState.style.display = "block";
    els.pagination.style.display = "none";
    return;
  }

  els.emptyState.style.display = "none";

  els.grid.innerHTML = deals.map((deal, i) => {
    const cardClass = deal.status === "NEW LOW" ? "new-low"
                    : deal.status === "PRICE DROP" ? "price-drop" : "";
    const prevNote = deal.prev_low
      ? `<span class="badge badge-category">Was $${deal.prev_low.toFixed(2)}</span>`
      : "";
    const img = deal.image_url
      ? `<img class="deal-image" src="${escHtml(deal.image_url)}" alt="${escHtml(deal.title)}" loading="lazy">`
      : `<div class="deal-image-placeholder">🏷️</div>`;

    return `
      <div class="deal-card ${cardClass}" style="animation-delay:${i * 40}ms">
        ${img}
        <div class="deal-body">
          <div class="deal-badges">
            ${statusBadge(deal)}
            <span class="badge badge-category">${escHtml(deal.feed_name)}</span>
            ${prevNote}
          </div>
          <div class="deal-title">${escHtml(deal.title)}</div>
          <div class="deal-pricing">
            <span class="price-sale">$${deal.sale_price.toFixed(2)}</span>
            <span class="price-list">$${deal.list_price.toFixed(2)}</span>
            <span class="price-off">${deal.discount_percent.toFixed(0)}% OFF</span>
          </div>
          <div class="deal-savings">You save $${deal.savings_amount.toFixed(2)}</div>
          <a class="deal-link" href="${escHtml(deal.url)}" target="_blank" rel="noopener noreferrer">
            View Deal →
          </a>
        </div>
      </div>`;
  }).join("");
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// Update pagination  
function updatePagination(page, totalPages) {
  state.totalPages = totalPages;
  if (totalPages <= 1) {
    els.pagination.style.display = "none";
    return;
  }
  els.pagination.style.display = "flex";
  els.pagePrev.disabled = page <= 1;
  els.pageNext.disabled = page >= totalPages;
  els.pageInfo.textContent = `Page ${page} of ${totalPages}`;
}

// ── Update stats UI ────────────────────────────────────────────────────────────
function updateStats(data) {
  animateNumber(els.statTotal.querySelector(".stat-value"), data.total);
  animateNumber(els.statNewLow.querySelector(".stat-value"), data.new_lows);
  animateNumber(els.statDrop.querySelector(".stat-value"), data.price_drops);
  animateNumber(els.statGreat.querySelector(".stat-value"), data.great_deals);
}

function animateNumber(el, target) {
  if (!el) return;
  const start = parseInt(el.textContent) || 0;
  const diff = target - start;
  const duration = 400;
  const startTime = performance.now();
  function step(now) {
    const p = Math.min((now - startTime) / duration, 1);
    el.textContent = Math.round(start + diff * easeOut(p));
    if (p < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}
function easeOut(t) { return 1 - Math.pow(1 - t, 3); }

// ── Fetch deals ───────────────────────────────────────────────────────────────
async function fetchDeals(page = 1) {
  const params = new URLSearchParams({
    page,
    category: state.currentCategory,
    q: state.currentQuery,
  });

  try {
    const res = await fetch(`/api/deals?${params}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || `HTTP ${res.status}`);
    }
    const data = await res.json();
    state.currentPage = data.page;

    renderDeals(data.deals);
    updatePagination(data.page, data.total_pages);

    if (data.fetched_at) {
      els.lastUpdated.textContent = `Last fetched: ${fmtTime(data.fetched_at)}`;
    }
  } catch (e) {
    showToast(`Error loading deals: ${e.message}`, "error");
    els.grid.innerHTML = "";
    els.emptyState.style.display = "block";
  }
}

// get stats 
async function fetchStats() {
  try {
    const res = await fetch("/api/stats");
    if (!res.ok) return;
    const data = await res.json();
    updateStats(data);
  } catch (_) { /* silently fail */ }
}

// Manual refresh 
async function doRefresh() {
  if (els.btnRefresh.classList.contains("spinning")) return;
  els.btnRefresh.classList.add("spinning");
  els.btnRefresh.disabled = true;

  try {
    const res = await fetch("/api/refresh", { method: "POST" });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    showToast(`✓ Refreshed in ${data.elapsed_seconds}s — ${data.total_deals} deals found`, "success");
    await Promise.all([fetchDeals(1), fetchStats()]);
  } catch (e) {
    showToast(`Refresh failed: ${e.message}`, "error");
  } finally {
    els.btnRefresh.classList.remove("spinning");
    els.btnRefresh.disabled = false;
  }
}

els.btnRefresh.addEventListener("click", doRefresh);

els.pagePrev.addEventListener("click", () => {
  if (state.currentPage > 1) fetchDeals(state.currentPage - 1);
});
els.pageNext.addEventListener("click", () => {
  if (state.currentPage < state.totalPages) fetchDeals(state.currentPage + 1);
});

els.filterPills.addEventListener("click", (e) => {
  const pill = e.target.closest(".pill");
  if (!pill) return;
  document.querySelectorAll(".pill").forEach(p => p.classList.remove("active"));
  pill.classList.add("active");
  state.currentCategory = pill.dataset.category;
  state.currentPage = 1;
  fetchDeals(1);
});

els.searchInput.addEventListener("input", () => {
  const val = els.searchInput.value.trim();
  els.clearSearch.classList.toggle("visible", val.length > 0);
  clearTimeout(state.debounceTimer);
  state.debounceTimer = setTimeout(() => {
    state.currentQuery = val;
    state.currentPage = 1;
    fetchDeals(1);
  }, 350);
});

els.clearSearch.addEventListener("click", () => {
  els.searchInput.value = "";
  els.clearSearch.classList.remove("visible");
  state.currentQuery = "";
  state.currentPage = 1;
  fetchDeals(1);
});

(async () => {
  await Promise.all([fetchDeals(1), fetchStats()]);
})();
