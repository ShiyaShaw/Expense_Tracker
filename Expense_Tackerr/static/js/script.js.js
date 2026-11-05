// Frontend logic: talks to the Flask API using fetch()
const $ = (id) => document.getElementById(id);
let loggedIn = false;

// Escape text so user input cannot inject HTML
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const money = (n) => "Rs. " + Number(n).toLocaleString("en-IN", {maximumFractionDigits: 2});

// Show a message (green = ok, red = error)
function notify(text, ok = false) {
  const m = $("msg");
  m.textContent = text;
  m.className = "msg " + (ok ? "ok" : "err");
  m.hidden = false;
  setTimeout(() => (m.hidden = true), 4000);
}

// Wrapper around fetch with error handling
async function api(url, method = "GET", body = null) {
  try {
    const res = await fetch(url, {
      method,
      headers: {"Content-Type": "application/json"},
      body: body ? JSON.stringify(body) : null,
    });
    const data = await res.json();
    if (!res.ok) { notify(data.error || "Something went wrong."); return null; }
    return data;
  } catch (e) {
    notify("Cannot reach the server. Is app.py running?");
    return null;
  }
}

// ----- 1. Loading screen: counts 0% to 100%, then fades out -----
let pct = 0;
const timer = setInterval(() => {
  pct += 1;
  $("percent").textContent = pct + "%";
  if (pct >= 100) {
    clearInterval(timer);
    $("loader").classList.add("hide");
  }
}, 25);

// ----- Navigation -----
function showPage(name) {
  if (!loggedIn && name !== "auth") { name = "auth"; }
  document.querySelectorAll(".page").forEach((p) => (p.hidden = p.id !== name));
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("active", a.dataset.page === name));
  if (name === "dashboard") loadSummary();
  if (name === "expenses") loadExpenses();
  if (name === "reports") loadCharts();
}
document.querySelectorAll("nav a").forEach((a) => (a.onclick = () => showPage(a.dataset.page)));
$("auth-btn").onclick = () => showPage("auth");

// ----- Auth -----
function setUser(name) {
  loggedIn = !!name;
  $("auth-btn").hidden = loggedIn;
  $("user-info").hidden = !loggedIn;
  $("username").textContent = name || "";
}
async function authenticate(path) {
  const d = await api(path, "POST", {username: $("a-user").value, password: $("a-pass").value});
  if (d) { setUser(d.username); $("a-pass").value = ""; showPage("dashboard"); }
}
$("login-btn").onclick = () => authenticate("/api/login");
$("signup-btn").onclick = () => authenticate("/api/signup");
$("logout-btn").onclick = async () => { await api("/api/logout", "POST"); setUser(null); showPage("auth"); };

// ----- Dashboard summary cards -----
const month = () => $("month").value;
async function loadSummary() {
  const d = await api("/api/summary?month=" + month());
  if (!d) return;
  $("c-total").textContent = money(d.total);
  $("c-all").textContent = money(d.total_all);
  $("c-avg").textContent = money(d.average);
  $("c-high").textContent = d.highest ? `${money(d.highest.amount)} (${d.highest.category})` : "-";
  $("c-low").textContent = d.lowest ? `${money(d.lowest.amount)} (${d.lowest.category})` : "-";
  const cats = Object.entries(d.by_category);
  $("c-cat").innerHTML = cats.length
    ? cats.map(([k, v]) => `<div class="cat-line"><span>${esc(k)}</span><span>${money(v)}</span></div>`).join("")
    : '<p class="empty">No data yet</p>';
}
$("month").onchange = loadSummary;
$("clear-month").onclick = () => { $("month").value = ""; loadSummary(); };

// ----- Sample data -----
$("sample-add").onclick = async () => { if (await api("/api/sample", "POST", {action: "add"})) { notify("Sample data added.", true); loadSummary(); } };
$("sample-remove").onclick = async () => { if (await api("/api/sample", "POST", {action: "remove"})) { notify("Sample data removed.", true); loadSummary(); } };

// ----- Add expense -----
$("e-date").value = new Date().toISOString().slice(0, 10);
$("add-btn").onclick = async () => {
  const d = await api("/api/expenses", "POST", {
    date: $("e-date").value, category: $("e-cat").value,
    amount: $("e-amt").value, description: $("e-desc").value,
  });
  if (d) {
    notify("Expense saved!", true);
    $("e-amt").value = ""; $("e-desc").value = "";
    loadExpenses(); loadSummary(); loadCharts();   // refresh everything
  }
};

// ----- Expense table -----
async function loadExpenses() {
  const d = await api(`/api/expenses?sort=${$("sort-field").value}&order=${$("sort-order").value}`);
  if (!d) return;
  $("tbody").innerHTML = d.expenses.length
    ? d.expenses.map((e) => `<tr><td>${esc(e.date)}</td><td>${esc(e.category)}</td><td>${money(e.amount)}</td>
        <td>${esc(e.description)}</td><td><button class="btn del" onclick="removeExpense(${e.id})">Delete</button></td></tr>`).join("")
    : '<tr><td colspan="5" class="empty">No data yet</td></tr>';
}
$("sort-field").onchange = loadExpenses;
$("sort-order").onchange = loadExpenses;
async function removeExpense(id) {
  if (!confirm("Delete this expense?")) return;
  if (await api("/api/expenses/" + id, "DELETE")) { loadExpenses(); loadSummary(); loadCharts(); }
}

// ----- Charts -----
async function loadCharts() {
  for (const box of document.querySelectorAll(".chart")) {
    const img = box.querySelector("img"), p = box.querySelector("p");
    const d = await api(`/api/chart/${box.dataset.kind}?month=${month()}`);
    if (d && d.image) { img.src = "data:image/png;base64," + d.image; img.hidden = true; img.hidden = false; p.hidden = true; }
    else { img.hidden = true; p.hidden = false; p.textContent = "No data yet"; }
  }
}

// ----- On page load: check if already logged in -----
(async () => {
  const d = await api("/api/me");
  setUser(d && d.username);
  showPage("dashboard");
})();