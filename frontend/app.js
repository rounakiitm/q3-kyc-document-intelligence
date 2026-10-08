/* KYC Onboarding — auth + classification table + normalized field tables */
/* API base: same-origin locally; Vercel sets window.__KYC_API__ via config.js */
const API = String(window.__KYC_API__ || "").replace(/\/$/, "");
const $ = (s) => document.querySelector(s);
const LS_TOKEN = "q3_sb_token";
const LS_REFRESH = "q3_sb_refresh";
const LS_EMAIL = "q3_sb_email";
const LS_KYC_SID = "q3_kyc_session";

let files = [];
let lastRun = null;
let AUTH_REQUIRED = false;
let AUTH_READY = false;
let ACCESS_TOKEN = localStorage.getItem(LS_TOKEN) || "";
let KYC_SID = localStorage.getItem(LS_KYC_SID) || "";
let cachedDocs = []; // from GET /kyc/sessions/{id}/docs

const DOC_TYPES = {
  "Aadhaar Card": 1, "PAN Card": 1, "Driving Licence": 1, "Passport": 1,
  "NACH / ECS Mandate (handwritten)": 1, "FATCA Annexure Form (handwritten)": 1,
  "Benefit Illustration Declaration (handwritten)": 1,
  "Moral Hazard Questionnaire (handwritten)": 1,
  "Multiple Policies Consent Form (handwritten)": 1,
  "Suitability Profiler Declaration (handwritten)": 1,
};

const pages = ["run", "results", "report", "about"];
function route() {
  const page = location.hash.replace("#/", "") || "run";
  pages.forEach((p) => {
    document.getElementById("page-" + p)?.classList.toggle("active", p === page);
    document.querySelector(`[data-page="${p}"]`)?.classList.toggle("active", p === page);
  });
}
window.addEventListener("hashchange", route);

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

/* ---------- auth ---------- */
function authHeaders(extra = {}) {
  const h = { ...extra };
  if (ACCESS_TOKEN) h.Authorization = "Bearer " + ACCESS_TOKEN;
  return h;
}

function setSessionTokens(access, refresh, email) {
  ACCESS_TOKEN = access || "";
  if (access) localStorage.setItem(LS_TOKEN, access);
  else localStorage.removeItem(LS_TOKEN);
  if (refresh) localStorage.setItem(LS_REFRESH, refresh);
  else localStorage.removeItem(LS_REFRESH);
  if (email) localStorage.setItem(LS_EMAIL, email);
  const signedIn = AUTH_REQUIRED && !!ACCESS_TOKEN;
  const row = $("#authUserRow");
  if (row) {
    row.hidden = !signedIn;
    $("#authEmailLabel").textContent = email || localStorage.getItem(LS_EMAIL) || "";
  }
  const topOut = $("#authSignOutTop");
  if (topOut) topOut.hidden = !signedIn;
}

function showAuthGate(show) {
  const gate = $("#authGate");
  gate.hidden = !show;
  gate.style.display = show ? "grid" : "none";
  $("#appShell").style.display = show ? "none" : "";
}

async function authRequest(path, body) {
  const r = await fetch(API + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const detail = data.detail;
    throw new Error(
      (typeof detail === "string" ? detail : null)
      || data.error_description || data.msg || data.error || r.statusText || "auth failed"
    );
  }
  return data;
}

async function signIn(email, password) {
  const data = await authRequest("/auth/login", { email, password });
  if (!data.access_token) throw new Error("No access token returned");
  setSessionTokens(data.access_token, data.refresh_token, email);
  showAuthGate(false);
  await bootApp();
}

async function signUp(email, password) {
  const data = await authRequest("/auth/signup", { email, password });
  if (data.access_token) {
    setSessionTokens(data.access_token, data.refresh_token, email);
    showAuthGate(false);
    await bootApp();
    return;
  }
  $("#authMsg").textContent = "Account created — confirm email if required, then sign in.";
}

function signOut() {
  setSessionTokens("", "", "");
  KYC_SID = "";
  localStorage.removeItem(LS_KYC_SID);
  cachedDocs = [];
  files = [];
  if (AUTH_REQUIRED) showAuthGate(true);
}

$("#authForm").onsubmit = async (e) => {
  e.preventDefault();
  const email = $("#authEmail").value.trim();
  const password = $("#authPassword").value;
  const msg = $("#authMsg");
  msg.textContent = "Signing in…";
  $("#authSignIn").disabled = true;
  try {
    await signIn(email, password);
    msg.textContent = "";
  } catch (err) {
    msg.textContent = err.message;
  }
  $("#authSignIn").disabled = false;
};
$("#authSignUp").onclick = async () => {
  const email = $("#authEmail").value.trim();
  const password = $("#authPassword").value;
  const msg = $("#authMsg");
  if (!email || password.length < 6) {
    msg.textContent = "Enter email and a password (6+ chars).";
    return;
  }
  msg.textContent = "Creating account…";
  try { await signUp(email, password); }
  catch (err) { msg.textContent = err.message; }
};
$("#authSignOut").onclick = signOut;
$("#authSignOutTop").onclick = signOut;

/* ---------- files ---------- */
const dz = $("#dropzone");
$("#browseBtn").onclick = () => $("#fileInput").click();
dz.onclick = (e) => { if (e.target.id !== "browseBtn") $("#fileInput").click(); };
$("#fileInput").onchange = (e) => addFiles([...e.target.files]);
dz.ondragover = (e) => { e.preventDefault(); dz.classList.add("over"); };
dz.ondragleave = () => dz.classList.remove("over");
dz.ondrop = (e) => {
  e.preventDefault();
  dz.classList.remove("over");
  addFiles([...e.dataTransfer.files]);
};

function addFiles(list) {
  for (const f of list) files.push({ name: f.name, bytes: f, type: f.type });
  renderFiles();
}
function renderFiles() {
  const cachedNames = new Set((cachedDocs || []).map((d) => (d.file || "").toLowerCase()));
  $("#filelist").innerHTML = files
    .map((f, i) => {
      const maybe = cachedNames.has(f.name.toLowerCase());
      return `<span class="filepill${maybe ? " cached" : ""}">${esc(f.name)}${maybe ? " · may skip" : ""} <button type="button" data-i="${i}">✕</button></span>`;
    })
    .join("");
  $("#filelist").querySelectorAll("button").forEach((btn) => {
    btn.onclick = () => { files.splice(Number(btn.dataset.i), 1); renderFiles(); };
  });
  $("#runBtn").disabled = files.length === 0;
}

async function ensureKycSession() {
  if (KYC_SID) {
    try {
      await refreshCacheHint();
      return KYC_SID;
    } catch {
      KYC_SID = "";
      localStorage.removeItem(LS_KYC_SID);
    }
  }
  const r = await fetch(API + "/kyc/sessions", { method: "POST", headers: authHeaders() });
  if (!r.ok) throw new Error("Could not create KYC session");
  const data = await r.json();
  KYC_SID = data.session_id;
  localStorage.setItem(LS_KYC_SID, KYC_SID);
  await refreshCacheHint();
  return KYC_SID;
}

async function refreshCacheHint() {
  if (!KYC_SID) {
    cachedDocs = [];
    const el = $("#cacheHint");
    if (el) el.textContent = "Session cache: 0 documents";
    return;
  }
  const r = await fetch(`${API}/kyc/sessions/${KYC_SID}/docs`, { headers: authHeaders() });
  if (!r.ok) throw new Error("session expired");
  const data = await r.json();
  cachedDocs = data.documents || [];
  const el = $("#cacheHint");
  if (el) {
    el.textContent = `Session cache: ${data.n_cached} document(s) — re-selecting them will skip Gemini`;
  }
}

$("#clearCacheBtn").onclick = async () => {
  if (!KYC_SID) return;
  if (!confirm("Clear all processed documents from this KYC session?")) return;
  await fetch(`${API}/kyc/sessions/${KYC_SID}/docs`, { method: "DELETE", headers: authHeaders() });
  await refreshCacheHint();
  renderFiles();
};

/* ---------- run ---------- */
$("#runBtn").onclick = () => runKyc();
$("#sampleBtn").onclick = () => { files = []; renderFiles(); runKyc("/kyc/samples"); };

async function runKyc(url = "/kyc/run") {
  if (typeof url !== "string") url = "/kyc/run";
  $("#progressWrap").hidden = false;
  setProgress(0.02, "Submitting documents…");
  $("#runBtn").disabled = true;
  try {
    await ensureKycSession();
    let r;
    const fd = new FormData();
    fd.append("session_id", KYC_SID);
    if (url === "/kyc/samples") {
      r = await fetch(API + url, { method: "POST", headers: authHeaders(), body: fd });
    } else {
      if (!files.length) throw new Error("Add at least one document first");
      for (const f of files) fd.append("files", f.bytes, f.name);
      r = await fetch(API + url, { method: "POST", headers: authHeaders(), body: fd });
    }
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || r.statusText);
    }
    const { job_id } = await r.json();
    await poll(job_id);
  } catch (err) {
    setProgress(0, err.message);
  }
  $("#runBtn").disabled = files.length === 0;
}

async function poll(jobId) {
  while (true) {
    const j = await (await fetch(`${API}/kyc/jobs/${jobId}`, { headers: authHeaders() })).json();
    if (j.status === "error") { setProgress(1, j.error || "failed"); return; }
    if (j.status === "done") {
      const nSkip = (j.skipped || []).length;
      const nNew = (j.processed_now || []).length;
      const nAll = j.n_session_docs || (j.results || []).length;
      setProgress(
        1,
        `Done — ${nNew} new, ${nSkip} re-selected skips, ${nAll} total in session. Selection cleared.`
      );
      // Clear current selection so the next run only adds new docs
      files = [];
      $("#fileInput").value = "";
      renderFiles();
      await refreshCacheHint();

      lastRun = {
        summary: j.summary,
        documents: j.results,
        skipped: j.skipped || [],
        processed_now: j.processed_now || [],
      };
      renderResults(j.results, j.summary, lastRun);
      renderReport(j.results, j.summary);
      location.hash = "#/results";
      return;
    }
    setProgress(Math.max(j.progress, 0.03), `${j.current || "Working"}…`);
    await new Promise((r) => setTimeout(r, 1200));
  }
}
function setProgress(p, text) {
  $("#progressWrap").hidden = false;
  $("#progressBar").style.width = (p * 100).toFixed(1) + "%";
  $("#progressText").textContent = text;
  $("#sessionHint").textContent = text;
}

/* ---------- results: classification table + field tables ---------- */
function pill(c) {
  const n = Number(c) || 0;
  const cls = n >= 0.9 ? "hi" : n >= 0.7 ? "mid" : "lo";
  return `<span class="pill ${cls}">${n.toFixed(2)}</span>`;
}
function typePill(docType, conf) {
  let cls = "typepill";
  if (docType === "ERROR") cls += " err";
  else if (docType?.startsWith("Other")) cls += " warn";
  return `<span class="${cls}">${esc(docType || "Unknown")} ${pill(conf ?? 0)}</span>`;
}
function fieldStatus(f) {
  if (f.value == null || f.value === "") return '<span class="statusmiss">Missing</span>';
  if (f.format_ok === false) return '<span class="statusmiss">Bad format</span>';
  if (f.flagged) return '<span class="statusflag">Review</span>';
  return '<span class="statusok">OK</span>';
}
function formatCell(f) {
  if (f.value == null || f.value === "") return '<span class="muted">—</span>';
  if (f.format_rule === "none" || f.format_rule === "empty") return '<span class="muted">n/a</span>';
  if (f.format_ok) return `<span class="statusok">Valid</span><div class="raw">${esc(f.format_rule || "")}</div>`;
  return `<span class="statusmiss">Invalid</span><div class="raw">${esc(f.format_message || f.format_rule || "")}</div>`;
}

function renderResults(results, summary, meta = {}) {
  const s = summary || {};
  const nSkip = (meta.skipped || []).length;
  const nNew = (meta.processed_now || []).length;
  const skipNote = (nSkip || nNew)
    ? `<div class="skipnote">This run: <b>${nNew}</b> newly processed · <b>${nSkip}</b> re-selected skips · showing <b>${results.length}</b> docs in this session (prior files stay)${
        nSkip ? " — skipped: " + (meta.skipped || []).map((x) => esc(x.file)).join(", ") : ""
      }</div>`
    : `<div class="skipnote">Session dossier: <b>${results.length}</b> document(s) — new uploads append; unrelated / Other types do not replace prior docs.</div>`;
  const statusHtml = `
    <div class="kycbar">
      <span class="st ${s.kyc_status === "CLEAN" ? "clean" : "review"}">${esc(s.kyc_status || "—")}</span>
      <div><b>${esc(s.applicant_name || "Unknown applicant")}</b><span>name agreement ${esc(s.applicant_name_agreement ?? "—")}</span></div>
      <div><b>${esc(s.policy_number || "—")}</b><span>policy / application (${esc(s.policy_number_agreement ?? "—")})</span></div>
      <div><b>${s.documents_received ?? results.length}</b><span>documents classified</span></div>
      <div><b>${(s.low_confidence_flags?.length || 0) + (s.cross_document_flags?.length || 0)}</b><span>flags</span></div>
    </div>${skipNote}`;

  const classRows = (results || []).map((r) => `
    <tr>
      <td>${esc(r.file)}${r.cached ? ' <span class="hw">(cached)</span>' : ""}</td>
      <td>${typePill(r.doc_type, r.classification_confidence)}</td>
      <td>${r.is_handwritten ? '<span class="hw">Handwritten</span>' : '<span class="hw">Printed / mixed</span>'}</td>
      <td>${r.cached ? '<span class="statusok">Skipped · cached</span>' : ((r.flagged_fields || []).length ? '<span class="statusflag">Needs review</span>' : (r.doc_type === "ERROR" ? '<span class="statusmiss">Failed</span>' : '<span class="statusok">Classified</span>'))}</td>
    </tr>`).join("");

  const classTable = `
    <div class="sectioncard">
      <header><h3>Document classification</h3><span class="muted">${results.length} file(s)</span></header>
      <div class="body">
        <table class="data">
          <thead><tr><th>File</th><th>Predicted type</th><th>Script</th><th>Status</th></tr></thead>
          <tbody>${classRows || '<tr><td colspan="4" class="muted">No documents</td></tr>'}</tbody>
        </table>
      </div>
    </div>`;

  const common = s.common_fields || [];
  const commonRows = common.map((g) => `
    <tr>
      <td class="fname">${esc(g.label || g.group)}</td>
      <td class="fval">${esc(g.consensus || "—")}</td>
      <td>${esc(g.agreement || "—")}</td>
      <td>${g.status === "OK" ? '<span class="statusok">Match</span>' : '<span class="statusflag">Mismatch</span>'}</td>
      <td class="fev">${(g.sightings || []).map((x) => `${esc(x.file)}: ${esc(x.value)}`).join(" · ")}</td>
    </tr>`).join("");
  const commonTable = `
    <div class="sectioncard">
      <header><h3>Cross-document common fields</h3>
        <span class="muted">name · DOB · PAN · policy · dates · place</span></header>
      <div class="body">
        <table class="data">
          <thead><tr><th>Field group</th><th>Consensus</th><th>Agreement</th><th>Status</th><th>Seen on</th></tr></thead>
          <tbody>${commonRows || '<tr><td colspan="5" class="muted">Not enough overlapping fields yet</td></tr>'}</tbody>
        </table>
      </div>
    </div>`;

  const docCards = (results || []).map((r) => {
    if (r.doc_type === "ERROR") {
      return `<div class="sectioncard">
        <header><h3>${esc(r.file)}</h3>${typePill("ERROR", 0)}</header>
        <div class="flagbox">${esc((r.schema_issues || []).join("; "))}</div>
      </div>`;
    }
    const rows = (r.fields || []).map((f) => {
      const val = f.value == null || f.value === "" ? "—" : String(f.value);
      const raw = f.raw_value != null && String(f.raw_value) !== val
        ? `<div class="raw">raw: ${esc(String(f.raw_value))}</div>` : "";
      return `<tr>
        <td class="fname">${esc(f.name)}</td>
        <td class="fval">${esc(val)}${raw}</td>
        <td>${pill(f.confidence)}</td>
        <td>${formatCell(f)}</td>
        <td>${fieldStatus(f)}</td>
        <td class="fev">${esc(String(f.evidence || "").slice(0, 120))}</td>
      </tr>`;
    }).join("");
    const flags = (r.flagged_fields || [])
      .map((f) => {
        const why = (f.reasons || []).join(", ") || "review";
        const fmt = f.format_ok === false ? ` · ${esc(f.format_message || "bad format")}` : "";
        return `<div class="flagbox"><b>${esc(f.field)}</b> — ${esc(why)} (conf ${f.confidence})${fmt}</div>`;
      })
      .concat((r.schema_issues || []).map((i) => `<div class="flagbox">${esc(i)}</div>`))
      .join("");
    return `<div class="sectioncard">
      <header>
        <h3>${esc(r.file)}</h3>
        <div>${typePill(r.doc_type, r.classification_confidence)}${r.is_handwritten ? ' <span class="hw">· handwritten</span>' : ""}</div>
      </header>
      <div class="body">
        <table class="data">
          <thead><tr><th>Field</th><th>Normalized value</th><th>Confidence</th><th>Format</th><th>Status</th><th>Evidence</th></tr></thead>
          <tbody>${rows || '<tr><td colspan="6" class="muted">No fields extracted</td></tr>'}</tbody>
        </table>
      </div>
      ${flags}
    </div>`;
  }).join("");

  $("#resultCards").innerHTML = statusHtml + classTable + commonTable + (docCards || '<div class="empty">No results yet — run a KYC first.</div>');
}

function renderReport(results, s) {
  s = s || {};
  const checklist = Object.keys(DOC_TYPES).map((t) => {
    const got = (s.document_types_identified || []).includes(t);
    return `<div class="check"><span class="${got ? "ok" : "miss"}">${got ? "✓" : "○"}</span> ${esc(t)}</div>`;
  }).join("");
  const flags = [
    ...(s.format_flags || []).map((f) =>
      `<div class="flagbox"><b>${esc(f.file)}</b> — ${esc(f.field)} = ${esc(String(f.value))} · format rule <code>${esc(f.rule)}</code>: ${esc(f.message)}</div>`),
    ...(s.low_confidence_flags || []).map((f) =>
      `<div class="flagbox"><b>${esc(f.file)}</b> — ${esc(f.field)} at ${f.confidence}${f.reasons?.length ? " (" + esc(f.reasons.join(", ")) + ")" : ""} → human review</div>`),
    ...(s.cross_document_flags || []).map((f) =>
      `<div class="flagbox"><b>${esc(f.file)}</b> — ${esc(f.detail)}</div>`),
  ].join("");
  const common = (s.common_fields || []).map((g) =>
    `<div class="check"><span class="${g.status === "OK" ? "ok" : "miss"}">${g.status === "OK" ? "✓" : "!"}</span>
     <b>${esc(g.label)}</b> → ${esc(g.consensus)} <span class="muted">(${esc(g.agreement)})</span></div>`
  ).join("");
  $("#reportBody").innerHTML = `
    <div class="repblock"><h3>Verdict</h3>
      <p><b>${esc(s.kyc_status || "—")}</b> — ${s.documents_received || 0} documents,
      ${(s.document_types_identified || []).length}/10 types present,
      ${(s.low_confidence_flags?.length || 0) + (s.cross_document_flags?.length || 0) + (s.format_flags?.length || 0)} flag(s).
      Threshold: ${s.threshold ?? 0.7}.</p></div>
    <div class="repblock"><h3>Document checklist</h3>${checklist}</div>
    <div class="repblock"><h3>Cross-document common fields</h3>${common || "<p class='muted'>None overlapping.</p>"}</div>
    <div class="repblock"><h3>Flags for human review</h3>${flags || "<p class='muted'>None.</p>"}</div>
    <div class="repblock"><h3>Format rules</h3>
      <p class="muted">PAN = AAAAA9999A · Aadhaar = 12 digits · IFSC = AAAA0XXXXXX · account = 9–18 digits ·
      dates = DD-MM-YYYY · passport / DL / MRZ structural checks. Invalid formats are flagged even if confidence is high.</p></div>`;
}

$("#dlBtn").onclick = () => {
  if (!lastRun) return;
  const blob = new Blob([JSON.stringify(lastRun, null, 2)], { type: "application/json" });
  const a = Object.assign(document.createElement("a"), {
    href: URL.createObjectURL(blob),
    download: "kyc_run.json",
  });
  a.click();
};

/* ---------- boot ---------- */
async function bootApp() {
  try {
    const h = await (await fetch(API + "/health")).json();
    $("#modelBadge").textContent = `${h.model} · auth ${h.auth || "local"}`;
  } catch {
    $("#modelBadge").textContent = "backend offline";
  }
  if (ACCESS_TOKEN) {
    try {
      const me = await (await fetch(API + "/auth/me", { headers: authHeaders() })).json();
      setSessionTokens(ACCESS_TOKEN, localStorage.getItem(LS_REFRESH) || "", me.email || "");
    } catch {
      if (AUTH_REQUIRED) { setSessionTokens("", "", ""); showAuthGate(true); return; }
    }
  }
  try {
    await ensureKycSession();
  } catch (err) {
    $("#sessionHint").textContent = "KYC session error: " + err.message;
  }
  $("#sessionHint").textContent = "Ready — upload documents or load samples";
  route();
}

(async () => {
  try {
    const cfg = await (await fetch(API + "/auth/config")).json();
    AUTH_REQUIRED = !!cfg.auth_required;
    AUTH_READY = true;
    if (AUTH_REQUIRED && !ACCESS_TOKEN) {
      showAuthGate(true);
      return;
    }
    showAuthGate(false);
    await bootApp();
  } catch {
    AUTH_REQUIRED = false;
    showAuthGate(false);
    await bootApp();
  }
})();
