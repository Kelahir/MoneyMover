// Everything below talks to the real webapp.py/Flask backend, including
// inserting recognized transactions and manual entries - those are real
// writes to the user's MoneyLover account.

const state = {
  wallet: null,
  statement: null,
  transactions: [],
  expandedId: null,
  // { expense: { parentName: [subcategoryNames] }, income: {...} }, loaded
  // from /api/categories once a wallet is selected.
  categories: { expense: {}, income: {} },
};

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function apiFetch(path, options) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.error || `Request to ${path} failed (${response.status})`);
  }
  return body;
}

function showLoading(text) {
  document.getElementById("loading-text").textContent = text;
  document.getElementById("loading-overlay").hidden = false;
}

function hideLoading() {
  document.getElementById("loading-overlay").hidden = true;
}

function showScreen(id) {
  document.querySelectorAll(".screen").forEach((el) => el.classList.remove("active"));
  document.getElementById(id).classList.add("active");
  // Only useful once a wallet has actually been picked, and pointless while
  // already on the wallet-picking screen itself.
  document.getElementById("change-wallet-btn").hidden = id === "screen-auth" || id === "screen-wallets";
}

function formatAmount(amount) {
  const sign = amount < 0 ? "-" : "+";
  return `${sign}€${Math.abs(amount).toFixed(2)}`;
}

function statusInfo(tx) {
  if (tx.origin === "existing") return { cls: "added", label: "Already added" };
  if (tx.origin === "preset") return { cls: "autofilled", label: "Autofilled" };
  return tx.filled
    ? { cls: "autofilled", label: "Added" }
    : { cls: "manual", label: "Needs review" };
}

function categoryOptions(type, selected) {
  return Object.keys(state.categories[type] || {})
    .map((c) => `<option value="${c}" ${c === selected ? "selected" : ""}>${c}</option>`)
    .join("");
}

function subcategoryOptions(type, category, selected) {
  const subcategories = state.categories[type]?.[category] || [];
  const noneOption = `<option value="" ${!selected ? "selected" : ""}>&mdash; none &mdash;</option>`;
  const options = subcategories
    .map((s) => `<option value="${s}" ${s === selected ? "selected" : ""}>${s}</option>`)
    .join("");
  return noneOption + options;
}

function categoryDisplay(tx) {
  if (!tx.category) return "&mdash;";
  return tx.subcategory ? `${tx.category} / ${tx.subcategory}` : tx.category;
}

// ---------- Boot: skip the login screen if a session is already usable ----------

async function boot() {
  try {
    const session = await apiFetch("/api/session");
    if (session.authenticated) {
      renderWallets(session.wallets);
      showLoggedInChrome();
      showScreen("screen-wallets");
      return;
    }
  } catch (e) {
    console.error("Session check failed:", e);
  }

  await showAuthOptions();
}

function showLoggedInChrome() {
  document.getElementById("logout-btn").hidden = false;
}

function hideLoggedInChrome() {
  document.getElementById("logout-btn").hidden = true;
  document.getElementById("wallet-info").hidden = true;
}

function initLogout() {
  document.getElementById("logout-btn").addEventListener("click", async () => {
    try {
      await apiFetch("/api/logout", { method: "POST" });
    } catch (e) {
      console.error("Logout failed:", e);
    }

    state.wallet = null;
    state.statement = null;
    state.transactions = [];
    state.expandedId = null;

    hideLoggedInChrome();
    document.getElementById("auth-checking").hidden = false;
    showScreen("screen-auth");
    await showAuthOptions();
  });
}

function initChangeWallet() {
  document.getElementById("change-wallet-btn").addEventListener("click", () => {
    // Re-render from the wallet list already fetched at login - one call
    // for wallet info per session is enough, no need to hit the API again
    // just to go back and pick a different wallet.
    state.statement = null;
    state.transactions = [];
    state.expandedId = null;

    renderWallets(state.wallets);
    showScreen("screen-wallets");
  });
}

// ---------- Screen 1: auth ----------

async function showAuthOptions() {
  const checkingEl = document.getElementById("auth-checking");
  const detectedEl = document.getElementById("auth-detected");
  const manualEl = document.getElementById("auth-manual");

  let status;
  try {
    status = await apiFetch("/api/auth-status");
  } catch (e) {
    status = { method: "none" };
  }
  checkingEl.hidden = true;

  if (status.method === "none") {
    detectedEl.hidden = true;
    manualEl.hidden = false;
    document.getElementById("auth-back").hidden = true;
    return;
  }

  const message =
    status.method === "token"
      ? `A previous session was found (valid for ${status.days_left} more day${status.days_left === 1 ? "" : "s"}).`
      : `Credentials found in .env for ${status.email}.`;

  document.getElementById("auth-detected-message").textContent = message;
  detectedEl.hidden = false;
  manualEl.hidden = true;
}

function initAuth() {
  const emailEl = document.getElementById("auth-email");
  const passwordEl = document.getElementById("auth-password");
  const errorEl = document.getElementById("auth-error");

  async function attemptLogin(body) {
    errorEl.hidden = true;
    showLoading("Requesting access token...");
    try {
      const data = await apiFetch("/api/login", { method: "POST", body: JSON.stringify(body) });
      hideLoading();
      renderWallets(data.wallets);
      showLoggedInChrome();
      showScreen("screen-wallets");
    } catch (e) {
      hideLoading();
      errorEl.textContent = e.message;
      errorEl.hidden = false;
    }
  }

  document.getElementById("auth-continue").addEventListener("click", () => attemptLogin({}));

  document.getElementById("auth-use-other").addEventListener("click", () => {
    document.getElementById("auth-detected").hidden = true;
    document.getElementById("auth-manual").hidden = false;
    document.getElementById("auth-back").hidden = false;
  });

  document.getElementById("auth-back").addEventListener("click", () => {
    document.getElementById("auth-manual").hidden = true;
    document.getElementById("auth-detected").hidden = false;
  });

  document.getElementById("auth-submit").addEventListener("click", () => {
    if (!emailEl.value.trim() || !passwordEl.value.trim()) {
      errorEl.textContent = "Enter both an e-mail and a password.";
      errorEl.hidden = false;
      return;
    }
    attemptLogin({ email: emailEl.value.trim(), password: passwordEl.value });
  });
}

// ---------- Screen 2: wallets ----------

function renderWallets(wallets) {
  state.wallets = wallets;
  const list = document.getElementById("wallet-list");
  list.innerHTML = wallets
    .map(
      (w) => `
      <div class="wallet-card" data-id="${w._id}">
        <span class="wallet-card-name">${w.name}</span>
        <span class="wallet-card-balance"><strong>${Number(w.balance).toFixed(2)}</strong> ${w.currency}</span>
      </div>`
    )
    .join("");

  list.querySelectorAll(".wallet-card").forEach((card) => {
    card.addEventListener("click", async () => {
      try {
        const data = await apiFetch("/api/wallets/select", {
          method: "POST",
          body: JSON.stringify({ wallet_id: card.dataset.id }),
        });

        state.wallet = { id: data.wallet_id, name: data.wallet_name };

        const info = document.getElementById("wallet-info");
        info.hidden = false;
        document.getElementById("wallet-info-name").textContent = data.wallet_name;
        document.getElementById("wallet-info-range").textContent = "No bank statement loaded yet";

        apiFetch("/api/categories")
          .then((categories) => {
            state.categories = categories;
            refreshManualAddCategories();
          })
          .catch((err) => console.error("Failed to load categories:", err));

        showScreen("screen-dashboard");
        loadStatementInfo();
      } catch (e) {
        alert(e.message);
      }
    });
  });
}

// ---------- Screen 3: load from file ----------

function formatDateRange([start, end]) {
  // Parse "YYYY-MM-DD" as local calendar date components, not UTC - passing
  // the string straight to `new Date()` parses it as UTC midnight, which
  // then shifts a day off when formatted back in a negative-offset timezone.
  const fmt = (str) => {
    const [year, month, day] = str.split("-").map(Number);
    return new Date(year, month - 1, day).toLocaleDateString(undefined, {
      day: "numeric",
      month: "short",
      year: "numeric",
    });
  };
  return `${fmt(start)} – ${fmt(end)}`;
}

function applyStatementInfo(data) {
  const statusEl = document.getElementById("dashboard-status");
  const continueBtn = document.getElementById("continue-detected-btn");

  if (data.found) {
    state.statement = { filename: data.filename, rangeText: formatDateRange(data.date_range) };
    statusEl.innerHTML = `Found <code>${data.filename}</code> (${state.statement.rangeText})`;
    document.getElementById("wallet-info-range").textContent = state.statement.rangeText;
    continueBtn.hidden = false;
  } else {
    state.statement = null;
    statusEl.textContent = "No bank statement found automatically in ./bank_statements.";
    continueBtn.hidden = true;
  }
}

async function loadStatementInfo() {
  const statusEl = document.getElementById("dashboard-status");
  document.getElementById("continue-detected-btn").hidden = true;
  document.getElementById("choose-file-btn").hidden = true;
  statusEl.textContent = "Looking in ./bank_statements...";

  try {
    const data = await apiFetch("/api/statement");
    applyStatementInfo(data);
  } catch (e) {
    state.statement = null;
    statusEl.textContent = e.message;
  }

  document.getElementById("choose-file-btn").hidden = false;
}

async function proceedToReview() {
  showLoading("Matching transactions against your presets...");
  try {
    const data = await apiFetch("/api/transactions/review");
    state.transactions = data.transactions;
  } catch (e) {
    hideLoading();
    alert(e.message);
    return;
  }
  hideLoading();

  renderReview();
  showScreen("screen-review");
}

function initDashboard() {
  document.getElementById("continue-detected-btn").addEventListener("click", proceedToReview);

  document.getElementById("choose-file-btn").addEventListener("click", () => {
    document.getElementById("file-input").click();
  });

  document.getElementById("file-input").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;

    const formData = new FormData();
    formData.append("file", file);

    showLoading(`Uploading ${file.name}...`);
    try {
      const response = await fetch("/api/statement/upload", { method: "POST", body: formData });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || "Upload failed.");
      hideLoading();
      applyStatementInfo(data);
    } catch (err) {
      hideLoading();
      alert(err.message);
    }
  });
}

// ---------- Dashboard: add a single transaction manually ----------
// Same /api/transactions/manual endpoint the entries screen uses - handy
// both as a standalone feature and for testing an insert without a batch.

function refreshManualAddCategories() {
  const typeEl = document.getElementById("manual-add-type");
  const categoryEl = document.getElementById("manual-add-category");
  const subcategoryEl = document.getElementById("manual-add-subcategory");

  const type = typeEl.value;
  const defaultCategory = Object.keys(state.categories[type] || {})[0];
  categoryEl.innerHTML = categoryOptions(type, defaultCategory);
  subcategoryEl.innerHTML = subcategoryOptions(type, categoryEl.value, null);
}

async function submitManualAdd() {
  const dateEl = document.getElementById("manual-add-date");
  const amountEl = document.getElementById("manual-add-amount");
  const typeEl = document.getElementById("manual-add-type");
  const categoryEl = document.getElementById("manual-add-category");
  const subcategoryEl = document.getElementById("manual-add-subcategory");
  const noteEl = document.getElementById("manual-add-note");
  const errorEl = document.getElementById("manual-add-error");

  const date = dateEl.value;
  const amountValue = parseFloat(amountEl.value);
  const note = noteEl.value.trim();

  if (!date || !(amountValue > 0) || !note) {
    errorEl.textContent = "Date, a positive amount, and a note are all required.";
    errorEl.hidden = false;
    return;
  }
  errorEl.hidden = true;

  const type = typeEl.value;
  const signedAmount = type === "expense" ? -amountValue : amountValue;

  showLoading("Adding transaction to MoneyLover...");
  try {
    await apiFetch("/api/transactions/manual", {
      method: "POST",
      body: JSON.stringify({
        date,
        amount: signedAmount,
        type,
        category: categoryEl.value,
        subcategory: subcategoryEl.value || null,
        note,
      }),
    });
  } catch (e) {
    hideLoading();
    errorEl.textContent = e.message;
    errorEl.hidden = false;
    return;
  }
  hideLoading();

  amountEl.value = "";
  noteEl.value = "";
  noteEl.focus();
}

function initManualAdd() {
  document.getElementById("manual-add-date").value = new Date().toISOString().slice(0, 10);
  refreshManualAddCategories();

  document.getElementById("manual-add-type").addEventListener("change", refreshManualAddCategories);

  document.getElementById("manual-add-category").addEventListener("change", () => {
    const type = document.getElementById("manual-add-type").value;
    const category = document.getElementById("manual-add-category").value;
    document.getElementById("manual-add-subcategory").innerHTML = subcategoryOptions(type, category, null);
  });

  document.getElementById("manual-add-submit").addEventListener("click", submitManualAdd);
}

// ---------- Screen 4: review recognized categories ----------

function renderReview() {
  const counts = { existing: 0, preset: 0, manual: 0 };
  state.transactions.forEach((t) => counts[t.origin]++);

  const filename = state.statement ? state.statement.filename : "the bank statement";
  document.getElementById("review-subtitle").textContent =
    `${state.transactions.length} transactions found in ${filename}.`;

  document.getElementById("review-summary").innerHTML = `
    <span class="summary-chip"><strong>${counts.existing}</strong> already in MoneyLover</span>
    <span class="summary-chip"><strong>${counts.preset}</strong> recognized from presets</span>
    <span class="summary-chip"><strong>${counts.manual}</strong> need manual entry</span>
  `;

  document.getElementById("review-list").innerHTML = state.transactions
    .map((tx) => {
      const { cls, label } = statusInfo(tx);
      return `
        <div class="tx-row ${cls}">
          <div class="tx-row-main">
            <span class="tx-date">${tx.date}</span>
            <span class="tx-note">${tx.note}</span>
            <span class="tx-amount ${tx.amount < 0 ? "negative" : "positive"}">${formatAmount(tx.amount)}</span>
            <span class="tx-category">${categoryDisplay(tx)}</span>
            <span class="tx-status">${label} <span class="dot dot-${cls}"></span></span>
          </div>
        </div>`;
    })
    .join("");

  const confirmBtn = document.getElementById("confirm-insert-btn");
  const presetCount = counts.preset;
  confirmBtn.textContent =
    presetCount > 0
      ? `Confirm & insert ${presetCount} recognized transaction${presetCount === 1 ? "" : "s"}`
      : "Continue to manual entries";
}

async function goToEntries() {
  state.expandedId = firstManualId();
  renderEntries();
  showScreen("screen-entries");
}

function initReview() {
  document.getElementById("confirm-insert-btn").addEventListener("click", async () => {
    const presetCount = state.transactions.filter((t) => t.origin === "preset").length;

    if (presetCount === 0) {
      await goToEntries();
      return;
    }

    showLoading(`Adding ${presetCount} recognized transaction${presetCount === 1 ? "" : "s"} to MoneyLover...`);
    try {
      await apiFetch("/api/transactions/insert-recognized", { method: "POST" });
      // Re-fetch rather than patch locally - the insert re-runs the
      // is_in_ml comparison server-side, so this is the source of truth
      // for what's actually in MoneyLover now.
      const data = await apiFetch("/api/transactions/review");
      state.transactions = data.transactions;
    } catch (e) {
      hideLoading();
      alert(e.message);
      return;
    }
    hideLoading();

    await goToEntries();
  });
}

// ---------- Screen 5: manual entries ----------

function firstManualId() {
  const first = state.transactions.find((t) => t.origin === "manual" && !t.filled);
  return first ? first.id : null;
}

function renderEntrySummary() {
  const counts = {};
  state.transactions.forEach((t) => {
    const { cls } = statusInfo(t);
    counts[cls] = (counts[cls] || 0) + 1;
  });
  document.getElementById("summary").innerHTML = `
    <span class="summary-chip"><strong>${state.transactions.length}</strong> transactions</span>
    <span class="summary-chip"><strong>${counts.added || 0}</strong> already added</span>
    <span class="summary-chip"><strong>${counts.autofilled || 0}</strong> added</span>
    <span class="summary-chip"><strong>${counts.manual || 0}</strong> need review</span>
  `;
}

function renderEntryRow(tx) {
  const { cls, label } = statusInfo(tx);
  const isManual = cls === "manual";
  const isExpanded = isManual && tx.id === state.expandedId;
  const rowClasses = ["tx-row", cls, isExpanded ? "expanded" : ""].join(" ").trim();

  const statusExtra = isManual
    ? `<span class="chevron">&#9656;</span>`
    : `<span class="dot dot-${cls}"></span>`;

  // A <select> with no explicitly-selected option defaults to its first one,
  // so resolve the effective category up front and use it consistently for
  // both dropdowns - otherwise the sub-category list can start out of sync
  // with what the category dropdown is actually showing.
  const defaultCategory = tx.category ?? Object.keys(state.categories[tx.type] || {})[0];

  const detail = isManual
    ? `
      <div class="tx-detail">
        <div class="tx-detail-inner">
          <div class="tx-detail-form">
            <div class="tx-detail-row">
              <div class="field">
                <label>Type</label>
                <select data-role="type" data-id="${tx.id}">
                  <option value="expense" ${tx.type === "expense" ? "selected" : ""}>Expense</option>
                  <option value="income" ${tx.type === "income" ? "selected" : ""}>Income</option>
                </select>
              </div>
              <div class="field">
                <label>Category</label>
                <select data-role="category" data-id="${tx.id}">
                  ${categoryOptions(tx.type, defaultCategory)}
                </select>
              </div>
              <div class="field">
                <label>Sub-category (optional)</label>
                <select data-role="subcategory" data-id="${tx.id}">
                  ${subcategoryOptions(tx.type, defaultCategory, tx.subcategory)}
                </select>
              </div>
            </div>
            <div class="tx-detail-row tx-detail-row--note">
              <div class="field" data-role="note-field" data-id="${tx.id}">
                <label>Note / description (required)</label>
                <input type="text" data-role="note" data-id="${tx.id}" placeholder="e.g. Dinner with friends" value="${tx.noteInput ?? ""}" />
                <p class="field-error" data-role="note-error" data-id="${tx.id}" hidden>A note is required.</p>
              </div>
              <button class="btn btn-primary" data-action="save" data-id="${tx.id}">Add to MoneyLover</button>
              <button class="btn btn-skip" data-action="skip" data-id="${tx.id}">Skip</button>
            </div>
          </div>
        </div>
      </div>`
    : "";

  return `
    <div class="${rowClasses}" data-id="${tx.id}">
      <div class="tx-row-main" data-role="toggle" data-id="${tx.id}">
        <span class="tx-date">${tx.date}</span>
        <span class="tx-note">${tx.note}</span>
        <span class="tx-amount ${tx.amount < 0 ? "negative" : "positive"}">${formatAmount(tx.amount)}</span>
        <span class="tx-category">${categoryDisplay(tx)}</span>
        <span class="tx-status">${label} ${statusExtra}</span>
      </div>
      ${detail}
    </div>`;
}

function renderEntries() {
  document.getElementById("tx-list").innerHTML = state.transactions.map(renderEntryRow).join("");
  renderEntrySummary();
}

function advanceToNextManual(currentId) {
  const remaining = state.transactions.filter(
    (t) => t.origin === "manual" && !t.filled && t.id !== currentId
  );
  state.expandedId = remaining.length ? remaining[0].id : null;
}

async function handleEntriesClick(e) {
  const toggle = e.target.closest('[data-role="toggle"]');
  if (toggle) {
    const id = Number(toggle.dataset.id);
    const tx = state.transactions.find((t) => t.id === id);
    if (tx && statusInfo(tx).cls === "manual") {
      state.expandedId = state.expandedId === id ? null : id;
      renderEntries();
    }
    return;
  }

  const action = e.target.closest("[data-action]");
  if (!action) return;

  const id = Number(action.dataset.id);
  const tx = state.transactions.find((t) => t.id === id);

  if (action.dataset.action === "skip") {
    advanceToNextManual(id);
    renderEntries();
    return;
  }

  if (action.dataset.action === "save") {
    const noteInput = document.querySelector(`input[data-role="note"][data-id="${id}"]`);
    const noteError = document.querySelector(`p[data-role="note-error"][data-id="${id}"]`);
    const noteField = document.querySelector(`div[data-role="note-field"][data-id="${id}"]`);
    const note = noteInput.value.trim();

    if (!note) {
      noteError.hidden = false;
      noteField.classList.add("invalid");
      return;
    }

    const typeSelect = document.querySelector(`select[data-role="type"][data-id="${id}"]`);
    const categorySelect = document.querySelector(`select[data-role="category"][data-id="${id}"]`);
    const subcategorySelect = document.querySelector(`select[data-role="subcategory"][data-id="${id}"]`);

    const type = typeSelect.value;
    const category = categorySelect.value;
    const subcategory = subcategorySelect.value || null;

    showLoading("Adding transaction to MoneyLover...");
    try {
      await apiFetch("/api/transactions/manual", {
        method: "POST",
        body: JSON.stringify({
          date: tx.date,
          amount: tx.amount,
          type,
          category,
          subcategory,
          note,
        }),
      });
    } catch (err) {
      hideLoading();
      alert(err.message);
      return;
    }
    hideLoading();

    tx.type = type;
    tx.category = category;
    tx.subcategory = subcategory;
    tx.note = note;
    tx.filled = true;

    advanceToNextManual(id);
    renderEntries();
  }
}

// Cascades type -> category -> sub-category without a full re-render, so an
// in-progress note doesn't get wiped out.
function handleEntriesChange(e) {
  const role = e.target.dataset.role;
  const id = e.target.dataset.id;
  if (!id) return;

  if (role === "type") {
    const categorySelect = document.querySelector(`select[data-role="category"][data-id="${id}"]`);
    const subcategorySelect = document.querySelector(`select[data-role="subcategory"][data-id="${id}"]`);
    categorySelect.innerHTML = categoryOptions(e.target.value, null);
    subcategorySelect.innerHTML = subcategoryOptions(e.target.value, categorySelect.value, null);
  } else if (role === "category") {
    const typeSelect = document.querySelector(`select[data-role="type"][data-id="${id}"]`);
    const subcategorySelect = document.querySelector(`select[data-role="subcategory"][data-id="${id}"]`);
    subcategorySelect.innerHTML = subcategoryOptions(typeSelect.value, e.target.value, null);
  }
}

// ---------- Boot ----------

initAuth();
initDashboard();
initManualAdd();
initReview();
initLogout();
initChangeWallet();
document.getElementById("tx-list").addEventListener("click", handleEntriesClick);
document.getElementById("tx-list").addEventListener("change", handleEntriesChange);
boot();
