const $ = (id) => document.getElementById(id);
let token = sessionStorage.getItem("jamieControllerToken") || "";
let loading = false;
const openScreens = new Set();

function message(value, good = false) {
  $("message").textContent = value;
  $("message").className = good ? "ok" : "";
}

function connected(yes) {
  $("connection").textContent = yes ? "Connected" : "Disconnected";
  $("connection").classList.toggle("on", yes);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { Authorization: `Bearer ${token}`, ...options.headers },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(response.status === 401 ? "Controller token was rejected." : body.error || `HTTP ${response.status}`);
  return body;
}

function element(tag, className, content) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content) node.textContent = content;
  return node;
}

function empty(container, text) {
  container.replaceChildren(element("p", "empty", text));
}

function screenCard(title, detail, screen, id, status, stop, apps = {}) {
  const card = element("article", "card");
  card.dataset.key = id;
  const head = element("div", "card-head");
  head.append(element("h3", "", title), element("span", "status", status));
  card.append(head, element("p", "meta", detail));

  const actions = element("div", "actions");
  const toggle = element("button", "secondary", openScreens.has(id) ? "Hide screen" : "View screen");
  toggle.type = "button";
  const link = element("a", "button-link secondary", "Open in new tab");
  link.href = screen;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  if (!screen) {
    toggle.disabled = true;
    link.removeAttribute("href");
    link.setAttribute("aria-disabled", "true");
  }
  actions.append(toggle, link);
  for (const [port, url] of Object.entries(apps)) {
    const app = element("a", "button-link secondary", `App :${port}`);
    app.href = url;
    app.target = "_blank";
    app.rel = "noopener noreferrer";
    actions.append(app);
  }
  if (stop) {
    const button = element("button", "danger", "Stop Jamie");
    button.type = "button";
    button.onclick = async () => {
      button.disabled = true;
      try {
        await api(`/jamies/${encodeURIComponent(id)}`, { method: "DELETE" });
        openScreens.delete(id);
        await refresh();
      } catch (error) {
        button.disabled = false;
        message(error.message);
      }
    };
    actions.append(button);
  }
  card.append(actions);

  const viewer = element("iframe", "viewer");
  viewer.title = `${title} screen`;
  viewer.classList.toggle("open", openScreens.has(id));
  if (openScreens.has(id)) viewer.src = screen;
  toggle.onclick = () => {
    const open = !openScreens.has(id);
    if (open) openScreens.add(id);
    else openScreens.delete(id);
    viewer.classList.toggle("open", open);
    viewer.src = open ? screen : "about:blank";
    toggle.textContent = open ? "Hide screen" : "View screen";
  };
  card.append(viewer);
  return card;
}

function render(jamies, logins) {
  const loginRows = logins.map((login) => ({
    title: `Google account: ${login.account}`, detail: "Sign in, then close the Chromium window to save this account.",
    screen: login.screen, id: `login:${login.account}`, status: "Signing in", stop: false,
  }));
  const jamieRows = jamies.map((jamie) => ({
    title: jamie.id,
    detail: `${jamie.meet_url} · ${jamie.env} room · ${jamie.personality} personality · ${jamie.agent} agent · Google: ${jamie.google}`,
    screen: jamie.screen, id: jamie.id, status: jamie.status || jamie.state, stop: true, apps: jamie.apps,
  }));
  renderCards($("logins"), loginRows, "No Google sign-in session is running.");
  renderCards($("jamies"), jamieRows, "No Jamies are running. Start one from the Chrome extension.");
}

function renderCards(container, rows, emptyText) {
  if (!rows.length) {
    for (const card of container.querySelectorAll("article.card")) openScreens.delete(card.dataset.key);
    return empty(container, emptyText);
  }
  container.querySelector(".empty")?.remove();
  const cards = new Map([...container.querySelectorAll("article.card")].map((card) => [card.dataset.key, card]));
  const keep = new Set(rows.map((row) => row.id));
  for (const row of rows) {
    const card = cards.get(row.id);
    if (card) {
      card.querySelector("h3").textContent = row.title;
      card.querySelector(".meta").textContent = row.detail;
      card.querySelector(".status").textContent = row.status;
    } else {
      container.append(screenCard(row.title, row.detail, row.screen, row.id, row.status, row.stop, row.apps));
    }
  }
  for (const [id, card] of cards) if (!keep.has(id)) {
    openScreens.delete(id);
    card.remove();
  }
}

async function refresh() {
  if (!token || loading) return;
  loading = true;
  try {
    const [jamies, logins] = await Promise.all([api("/jamies"), api("/logins")]);
    connected(true);
    message("");
    render(jamies, logins);
  } catch (error) {
    connected(false);
    message(error.message);
  } finally {
    loading = false;
  }
}

$("connect").onsubmit = (event) => {
  event.preventDefault();
  token = $("token").value.trim();
  sessionStorage.setItem("jamieControllerToken", token);
  refresh();
};
$("refresh").onclick = refresh;
if (token) {
  $("token").value = token;
  refresh();
}
setInterval(refresh, 5000);
