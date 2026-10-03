"""The last step: copies the PDF to `cv/delivered/`, only if the checks pass.

The PDF in `cv/` is a draft. It becomes a delivery when the plan is signed by the review
and has not changed since, the PDF is newer than the plan and the gate does not block it.

    py -m jobsearch.deliver plans/example.json
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from jobsearch.facts import ROOT
from jobsearch.gate import check
from jobsearch.render import delivery_name
from jobsearch.review import signature


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    path = Path(argv[0])
    plan = json.loads(path.read_text(encoding="utf-8"))
    rev = plan.get("review", {})
    if rev.get("signature") != signature(plan):
        state = "changed after the review" if rev else "never reviewed"
        print(f"[not delivered] plan {state}: py -m jobsearch.review prepare {argv[0]}")
        return 1
    draft = ROOT / "cv" / f"{plan['profile']}.pdf"
    if not draft.exists() or draft.stat().st_mtime < path.stat().st_mtime:
        print(f"[not delivered] {draft.name} is missing or older than the plan: rerun render")
        return 1
    blocks, _ = check(plan, path)
    if blocks:
        for line in blocks:
            print(f"[blocked]       {line}")
        print("[not delivered] the gate blocks: fix the plan and rerun render")
        return 1
    delivery = ROOT / "cv" / "delivered" / delivery_name(plan)
    delivery.parent.mkdir(exist_ok=True)
    try:
        shutil.copyfile(draft, delivery)
    except PermissionError:
        # On Windows a PDF open in a viewer is locked: the delivery stays old.
        print(f"[not delivered] {delivery.name} is open in a viewer: close it and rerun")
        return 1
    print(f"[ok] {delivery.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
