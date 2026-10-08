"""Live KYC app (Q3): upload documents for any user and run the pipeline.

Reuses the same classification/extraction engine as the batch CLI
(pipeline.process_document) plus consolidated KYC summary (kyc.py).

    streamlit run kyc_app.py --server.port 8503
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import API_KEYS, CONFIDENCE_THRESHOLD, DEFAULT_INPUT_DIR, MODEL_NAME  # noqa: E402
from kyc import build_kyc_summary, process_upload, run_kyc, save_run  # noqa: E402
from llm import LLMClient  # noqa: E402
from schemas import DOC_SCHEMAS  # noqa: E402

st.set_page_config(page_title="KYC Document Intelligence", page_icon="🪪", layout="wide")

# ---------------------------------------------------------------- session state
if "results" not in st.session_state:
    st.session_state.results = None
if "summary" not in st.session_state:
    st.session_state.summary = None

st.title("🪪 KYC Document Intelligence")
st.caption(
    f"Classify documents · extract fields with per-field confidence · flag for human "
    f"review · consolidate a full KYC run  |  model: `{MODEL_NAME}` · threshold: "
    f"{CONFIDENCE_THRESHOLD:.2f}"
)


def _conf_color(c: float) -> str:
    if c >= 0.9:
        return "🟢"
    if c >= CONFIDENCE_THRESHOLD:
        return "🟡"
    return "🔴"


# ---------------------------------------------------------------- inputs
with st.sidebar:
    st.header("1 · Documents")
    uploads = st.file_uploader(
        "Upload documents for this applicant",
        type=["png", "jpg", "jpeg", "pdf"],
        accept_multiple_files=True,
    )
    st.divider()
    if st.button("📋 Load the 10 sample documents instead", use_container_width=True):
        files = sorted(
            p for p in DEFAULT_INPUT_DIR.iterdir()
            if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".pdf"}
        )
        st.session_state.sample_sources = [(p.name, p.read_bytes()) for p in files]
        st.session_state.results = None
        st.session_state.summary = None
        st.rerun()
    n_sample = len(st.session_state.get("sample_sources", []))
    st.info(f"{len(uploads or [])} uploaded · {n_sample} sample docs loaded")

    run_clicked = st.button(
        "▶️ Run KYC", type="primary", use_container_width=True,
        disabled=not (uploads or n_sample),
    )

sources = [(f.name, f.getvalue()) for f in (uploads or [])] or st.session_state.get("sample_sources", [])

# ---------------------------------------------------------------- run
if run_clicked and sources:
    client = LLMClient()
    st.session_state.results = []
    st.session_state.summary = None
    progress = st.progress(0.0, text="Starting KYC run…")
    for i, (fname, data) in enumerate(sources):
        progress.progress(i / len(sources), text=f"Processing {fname}…")
        try:
            st.session_state.results.append(process_upload(data, fname, client))
        except Exception as exc:  # noqa: BLE001
            st.session_state.results.append({
                "file": fname, "doc_type": "ERROR", "is_handwritten": None,
                "fields": [], "flagged_fields": [],
                "schema_issues": [f"pipeline failure: {exc}"],
            })
    progress.progress(1.0, text="Consolidating KYC summary…")
    st.session_state.summary = build_kyc_summary(st.session_state.results)
    st.rerun()

results = st.session_state.results
summary = st.session_state.summary

if results and summary is None:
    # Results exist from a prior partial run; build summary without new API calls.
    summary = st.session_state.summary = build_kyc_summary(results)

# ---------------------------------------------------------------- results
if results and summary:
    status = summary["kyc_status"]
    (st.success if status == "CLEAN" else st.warning)(
        f"**KYC status: {status}** — applicant: {summary.get('applicant_name') or 'unknown'} · "
        f"documents: {summary['documents_received']}"
    )

    tab_overview, tab_docs, tab_flags, tab_json = st.tabs(
        ["📊 KYC Summary", "📄 Documents", "🚩 Flags", "🧾 JSON"]
    )

    with tab_overview:
        c1, c2, c3 = st.columns(3)
        c1.metric("Applicant", summary.get("applicant_name") or "—",
                  summary.get("applicant_name_agreement") or "")
        c2.metric("Policy / Application No.", summary.get("policy_number") or "—",
                  summary.get("policy_number_agreement") or "")
        c3.metric("Date of Birth", summary.get("date_of_birth") or "—")
        c4, c5, c6 = st.columns(3)
        c4.metric("Documents", summary["documents_received"])
        c5.metric("Types identified", len(summary["document_types_identified"]))
        c6.metric("Flags", len(summary["low_confidence_flags"]) + len(summary["cross_document_flags"]))

        st.subheader("Document checklist")
        cols = st.columns(2)
        for i, t in enumerate(DOC_SCHEMAS):
            got = t in summary["document_types_identified"]
            cols[i % 2].markdown(f"{'+ ✅' if got else '— ⬜'} {t}")
        if summary["unrecognized_documents"]:
            st.info("Documents outside the 10-type schema (kept, flagged for review): "
                    + ", ".join(f"`{f}`" for f in summary["unrecognized_documents"]))

    with tab_docs:
        for r in results:
            icon = "🟢" if r["doc_type"] not in ("ERROR",) and not r["flagged_fields"] else "🔴"
            with st.expander(f"{icon} `{r['file']}` — {r['doc_type']}"):
                if r["doc_type"] == "ERROR":
                    st.error("; ".join(r["schema_issues"]))
                    continue
                st.markdown(f"Handwritten entries: **{'yes' if r['is_handwritten'] else 'no'}**")
                for f in r["fields"]:
                    val = f.get("value") or "*(unreadable)*"
                    st.markdown(
                        f"{_conf_color(f['confidence'])} **{f['name']}**: `{val}` "
                        f"&nbsp;`(confidence {f['confidence']:.2f})`"
                    )
                    if f.get("evidence"):
                        st.caption(f"evidence: “{f['evidence'][:120]}”")
                if r["schema_issues"]:
                    st.warning("Schema issues: " + "; ".join(r["schema_issues"]))

    with tab_flags:
        if summary["low_confidence_flags"]:
            st.subheader("Low-confidence fields (human review)")
            st.dataframe(
                [{"Document": f["file"], "Field": f["field"], "Confidence": f["confidence"]}
                 for f in summary["low_confidence_flags"]],
                use_container_width=True,
            )
        else:
            st.success("No field fell below the threshold.")
        if summary["cross_document_flags"]:
            st.subheader("Cross-document inconsistencies")
            for cflag in summary["cross_document_flags"]:
                st.warning(f"**{cflag['file']}**: {cflag['detail']}")
        if summary["document_types_missing"]:
            st.caption("Document types not present in this run: "
                       + ", ".join(summary["document_types_missing"]))

    with tab_json:
        st.download_button(
            "⬇️ Download full KYC run (JSON)",
            data=json.dumps({"summary": summary, "documents": results}, indent=2),
            file_name="kyc_run.json", mime="application/json",
        )
        st.json(summary, expanded=False)

    if st.button("💾 Save this run to output/kyc_runs/"):
        out = Path(__file__).parent / "output" / "kyc_runs"
        save_run(results, summary, out)
        st.success(f"Saved to {out}")
else:
    st.info("Upload documents (left) or load the 10 sample documents, then press **Run KYC**.")
