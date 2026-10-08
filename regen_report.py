"""One-off: regenerate the flagging report from the per-doc output JSONs."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import DEFAULT_OUTPUT_DIR  # noqa: E402
from report import write_reports  # noqa: E402

if __name__ == "__main__":
    out_dir = DEFAULT_OUTPUT_DIR
    results = []
    for j in sorted(out_dir.glob("*.json")):
        if j.name.startswith("_") or j.name in {"flagging_report.json"}:
            continue
        results.append(json.loads(j.read_text(encoding="utf-8")))
    write_reports(results, out_dir)
    print(f"report regenerated from {len(results)} results")
