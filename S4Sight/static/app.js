/* S4Sight front end: core helpers, router, charts. No external libraries, works offline. */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const S = { state: null, cleanup: [] };

function reader() { try { return localStorage.getItem("ss_reader") || ""; } catch (e) { return ""; } }
function setReader(n) { try { localStorage.setItem("ss_reader", n); } catch (e) {} }

async function api(path, opt = {}) {
  const o = { method: opt.method || "GET", headers: { "X-Reader": reader() } };
  if (opt.json !== undefined) { o.headers["Content-Type"] = "application/json"; o.body = JSON.stringify(opt.json); }
  if (opt.form) o.body = opt.form;
  const r = await fetch(path, o);
  if (r.status === 401) { location.href = "/login"; throw new Error("PIN required"); }
  let data = null;
  try { data = await r.json(); } catch (e) {}
  if (!r.ok) {
    let d = data && data.detail;
    if (Array.isArray(d)) d = d.map(x => x.msg).join("; ");
    throw new Error(d || ("Request failed (" + r.status + ")"));
  }
  return data;
}

function toast(msg, err) {
  const t = document.createElement("div");
  t.className = "toast" + (err ? " err" : "");
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), err ? 6000 : 2800);
}
async function guard(fn) { try { return await fn(); } catch (e) { toast(e.message, true); } }

function fmtDur(s) {
  if (s == null || isNaN(s)) return "n/a";
  s = Math.round(s);
  const m = Math.floor(s / 60), r = s % 60;
  return m + ":" + String(r).padStart(2, "0");
}
function fmtDate(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  return d.toLocaleDateString(undefined, { day: "2-digit", month: "short" }) + " " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
const pct = (x, d = 1) => x == null ? "n/a" : (x * 100).toFixed(d) + "%";
const ci = c => c ? `(${(c[0] * 100).toFixed(0)} to ${(c[1] * 100).toFixed(0)}%)` : "";
const gradeLabel = g => g === "negative" ? "Negative" : g === "scanty" ? "Scanty" : g === "positive" ? "Positive" : (g || "n/a");
function gradeClass(g) { return g === "negative" ? "neg" : g === "scanty" ? "mid" : g ? "pos" : ""; }
function gradePill(g) { return g ? `<span class="pill ${g === "negative" ? "neg" : g === "scanty" ? "warn" : "pos"}">${esc(gradeLabel(g))}</span>` : `<span class="muted">n/a</span>`; }
function demoPill(d) { return d ? `<span class="pill demo">DEMO</span>` : ""; }

function modal(html, wide) {
  const bg = document.createElement("div");
  bg.className = "modal-bg";
  bg.innerHTML = `<div class="modal" ${wide ? 'style="max-width:1100px"' : ""}>${html}</div>`;
  bg.addEventListener("mousedown", e => { if (e.target === bg) bg.remove(); });
  document.body.appendChild(bg);
  bg.close = () => bg.remove();
  return bg;
}

/* ---------- tiny SVG charts ---------- */
function lineChart(series, { w = 560, h = 200, yfmt = v => v, ymin = null } = {}) {
  // series: [{name,color,points:[[x,y]...]}] x are numbers (epoch / index)
  const pad = { l: 44, r: 12, t: 10, b: 24 };
  const all = series.flatMap(s => s.points.filter(p => p[1] != null));
  if (!all.length) return `<div class="empty small">No data yet.</div>`;
  const xs = all.map(p => p[0]), ys = all.map(p => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs) || 1;
  let y0 = ymin != null ? ymin : Math.min(...ys), y1 = Math.max(...ys);
  if (y1 === y0) y1 = y0 + 1;
  const X = x => pad.l + (x1 === x0 ? 0.5 : (x - x0) / (x1 - x0)) * (w - pad.l - pad.r);
  const Y = y => h - pad.b - (y - y0) / (y1 - y0) * (h - pad.t - pad.b);
  let g = "";
  for (let i = 0; i <= 4; i++) {
    const v = y0 + (y1 - y0) * i / 4, y = Y(v);
    g += `<line x1="${pad.l}" x2="${w - pad.r}" y1="${y}" y2="${y}" stroke="#E6EEF0"/><text x="${pad.l - 6}" y="${y + 4}" text-anchor="end">${esc(yfmt(v))}</text>`;
  }
  const xt = (x0 === x1 ? [x0] : [x0, (x0 + x1) / 2, x1]).map((v, i) => `<text x="${X(v)}" y="${h - 6}" text-anchor="${x0 === x1 ? "middle" : i == 0 ? "start" : i == 2 ? "end" : "middle"}">${Math.round(v)}</text>`).join("");
  const lines = series.map(s => {
    const pts = s.points.filter(p => p[1] != null);
    const d = pts.map((p, i) => (i ? "L" : "M") + X(p[0]).toFixed(1) + " " + Y(p[1]).toFixed(1)).join(" ");
    const dots = pts.length < 25 ? pts.map(p => `<circle cx="${X(p[0])}" cy="${Y(p[1])}" r="3" fill="${s.color}"/>`).join("") : "";
    return `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2.2" stroke-linejoin="round"/>${dots}`;
  }).join("");
  const leg = series.map(s => `<span><i style="background:${s.color}"></i>${esc(s.name)}</span>`).join(" &nbsp; ");
  return `<svg viewBox="0 0 ${w} ${h}" width="100%" role="img">${g}${xt}${lines}</svg><div class="legend tiny muted">${leg}</div>`;
}

function barChart(items, { w = 560, h = 190, color = "#0891A0" } = {}) {
  // items: [{label, value}]
  const pad = { l: 30, r: 8, t: 14, b: 40 };
  const max = Math.max(1, ...items.map(i => i.value));
  const bw = (w - pad.l - pad.r) / items.length;
  const bars = items.map((it, i) => {
    const bh = (it.value / max) * (h - pad.t - pad.b), x = pad.l + i * bw + 6, y = h - pad.b - bh;
    return `<rect x="${x}" y="${y}" width="${bw - 12}" height="${bh}" rx="4" fill="${color}"/>
      <text x="${x + (bw - 12) / 2}" y="${y - 4}" text-anchor="middle" style="fill:#0F2A33">${it.value}</text>
      <text x="${x + (bw - 12) / 2}" y="${h - 22}" text-anchor="middle">${esc(it.label.split(" to ")[0])}</text>
      <text x="${x + (bw - 12) / 2}" y="${h - 9}" text-anchor="middle">${it.label.includes(" to ") ? "to " + esc(it.label.split(" to ")[1]) : ""}</text>`;
  }).join("");
  return `<svg viewBox="0 0 ${w} ${h}" width="100%" role="img"><line x1="${pad.l}" x2="${w - pad.r}" y1="${h - pad.b}" y2="${h - pad.b}" stroke="#C5D3D8"/>${bars}</svg>`;
}

/* ---------- router ---------- */
const ROUTES = {};
function route(name, fn) { ROUTES[name] = fn; }
function go(h) { location.hash = h; }

async function render() {
  S.cleanup.forEach(f => { try { f(); } catch (e) {} });
  S.cleanup = [];
  const parts = location.hash.replace(/^#\/?/, "").split("/");
  const name = parts[0] || "";
  const tools = ["dataset", "training", "performance", "settings"];
  $$("nav a[data-r]").forEach(a => a.classList.toggle("on", a.dataset.r === name || (a.dataset.r === "more" && tools.includes(name))));
  const view = $("#view");
  const fn = ROUTES[name] || ROUTES[""];
  try {
    await refreshState();
    view.innerHTML = `<div class="empty"><span class="spin"></span></div>`;
    await fn(view, parts.slice(1));
    window.scrollTo(0, 0);
  } catch (e) {
    view.innerHTML = `<div class="banner bad">Something went wrong: ${esc(e.message)}</div>`;
  }
}

async function refreshState() {
  S.state = await api("/api/state");
  const sel = $("#reader");
  const cur = reader() && S.state.readers.find(r => r.name === reader()) ? reader() : S.state.readers[0].name;
  setReader(cur);
  const opts = S.state.readers.map(r => `<option ${r.name === cur ? "selected" : ""} value="${esc(r.name)}">${esc(r.name)} (${esc(roleLabel(r.role))})</option>`).join("");
  sel.innerHTML = opts;
  const selM = $("#reader-m"); if (selM) selM.innerHTML = opts;
  ["#rv-badge", "#rv-badge-m"].forEach(id => { const b = $(id); if (b) { b.hidden = !S.state.set_aside; b.textContent = S.state.set_aside; } });
  $("#model-chip").innerHTML = S.state.panel_order.map(k => {
    const m = S.state.active_models[k];
    return m ? `${esc(MOD_SHORT[k])}: <b style="color:#fff">AI ready</b> ${m.demo ? '<span class="pill demo">DEMO</span>' : ""}`
      : `${esc(MOD_SHORT[k])}: <span style="color:#F7C98B">no AI yet</span>`;
  }).join("<br>");
  const more = $("#more-nav");
  if (more && !more.dataset.init) { more.dataset.init = 1; more.open = isExpert() || (() => { try { return localStorage.getItem("ss_more") === "1"; } catch (e) { return false; } })(); }
}

function boot() {
  $("#reader").addEventListener("change", e => { setReader(e.target.value); render(); });
  const selM = $("#reader-m"); if (selM) selM.addEventListener("change", e => { setReader(e.target.value); render(); });
  document.addEventListener("click", e => { const a = e.target.closest && e.target.closest(".open-phone"); if (a) { e.preventDefault(); openOnPhone(); } });
  const more = $("#more-nav");
  if (more) more.addEventListener("toggle", () => { try { localStorage.setItem("ss_more", more.open ? "1" : "0"); } catch (e) {} });
  window.addEventListener("hashchange", render);
  render();
}

/* ---------- test types (TB, stool, STI) ---------- */
const MOD_SHORT = { zn: "TB (ZN)", fm: "TB (fluorescence)", stl: "Stool", sti: "STI swab" };
const MOD_CLASS = { zn: "teal", fm: "fm", stl: "stl", sti: "sti" };
const modPill = m => `<span class="pill ${MOD_CLASS[m] || ""}">${esc(MOD_SHORT[m] || m)}</span>`;
const panel = m => S.state.panels[m] || S.state.panels.zn;
const isGraded = m => panel(m).kind === "graded";
const className = (m, id) => { const c = panel(m).classes.find(x => x.id === id); return c ? c.name : id; };
const CLASS_COLORS = ["#0891A0", "#7A3E9D", "#B54708", "#1D5FA8", "#067647", "#C11574", "#5E6AD2", "#8A6100", "#0E7490", "#9F1239", "#4D7C0F"];
const classColor = (m, id) => { const i = panel(m).classes.findIndex(x => x.id === id); return CLASS_COLORS[Math.max(0, i) % CLASS_COLORS.length]; };
const TEST_ICON = {
  zn: `<svg viewBox="0 0 48 48" aria-hidden="true"><circle cx="24" cy="24" r="20" fill="#E3F2F4"/><path d="M14 30c4-9 9-13 20-16M16 20c5 1 9 6 12 13" stroke="#B42318" stroke-width="3" fill="none" stroke-linecap="round"/></svg>`,
  fm: `<svg viewBox="0 0 48 48" aria-hidden="true"><circle cx="24" cy="24" r="20" fill="#0F2A33"/><path d="M14 30c4-9 9-13 20-16M16 20c5 1 9 6 12 13" stroke="#B7F36B" stroke-width="3" fill="none" stroke-linecap="round"/></svg>`,
  stl: `<svg viewBox="0 0 48 48" aria-hidden="true"><circle cx="24" cy="24" r="20" fill="#FEF3E2"/><ellipse cx="22" cy="24" rx="11" ry="8" fill="#B5783C"/><ellipse cx="22" cy="24" rx="7" ry="4.5" fill="#E2B57E"/><circle cx="35" cy="16" r="4" fill="#8A5A2B"/></svg>`,
  sti: `<svg viewBox="0 0 48 48" aria-hidden="true"><circle cx="24" cy="24" r="20" fill="#F3E8FA"/><circle cx="20" cy="25" r="9" fill="#D7B8EC"/><circle cx="18" cy="23" r="3" fill="#7A3E9D"/><circle cx="23" cy="27" r="2" fill="#C11574"/><circle cx="26" cy="27" r="2" fill="#C11574"/><ellipse cx="35" cy="15" rx="4" ry="3" fill="#7A3E9D"/></svg>`,
};

/* ---------- phones ---------- */
const isPhone = () => window.matchMedia("(max-width: 760px)").matches;

/* Phone photos are 3-12 MB. Shrink to 1600 px before sending: much faster on lab Wi-Fi, and re-drawing
   the picture drops GPS and camera details (EXIF). The server keeps at most 1920 px anyway. */
function shrinkImage(file, maxSide = 1600) {
  return new Promise(resolve => {
    const draw = (src, w, h) => {
      const s = Math.min(1, maxSide / Math.max(w, h)), c = document.createElement("canvas");
      c.width = Math.round(w * s); c.height = Math.round(h * s);
      c.getContext("2d").drawImage(src, 0, 0, c.width, c.height);
      c.toBlob(b => resolve(b ? new File([b], (file.name || "photo").replace(/\.\w+$/, "") + ".jpg", { type: "image/jpeg" }) : file), "image/jpeg", 0.9);
    };
    const fallback = () => {
      const img = new Image(), u = URL.createObjectURL(file);
      img.onload = () => { draw(img, img.naturalWidth, img.naturalHeight); URL.revokeObjectURL(u); };
      img.onerror = () => { URL.revokeObjectURL(u); resolve(file); };
      img.src = u;
    };
    try {
      if (window.createImageBitmap) createImageBitmap(file, { imageOrientation: "from-image" }).then(bm => draw(bm, bm.width, bm.height), fallback);
      else fallback();
    } catch (e) { fallback(); }
  });
}

async function openOnPhone() {
  const m = modal(`<h2>Use S4Sight on a phone</h2><div id="op-body"><div class="empty"><span class="spin"></span></div></div>
    <div class="row" style="margin-top:12px"><button id="op-x">Close</button></div>`);
  $("#op-x", m).onclick = () => m.close();
  try {
    const d = await api("/api/app-link");
    const warn = d.network.warnings.map(w => `<div class="banner" style="margin:8px 0">${esc(w)}</div>`).join("");
    $("#op-body", m).innerHTML = d.url ? `
      <ol class="small" style="margin:0 0 10px 18px;padding:0;line-height:1.7">
        <li>Connect the phone to the <b>same Wi-Fi</b> as this computer.</li>
        <li>Scan this QR code with the phone camera, or type <b class="mono">${esc(d.url)}</b> in the phone's browser.</li>
        <li>${d.network.pin_enabled ? "Enter the access PIN." : "No PIN is set, so anyone on this Wi-Fi can open the app."}</li>
        <li>In the browser menu choose <b>Add to Home screen</b>, so S4Sight opens like an app next time.</li></ol>
      <div class="qrbox" style="margin:8px auto">${d.qr_svg}</div>${warn}
      <p class="tiny muted">The phone opens the full app: start samples, photograph through the eyepiece adapter, check and verify. The computer must stay on while phones use it.</p>`
      : warn;
  } catch (e) { $("#op-body", m).innerHTML = `<div class="banner bad">${esc(e.message)}</div>`; }
}

/* ---------- people ---------- */
const ROLE_LABEL = { technician: "Technician", reader: "Technician", senior: "Expert (senior reader)", lead: "Expert (lab lead)" };
const roleLabel = r => ROLE_LABEL[r] || r;
function isExpert(name) { return (S.state.expert_roles || ["senior", "lead"]).includes(roleOf(name || reader())); }
function demoBanner(modality) {
  const am = S.state.active_models;
  const demo = modality ? (am[modality] && am[modality].demo) : Object.values(am).some(m => m && m.demo);
  return demo ? `<div class="banner"><b>Demo AI in use.</b> ${esc(S.state.demo_banner)} Use it only to practise the steps.</div>` : "";
}

function roleOf(name) { const r = S.state.readers.find(x => x.name === name); return r ? r.role : "technician"; }
