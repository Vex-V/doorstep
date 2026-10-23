// The family's page: Set up (alerts, visits), Notifications, View (the clips).
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

let data = null;
let selected = null;     // the event shown in View
let fresh = null;        // the alert just added: its card is outlined for a moment
let seenUpTo = 0;        // notifications up to this time have been looked at

async function api(path, opts = {}) {
  const res = await fetch(path, {headers: {"Content-Type": "application/json"}, ...opts});
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || res.statusText);
  return body;
}

function fmt(ms, opts = {}) {
  return ms ? new Intl.DateTimeFormat(undefined, {hour: "2-digit", minute: "2-digit",
                                                  timeZone: data.tz, ...opts}).format(new Date(ms)) : "";
}

function camName(id) {
  const c = (data.cameras || []).find((c) => c.id === id);
  return c ? c.name : id;
}

// -- tabs -------------------------------------------------------------------------
function tab() { return (location.hash || "#notifications").slice(1); }

function showTab() {
  const t = ["setup", "notifications", "view"].includes(tab()) ? tab() : "notifications";
  for (const name of ["setup", "notifications", "view"]) {
    $(`tab-${name}`).hidden = name !== t;
    document.querySelector(`[data-tab="${name}"]`).classList.toggle("on", name === t);
  }
  if (t === "notifications" && data) { seenUpTo = Math.max(seenUpTo, data.now_ms); renderCount(); }
}
window.addEventListener("hashchange", showTab);

function watch(eventId, offset = 0) {
  if (!eventId) return;
  location.hash = "#view";
  select(eventId, offset);
}

// -- loading ----------------------------------------------------------------------
async function load() {
  data = await api("/api/timeline");
  render();
}

let reloadTimer = null;
function reloadSoon() {
  clearTimeout(reloadTimer);
  reloadTimer = setTimeout(load, 400);
}

function render() {
  $("clock").textContent = fmt(data.now_ms);
  $("steps").hidden = !data.sim;
  renderRules();
  renderVisits();
  renderNotes();
  renderDigest();
  renderTimeline();
  const shown = selected && data.events.find((e) => e.id === selected);
  if (shown && shown.state !== $("detail").dataset.state) select(selected);   // read meanwhile
  if (tab() === "notifications") seenUpTo = Math.max(seenUpTo, data.now_ms);
  renderCount();
}

// -- set up -----------------------------------------------------------------------
function renderRules() {
  $("rules").innerHTML = data.rules.map((r) => `
    <div class="item ${r.id === fresh ? "fresh" : ""}">
      <div class="row"><span class="title">${esc(r.title)}</span>
        <span class="badge ${esc(r.state.state)}">${esc(r.state.state)}</span>
        <span class="spacer"></span>
        <label class="small"><input type="checkbox" data-toggle="${r.id}" ${r.enabled ? "checked" : ""}> on</label>
        <button class="danger small" data-delete="${r.id}">Remove</button></div>
      <div class="small muted">“${esc(r.text)}”</div>
      <div class="small">${esc(r.sentence)}</div>
    </div>`).join("") || '<p class="muted small">No alerts yet.</p>';
  $("rules").querySelectorAll("[data-toggle]").forEach((el) => el.addEventListener("change", async () => {
    await api(`/api/rules/${el.dataset.toggle}`, {method: "PATCH", body: JSON.stringify({enabled: el.checked})});
    load();
  }));
  $("rules").querySelectorAll("[data-delete]").forEach((el) => armed(el, async () => {
    await api(`/api/rules/${el.dataset.delete}`, {method: "DELETE"});
    load();
  }));
}

function visitStatus(v) {      // today's
  const t = v.today || {};
  if (v.state === "left") return `came ${t.arrived || "?"}, left ${t.left}` +
    (t.stayed_minutes != null ? ` · ${t.stayed_minutes} min` : "");
  if (v.state === "arrived") return `arrived ${t.arrived}`;
  if (v.state === "missed") return "not seen";
  if (v.state === "due") return `due ${v.from}–${v.to}`;
  return v.state;
}

function renderVisits() {
  const sel = $("visit-camera");
  if (sel.options.length !== data.cameras.length + 1) {
    sel.innerHTML = '<option value="">Any camera</option>' + data.cameras.map((c) =>
      `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join("");
  }
  $("visits").innerHTML = (data.visits || []).map((v) => `
    <div class="item">
      <div class="row"><span class="title">${esc(cap(v.label))}</span>
        <span class="badge ${esc(v.state)}">${esc(visitStatus(v))}</span>
        <span class="spacer"></span>
        <label class="small"><input type="checkbox" data-toggle-visit="${v.id}" ${v.enabled ? "checked" : ""}> on</label>
        <button class="danger small" data-delete-visit="${v.id}">Remove</button></div>
      <div class="small muted">${esc(v.description)} · ${esc(v.from)}–${esc(v.to)}</div>
    </div>`).join("") || '<p class="muted small">No expected visits yet.</p>';
  $("visits").querySelectorAll("[data-toggle-visit]").forEach((el) => el.addEventListener("change", async () => {
    await api(`/api/visits/${el.dataset.toggleVisit}`, {method: "PATCH", body: JSON.stringify({enabled: el.checked})});
    load();
  }));
  $("visits").querySelectorAll("[data-delete-visit]").forEach((el) => armed(el, async () => {
    await api(`/api/visits/${el.dataset.deleteVisit}`, {method: "DELETE"});
    load();
  }));
}

$("rule-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const text = $("rule-text").value.trim();
  if (!text) return;
  $("rule-add").disabled = true;
  $("rule-status").textContent = "Working out what that means…";
  try {
    const rule = await api("/api/rules", {method: "POST", body: JSON.stringify({text})});
    $("rule-text").value = "";
    $("rule-status").textContent = "On. Below is exactly what it will do.";
    fresh = rule.id;
    setTimeout(() => { fresh = null; renderRules(); }, 8000);
    load();
  } catch (e) { $("rule-status").textContent = e.message; }
  finally { $("rule-add").disabled = false; }
});

$("visit-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const cam = $("visit-camera").value;
  try {
    await api("/api/visits", {method: "POST", body: JSON.stringify({
      label: $("visit-label").value.trim(), description: $("visit-description").value.trim(),
      from_hhmm: $("visit-from").value, to_hhmm: $("visit-to").value,
      cameras: cam ? [cam] : []})});
    $("visit-status").textContent = "";
    $("visit-label").value = ""; $("visit-description").value = "";
    load();
  } catch (e) { $("visit-status").textContent = e.message; }
});

function cleared() {
  selected = null; seenUpTo = 0;
  delete $("detail").dataset.state;
  $("detail").innerHTML = '<p class="muted">Pick a clip on the timeline, or a notification, to watch it.</p>';
  load();
}
armed($("clear-timeline"), async () => { await api("/api/timeline", {method: "DELETE"}); cleared(); });
armed($("delete-all"), async () => { await api("/api/everything", {method: "DELETE"}); cleared(); });

// -- notifications: alerts, visits, doorbell presses --------------------------------
function notes() {
  const out = data.alerts.map((a) => ({
    at: a.at_ms, title: a.title, body: a.message, eventId: a.event_id, alert: true,
    img: a.snapshot ? `/media/alert-snapshot/${a.id}` : null}));
  for (const v of data.visits || []) for (const r of v.seen) {
    if (r.arrived_ms) out.push({at: r.arrived_ms, title: `${cap(v.label)} arrived`,
      body: `At ${r.arrived}.`, eventId: r.arrived_event});
    if (r.left_ms) out.push({at: r.left_ms, title: `${cap(v.label)} left`,
      body: `At ${r.left}` + (r.stayed_minutes != null ? `, after ${r.stayed_minutes} minutes.` : "."),
      eventId: r.left_event});
  }
  const alerted = new Set(data.alerts.map((a) => a.event_id));      // the alert says it already
  for (const e of data.events.filter((e) => e.kind === "ding" && e.state === "done" && !alerted.has(e.id)))
    out.push({at: e.start_ms, title: `Doorbell: ${camName(e.camera)}`, body: e.summary, eventId: e.id});
  for (const n of out)
    if (!n.img && n.eventId) n.img = `/media/event-snapshot/${encodeURIComponent(n.eventId)}`;
  return out.sort((a, b) => b.at - a.at);
}

function noteHtml(n, i) {
  return `<div class="note ${n.alert ? "alert" : ""} ${n.eventId ? "cite" : ""}" data-i="${i}">
    <div class="what">${esc(n.title)}</div><div class="when">${esc(data ? fmt(n.at) : "")}</div>
    ${n.img ? `<img src="${esc(n.img)}" alt="" onerror="this.remove()">` : ""}
    <div class="body">${esc(n.body || "")}</div></div>`;
}

function renderNotes() {
  const list = notes();
  $("notes").innerHTML = list.map(noteHtml).join("") ||
    '<p class="muted">Nothing yet. Alerts, visits and doorbell presses appear here.</p>';
  $("notes").querySelectorAll(".note.cite").forEach((el) =>
    el.addEventListener("click", () => watch(list[el.dataset.i].eventId)));
}

function renderCount() {
  const n = notes().filter((x) => x.at > seenUpTo).length;
  $("note-count").textContent = n ? String(n) : "";
}

function renderDigest() {
  const d = data.digest;
  if (!d) { $("digest").innerHTML = '<p class="muted small">In brief, written at 8 pm, or now with the button.</p>'; return; }
  $("digest").innerHTML = `<div><strong>${esc(d.headline)}</strong></div>` +
    (d.lines || []).map((l) => `<div class="line ${l.event_id ? "cite" : ""}" data-id="${esc(l.event_id)}">
      <span class="muted">${esc(l.time)}</span> ${esc(l.text)}</div>`).join("") +
    ((d.worth_a_look || []).length ? `<div class="item alert"><div class="title">Worth a look</div>` +
      d.worth_a_look.map((w) => `<div class="small">${esc(w)}</div>`).join("") + "</div>" : "");
  $("digest").querySelectorAll(".cite").forEach((el) => el.dataset.id &&
    el.addEventListener("click", () => watch(el.dataset.id)));
}

$("digest-make").addEventListener("click", async () => {
  $("digest").innerHTML = '<p class="muted">Writing…</p>';
  try { await api("/api/digest", {method: "POST"}); } catch (e) { toast({title: e.message}); }
  load();
});

// -- view: the timeline, one clip, and questions -----------------------------------
// The axis runs from the first clip to now, in whole hours, at least three.
const HOUR = 3_600_000;
const STEPS = [1, 2, 3, 6, 12, 24, 48, 168];

function axis() {
  const times = data.events.map((e) => e.start_ms).concat(data.now_ms);
  let lo = Math.floor(Math.min(...times) / HOUR) * HOUR;
  const hi = Math.ceil((Math.max(...times) + 1) / HOUR) * HOUR;
  if (hi - lo < 3 * HOUR) lo = hi - 3 * HOUR;
  const step = (STEPS.find((h) => (hi - lo) / (h * HOUR) <= 8) || 168) * HOUR;
  const dates = new Set(times.map((t) => fmt(t, {hour: undefined, minute: undefined, day: "numeric"})));
  const ticks = [];
  for (let t = Math.ceil(lo / step) * step; t <= hi; t += step)
    ticks.push({t, label: fmt(t, {hourCycle: "h23", ...(dates.size > 1 ? {weekday: "short"} : {})})});
  return {lo, hi, ticks};
}

function renderTimeline() {
  const {lo, hi, ticks} = axis();
  const pct = (ms) => ((ms - lo) / (hi - lo)) * 100;
  const cams = data.cameras.length ? data.cameras : [{id: "-", name: "no cameras"}];
  let html = '<div class="hours"><span></span><div class="scale">';
  for (const k of ticks) html += `<span style="left:${pct(k.t)}%">${esc(k.label)}</span>`;
  html += "</div></div>";
  for (const c of cams) {
    html += `<div class="track"><div class="label" title="${esc(c.name)}">${esc(c.name)}</div><div class="lane">`;
    html += `<div class="now-line" style="left:${pct(data.now_ms)}%"></div>`;
    let last = -Infinity, nudge = 0;           // clips at one moment: side by side
    for (const e of data.events.filter((e) => e.camera === c.id)) {
      const what = e.kind === "ding" ? "Doorbell" : "Motion";
      const at = pct(e.start_ms);
      nudge = at - last < 0.8 ? nudge + 12 : 0;
      last = at;
      html += `<div class="dot ${e.kind} ${e.state} ${e.id === selected ? "selected" : ""}" ` +
        `style="left:calc(${at}% + ${nudge}px)" data-id="${esc(e.id)}" ` +
        `title="${what} ${fmt(e.start_ms)}${e.summary ? " — " + esc(e.summary.slice(0, 120)) : ""}"></div>`;
    }
    html += "</div></div>";
  }
  $("timeline").innerHTML = html;
  $("timeline").querySelectorAll(".dot").forEach((d) =>
    d.addEventListener("click", () => select(d.dataset.id)));
  const n = data.events.length;
  const busy = data.events.filter((e) => e.state === "new" || e.state === "processing").length;
  $("timeline-note").textContent = n ? `${n} clip${n > 1 ? "s" : ""}` +
    (busy ? `, ${busy} still being read` : "") + ". Filled: the doorbell rang; hollow: motion." :
    "Nothing on the timeline yet.";
}

async function select(id, offset = 0) {
  selected = id;
  const e = await api(`/api/events/${encodeURIComponent(id)}`);
  renderDetail(e, offset);
  if (data) renderTimeline();
}

function renderDetail(e, offset = 0) {
  if (!e) return;
  const media = e.has_clip
    ? `<video src="/media/clip/${encodeURIComponent(e.id)}#t=${offset}" controls autoplay muted preload="metadata"></video>`
    : e.has_snapshot ? `<img src="/media/event-snapshot/${encodeURIComponent(e.id)}" alt="">` : "";
  $("detail").dataset.state = e.state;
  $("detail").innerHTML = `
    <div class="row"><strong>${e.kind === "ding" ? "Doorbell" : "Motion"} · ${esc(camName(e.camera))} · ${fmt(e.start_ms)}</strong>
      <span class="spacer"></span><button class="danger small" id="delete-event">Delete this clip</button></div>
    ${media}
    <div>${esc(e.summary || (e.state === "done" ? "" : "Being read…"))}</div>
    ${e.error ? `<div class="item alert">${esc(e.error)}</div>` : ""}
    ${e.answers ? `<details><summary class="muted small">Everything the model answered</summary><pre>${esc(JSON.stringify(e.answers, null, 1))}</pre></details>` : ""}`;
  armed($("delete-event"), async () => {
    await api(`/api/events/${encodeURIComponent(e.id)}`, {method: "DELETE"});
    selected = null;
    delete $("detail").dataset.state;
    $("detail").innerHTML = '<p class="muted">Pick a clip on the timeline, or a notification, to watch it.</p>';
    load();
  });
}

$("ask").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const q = $("question").value.trim();
  if (!q) return;
  $("answer").innerHTML = '<p class="muted">Looking through the footage…</p>';
  try {
    const a = await api("/api/ask", {method: "POST", body: JSON.stringify({question: q})});
    $("answer").innerHTML = `<div>${esc(a.answer)}</div>` + a.citations.map((c) => `
      <div class="item cite" data-id="${esc(c.event_id)}" data-offset="${c.offset_s || 0}">
        <span class="muted small">${esc(c.time)} · ${esc(c.camera)}</span><br>${esc(c.summary || "")}</div>`).join("");
    $("answer").querySelectorAll(".cite").forEach((el) =>
      el.addEventListener("click", () => select(el.dataset.id, Number(el.dataset.offset))));
  } catch (e) { $("answer").innerHTML = `<p class="muted">${esc(e.message)}</p>`; }
});

// A destructive button asks twice, in place: no dialogs.
function armed(button, action) {
  let timer = null;
  const label = button.textContent;
  button.addEventListener("click", async () => {
    if (!button.classList.contains("armed")) {
      button.classList.add("armed"); button.textContent = "Click again to confirm";
      timer = setTimeout(() => { button.classList.remove("armed"); button.textContent = label; }, 4000);
      return;
    }
    clearTimeout(timer);
    button.disabled = true;
    try { await action(); } finally { button.disabled = false; button.classList.remove("armed"); button.textContent = label; }
  });
}

// -- stepping through the simulated day: no waiting between events ---------------
let auto = false;

// Settled when nothing is queued or being read twice running: a deadline's
// alert is written by the tick after the jump, a second or so later.
async function settled() {
  let quiet = 0;
  for (let i = 0; i < 300 && quiet < 2; i++) {
    await sleep(1000);
    const d = await api("/api/timeline");
    const reading = d.events.some((e) => e.state === "new" || e.state === "processing");
    quiet = d.worker.busy || reading ? 0 : quiet + 1;
  }
}

async function step() {
  $("step-next").disabled = true;
  try {
    $("step-status").textContent = "Going on…";
    const s = await api("/api/sim/next", {method: "POST"});
    if (s.done) { $("step-status").textContent = "That's the whole day."; return false; }
    $("step-status").textContent = `${s.what} — reading…`;
    await load();
    await settled();
    $("step-status").textContent = `${s.what}` + (s.left ? ` · ${s.left} more` : " · the last one");
    return Boolean(s.left);
  } catch (e) { $("step-status").textContent = e.message; return false; }
  finally { $("step-next").disabled = false; }
}

function setAuto(on) {
  auto = on;
  $("step-auto").textContent = on ? "Stop" : "Auto-play";
  $("step-auto").setAttribute("aria-pressed", String(on));
}

$("step-next").addEventListener("click", () => { if (!auto) step(); });
$("step-auto").addEventListener("click", async () => {
  if (auto) { setAuto(false); return; }
  setAuto(true);
  while (auto && await step()) {
    if (auto) await sleep(Number($("step-dwell").value) * 1000);
  }
  setAuto(false);
});
armed($("step-restart"), async () => {
  setAuto(false);
  try {
    await api("/api/sim/restart", {method: "POST"});
    $("step-status").textContent = "The day from the top: press Next.";
    cleared();
  } catch (e) { toast({title: e.message}); }
});

// -- live: a pop-up for each new notification, on any tab ---------------------------
const TOAST_LIMIT = 3;

function toast(n, seconds = 12) {
  const box = $("toasts");
  const el = document.createElement("div");
  el.innerHTML = noteHtml(n, 0);
  const note = el.firstElementChild;
  const close = () => {
    if (note.classList.contains("leaving")) return;
    note.classList.add("leaving");
    setTimeout(() => note.remove(), 300);
  };
  note.addEventListener("click", () => { if (n.eventId) watch(n.eventId); close(); });
  box.prepend(note);
  while (box.children.length > TOAST_LIMIT) box.lastElementChild.remove();
  setTimeout(close, (n.alert ? 30 : seconds) * 1000);
}

function toastFrom(msg) {
  if (msg.type === "alert") {
    toast({at: msg.at_ms, title: msg.title, body: msg.message, eventId: msg.event_id, alert: true,
           img: msg.snapshot ? `/media/alert-snapshot/${msg.id}` : null});
  } else if (msg.type === "visit" && msg.state !== "missed") {     // a missed visit is an alert
    const left = msg.state === "left";
    const eventId = left ? msg.left_event : msg.arrived_event;
    toast({at: left ? msg.left_ms : msg.arrived_ms, title: `${cap(msg.label)} ${left ? "left" : "arrived"}`,
           body: msg.message, eventId,
           img: eventId ? `/media/event-snapshot/${encodeURIComponent(eventId)}` : null});
  } else if (msg.type === "event" && msg.kind === "ding" && msg.state === "done") {
    toast({at: msg.start_ms, title: `Doorbell: ${data ? camName(msg.camera) : msg.camera}`,
           body: msg.summary, eventId: msg.id,
           img: `/media/event-snapshot/${encodeURIComponent(msg.id)}`});
  }
}

const stream = new EventSource("/api/stream/family");
stream.onmessage = (m) => {
  toastFrom(JSON.parse(m.data));
  reloadSoon();
};
setInterval(() => { if (data && data.sim && data.sim.running) load(); }, 5000);
showTab();
load();
