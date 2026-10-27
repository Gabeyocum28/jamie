// Popup: picks a room, personality and agent, and asks the controller to send a Jamie into the meeting.
const $ = (id) => document.getElementById(id);
const cfg = await chrome.storage.local.get({ url: "http://localhost:7070", token: "", env: "", personality: "", agent: "", look: {} });

async function api(method, path, body) {
  const r = await fetch(cfg.url.replace(/\/$/, "") + path, {
    method,
    headers: { Authorization: `Bearer ${cfg.token}`, "Content-Type": "application/json" },
    body: body && JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}

function status(msg, err = false) {
  $("status").textContent = msg;
  $("status").className = err ? "err" : "";
}

function fill(select, items, saved) {
  select.disabled = false;
  select.replaceChildren(...items.map((v) => new Option(v, v, false, v === saved)));
}

async function list() {
  const jamies = await api("GET", "/jamies");
  $("jamies").replaceChildren(...jamies.map((j) => {
    const li = document.createElement("li");
    li.className = j.meet_url.split("/").pop() === $("meet").value.split("?")[0].split("/").pop() ? "here" : "";
    li.append(`${j.env} · ${j.personality} · ${j.agent} — ${j.meet_url.split("/").pop()} `);
    const watch = Object.assign(document.createElement("a"), { href: j.screen, target: "_blank", textContent: "watch" });
    const stop = Object.assign(document.createElement("button"), { textContent: "Stop" });
    stop.onclick = async () => {
      stop.disabled = true;
      try { await api("DELETE", `/jamies/${j.id}`); await list(); } catch (e) { status(e.message, true); }
    };
    const apps = Object.entries(j.apps).map(([port, href]) =>
      Object.assign(document.createElement("a"), { href, target: "_blank", textContent: ` :${port}` }));
    li.append(watch, ...apps, stop);
    return li;
  }));
  if (!jamies.length) $("jamies").textContent = "None.";
}

async function load() {
  try {
    const o = await api("GET", "/options");
    fill($("env"), o.environments, cfg.env);
    fill($("personality"), o.personalities, cfg.personality);
    fill($("agent"), o.agents, cfg.agent);
    $("start").disabled = false;
    status("");
    await list();
  } catch (e) {
    status(`Can't reach the controller: ${e.message}`, true);
    $("settings").open = true;
  }
}

$("form").onsubmit = async (e) => {
  e.preventDefault();
  const pick = { env: $("env").value, personality: $("personality").value, agent: $("agent").value };
  Object.assign(cfg, pick);
  chrome.storage.local.set(pick);  // remember the last choices
  $("start").disabled = true;
  status("Starting… the first run of a room builds its image and can take a few minutes.");
  try {
    const j = await api("POST", "/jamies", { meet_url: $("meet").value.trim(), ...pick, look: cfg.look });
    status(`${j.id} is joining. Admit it in Meet.`);
    await list();
  } catch (err) {
    status(err.message, true);
  } finally {
    $("start").disabled = false;
  }
};

$("save").onclick = async () => {
  Object.assign(cfg, { url: $("url").value.trim(), token: $("token").value.trim() });
  try {  // a controller off localhost (the homelab) needs permission to reach it
    await chrome.permissions.request({ origins: [new URL(cfg.url).origin + "/*"] });
  } catch (e) {
    return status(`Bad controller URL: ${e.message}`, true);
  }
  await chrome.storage.local.set({ url: cfg.url, token: cfg.token });
  load();
};

// Look: one dropdown per part, a live preview that cycles through Jamie's states
const avatar = JamieAvatar.create($("preview"), cfg.look);
const pretty = (s) => s[0].toUpperCase() + s.slice(1).replace("-", " ");
for (const [part, choices] of Object.entries(JamieAvatar.OPTIONS)) {
  const label = Object.assign(document.createElement("label"), { htmlFor: `look-${part}`, textContent: pretty(part) });
  const select = Object.assign(document.createElement("select"), { id: `look-${part}` });
  choices.forEach((c) => select.add(new Option(pretty(c), c, false, c === avatar.look[part])));
  select.onchange = () => {
    avatar.look[part] = select.value;
    cfg.look = { ...avatar.look };
    chrome.storage.local.set({ look: cfg.look });
  };
  const cell = document.createElement("div");
  cell.append(label, select);
  $("looks").append(cell);
}
setInterval(avatar.draw, 1000 / 30);
const states = ["listening", "thinking", "talking"];
setInterval(() => (avatar.state = states[(states.indexOf(avatar.state) + 1) % 3]), 3000);

$("url").value = cfg.url;
$("token").value = cfg.token;
const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
if (tab?.url?.startsWith("https://meet.google.com/")) $("meet").value = tab.url.split("?")[0];
if (cfg.token) load();
else {
  $("settings").open = true;
  status("Paste the controller token from .env to get started.");
}
