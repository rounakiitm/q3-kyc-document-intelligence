"""Q3 pipeline entry point.

Usage:
    python run_pipeline.py                 # process all docs with defaults
    python run_pipeline.py --input DIR     # override input directory
    python run_pipeline.py --output DIR    # override output directory
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from config import DEFAULT_INPUT_DIR, DEFAULT_OUTPUT_DIR
from llm import LLMClient
from pipeline import process_document
from report import write_reports

IMAGE_EXTS = {".png", ".jpg", ".jpeg"}


def main() -> int:
    ap = argparse.ArgumentParser(description="Q3 document classification/extraction")
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT_DIR)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR)
    ap.add_argument("--limit", type=int, default=0, help="process first N files only")
    ap.add_argument("--force", action="store_true",
                    help="reprocess even files with a successful existing output")
    args = ap.parse_args()

    files = sorted(
        p for p in args.input.iterdir()
        if p.suffix.lower() in IMAGE_EXTS | {".pdf"} and not p.name.startswith("~$")
    )
    if not files:
        print(f"No documents found in {args.input}", file=sys.stderr)
        return 1
    if args.limit:
        files = files[: args.limit]

    out_dir = args.output
    out_dir.mkdir(parents=True, exist_ok=True)
    client = LLMClient()

    results = []
    for i, path in enumerate(files, 1):
        out_file = out_dir / f"{path.stem}.json"
        if not args.force and out_file.exists():
            cached = json.loads(out_file.read_text(encoding="utf-8"))
            if cached.get("doc_type") not in (None, "", "ERROR"):
                print(f"[{i}/{len(files)}] {path.name} ... cached ({cached['doc_type']})")
                results.append(cached)
                continue
        t0 = time.time()
        print(f"[{i}/{len(files)}] {path.name} ...", flush=True)
        try:
            result = process_document(path, client)
        except Exception as exc:  # noqa: BLE001 - record and continue
            print(f"    FAILED: {exc}", file=sys.stderr)
            result = {
                "file": path.name,
                "doc_type": "ERROR",
                "is_handwritten": None,
                "fields": [],
                "flagged_fields": [],
                "schema_issues": [f"pipeline failure: {exc}"],
            }
        (out_dir / f"{path.stem}.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
        n = len(result["fields"])
        nf = len(result["flagged_fields"])
        print(f"    {result['doc_type']} | {n} fields | {nf} flagged | {time.time()-t0:.1f}s")
        results.append(result)

    write_reports(results, out_dir)
    print(f"\nDone. {len(results)} docs, {client.calls_made} LLM calls. Output -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
