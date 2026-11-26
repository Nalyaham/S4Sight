/* Home, New sample, the sample page (photograph -> check -> verify or ask an expert), Results, Expert queue */

function ago(ts) {
  if (!ts) return "";
  const s = Date.now() / 1000 - ts;
  return s < 90 ? "just now" : s < 3600 ? Math.round(s / 60) + " min ago" : s < 86400 ? Math.round(s / 3600) + " h ago" : Math.round(s / 86400) + " days ago";
}
function lastUsed(key, dflt) { try { return localStorage.getItem(key) || dflt; } catch (e) { return dflt; } }
function remember(key, v) { try { localStorage.setItem(key, v); } catch (e) {} }

function findingsText(m, f) {
  const e = Object.entries(f || {}).filter(([, n]) => n > 0);
  return e.length ? e.map(([k, n]) => `${esc(className(m, k))} (${n})`).join(", ") : "";
}
function resultCell(s) {
  const f = !isGraded(s.modality) ? findingsText(s.modality, s.findings) : "";
  return `${gradePill(s.final_grade)}${f ? `<div class="tiny muted">${f}</div>` : ""}`;
}
function verifiedBy(s) {
  return `${esc(s.confirmed_by || "")}${s.verification === "expert" ? ' <span class="pill fm">expert</span>' : ""}`;
}

function testTile(k, href) {
  const p = panel(k), m = S.state.active_models[k];
  return `<a class="tile" href="${href || "#/analyze/new/" + k}">${TEST_ICON[k] || ""}
    <div><b>${esc(p.name)}</b><span>${esc(p.specimen)}</span>
    <span class="tiny ${m ? "" : "warnline"}">${m ? (m.demo ? "Demo AI" : "AI helps count") : "No AI yet: record by eye"}</span></div></a>`;
}

/* Samples still being read, as the computer sees them while phones photograph at the microscope. */
const liveSig = open => open.map(s => [s.id, s.n_fields, s.photos_done_at, s.last_image_id].join(":")).join("|");
function liveCard(open) {
  const now = Date.now() / 1000;
  const state = s => s.photos_done_at ? "ready" : (s.last_photo_at && now - s.last_photo_at < 300 ? "busy" : "open");
  const order = { ready: 0, busy: 1, open: 2 };
  const rows = [...open].sort((a, b) => (order[state(a)] - order[state(b)]) || ((b.last_photo_at || b.started_at) - (a.last_photo_at || a.started_at)));
  const nReady = rows.filter(s => state(s) === "ready").length;
  return `<div class="row between"><h2 style="margin:0">From the microscope ${nReady ? `<span class="pill neg">${nReady} ready to check</span>` : ""}</h2>
      ${isPhone() ? "" : `<span class="tiny muted"><span class="livedot"></span> updates by itself</span>`}</div>
    ${rows.length ? `<table style="margin-top:6px"><tbody>${rows.slice(0, 10).map(s => {
      const st = state(s);
      return `<tr class="click ${st === "ready" ? "ready" : ""}" onclick="go('#/analyze/${s.id}')">
        <td style="width:58px">${s.last_image_id ? `<img class="mini-thumb" src="/api/images/${s.last_image_id}/thumb?size=120" alt="">` : `<div class="mini-thumb empty-thumb">&#128247;</div>`}</td>
        <td><b>${esc(s.code)}</b> ${demoPill(s.demo)}<div class="tiny muted">${modPill(s.modality)} ${esc(s.started_by || "")}</div></td>
        <td class="small">${s.n_fields} photo${s.n_fields === 1 ? "" : "s"}<div class="tiny muted">${s.last_photo_at ? "last " + ago(s.last_photo_at) : "none yet"}</div></td>
        <td>${st === "ready" ? '<span class="pill neg">Ready to check</span>' : st === "busy" ? '<span class="pill teal">Photographing now</span>' : '<span class="pill">Not finished</span>'}</td>
        <td><button class="sm ${st === "ready" ? "primary" : ""}">${st === "ready" ? "Check" : "Open"}</button></td></tr>`;
    }).join("")}</tbody></table>`
    : `<div class="empty small">Nothing is being read. Start a sample on a phone at the microscope, or pick a test above.</div>`}`;
}

/* ---------------- Home ---------------- */
route("", async (view) => {
  const [sum, slides] = await Promise.all([api("/api/summary"), api("/api/slides?limit=60")]);
  const me = reader(), expert = isExpert();
  const open = slides.filter(s => s.status === "open");
  // keep the "From the microscope" list and the expert badge live while this page is open
  let sig = liveSig(open), readyIds = new Set(open.filter(s => s.photos_done_at).map(s => s.id));
  const liveTimer = setInterval(async () => {
    if (location.hash.replace(/^#\/?/, "") !== "" || document.hidden) return;
    try {
      const now = (await api("/api/slides?status=open&limit=60"));
      const ns = liveSig(now);
      if (ns !== sig) {
        sig = ns; const c = $("#live-card"); if (c) c.innerHTML = liveCard(now);
        now.filter(s => s.photos_done_at && !readyIds.has(s.id)).forEach(s => toast(`${s.code} is ready to check`));
        readyIds = new Set(now.filter(s => s.photos_done_at).map(s => s.id));
      }
      const before = S.state.set_aside; await refreshState(); if (S.state.set_aside > before) toast("A sample was sent to the Expert queue");
    } catch (e) {}
  }, 5000);
  S.cleanup.push(() => clearInterval(liveTimer));
  const back = open.filter(s => s.expert_note);
  const done = slides.filter(s => s.status === "confirmed").slice(0, 8);
  view.innerHTML = `
    <div class="topbar"><div><h1>Hello, ${esc(me)}</h1><div class="muted">${esc(roleLabel(roleOf(me)))}. Choose the test you want to read.</div></div>
      <div class="sp"></div>${isPhone() ? "" : `<button class="open-phone">&#128241; Open on a phone</button>`}</div>
    ${demoBanner()}
    <div class="tiles">${S.state.panel_order.map(k => testTile(k)).join("")}</div>

    ${sum.set_aside_n ? `<div class="card attention" style="margin-top:16px"><div class="row between"><h2 style="margin:0">Waiting for an expert <span class="pill warn">${sum.set_aside_n}</span></h2>
        <a class="btn ${expert ? "primary" : ""}" href="#/expert">${expert ? "Check them now" : "Open the queue"}</a></div>
        ${expert ? "" : `<div class="tiny muted" style="margin-top:4px">An expert (senior reader or lab lead) checks these. Choose the expert's name under <i>Who is working?</i></div>`}
        <table style="margin-top:8px"><tbody>${sum.set_aside.slice(0, 5).map(a => `<tr class="click" onclick="go('#/analyze/${a.id}')"><td><b>${esc(a.code)}</b></td><td>${modPill(a.modality)}</td><td class="small">${esc(a.reason || "")}</td><td class="tiny muted">${esc(a.by || "")}, ${ago(a.at)}</td></tr>`).join("")}</tbody></table></div>` : ""}

    ${back.length ? `<div class="card attention" style="margin-top:16px"><h2>Sent back to the bench</h2>
        <table><tbody>${back.map(s => `<tr class="click" onclick="go('#/analyze/${s.id}')"><td><b>${esc(s.code)}</b></td><td>${modPill(s.modality)}</td><td class="small">${esc(s.expert_note)}</td><td><button class="sm primary">Open</button></td></tr>`).join("")}</tbody></table></div>` : ""}

    <div class="grid g2" style="margin-top:16px">
      <div class="card" id="live-card">${liveCard(open)}</div>
      <div class="card"><h2>Today and recent</h2>
        <div class="row" style="margin-bottom:8px">${S.state.panel_order.map(k => `<div class="mini"><b>${sum.by_test[k] ? sum.by_test[k].verified : 0}</b><span>${esc(MOD_SHORT[k])}</span></div>`).join("")}</div>
        ${done.length ? `<table><tbody>${done.map(s => `<tr class="click" onclick="go('#/analyze/${s.id}')"><td><b>${esc(s.code)}</b> ${demoPill(s.demo)}</td><td>${modPill(s.modality)}</td><td>${resultCell(s)}</td><td class="tiny muted">${verifiedBy(s)}</td></tr>`).join("")}</tbody></table>
          <div style="margin-top:8px"><a href="#/results">All results</a></div>`
          : `<div class="empty small">No verified samples yet.</div>`}
        <div class="tiny muted" style="margin-top:6px">Numbers are samples verified in the last 30 days.</div></div>
    </div>
    ${sum.awaiting_confirmation_n ? `<div class="card" style="margin-top:16px"><h2>TB results to look into <span class="pill pos">${sum.awaiting_confirmation_n}</span></h2>
      <table><tbody>${sum.awaiting_confirmation.map(a => `<tr class="click" onclick="go('#/analyze/${a.id}')"><td><b>${esc(a.code)}</b></td><td>${gradePill(a.grade)}</td><td class="small">${esc(a.label)}</td></tr>`).join("")}</tbody></table></div>` : ""}`;
});

/* ---------------- New sample ---------------- */
route("analyze", async (view, args) => {
  if (!args[0]) return chooseTest(view);
  if (args[0] === "new") return newSample(view, args[1] || "zn");
  return samplePage(view, parseInt(args[0]));
});

async function chooseTest(view) {
  const open = await api("/api/slides?status=open&limit=20");
  view.innerHTML = `
    <div class="topbar"><div><h1>New sample</h1><div class="muted">Which test is this?</div></div></div>
    <div class="tiles">${S.state.panel_order.map(k => testTile(k)).join("")}</div>
    ${open.length ? `<div class="card" style="margin-top:16px"><h2>Or continue a sample</h2><table><tbody>${open.map(s => `<tr class="click" onclick="go('#/analyze/${s.id}')"><td><b>${esc(s.code)}</b> ${demoPill(s.demo)}</td><td>${modPill(s.modality)}</td><td class="muted small">${s.n_fields} photos</td><td><button class="sm">Continue</button></td></tr>`).join("")}</tbody></table></div>` : ""}`;
}

async function newSample(view, mod) {
  if (!S.state.panels[mod]) mod = "zn";
  const p = panel(mod);
  const dv = await api("/api/devices");
  const devs = dv.devices.filter(d => !d.revoked);
  const stain = lastUsed("ss_stain_" + mod, p.stains[0]), mag = lastUsed("ss_mag_" + mod, p.magnifications[p.magnifications.length - 1]);
  const lastDev = lastUsed("ss_dev", "");
  view.innerHTML = `
    <div class="topbar"><div><a href="#/analyze" class="small">&larr; Change test</a><h1 style="margin-top:4px">${TEST_ICON[mod] ? `<span class="h-ico">${TEST_ICON[mod]}</span>` : ""}${esc(p.name)}</h1>
      <div class="muted">${esc(p.specimen)}</div></div></div>
    ${demoBanner(mod)}
    ${S.state.active_models[mod] ? "" : `<div class="banner">No AI for this test yet. You can still photograph the fields and record what you see; the AI can be trained later from these pictures.</div>`}
    <div class="card form-card">
      <label class="f big">Sample number <span class="tiny muted">(lab number only, never the patient's name)</span>
        <input id="n-code" placeholder="e.g. 26-0412" autofocus autocomplete="off"></label>
      <label class="f big" ${isPhone() ? "hidden" : ""}>Take photos with
        <select id="n-dev"><option value="">This device (camera or picture files)</option>
          ${devs.map(d => `<option value="${d.id}" ${String(d.id) === lastDev ? "selected" : ""}>Phone: ${esc(d.name)} ${d.online ? "(online)" : "(offline)"}</option>`).join("")}
          <option value="__pair">+ Connect a phone...</option></select></label>
      <details class="opts"><summary>More options (stain, magnification, site)</summary>
        <div class="grid g3" style="margin-top:10px">
          <label class="f">Stain / preparation<select id="n-stain">${p.stains.map(x => `<option ${x === stain ? "selected" : ""}>${esc(x)}</option>`).join("")}</select></label>
          <label class="f">Magnification<select id="n-mag">${p.magnifications.map(x => `<option ${x === mag ? "selected" : ""}>${esc(x)}</option>`).join("")}</select></label>
          <label class="f">Site or laboratory<input id="n-site" value="${esc(lastUsed("ss_site", ""))}" placeholder="optional"></label>
        </div></details>
      <ul class="tips">${(p.tips || []).map(t => `<li>${esc(t)}</li>`).join("")}</ul>
      <button class="primary big" id="n-go">Start</button>
    </div>`;
  $("#n-dev").onchange = e => { if (e.target.value === "__pair") { e.target.value = ""; openPairing(d => { const o = document.createElement("option"); o.value = d.id; o.textContent = "Phone: " + d.name + " (just connected)"; $("#n-dev").insertBefore(o, $("#n-dev").lastElementChild); $("#n-dev").value = d.id; }); } };
  $("#n-go").onclick = () => guard(async () => {
    const site = $("#n-site").value, dev = isPhone() ? "" : $("#n-dev").value;
    remember("ss_site", site); remember("ss_stain_" + mod, $("#n-stain").value); remember("ss_mag_" + mod, $("#n-mag").value);
    if (!isPhone()) remember("ss_dev", dev);
    const s = await api("/api/slides", { method: "POST", json: { code: $("#n-code").value, site, microscopy: mod, stain: $("#n-stain").value, magnification: $("#n-mag").value, device_id: dev ? +dev : null } });
    go("#/analyze/" + s.id);
  });
  $("#n-code").addEventListener("keydown", e => { if (e.key === "Enter") $("#n-go").click(); });
}

/* ---------------- One sample ---------------- */
const RETAKE_TIP = {
  "blurry": "Turn the fine focus until the smear is sharp, hold the phone still, then retake.",
  "too dark": "Open the condenser or turn up the light, then retake.",
  "too bright": "Turn the light down a little, then retake.",
  "washed out": "Check the filter and darken the room, then retake.",
};
const ASIDE_REASONS = {
  graded: ["Not sure if these are AFB", "Count is near a grade boundary", "Smear or photo quality is poor", "Something unusual"],
  findings: ["Cannot tell what this is", "Not sure if it is an artefact", "Smear or photo quality is poor", "Something unusual"],
};

function samplePage(view, sid) {
  const W = { sl: null, cur: 0, fetchedAt: 0, busy: null, drag: null, devices: [], hist: [], label: null,
              grade: null, gradeTouched: false, find: {}, findTouched: false, aside: false, chips: new Set(),
              drawMode: false, retake: null, upload: null };
  // One camera picker that lives outside the redrawn page: phones only open the camera from a direct tap,
  // and a photo must not be lost if the page redraws while the camera app is open.
  const cam = document.createElement("input");
  cam.type = "file"; cam.accept = "image/*"; cam.setAttribute("capture", "environment"); cam.className = "vh";
  cam.setAttribute("aria-hidden", "true"); cam.tabIndex = -1;
  cam.onchange = () => { const fl = [...cam.files]; cam.value = ""; if (fl.length && W.upload) W.upload(fl); };
  document.body.appendChild(cam);
  S.cleanup.push(() => cam.remove());

  async function load() {
    W.sl = await api("/api/slides/" + sid);
    W.fetchedAt = performance.now();
    const extra = await Promise.all([
      W.sl.status === "open" ? api("/api/devices").then(d => d.devices, () => []) : [],
      W.sl.status === "confirmed" && isGraded(W.sl.modality) ? api(`/api/slides/${sid}/confirmation`).then(d => d.history, () => []) : []]);
    W.devices = extra[0]; W.hist = extra[1];
    if (W.cur >= W.sl.fields.length) W.cur = Math.max(0, W.sl.fields.length - 1);
    if (!W.label) W.label = panel(W.sl.modality).classes[0].id;
    syncResult();
    draw();
  }
  /* the result controls follow the marks until the person changes them by hand */
  function syncResult() {
    const sl = W.sl, sg = sl.suggested;
    const aside = sl.status === "set_aside";
    if (isGraded(sl.modality)) {
      if (!W.gradeTouched) W.grade = (aside && sl.tech_result) || sg.grade || "negative";
    } else if (!W.findTouched) {
      W.find = { ...((aside && Object.keys(sl.tech_findings || {}).length) ? sl.tech_findings : (sg.findings || {})) };
    }
  }
  const isOpen = () => W.sl.status === "open";
  const graded = () => isGraded(W.sl.modality);
  const thr = () => S.state.thresholds_by_modality[(W.sl && W.sl.modality) || "zn"];
  const counted = d => d.status === "kept" || d.status === "added" || (d.status === "pending" && d.conf >= thr().positive);
  const field = () => W.sl.fields[W.cur];
  const canDraw = () => !!(isOpen() && field());          // with or without AI: people can always mark by hand
  // On a phone a finger on the photo must scroll the page, so drawing new boxes is switched on by a button.
  const drawing = () => !!(canDraw() && (W.drawMode || !isPhone()));
  const currentResult = () => graded() ? W.grade : (Object.entries(W.find).some(([k, n]) => n > 0 && (panel(W.sl.modality).classes.find(c => c.id === k) || {}).diagnostic) ? "positive" : "negative");

  function elapsed() { return W.sl.elapsed_seconds + (isOpen() ? (performance.now() - W.fetchedAt) / 1000 : 0); }
  const tick = setInterval(() => { const e = $("#timer"); if (e && W.sl) e.textContent = fmtDur(elapsed()); }, 1000);
  S.cleanup.push(() => clearInterval(tick));

  function stepBar(sl) {
    const n = sl.fields.length;
    const st = sl.status === "confirmed" ? 4 : sl.status === "set_aside" ? 3 : n ? 2 : 1;
    const steps = [["1", "Photograph", `${n} photo${n === 1 ? "" : "s"}`], ["2", "Check", graded() ? "tap boxes to fix" : "tick what you see"], ["3", sl.status === "set_aside" ? "With expert" : "Verify", sl.status === "set_aside" ? "waiting" : "or ask an expert"]];
    return `<ol class="stepbar">${steps.map((s, i) => `<li class="${st > i + 1 ? "done" : st === i + 1 ? "now" : ""}"><span>${st > i + 1 ? "&#10003;" : s[0]}</span><div><b>${s[1]}</b><small>${s[2]}</small></div></li>`).join("")}</ol>`;
  }
  const statusPill = sl => sl.status === "confirmed" ? '<span class="pill neg">Verified</span>' : sl.status === "set_aside" ? '<span class="pill warn">Waiting for expert</span>' : '<span class="pill">Being read</span>';

  function draw() {
    const sl = W.sl, f = field();
    const nb = sl.fields.map(x => x.detections.filter(counted).length);
    const p = panel(sl.modality);
    const snap = snapSide();
    view.innerHTML = `
      <div class="topbar">
        <div><h1>${esc(sl.code)} ${demoPill(sl.demo)} ${statusPill(sl)}</h1>
          <div class="muted small">${modPill(sl.modality)} ${esc(sl.stain)} &middot; ${esc(sl.magnification)}${sl.site ? " &middot; " + esc(sl.site) : ""} &middot; started by ${esc(sl.started_by || "")}</div></div>
        <div class="sp"></div>
        <div class="timer"><span class="tiny muted">Time</span><b class="mono" id="timer">${fmtDur(elapsed())}</b></div>
      </div>
      ${stepBar(sl)}
      ${demoBanner(sl.modality)}
      ${sl.model_missing && isOpen() ? `<div class="banner">No AI for this test yet. Mark each one you see by dragging a box on the photo (on the computer, zoom in for small ones), or just count with + and &minus; ${isPhone() ? "below" : "on the right"}.</div>` : ""}
      ${isOpen() && sl.expert_note ? `<div class="banner bad"><b>Sent back by the expert:</b> ${esc(sl.expert_note)}</div>` : ""}
      ${isOpen() && sl.photos_done_at && !isPhone() ? `<div class="banner ok"><b>All photos taken</b> on the phone by ${esc(sl.photos_done_by || "")} ${ago(sl.photos_done_at)}. Check the marks here (zoom in for small ones), then verify or ask an expert.</div>` : ""}
      ${isOpen() && sl.photos_done_at && isPhone() ? `<div class="banner ok">Sent to the computer for checking. You can still verify here.</div>` : ""}
      ${W.busy ? `<div class="banner"><span class="spin"></span> ${esc(W.busy)}</div>` : ""}
      ${W.retake && isOpen() ? `<div class="banner bad retake"><b>Photo ${W.retake.field_no} looks ${esc(W.retake.flag)}.</b> ${esc(RETAKE_TIP[W.retake.flag] || "Check focus and light.")}
          <div class="row" style="margin-top:8px"><button class="primary" id="rt-again">&#128247; Retake it</button><button id="rt-keep">Keep it</button></div></div>` : ""}
      <div class="split">
        <div>
          <div class="card vcard ${W.large && f ? "large" : ""}">
            ${f && !isPhone() ? `<div class="zoombar">
                <button class="sm" id="p-prev" ${W.cur ? "" : "disabled"} title="Previous photo (left arrow)">&#9664;</button>
                <span class="small">Photo ${f.field_no} / ${sl.fields.length}</span>
                <button class="sm" id="p-next" ${W.cur < sl.fields.length - 1 ? "" : "disabled"} title="Next photo (right arrow)">&#9654;</button>
                <span class="sp"></span>
                <button class="sm" id="z-out" title="Zoom out (-)">&minus;</button><span class="mono small" id="zoom-level">${Math.round(Z.z * 100)}%</span><button class="sm" id="z-in" title="Zoom in (+)">+</button>
                <button class="sm" id="z-fit" title="Whole photo (0)">Fit</button>
                <button class="sm ${W.large ? "primary" : ""}" id="z-large" title="Large view (L), Esc to leave">${W.large ? "&#10005; Close large view" : "&#10530; Large view"}</button>
              </div>` : ""}
            ${f ? `<div class="viewer ${drawing() ? "drawing" : ""}" id="viewer"><div class="zoomer" id="zoomer"><img id="vimg" src="/api/images/${f.id}/file" alt="Field ${f.field_no}"><canvas id="cv"></canvas></div></div>
              <div class="row between" style="margin-top:8px">
                <div class="small">Photo ${f.field_no} of ${sl.fields.length}
                  ${f.quality_flag ? `<span class="pill warn">${esc(f.quality_flag)}</span>` : ""}
                  ${f.analysis ? "" : sl.model_missing ? "" : `<span class="pill warn">not analysed</span>`}</div>
                <div class="tiny muted legend">${graded() ? `<span><i style="background:#0891A0"></i>counted</span> <span><i style="background:#F79009"></i>needs a look</span> <span><i style="background:#16A34A"></i>added by you</span> <span><i style="background:#D92D20"></i>removed</span>` : `<span><i style="background:#F79009"></i>needs a look</span> <span><i style="background:#D92D20"></i>removed</span>`}</div>
              </div>
              ${isOpen() ? `<div class="row photo-tools">
                  ${canDraw() && isPhone() ? `<button class="sm ${W.drawMode ? "primary" : ""}" id="b-draw">${W.drawMode ? "&#10003; Done adding" : "&#9998; Add a missed one"}</button>` : ""}
                  <button class="sm danger" id="b-rm">Remove this photo</button></div>` : ""}
              ${drawing() && !graded() ? `<div class="markbar"><span class="tiny muted">To add a missed one, choose what it is, then drag a box around it:</span>
                  <div class="chips">${p.classes.map(c => `<button class="chip ${W.label === c.id ? "on" : ""}" data-lb="${c.id}" style="--c:${classColor(sl.modality, c.id)}">${esc(c.name)}</button>`).join("")}</div></div>` : ""}
              ${canDraw() ? `<div class="tiny muted" style="margin-top:4px">${drawing() ? (isPhone() ? "Drag a box around the one the AI missed. Tap a box to count or remove it." : "Tap a box to count or remove it. Drag on the picture to add one the AI missed.") : "Tap a box to count or remove it. To add one the AI missed, press <b>Add a missed one</b>."}</div>` : ""}
              ${!isPhone() ? `<div class="tiny muted keys">Zoom: mouse wheel or + / &minus;. Move around: hold <span class="kbd">Space</span> and drag. Photos: <span class="kbd">&larr;</span> <span class="kbd">&rarr;</span>.${!graded() && canDraw() ? ` What you mark: keys <span class="kbd">1</span>&ndash;<span class="kbd">${Math.min(9, p.classes.length)}</span>.` : ""} Large view: <span class="kbd">L</span>.</div>` : ""}`
        : `<div class="empty"><div style="font-size:40px">&#128247;</div>No photos yet. Take the first photo below.</div>`}
          </div>
          <div class="card" style="margin-top:12px">
            ${isOpen() && !isPhone() ? captureBar(sl) : ""}
            ${isOpen() ? `<div class="row"><button class="primary big" id="b-cam">&#128247; ${sl.fields.length ? "Take next photo" : "Take photo"}</button><button class="big" id="b-add">${isPhone() ? "From gallery" : "Add picture files"}</button>
                <input type="file" id="in-add" accept="image/*" multiple hidden>
                <span class="tiny muted">Aim for about ${sl.standard_fields} fields${graded() ? " (a full reading)" : ""}.</span></div>
              ${sl.fields.length && isPhone() ? `<div class="handoff">${sl.photos_done_at
                ? `<span class="small">&#10003; Marked as all photos taken.</span> <button class="sm" id="b-more">I will take more</button>`
                : `<button class="big handbtn" id="b-done">&#128187; Done taking photos: check on the computer</button>
                   <div class="tiny muted">The sample appears on the lab computer as ready to check. Or verify it here yourself.</div>`}</div>` : ""}` : ""}
            <div class="strip" style="margin-top:8px">${sl.fields.map((x, i) => `<div class="thumb ${i === W.cur ? "on" : ""}" data-i="${i}"><img loading="lazy" src="/api/images/${x.id}/thumb?size=160"><span class="c">${nb[i]}</span>${x.quality_flag ? `<span class="q">!</span>` : ""}</div>`).join("") || `<span class="muted small">No photos yet</span>`}</div>
            ${isOpen() && !isPhone() ? `<div class="drop small" id="drop" style="margin-top:8px;padding:12px">Or drop picture files here</div>` : ""}
          </div>
        </div>
        <div class="grid" style="gap:12px" id="side"></div>
      </div>
      ${isOpen() && sl.fields.length ? `<button class="fab" id="b-fab" aria-label="Take next photo">&#128247;<span>${sl.fields.length + 1}</span></button>` : ""}`;
    drawSide(snap);
    wire();
    paint();
  }

  /* ----- right-hand side: the decision ----- */
  function suggestionBox(sl) {
    const sg = sl.suggested;
    if (!sg || sg.grade == null) return sl.model_missing || !sl.fields.some(f => f.analysis) ? "" : `<div class="muted small">Add photos to get a suggestion.</div>`;
    return `<div class="suggest"><div class="tiny muted">AI and your marks suggest</div>
      <div class="row"><span class="grade ${gradeClass(sg.grade)}" style="font-size:24px">${esc(gradeLabel(sg.grade))}</span>
        ${sg.provisional && graded() ? '<span class="pill warn">fewer fields than a full reading</span>' : ""}</div>
      <div class="tiny muted">${esc(sg.explanation)}</div></div>`;
  }
  function resultControls(sl) {
    if (graded()) {
      return `${suggestionBox(sl)}<div class="tiny muted" style="margin-top:10px">Your grade</div>
        <div class="gradebtns">${["negative", "scanty", "1+", "2+", "3+"].map(g => `<button data-g="${g}" class="${W.grade === g ? "on " + gradeClass(g) : ""}">${gradeLabel(g)}</button>`).join("")}</div>`;
    }
    const p = panel(sl.modality), groups = {};
    p.classes.forEach(c => (groups[c.group] = groups[c.group] || []).push(c));
    const res = currentResult();
    const sgf = (sl.suggested && sl.suggested.findings) || {};
    const differs = JSON.stringify(Object.entries(W.find).filter(([, n]) => n > 0).sort()) !== JSON.stringify(Object.entries(sgf).filter(([, n]) => n > 0).sort());
    return `${suggestionBox(sl)}
      ${W.findTouched && differs && Object.keys(sgf).length ? `<button class="sm" id="f-reset" style="margin-top:6px">Use the counts from the marks</button>` : ""}
      <div class="tiny muted" style="margin-top:10px">What did you see? Use + and &minus;.</div>
      <div class="checklist">${Object.entries(groups).map(([g, cs]) => `<div class="grp">${esc(g)}</div>${cs.map(c => {
        const n = W.find[c.id] || 0;
        return `<div class="ck-row ${n ? "on" : ""}" style="--c:${classColor(sl.modality, c.id)}"><div class="ck-name"><b>${esc(c.name)}</b><div class="tiny muted">${esc(c.look)}</div></div>
          <div class="stepper"><button data-dec="${c.id}" aria-label="less">&minus;</button><span>${n}</span><button data-inc="${c.id}" aria-label="more">+</button></div></div>`;
      }).join("")}`).join("")}</div>
      <div class="resline">Result: <span class="grade ${gradeClass(res)}" style="font-size:24px">${gradeLabel(res)}</span></div>`;
  }
  function needsReason(sl) { const sg = sl.suggested && sl.suggested.grade; return !!(sl.model_id && sg && currentResult() !== sg); }
  function moreOptions(prefix) {
    return `<details class="opts"><summary>More options</summary><div class="grid" style="gap:8px;margin-top:8px">
      ${prefix === "c" ? `<label class="f">How long this would take you by eye, m:ss (optional, to measure time saved)<input id="c-manual" placeholder="e.g. 7:30" style="width:120px"></label>` : ""}
      <label class="chk"><input type="checkbox" id="${prefix}-ds"> Use these photos and marks to train the AI</label>
      <label class="chk" id="${prefix}-consent-wrap" hidden><input type="checkbox" id="${prefix}-consent"> Consent or an ethics waiver covers training use, and no patient details are visible.</label></div></details>`;
  }
  function techCard(sl) {
    const r = ASIDE_REASONS[graded() ? "graded" : "findings"];
    return `<div class="card" id="decision"><h2>Your result</h2>
      ${resultControls(sl)}
      <label class="f" id="c-why-wrap" ${needsReason(sl) ? "" : "hidden"} style="margin-top:8px">Why is your result different from the suggestion?
        <input id="c-why" placeholder="e.g. clumps counted as one"></label>
      <div class="bigbtns">
        <button class="primary big okbtn" id="b-verify" ${sl.fields.length ? "" : "disabled"}>&#10003; Verify result</button>
        <button class="big warnbtn" id="b-unsure" ${sl.fields.length ? "" : "disabled"}>? Not sure: ask an expert</button>
      </div>
      <div id="aside-box" class="aside-box" ${W.aside ? "" : "hidden"}>
        <div class="small"><b>Why are you not sure?</b></div>
        <div class="chips">${r.map(x => `<button class="chip ${W.chips.has(x) ? "on" : ""}" data-rs="${esc(x)}">${esc(x)}</button>`).join("")}</div>
        <input id="a-text" placeholder="Anything else for the expert (optional)" style="width:100%;margin-top:6px">
        <div class="tiny muted" style="margin-top:4px">Your result above is sent as your best guess. The sample waits in the Expert queue, and you can carry on with the next one.</div>
        <button class="big warnbtn solid" id="a-send" style="margin-top:8px">Send to expert</button>
      </div>
      ${moreOptions("c")}
      <div class="tiny muted" style="margin-top:8px">One person verifies. If you are unsure, an expert checks it. S4Sight suggests; a person decides.</div></div>`;
  }
  function asideInfo(sl) {
    return `<div class="banner"><b>Set aside by ${esc(sl.set_aside_by || "")}</b> ${ago(sl.set_aside_at)}: ${esc(sl.set_aside_reason || "")}
      <div style="margin-top:4px">Technician's best guess: ${gradePill(sl.tech_result)} ${!graded() ? findingsText(sl.modality, sl.tech_findings) : ""}</div></div>`;
  }
  function expertCard(sl) {
    return `<div class="card" id="decision"><h2>Expert decision</h2>${asideInfo(sl)}
      ${resultControls(sl)}
      <label class="f" style="margin-top:8px">Note for the technician (optional; needed to send back)<input id="x-note" placeholder="e.g. this is pollen, not an egg"></label>
      <div class="bigbtns">
        <button class="primary big okbtn" id="x-verify">&#10003; Verify as expert</button>
        <button class="big" id="x-back">Send back to the bench</button></div>
      ${moreOptions("x")}</div>`;
  }
  function waitingCard(sl) {
    const me = reader(), mine = me === sl.set_aside_by;
    return `<div class="card"><h2>Waiting for an expert</h2>${asideInfo(sl)}
      <p class="small">${mine && isExpert() ? "You set this sample aside, so a different expert verifies it." :
        "An expert (senior reader or lab lead) verifies this from the <a href=\"#/expert\">Expert queue</a>. If you are the expert, choose your name under <i>Who is working?</i>"}</p>
      <a class="btn primary big" href="#/analyze">Next sample</a></div>`;
  }
  function doneCard(sl) {
    const r = sl.reference_result;
    const rep = sl.report || [];
    return `<div class="card"><h2>Result</h2>
      <div class="row"><div><div class="tiny muted">${graded() ? "Final grade" : "Final result"}</div><div class="grade ${gradeClass(sl.final_grade)}">${esc(gradeLabel(sl.final_grade))}</div></div>
        ${sl.ai_grade ? `<div><div class="tiny muted">AI alone</div><div style="font-size:18px;font-weight:700">${esc(gradeLabel(sl.ai_grade))}</div></div>` : ""}</div>
      ${rep.length ? `<ul class="report">${rep.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
      <div class="small" style="margin-top:8px">Verified by ${verifiedBy(sl)}${sl.session_seconds ? ` &middot; bench time <b>${fmtDur(sl.session_seconds)}</b>` : ""}</div>
      ${sl.set_aside_by ? `<div class="small muted">Set aside by ${esc(sl.set_aside_by)}: ${esc(sl.set_aside_reason || "")} (best guess: ${esc(gradeLabel(sl.tech_result))})</div>` : ""}
      ${sl.expert_note ? `<div class="small muted">Expert note: ${esc(sl.expert_note)}</div>` : ""}
      ${sl.override_reason ? `<div class="small muted">Why it differs from the AI: ${esc(sl.override_reason)}</div>` : ""}
      <div style="margin-top:14px"><a class="btn primary big" href="#/analyze/new/${sl.modality}">Next ${esc(MOD_SHORT[sl.modality])} sample</a></div>
      <details class="opts" style="margin-top:12px"><summary>Reference test result (optional, for the performance figures)</summary>
        <div class="row" style="margin-top:8px"><select id="r-res"><option value="">Not available</option><option value="pos" ${r === "pos" ? "selected" : ""}>Positive</option><option value="neg" ${r === "neg" ? "selected" : ""}>Negative</option></select>
        <input id="r-method" placeholder="Method (e.g. Xpert, culture, NAAT)" value="${esc(sl.reference_method || "")}" style="width:200px">
        <button id="r-save">Save</button></div></details></div>
      ${graded() ? confirmationCard(sl, W.hist) : ""}`;
  }
  // keep what the person typed or ticked when the panel is redrawn (e.g. after pressing + or -, or a new photo)
  function snapSide() {
    const side = $("#side"), kept = {};
    if (!side) return { kept, opened: [] };
    $$("input, textarea", side).forEach(i => { if (i.id) kept[i.id] = i.type === "checkbox" ? i.checked : i.value; });
    return { kept, opened: $$("details", side).map(d => d.open) };
  }
  function drawSide(snap) {
    const sl = W.sl;
    const { kept, opened } = snap || snapSide();
    const side = $("#side");
    if (!side) return;
    const expertHere = sl.status === "set_aside" && isExpert() && reader() !== sl.set_aside_by;
    side.innerHTML = isOpen() ? techCard(sl) : sl.status === "set_aside" ? (expertHere ? expertCard(sl) : waitingCard(sl)) : doneCard(sl);
    Object.entries(kept).forEach(([id, v]) => { const i = $("#" + id, side); if (i) { if (i.type === "checkbox") i.checked = v; else if (i.type !== "file") i.value = v; } });
    $$("details", side).forEach((d, i) => { if (opened[i]) d.open = true; });
    ["c", "x"].forEach(px => { const d = $(`#${px}-ds`, side), w = $(`#${px}-consent-wrap`, side); if (d && w) w.hidden = !d.checked; });
    wireSide();
  }
  function body(prefix) {
    const ds = $(`#${prefix}-ds`), cs = $(`#${prefix}-consent`);
    const b = { add_to_dataset: !!(ds && ds.checked), consent_confirmed: !!(cs && cs.checked) };
    if (graded()) b.final_grade = W.grade; else b.findings = { ...W.find };
    return b;
  }
  function wireSide() {
    const sl = W.sl;
    $$("[data-g]").forEach(b => b.onclick = () => { W.grade = b.dataset.g; W.gradeTouched = true; drawSide(); });
    $$("[data-inc]").forEach(b => b.onclick = () => { W.find[b.dataset.inc] = (W.find[b.dataset.inc] || 0) + 1; W.findTouched = true; drawSide(); });
    $$("[data-dec]").forEach(b => b.onclick = () => { W.find[b.dataset.dec] = Math.max(0, (W.find[b.dataset.dec] || 0) - 1); W.findTouched = true; drawSide(); });
    const fr = $("#f-reset"); if (fr) fr.onclick = () => { W.findTouched = false; syncResult(); drawSide(); };
    ["c", "x"].forEach(px => { const d = $(`#${px}-ds`); if (d) d.onchange = e => { $(`#${px}-consent-wrap`).hidden = !e.target.checked; }; });
    const ver = $("#b-verify");
    if (ver) ver.onclick = () => guard(async () => {
      let manual = null; const mv = ($("#c-manual") || { value: "" }).value.trim();
      if (mv) { const m = mv.match(/^(\d+):(\d{1,2})$/); manual = m ? (+m[1]) * 60 + (+m[2]) : parseFloat(mv) * 60; if (isNaN(manual)) throw new Error("Enter the time as m:ss, e.g. 7:30"); }
      const why = $("#c-why");
      if (needsReason(sl) && !why.value.trim()) { $("#c-why-wrap").hidden = false; why.focus(); throw new Error("Your result differs from the suggestion: write a short reason."); }
      W.sl = await api(`/api/slides/${sid}/confirm`, { method: "POST", json: { ...body("c"), override_reason: why ? why.value : "", manual_seconds: manual } });
      toast("Verified in " + fmtDur(W.sl.session_seconds)); refreshState(); W.fetchedAt = performance.now(); draw();
    });
    const un = $("#b-unsure"); if (un) un.onclick = () => { W.aside = !W.aside; $("#aside-box").hidden = !W.aside; if (W.aside) $("#a-text").focus(); };
    $$("[data-rs]").forEach(b => b.onclick = () => { const v = b.dataset.rs; W.chips.has(v) ? W.chips.delete(v) : W.chips.add(v); b.classList.toggle("on"); });
    const send = $("#a-send");
    if (send) send.onclick = () => guard(async () => {
      const reason = [...W.chips, $("#a-text").value.trim()].filter(Boolean).join(". ");
      if (!reason) throw new Error("Tick a reason or write a few words for the expert.");
      const b = body("c");
      W.sl = await api(`/api/slides/${sid}/set-aside`, { method: "POST", json: { reason, final_grade: b.final_grade || null, findings: b.findings || {} } });
      toast("Sent to the Expert queue. You can start the next sample."); await refreshState(); draw();
    });
    const xv = $("#x-verify");
    if (xv) xv.onclick = () => guard(async () => {
      W.sl = await api(`/api/slides/${sid}/expert-verify`, { method: "POST", json: { ...body("x"), note: $("#x-note").value } });
      toast("Verified by expert"); await refreshState(); draw();
    });
    const xb = $("#x-back");
    if (xb) xb.onclick = () => guard(async () => {
      const note = $("#x-note").value.trim();
      if (!note) { $("#x-note").focus(); throw new Error("Write in the note what the technician should do."); }
      W.sl = await api(`/api/slides/${sid}/return`, { method: "POST", json: { note } });
      toast("Sent back to the bench"); await refreshState(); draw();
    });
    const sv = $("#r-save");
    if (sv) sv.onclick = () => guard(async () => { W.sl = await api(`/api/slides/${sid}/reference`, { method: "PATCH", json: { reference_result: $("#r-res").value || null, reference_method: $("#r-method").value } }); toast("Saved"); });
    if (sl.status === "confirmed" && graded()) wireConfirmation(sl, W.hist, async () => { await load(); refreshState(); });
  }

  /* ----- canvas ----- */
  /* ----- zoom and pan (for accurate marking on the computer) ----- */
  const Z = { z: 1, tx: 0, ty: 0, fieldId: null, pan: null, space: false };
  function zoomer() { return $("#zoomer"); }
  function clampPan() {
    const zm = zoomer(); if (!zm) return;
    const bw = zm.offsetWidth, bh = zm.offsetHeight;
    Z.tx = Math.min(0, Math.max(bw - bw * Z.z, Z.tx));
    Z.ty = Math.min(0, Math.max(bh - bh * Z.z, Z.ty));
  }
  function applyZoom(repaint = true) {
    const zm = zoomer(); if (!zm) return;
    clampPan();
    zm.style.transform = `translate(${Z.tx}px,${Z.ty}px) scale(${Z.z})`;
    const lv = $("#zoom-level"); if (lv) lv.textContent = Math.round(Z.z * 100) + "%";
    if (repaint && W.fit) W.fit();
  }
  function zoomAt(factor, clientX, clientY) {
    const zm = zoomer(); if (!zm) return;
    const vr = zm.parentElement.getBoundingClientRect();
    const ox = vr.left + zm.offsetLeft, oy = vr.top + zm.offsetTop;
    const mx = clientX == null ? zm.offsetWidth / 2 : clientX - ox, my = clientY == null ? zm.offsetHeight / 2 : clientY - oy;
    const nz = Math.min(8, Math.max(1, Z.z * factor));
    const px = (mx - Z.tx) / Z.z, py = (my - Z.ty) / Z.z;
    Z.tx = mx - px * nz; Z.ty = my - py * nz; Z.z = nz;
    applyZoom();
  }
  function zoomReset() { Z.z = 1; Z.tx = 0; Z.ty = 0; applyZoom(); }
  /* large view: the photo fills the window (and the screen), for careful marking */
  function sizeLarge() {
    const zm = zoomer(), img = $("#vimg"); if (!zm || !img) return;
    if (!W.large || !img.naturalWidth) { zm.style.width = ""; return; }
    const v = zm.parentElement, a = img.naturalWidth / img.naturalHeight;
    zm.style.width = Math.floor(Math.min(v.clientWidth, v.clientHeight * a)) + "px";
  }
  function setLarge(on) {
    W.large = on;
    try {
      if (on && document.documentElement.requestFullscreen && !document.fullscreenElement) document.documentElement.requestFullscreen().catch(() => {});
      if (!on && document.fullscreenElement) document.exitFullscreen().catch(() => {});
    } catch (e) {}
    Z.z = 1; Z.tx = 0; Z.ty = 0;
    draw();
  }

  function paint() {
    const cv = $("#cv"), img = $("#vimg");
    if (!cv || !img) return;
    const f0 = field();
    if (f0 && Z.fieldId !== f0.id) { Z.fieldId = f0.id; Z.z = 1; Z.tx = 0; Z.ty = 0; }
    const fit = () => {
      // draw in CSS pixels of the (unzoomed) photo; the backing store follows the zoom so lines stay sharp
      sizeLarge();
      const cw = cv.offsetWidth, ch = cv.offsetHeight, dpr = window.devicePixelRatio || 1;
      if (!cw || !ch) return;
      const sc = Math.min(dpr * Z.z, 4096 / Math.max(cw, ch));
      cv.width = Math.round(cw * sc); cv.height = Math.round(ch * sc);
      const ctx = cv.getContext("2d"); ctx.setTransform(sc, 0, 0, sc, 0, 0);
      const r = { width: cw, height: ch }, k = 1 / Z.z;           // k keeps outlines and labels the same size on screen
      ctx.clearRect(0, 0, r.width, r.height);
      const f = field(); if (!f) return;
      f.detections.forEach(d => {
        const x = (d.cx - d.w / 2) * r.width, y = (d.cy - d.h / 2) * r.height, w = d.w * r.width, h = d.h * r.height;
        const base = graded() ? "#0891A0" : classColor(W.sl.modality, d.label);
        let col, dash = [];
        if (d.status === "removed") { col = "#D92D20"; dash = [4, 3]; }
        else if (d.status === "added") col = graded() ? "#16A34A" : base;
        else if (d.status === "kept") col = base;
        else if (d.conf < thr().positive) { col = "#F79009"; dash = [4, 3]; }
        else if (d.conf < thr().review) col = "#F79009";
        else col = base;
        ctx.lineWidth = 2 * k; ctx.strokeStyle = col; ctx.setLineDash(dash.map(v => v * k));
        const pad = 3 * k; ctx.strokeRect(x - pad, y - pad, w + 2 * pad, h + 2 * pad);
        ctx.setLineDash([]); ctx.font = `${11 * k}px system-ui`; ctx.fillStyle = col;
        const name = graded() ? "" : className(W.sl.modality, d.label).split(" ")[0] + " ";
        const label = name + (d.status === "added" ? "added" : Math.round(d.conf * 100) + "%");
        ctx.fillText(label, x - pad, Math.max(10 * k, y - pad - 3 * k));
      });
      if (W.drag && W.drag.moved && W.drag.draw) {
        const a = W.drag; ctx.strokeStyle = graded() ? "#16A34A" : classColor(W.sl.modality, W.label); ctx.setLineDash([5 * k, 3 * k]); ctx.lineWidth = 2 * k;
        ctx.strokeRect(Math.min(a.x0, a.x1) * r.width, Math.min(a.y0, a.y1) * r.height, Math.abs(a.x1 - a.x0) * r.width, Math.abs(a.y1 - a.y0) * r.height);
      }
    };
    W.fit = fit;
    if (img.complete) { applyZoom(false); fit(); } else img.onload = () => { applyZoom(false); fit(); };
    if (!W.ro) { W.ro = new ResizeObserver(() => W.fit && W.fit()); }
    W.ro.disconnect(); W.ro.observe(cv.parentElement.parentElement);
  }
  S.cleanup.push(() => W.ro && W.ro.disconnect());

  function pos(e) { const r = $("#cv").getBoundingClientRect(); return [Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))]; }
  function hit(x, y) {
    const f = field(); let best = null, area = 9;
    f.detections.forEach(d => {
      const m = 0.012 / Z.z;                              // zoomed in = finer picking
      if (x >= d.cx - d.w / 2 - m && x <= d.cx + d.w / 2 + m && y >= d.cy - d.h / 2 - m && y <= d.cy + d.h / 2 + m && d.w * d.h < area) { best = d; area = d.w * d.h; }
    });
    return best;
  }

  function wire() {
    $$(".thumb").forEach(t => t.onclick = () => { W.cur = +t.dataset.i; draw(); });
    $$("[data-lb]").forEach(b => b.onclick = () => { W.label = b.dataset.lb; $$("[data-lb]").forEach(x => x.classList.toggle("on", x === b)); });
    const cv = $("#cv"), vw = $("#viewer");
    // zoom tools (mouse wheel, buttons) work on every sample, also verified ones
    if (vw && !isPhone()) vw.onwheel = e => { e.preventDefault(); zoomAt(e.deltaY < 0 ? 1.25 : 0.8, e.clientX, e.clientY); };
    const zi = $("#z-in"), zo = $("#z-out"), zf = $("#z-fit"), zl = $("#z-large"), pv = $("#p-prev"), nx = $("#p-next");
    if (zi) zi.onclick = () => zoomAt(1.5);
    if (zo) zo.onclick = () => zoomAt(1 / 1.5);
    if (zf) zf.onclick = zoomReset;
    if (zl) zl.onclick = () => setLarge(!W.large);
    if (pv) pv.onclick = () => { if (W.cur > 0) { W.cur--; draw(); } };
    if (nx) nx.onclick = () => { if (W.cur < W.sl.fields.length - 1) { W.cur++; draw(); } };
    const startPan = e => (Z.space || e.button === 1 || (!canDraw() && Z.z > 1 && e.pointerType === "mouse"));
    if (cv) {
      cv.onpointerdown = e => {
        if (startPan(e)) {                               // Space + drag, or the middle button: move around the zoomed photo
          e.preventDefault(); cv.setPointerCapture(e.pointerId);
          Z.pan = { x: e.clientX, y: e.clientY, tx: Z.tx, ty: Z.ty }; cv.style.cursor = "grabbing"; return;
        }
        if (!canDraw()) return;
        if (drawing()) cv.setPointerCapture(e.pointerId);
        const [x, y] = pos(e); W.drag = { x0: x, y0: y, x1: x, y1: y, moved: false, draw: drawing() };
      };
      cv.onpointermove = e => {
        if (Z.pan) { Z.tx = Z.pan.tx + e.clientX - Z.pan.x; Z.ty = Z.pan.ty + e.clientY - Z.pan.y; applyZoom(false); return; }
        if (!W.drag) return; const [x, y] = pos(e); W.drag.x1 = x; W.drag.y1 = y;
        if (Math.hypot(x - W.drag.x0, y - W.drag.y0) > 0.012 / Z.z) W.drag.moved = true;
        if (W.drag.draw) W.fit();
      };
      cv.onpointercancel = () => { W.drag = null; Z.pan = null; };     // the finger scrolled the page instead
    }
    if (cv) {
      cv.onpointerup = () => guard(async () => {
        if (Z.pan) { Z.pan = null; cv.style.cursor = ""; W.fit(); return; }
        const a = W.drag; W.drag = null; if (!a) return;
        if (a.moved && !a.draw) return;                  // a swipe while not adding: ignore
        if (!a.moved) {
          const d = hit(a.x0, a.y0);
          if (d) { await api("/api/detections/" + d.id, { method: "PATCH", json: { status: counted(d) ? "removed" : "kept" } }); await load(); }
          else W.fit();
        } else {
          const w = Math.abs(a.x1 - a.x0), h = Math.abs(a.y1 - a.y0);
          await api(`/api/images/${field().id}/detections`, { method: "POST", json: { cx: (a.x0 + a.x1) / 2, cy: (a.y0 + a.y1) / 2, w, h, label: graded() ? "" : W.label } });
          await load();
        }
      });
    }
    if (!isOpen()) return;
    const upload = async files => {
      files = [...files].filter(f => f.type.startsWith("image/") || /\.(jpe?g|png|bmp|tiff?|heic)$/i.test(f.name));
      if (!files.length) return;
      let n = 0, flagged = null; const errs = [];
      W.retake = null;
      for (const f of files) {
        n++; W.busy = files.length > 1 ? `Sending photo ${n} of ${files.length}...` : "Sending the photo...";
        draw();
        const fd = new FormData(); fd.append("files", await shrinkImage(f));
        try {
          const d = await api(`/api/slides/${sid}/fields`, { method: "POST", form: fd });
          W.sl = d; W.fetchedAt = performance.now();
          (d.upload_results || []).forEach(r => {
            if (r.error) errs.push(`${r.file}: ${r.error}`);
            else if (r.quality_flag) flagged = { image_id: r.image_id, field_no: r.field_no, flag: r.quality_flag };
          });
        } catch (e) { errs.push(f.name + ": " + e.message); }
      }
      if (files.length === 1 && flagged) W.retake = flagged;     // one photo at the eyepiece: offer a retake at once
      W.busy = null; W.cur = Math.max(0, W.sl.fields.length - 1); syncResult(); draw();
      if (errs.length) toast(errs[0], true);
      else if (!W.retake && navigator.vibrate) try { navigator.vibrate(40); } catch (e) {}
    };
    const removePhoto = async (imageId, quiet) => {
      W.sl = await api(`/api/slides/${sid}/fields/${imageId}`, { method: "DELETE" });
      W.fetchedAt = performance.now(); W.cur = Math.max(0, Math.min(W.cur, W.sl.fields.length - 1));
      syncResult(); draw(); if (!quiet) toast("Photo removed");
    };
    W.upload = upload;
    wireCaptureBar();
    $("#b-cam").onclick = () => cam.click();
    $("#b-add").onclick = () => $("#in-add").click();
    const fab = $("#b-fab"); if (fab) fab.onclick = () => cam.click();
    $("#in-add").onchange = e => { upload([...e.target.files]); };
    const bd = $("#b-draw"); if (bd) bd.onclick = () => { W.drawMode = !W.drawMode; draw(); };
    const rm = $("#b-rm");
    if (rm) rm.onclick = () => { const f = field(); if (f && confirm(`Remove photo ${f.field_no} from this sample?`)) guard(() => removePhoto(f.id)); };
    const ra = $("#rt-again");
    if (ra) ra.onclick = () => { const r = W.retake; W.retake = null; cam.click(); guard(() => removePhoto(r.image_id, true)); };
    const rk = $("#rt-keep"); if (rk) rk.onclick = () => { W.retake = null; draw(); };
    const bdn = $("#b-done");
    if (bdn) bdn.onclick = () => guard(async () => {
      W.sl = await api(`/api/slides/${sid}/photos-done`, { method: "POST", json: { done: true } });
      toast("Sent to the computer. Start the next sample whenever you are ready.");
      if (isPhone()) go("#/"); else draw();
    });
    const bmo = $("#b-more");
    if (bmo) bmo.onclick = () => guard(async () => { W.sl = await api(`/api/slides/${sid}/photos-done`, { method: "POST", json: { done: false } }); draw(); });
    const drop = $("#drop");
    if (drop) {
      ["dragover", "dragenter"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); }));
      ["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); }));
      drop.addEventListener("drop", e => upload(e.dataTransfer.files));
    }
  }
  /* ----- phone selection and live refresh ----- */
  function captureBar(sl) {
    const sel = sl.capture_device_id, devs = W.devices.filter(d => !d.revoked);
    return `<div class="capbar">
      <label class="f" style="flex:1;min-width:230px">Take photos with
        <select id="cap-sel"><option value="">This computer (camera or picture files)</option>
          ${devs.map(d => `<option value="${d.id}" ${sel === d.id ? "selected" : ""}>Phone: ${esc(d.name)} (${d.online ? "online" : "offline"})</option>`).join("")}
          <option value="__pair">+ Connect a phone...</option></select></label>
      <div class="small" id="cap-state" style="flex:2;min-width:220px">${capState(sl)}</div></div>`;
  }
  function capState(sl) {
    const d = sl.capture_device;
    if (!d) return `<span class="muted">Use the buttons below, or choose a phone.</span>`;
    return d.online
      ? `<span class="pill neg">online</span> Take the photos on <b>${esc(d.name)}</b>. They appear here by themselves.`
      : `<span class="pill warn">offline</span> On <b>${esc(d.name)}</b>, open the S4Sight camera page (it reconnects by itself).`;
  }
  function wireCaptureBar() {
    const sel = $("#cap-sel"); if (!sel) return;
    sel.onchange = () => guard(async () => {
      if (sel.value === "__pair") { sel.value = W.sl.capture_device_id || ""; openPairing(async d => { await api(`/api/slides/${sid}/capture-device`, { method: "PUT", json: { device_id: d.id } }); await load(); }); return; }
      W.sl = await api(`/api/slides/${sid}/capture-device`, { method: "PUT", json: { device_id: sel.value ? +sel.value : null } });
      toast(sel.value ? "Phone selected" : "Using this computer"); await load();
    });
  }
  /* ----- keyboard (computer) ----- */
  const onKey = e => {
    if (!W.sl || !location.hash.startsWith("#/analyze/" + sid)) return;
    const t = e.target.tagName;
    if (["INPUT", "TEXTAREA", "SELECT"].includes(t) || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.type === "keyup") { if (e.code === "Space") { Z.space = false; } return; }
    if (e.code === "Space" && $("#cv")) { Z.space = true; e.preventDefault(); return; }
    const k = e.key;
    if (k === "ArrowLeft" && W.cur > 0) { W.cur--; draw(); }
    else if (k === "ArrowRight" && W.cur < W.sl.fields.length - 1) { W.cur++; draw(); }
    else if (k === "+" || k === "=") zoomAt(1.5);
    else if (k === "-" || k === "_") zoomAt(1 / 1.5);
    else if (k === "0") zoomReset();
    else if (k === "l" || k === "L") setLarge(!W.large);
    else if (k === "Escape" && W.large) setLarge(false);
    else if (/^[1-9]$/.test(k) && !graded() && canDraw()) {
      const c = panel(W.sl.modality).classes[+k - 1];
      if (c) { W.label = c.id; $$("[data-lb]").forEach(x => x.classList.toggle("on", x.dataset.lb === c.id)); toast("Marking: " + c.name); }
    } else return;
    e.preventDefault();
  };
  document.addEventListener("keydown", onKey);
  document.addEventListener("keyup", onKey);
  const onFs = () => { if (!document.fullscreenElement && W.large) { W.large = false; draw(); } };
  document.addEventListener("fullscreenchange", onFs);
  S.cleanup.push(() => {
    document.removeEventListener("keydown", onKey); document.removeEventListener("keyup", onKey);
    document.removeEventListener("fullscreenchange", onFs);
    if (W.large && document.fullscreenElement) document.exitFullscreen().catch(() => {});
  });

  const capTimer = setInterval(async () => {
    if (!W.sl || W.sl.status === "confirmed" || !location.hash.startsWith("#/analyze/" + sid) || W.busy || W.drag || Z.pan) return;
    try {
      const c = await api(`/api/slides/${sid}/capture-status`);
      if (c.status !== W.sl.status) { await load(); toast(c.status === "confirmed" ? "This sample was verified on another device" : c.status === "set_aside" ? "Sent to the Expert queue from another device" : "Sample updated"); return; }
      if (W.sl.status !== "open") return;
      if (c.n_fields !== W.sl.fields.length) {
        const before = W.sl.fields.length, wasLast = W.cur >= before - 1 && Z.z === 1;
        await load();
        if (wasLast || !before) { W.cur = Math.max(0, W.sl.fields.length - 1); draw(); toast("New photo received"); }
        else toast(c.n_fields > before ? `Photo ${c.n_fields} received. Press the right arrow when you are ready.` : "A photo was removed on the phone");
      }
      else if ((c.photos_done_at || null) !== (W.sl.photos_done_at || null)) { await load(); if (c.photos_done_at) toast("The phone has finished taking photos"); }
      else if (c.device && W.sl.capture_device && (c.device.online !== W.sl.capture_device.online)) { W.sl.capture_device = c.device; const e = $("#cap-state"); if (e) e.innerHTML = capState(W.sl); }
    } catch (e) {}
  }, 3000);
  S.cleanup.push(() => clearInterval(capTimer));
  load().catch(e => { view.innerHTML = `<div class="banner bad">${esc(e.message)}</div>`; });
}

/* ---------------- Results ---------------- */
route("results", async view => {
  const R = { mod: lastUsed("ss_rmod", ""), q: "" };
  const all = await api("/api/slides?status=confirmed&limit=500");
  function draw() {
    const rows = all.filter(s => (!R.mod || s.modality === R.mod) && (!R.q || s.code.toLowerCase().includes(R.q.toLowerCase())));
    view.innerHTML = `
      <div class="topbar"><div><h1>Results</h1><div class="muted small">Verified samples, newest first.</div></div><div class="sp"></div>
        <input id="rs-q" placeholder="Find a sample number" value="${esc(R.q)}" style="width:200px"></div>
      <div class="tabs"><a data-m="" class="${R.mod === "" ? "on" : ""}">All</a>${S.state.panel_order.map(k => `<a data-m="${k}" class="${R.mod === k ? "on" : ""}">${esc(MOD_SHORT[k])}</a>`).join("")}</div>
      <div class="card">${rows.length ? `<table><thead><tr><th>Sample</th><th>Test</th><th>Result</th><th>Verified by</th><th>When</th></tr></thead><tbody>
        ${rows.map(s => `<tr class="click" onclick="go('#/analyze/${s.id}')"><td><b>${esc(s.code)}</b> ${demoPill(s.demo)}</td><td>${modPill(s.modality)}</td><td>${resultCell(s)}</td><td class="small">${verifiedBy(s)}</td><td class="tiny muted">${fmtDate(s.confirmed_at)}</td></tr>`).join("")}</tbody></table>`
        : `<div class="empty small">No verified samples here yet.</div>`}</div>
      <div style="margin-top:10px"><a class="btn" href="/api/export/slides.csv?include_demo=1">Download all results (CSV)</a></div>`;
    $$(".tabs a").forEach(a => a.onclick = () => { R.mod = a.dataset.m; remember("ss_rmod", R.mod); draw(); });
    const q = $("#rs-q"); q.oninput = () => { R.q = q.value; const p = q.selectionStart; draw(); const n = $("#rs-q"); n.focus(); n.setSelectionRange(p, p); };
  }
  draw();
});

/* ---------------- Expert queue ---------------- */
route("expert", async view => {
  const items = await api("/api/slides?status=set_aside&limit=200");
  items.sort((a, b) => (a.set_aside_at || 0) - (b.set_aside_at || 0));
  const me = reader(), expert = isExpert();
  view.innerHTML = `
    <div class="topbar"><div><h1>Expert queue</h1>
      <div class="muted small">Samples a technician was not sure about. Oldest first. Open one, check the photos, and verify it or send it back.</div></div></div>
    ${expert ? "" : `<div class="banner">You are working as <b>${esc(me)}</b> (${esc(roleLabel(roleOf(me)))}). Only an expert (senior reader or lab lead) can verify these. If that is you, choose your name under <i>Who is working?</i></div>`}
    <div class="card">${items.length ? `<table><thead><tr><th>Sample</th><th>Test</th><th>Why it was set aside</th><th>Best guess</th><th>Waiting</th><th></th></tr></thead><tbody>
      ${items.map(s => `<tr class="click" onclick="go('#/analyze/${s.id}')"><td><b>${esc(s.code)}</b> ${demoPill(s.demo)}<div class="tiny muted">${s.n_fields} photos</div></td><td>${modPill(s.modality)}</td>
        <td class="small">${esc(s.set_aside_reason || "")}<div class="tiny muted">by ${esc(s.set_aside_by || "")}</div></td>
        <td>${gradePill(s.tech_result)}${!isGraded(s.modality) && findingsText(s.modality, s.tech_findings) ? `<div class="tiny muted">${findingsText(s.modality, s.tech_findings)}</div>` : ""}</td>
        <td class="tiny muted">${ago(s.set_aside_at)}</td>
        <td><button class="sm ${expert && s.set_aside_by !== me ? "primary" : ""}">${expert && s.set_aside_by !== me ? "Check" : "View"}</button></td></tr>`).join("")}</tbody></table>`
      : `<div class="empty">Nothing is waiting. &#10003;</div>`}</div>`;
});
route("review", async view => { go("#/expert"); });

/* ---------------- More (the phone's menu for the less used pages) ---------------- */
route("more", async view => {
  const am = S.state.active_models;
  view.innerHTML = `
    <div class="topbar"><div><h1>More</h1><div class="muted small">Working as ${esc(reader())} (${esc(roleLabel(roleOf(reader())))})</div></div></div>
    <div class="menu-list card">
      <a href="#/dataset"><b>Training pictures</b><span>Pictures and marks that teach the AI</span></a>
      <a href="#/training"><b>AI models</b><span>Train, approve or roll back a model</span></a>
      <a href="#/performance"><b>Performance</b><span>Time per sample, accuracy against reference tests</span></a>
      <a href="#/settings"><b>Settings and phones</b><span>People, cut-offs, targets, backup</span></a>
      <a href="#" class="open-phone"><b>Open on another phone</b><span>QR code for a colleague's phone</span></a>
      <a href="#" id="fb-link-m"><b>Give feedback</b><span>Tell us what is easy or hard</span></a>
    </div>
    <div class="card" style="margin-top:14px"><h2>AI for each test</h2>
      <table><tbody>${S.state.panel_order.map(k => `<tr><td>${modPill(k)}</td><td class="small">${am[k] ? esc(am[k].name) + (am[k].demo ? ' <span class="pill demo">DEMO</span>' : "") : '<span class="muted">none yet: record by eye</span>'}</td></tr>`).join("")}</tbody></table></div>
    <p class="tiny muted" style="margin-top:12px">S4Sight ${esc(S.state.version)}. It suggests; a person decides. Not a validated diagnostic device.</p>`;
  $("#fb-link-m").onclick = e => { e.preventDefault(); openFeedback(); };
});
