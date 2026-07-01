// Static mock of the full MoneyMover workflow (see example.py / example.ipynb
// for the equivalent CLI sequence). There is no real backend behind this yet -
// all "network" steps are simulated with timeouts over in-memory mock data.

const MOCK_WALLETS = [
  { id: "w1", name: "Main Wallet", balance: 3182.44, currency: "EUR" },
  { id: "w2", name: "Savings", balance: 12500.0, currency: "EUR" },
];

// Parent category -> list of sub-categories (empty array = no sub-categories).
const MOCK_CATEGORIES = {
  expense: {
    Groceries: ["Supermarket", "Market", "Bakery"],
    Rent: [],
    Transport: ["Public transport", "Fuel", "Parking"],
    "Eating out": ["Restaurant", "Coffee", "Takeaway"],
    Utilities: ["Electricity", "Water", "Internet", "Gas"],
    Health: ["Pharmacy", "Doctor", "Insurance"],
  },
  income: {
    Salary: [],
    Refund: [],
    "Other income": ["Gift", "Interest"],
  },
};

const STATEMENT_FILE = "NL00INGB0123456789_15-12-2023_31-12-2023.csv";
const STATEMENT_RANGE = "15 Dec – 31 Dec 2023";

// origin: 'existing' (already in MoneyLover) | 'preset' (recognized) | 'manual' (needs entry)
const MOCK_TRANSACTIONS = [
  { id: 1, date: "2023-12-16", note: "Albert Heijn", amount: -34.21, category: "Groceries", type: "expense", origin: "preset" },
  { id: 2, date: "2023-12-16", note: "NS Groep", amount: -12.4, category: "Transport", type: "expense", origin: "existing" },
  { id: 3, date: "2023-12-18", note: "Employer B.V.", amount: 2450.0, category: "Salary", type: "income", origin: "existing" },
  { id: 4, date: "2023-12-19", note: "Unknown card payment XYZ", amount: -18.5, category: null, type: "expense", origin: "manual" },
  { id: 5, date: "2023-12-20", note: "Vattenfall", amount: -64.0, category: "Utilities", type: "expense", origin: "preset" },
  { id: 6, date: "2023-12-22", note: "Restaurant De Kroon", amount: -41.9, category: null, type: "expense", origin: "manual" },
  { id: 7, date: "2023-12-23", note: "Refund - bol.com", amount: 22.99, category: null, type: "income", origin: "manual" },
  { id: 8, date: "2023-12-27", note: "Albert Heijn", amount: -19.85, category: "Groceries", type: "expense", origin: "preset" },
];

const state = {
  wallet: null,
  transactions: MOCK_TRANSACTIONS,
  expandedId: null,
};

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
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
  return Object.keys(MOCK_CATEGORIES[type])
    .map((c) => `<option value="${c}" ${c === selected ? "selected" : ""}>${c}</option>`)
    .join("");
}

function subcategoryOptions(type, category, selected) {
  const subcategories = MOCK_CATEGORIES[type]?.[category] || [];
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

// ---------- Screen 1: auth ----------

function initAuth() {
  const emailEl = document.getElementById("auth-email");
  const passwordEl = document.getElementById("auth-password");
  const errorEl = document.getElementById("auth-error");

  document.getElementById("auth-submit").addEventListener("click", async () => {
    if (!emailEl.value.trim() || !passwordEl.value.trim()) {
      errorEl.hidden = false;
      return;
    }
    errorEl.hidden = true;

    showLoading("Requesting access token...");
    await wait(700);
    hideLoading();

    renderWallets();
    showScreen("screen-wallets");
  });
}

// ---------- Screen 2: wallets ----------

function renderWallets() {
  const list = document.getElementById("wallet-list");
  list.innerHTML = MOCK_WALLETS.map(
    (w) => `
      <div class="wallet-card" data-id="${w.id}">
        <span class="wallet-card-name">${w.name}</span>
        <span class="wallet-card-balance"><strong>${w.balance.toFixed(2)}</strong> ${w.currency}</span>
      </div>`
  ).join("");

  list.querySelectorAll(".wallet-card").forEach((card) => {
    card.addEventListener("click", () => {
      state.wallet = MOCK_WALLETS.find((w) => w.id === card.dataset.id);

      const info = document.getElementById("wallet-info");
      info.hidden = false;
      document.getElementById("wallet-info-name").textContent = state.wallet.name;
      document.getElementById("wallet-info-range").textContent = "No bank statement loaded yet";

      showScreen("screen-dashboard");
    });
  });
}

// ---------- Screen 3: load from file ----------

function initDashboard() {
  document.getElementById("load-file-btn").addEventListener("click", async () => {
    showLoading(`Scanning ./bank_statements for the latest ING export...`);
    await wait(800);

    document.getElementById("dashboard-status").innerHTML =
      `Found <code>${STATEMENT_FILE}</code> (${STATEMENT_RANGE})`;
    document.getElementById("wallet-info-range").textContent = STATEMENT_RANGE;

    showLoading("Matching transactions against your presets...");
    await wait(700);
    hideLoading();

    renderReview();
    showScreen("screen-review");
  });
}

// ---------- Screen 4: review recognized categories ----------

function renderReview() {
  const counts = { existing: 0, preset: 0, manual: 0 };
  state.transactions.forEach((t) => counts[t.origin]++);

  document.getElementById("review-subtitle").textContent =
    `${state.transactions.length} transactions found in ${STATEMENT_FILE}.`;

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

function initReview() {
  document.getElementById("confirm-insert-btn").addEventListener("click", async () => {
    showLoading("Adding recognized transactions to MoneyLover...");
    await wait(900);
    hideLoading();

    state.expandedId = firstManualId();
    renderEntries();
    showScreen("screen-entries");
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
  const defaultCategory = tx.category ?? Object.keys(MOCK_CATEGORIES[tx.type])[0];

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

function handleEntriesClick(e) {
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

    tx.type = typeSelect.value;
    tx.category = categorySelect.value;
    tx.subcategory = subcategorySelect.value || null;
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
initReview();
document.getElementById("tx-list").addEventListener("click", handleEntriesClick);
document.getElementById("tx-list").addEventListener("change", handleEntriesChange);
