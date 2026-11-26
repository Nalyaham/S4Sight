/* v2 pieces: phone pairing, positive confirmation, blind re-read, cut-offs, phones and tuning panels, feedback */

/* ---------------- Pair a phone ---------------- */
function openPairing(onPaired) {
  let timer = null, tick = null, known = null, closed = false;
  const m = modal(`<h2>Pair a phone</h2><div id="pr-body"><div class="empty"><span class="spin"></span></div></div>
    <div class="row" style="margin-top:12px"><button id="pr-close">Close</button></div>`);
  const stop = () => { closed = true; clearInterval(timer); clearInterval(tick); m.close(); };
  $("#pr-close", m).onclick = stop;
  const obs = new MutationObserver(() => { if (!document.body.contains(m)) { closed = true; clearInterval(timer); clearInterval(tick); obs.disconnect(); } });
  obs.observe(document.body, { childList: true });
  (async () => {
    try {
      known = new Set((await api("/api/devices")).devices.map(d => d.id));
      const p = await api("/api/devices/pairing", { method: "POST", json: {} });
      const warn = p.network.warnings.map(w => `<div class="banner" style="margin:8px 0">${esc(w)}</div>`).join("");
      $("#pr-body", m).innerHTML = `
        <ol class="small" style="margin:0 0 10px 18px;padding:0;line-height:1.7">
          <li>Connect the phone to the <b>same Wi-Fi</b> as this computer.</li>
          <li>Scan the QR code with the phone camera, or open <b class="mono">${esc((p.url || "").split("?")[0])}</b> in the phone's browser.</li>
          <li>Type this code if the page asks for it:</li></ol>
        <div class="codebig">${esc(p.code.slice(0, 3))} ${esc(p.code.slice(3))}</div>
        <div class="qrbox" style="margin:8px auto">${p.qr_svg}</div>
        <div class="tiny muted" style="text-align:center">The code works once and expires in <span id="pr-left">${p.minutes}:00</span>.</div>
        ${warn}<div id="pr-got" style="margin-top:8px"></div>`;
      const end = p.expires_at * 1000;
      tick = setInterval(() => { const s = Math.max(0, Math.round((end - Date.now()) / 1000)); const e = $("#pr-left", m); if (e) e.textContent = Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); if (!s) $("#pr-left", m).textContent = "expired: close and make a new code"; }, 1000);
      timer = setInterval(async () => {
        if (closed) return;
        try {
          const d = (await api("/api/devices")).devices.find(x => !known.has(x.id) && !x.revoked);
          if (d) {
            clearInterval(timer); clearInterval(tick);
            $("#pr-got", m).innerHTML = `<div class="banner ok"><b>${esc(d.name)}</b> is connected (${esc(d.platform || "phone")}${d.browser ? ", " + esc(d.browser) : ""}). You can rename it later in Settings.</div>
              <button class="primary" id="pr-use">Use this phone</button>`;
            $("#pr-use", m).onclick = () => { stop(); onPaired && onPaired(d); };
          }
        } catch (e) {}
      }, 2000);
    } catch (e) { $("#pr-body", m).innerHTML = `<div class="banner bad">${esc(e.message)}</div>`; }
  })();
}

/* ---------------- Confirming a positive ---------------- */
const STATE_PILL = {
  awaiting_reread: "warn", awaiting_referee: "warn", awaiting_molecular: "warn", needs_investigation: "pos",
  overturned: "pos", confirmed: "neg", not_applicable: ""
};
const METHOD_NAMES = {
  blind_reread: "Blind second reading", referee_reread: "Referee reading", zn_restain: "ZN re-stain and re-read",
  xpert: "Xpert MTB/RIF Ultra", culture: "Culture", other: "Lead decision"
};

function confirmationCard(sl, hist) {
  const c = sl.confirmation;
  if (sl.status !== "confirmed") return "";
  if (!c || !c.applicable) {
    return `<div class="card"><details class="opts"><summary><b>Xpert or culture result (optional)</b></summary>
      <div class="small muted" style="margin-top:6px">If an Xpert or culture result exists for this person, record it so the negative predictive value can be measured.</div>
      ${confirmForm(sl, c, true)}</details></div>`;
  }
  const steps = c.steps.filter(s => !s.hidden).map(s => `<li class="${s.done ? "done" : ""}">
      <span class="dot">${s.done ? "&#10003;" : ""}</span><div><b>${esc(s.title)}</b> ${s.required ? "" : '<span class="tinyline">optional</span>'}
      <div class="small muted">${s.result ? esc(s.result) : ""}</div></div></li>`).join("");
  return `<div class="card"><h2>TB lab tests <span class="pill ${STATE_PILL[c.state] || ""}">${esc(c.label)}</span></h2>
    <div class="tiny muted" style="margin:-4px 0 8px">${esc(c.policy || "")}</div>
    <ul class="steps">${steps}</ul>
    ${c.recommendations.length ? `<ul class="small" style="margin:8px 0 0 18px;padding:0">${c.recommendations.map(r => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}
    ${hist.length ? `<div style="margin-top:10px"><h3>Recorded</h3><table><tbody>${hist.map(h => `<tr><td class="small">${esc(METHOD_NAMES[h.method] || h.method)}</td><td class="small mono">${esc(h.grade || h.result)}${h.rif_result ? " &middot; RIF " + esc(h.rif_result.replace("_", " ")) : ""}</td><td class="small muted">${esc(h.by)}</td><td class="tinyline">${fmtDate(h.created_at)}</td></tr>`).join("")}</tbody></table></div>` : ""}
    <details style="margin-top:10px" ${c.state === "needs_investigation" ? "open" : ""}><summary class="small" style="cursor:pointer"><b>Add an Xpert or culture result</b></summary>${confirmForm(sl, c, false)}</details></div>`;
}

function confirmForm(sl, c, negative) {
  const st = c ? c.state : "";
  const methods = negative ? ["xpert", "culture"] :
    ["xpert", "culture", "zn_restain", ...(st === "needs_investigation" ? ["other"] : [])];
  return `<div class="grid" style="gap:8px;margin-top:8px">
    <label class="f">Step<select id="cf-method">${methods.map(m => `<option value="${m}">${esc(METHOD_NAMES[m])}</option>`).join("")}</select></label>
    <div id="cf-fields"></div>
    <label class="f">Notes (optional)<input id="cf-notes" placeholder="e.g. new sputum sample 12 Oct"></label>
    <button class="primary" id="cf-save">Save result</button></div>`;
}

function wireConfirmation(sl, hist, reload) {
  const sel = $("#cf-method"); if (!sel) return;
  const draw = () => {
    const m = sel.value, grades = ["negative", "scanty", "1+", "2+", "3+"];
    const gsel = `<label class="f">Grade found<select id="cf-grade">${grades.map(g => `<option value="${g}">${esc(gradeLabel(g))}</option>`).join("")}</select></label>`;
    $("#cf-fields").innerHTML =
      m === "xpert" ? `<div class="row"><label class="f">Result<select id="cf-result"><option value="detected">MTB detected</option><option value="trace">MTB detected, trace</option><option value="not_detected">MTB not detected</option><option value="invalid">Invalid / error</option></select></label>
        <label class="f">Rifampicin<select id="cf-rif"><option value="">not reported</option><option value="not_detected">not detected</option><option value="detected">resistance detected</option><option value="indeterminate">indeterminate</option></select></label></div>` :
      m === "culture" ? `<label class="f">Result<select id="cf-result"><option value="positive">Positive</option><option value="negative">Negative</option><option value="contaminated">Contaminated</option></select></label>` :
      m === "other" ? `<input type="hidden" id="cf-result" value="accepted"><div class="tiny muted">Keep the smear result despite the negative test. Only an expert can do this, and the reason is recorded.</div>` :
      gsel;
  };
  sel.onchange = draw; draw();
  $("#cf-save").onclick = () => guard(async () => {
    const m = sel.value, g = $("#cf-grade"), r = $("#cf-result"), rf = $("#cf-rif");
    await api(`/api/slides/${sl.id}/confirmation`, { method: "POST", json: { method: m, grade: g ? g.value : null, result: r ? r.value : "", rif_result: rf ? rf.value : "", notes: $("#cf-notes").value } });
    toast("Saved"); await reload();
  });
}

/* ---------------- Cut-off table of a model ---------------- */
async function showCutoffs(mid) {
  const d = await api(`/api/models/${mid}/cutoffs`);
  const t = d.targets, c = x => x == null ? "n/a" : (x * 100).toFixed(0) + "%";
  const cell = (v, ciArr, key) => `<td class="mono ${v != null && v >= t[key] ? "" : "muted"}">${c(v)}${ciArr ? `<div class="tinyline">${ci(ciArr)}</div>` : ""}</td>`;
  const me = reader(), canApply = ["senior", "lead"].includes(roleOf(me));
  const m = modal(`<h2>Cut-off table: ${esc(d.model)} ${modPill(d.modality)}</h2>
    <p class="small muted">Each row calls an <b>image</b> positive when its most confident detection is at or above the cut-off. Measured on ${d.test_images ?? "n/a"} held-out test images
      (${d.test_positive_share != null ? Math.round(d.test_positive_share * 100) + "% of them contain AFB" : "mix unknown"}). Targets: sensitivity ${c(t.sensitivity)}, specificity ${c(t.specificity)}, PPV ${c(t.ppv)}, NPV ${c(t.npv)} (edit under Settings). Values below target are greyed.</p>
    ${d.rows.length ? `<div style="overflow:auto;max-height:55vh"><table class="cut"><thead><tr><th>Cut-off</th><th>Sensitivity</th><th>Specificity</th><th>PPV</th><th>NPV</th><th>TP</th><th>FP</th><th>FN</th><th>TN</th><th></th></tr></thead><tbody>
      ${d.rows.map(r => `<tr class="${Math.abs(r.cutoff - d.current_cutoff) < 0.001 ? "hl" : ""}"><td class="mono"><b>${r.cutoff.toFixed(2)}</b></td>
        ${cell(r.sensitivity, r.sens_ci, "sensitivity")}${cell(r.specificity, r.spec_ci, "specificity")}${cell(r.ppv, r.ppv_ci, "ppv")}${cell(r.npv, r.npv_ci, "npv")}
        <td class="mono">${r.tp}</td><td class="mono">${r.fp}</td><td class="mono">${r.fn}</td><td class="mono">${r.tn}</td>
        <td>${r.meets_targets ? '<span class="pill met">meets all</span>' : ""} ${Math.abs(r.cutoff - d.current_cutoff) < 0.001 ? '<span class="pill teal">in use</span>' : (canApply ? `<button class="sm" data-c="${r.cutoff}">Use</button>` : "")}</td></tr>`).join("")}</tbody></table></div>`
      : `<div class="empty small">This model has no cut-off table (it was trained before v2, or had no test images).</div>`}
    <div class="tiny muted" style="margin-top:8px">${esc(d.note)} A cut-off chosen on a small test set is optimistic; confirm it on new slides before relying on it. Changing the cut-off affects only how many detections are counted, and is logged.</div>
    <div class="row" style="margin-top:10px"><button id="co-x">Close</button></div>`, true);
  $("#co-x", m).onclick = () => m.close();
  $$("[data-c]", m).forEach(b => b.onclick = () => guard(async () => {
    await api(`/api/models/${mid}/cutoff`, { method: "POST", json: { cutoff: +b.dataset.c, approved_by: me } });
    toast("Count cut-off set to " + b.dataset.c); m.close(); await refreshState(); showCutoffs(mid);
  }));
}

/* ---------------- Settings: phones, cut-offs, targets, feedback ---------------- */
async function settingsExtras(host) {
  const [dv, st, fb, hl, ev] = await Promise.all([api("/api/devices"), api("/api/settings"), api("/api/feedback"), api("/api/health"), api("/api/capture/events?limit=25")]);
  const me = reader(), role = roleOf(me);
  const T = st.targets, pc = x => Math.round(x * 100);
  host.innerHTML = `
    <div class="card" style="margin-bottom:14px"><div class="row between"><h2 style="margin:0">Phones used as cameras</h2><button class="primary" id="ph-pair">Pair a phone</button></div>
      ${dv.network.warnings.map(w => `<div class="banner" style="margin-top:8px">${esc(w)}</div>`).join("")}
      ${dv.devices.length ? `<table style="margin-top:8px"><thead><tr><th>Name</th><th>Phone</th><th>Last seen</th><th>Photos</th><th></th></tr></thead><tbody>
        ${dv.devices.map(d => `<tr ${d.revoked ? 'style="opacity:.5"' : ""}><td><b>${esc(d.name)}</b> ${d.revoked ? '<span class="pill">removed</span>' : d.online ? '<span class="pill neg">online</span>' : ""}</td>
          <td class="small muted">${esc(d.platform || "")} ${esc(d.browser || "")}<div class="tinyline">paired by ${esc(d.paired_by || "")} ${fmtDate(d.paired_at)}</div></td>
          <td class="small">${d.last_seen ? fmtDate(d.last_seen) : "never"}</td><td class="mono">${d.upload_count}${d.fail_count ? ` <span class="pill warn">${d.fail_count} failed</span>` : ""}</td>
          <td style="white-space:nowrap">${d.revoked ? "" : `<button class="sm" data-rn="${d.id}">Rename</button> <button class="sm danger" data-rv="${d.id}">Remove</button>`}</td></tr>`).join("")}</tbody></table>`
        : `<div class="empty small">No phones paired yet.</div>`}
      <div class="tiny muted" style="margin-top:8px">A paired phone holds a private key that lets it send pictures to the slide you choose, and nothing else. It cannot read results, other slides or patient data. Remove a lost phone here and it stops working immediately.</div></div>

    <div class="grid g2" style="margin-bottom:14px;align-items:start">
      <div class="card"><h2>Count cut-offs</h2>
        <table><thead><tr><th></th><th>Count a mark at</th><th>Orange "needs a look" below</th></tr></thead><tbody>
        ${S.state.panel_order.map(k => `<tr><td>${modPill(k)}</td><td><input id="th-p-${k}" type="number" step="0.05" min="0.25" max="0.95" value="${st.thresholds[k].positive}" style="width:80px"></td><td><input id="th-r-${k}" type="number" step="0.05" min="0.25" max="1" value="${st.thresholds[k].review}" style="width:80px"></td></tr>`).join("")}</tbody></table>
        <button id="th-save" style="margin-top:8px" ${["senior", "lead"].includes(role) ? "" : "disabled"}>Save cut-offs</button>
        <div class="tiny muted" style="margin-top:6px">${["senior", "lead"].includes(role) ? "" : "Switch to an expert to change these. "}The AI models page shows, for each model, what every cut-off would have given on the test pictures.</div></div>
      <div class="card"><h2>Acceptance targets</h2>
        <div class="grid g2" style="gap:8px">
          ${[["sensitivity", "Sensitivity"], ["specificity", "Specificity"], ["ppv", "Positive predictive value"], ["npv", "Negative predictive value"]].map(([k, l]) => `<label class="f">${l} (%)<input id="tg-${k}" type="number" min="1" max="100" value="${pc(T[k])}" style="width:90px"></label>`).join("")}
          <label class="f">Expected share of positives (%)<input id="tg-prev" type="number" min="0.1" max="90" step="0.1" value="${(st.prevalence * 100).toFixed(1)}" style="width:90px"></label></div>
        <button id="tg-save" style="margin-top:8px" ${role === "lead" ? "" : "disabled"}>Save targets</button>
        <div class="tiny muted" style="margin-top:6px">${role === "lead" ? "" : "Only the laboratory lead can change these. "}These are <b>placeholders</b>, not WHO requirements: set the figures your validation protocol or national programme requires. The share of positives is used to convert sensitivity and specificity into the PPV and NPV expected at your site.</div></div>
    </div>

    <div class="grid g2" style="margin-bottom:14px;align-items:start">
      <div class="card"><h2>Health and monitoring</h2>
        <div class="banner ${hl.ok ? "ok" : "bad"}" style="margin-bottom:8px">${hl.ok ? "All checks passed." : esc(hl.problems.join(" "))}</div>
        <table><tbody>
          <tr><td>Version</td><td class="mono">${esc(hl.version)}</td></tr><tr><td>Free disk space</td><td class="mono">${hl.disk_free_gb} GB</td></tr>
          <tr><td>Phones paired / online</td><td class="mono">${hl.phones.paired} / ${hl.phones.online}</td></tr>
          <tr><td>Phone uploads last 24 h</td><td class="mono">${hl.phones.uploads_24h} ok, ${hl.phones.failed_24h} failed</td></tr>
          <tr><td>Active models</td><td class="small">${S.state.panel_order.map(k => `${esc(MOD_SHORT[k])}: ${esc(hl.active_models[k] || "none")}`).join("<br>")}</td></tr></tbody></table>
        <div style="max-height:170px;overflow:auto;margin-top:8px"><table><tbody>${ev.events.map(e => `<tr><td class="tinyline" style="white-space:nowrap">${fmtDate(e.created_at)}</td><td><code>${esc(e.kind)}</code></td><td class="small muted">${esc(e.device || "")} ${esc(e.detail)}</td></tr>`).join("") || '<tr><td class="muted small">No phone activity yet.</td></tr>'}</tbody></table></div></div>
      <div class="card"><h2>Usability feedback</h2>
        <div class="row"><div class="stat"><div class="n">${fb.mean != null ? fb.mean.toFixed(1) : "n/a"}</div><div class="l">average of ${fb.n} (1 to 5)</div></div>
          ${Object.entries(fb.by_source).map(([k, v]) => `<div class="stat"><div class="n">${v.mean.toFixed(1)}</div><div class="l">${esc(k)} (${v.n})</div></div>`).join("")}</div>
        <div style="max-height:200px;overflow:auto;margin-top:8px"><table><tbody>${fb.items.map(i => `<tr><td class="mono">${"&#9733;".repeat(i.rating)}</td><td class="small">${esc(i.comment || "")}<div class="tinyline">${esc(i.source)} &middot; ${esc(i.reader)} &middot; ${fmtDate(i.created_at)}</div></td></tr>`).join("") || '<tr><td class="muted small">No feedback yet. Phone users see a rating box on the phone page.</td></tr>'}</tbody></table></div></div>
    </div>`;
  $("#ph-pair", host).onclick = () => openPairing(() => render());
  $$("[data-rn]", host).forEach(b => b.onclick = () => { const n = prompt("New name for this phone"); if (n) guard(async () => { await api("/api/devices/" + b.dataset.rn, { method: "PATCH", json: { name: n } }); render(); }); });
  $$("[data-rv]", host).forEach(b => b.onclick = () => { if (confirm("Remove this phone? It will stop working at once and must be paired again.")) guard(async () => { await api("/api/devices/" + b.dataset.rv, { method: "DELETE" }); render(); }); });
  $("#th-save", host).onclick = () => guard(async () => {
    for (const k of S.state.panel_order) await api("/api/settings", { method: "PUT", json: { modality: k, positive: +$("#th-p-" + k).value, review: +$("#th-r-" + k).value, approved_by: me } });
    toast("Cut-offs saved"); await refreshState(); render();
  });
  $("#tg-save", host).onclick = () => guard(async () => {
    const targets = {}; ["sensitivity", "specificity", "ppv", "npv"].forEach(k => targets[k] = +$("#tg-" + k).value / 100);
    await api("/api/settings", { method: "PUT", json: { targets, prevalence: +$("#tg-prev").value / 100, approved_by: me } });
    toast("Targets saved"); await refreshState(); render();
  });
}

/* ---------------- Feedback from the computer ---------------- */
function openFeedback() {
  let rating = 0;
  const m = modal(`<h2>How is S4Sight working for you?</h2>
    <div class="stars" id="fb-stars">${[1, 2, 3, 4, 5].map(i => `<button data-n="${i}" aria-label="${i} of 5">&#9733;</button>`).join("")}</div>
    <label class="f" style="margin-top:8px">What was easy or hard? (optional)<textarea id="fb-text" rows="3"></textarea></label>
    <div class="row" style="margin-top:10px"><button class="primary" id="fb-go">Send</button><button id="fb-x">Cancel</button></div>`);
  $$("#fb-stars button", m).forEach(b => b.onclick = () => { rating = +b.dataset.n; $$("#fb-stars button", m).forEach(x => x.classList.toggle("on", +x.dataset.n <= rating)); });
  $("#fb-x", m).onclick = () => m.close();
  $("#fb-go", m).onclick = () => guard(async () => {
    if (!rating) throw new Error("Choose a rating from 1 to 5.");
    await api("/api/feedback", { method: "POST", json: { rating, comment: $("#fb-text", m).value, context: location.hash || "home" } });
    toast("Thank you"); m.close();
  });
}
document.addEventListener("click", e => { if (e.target && e.target.id === "fb-link") { e.preventDefault(); openFeedback(); } });
