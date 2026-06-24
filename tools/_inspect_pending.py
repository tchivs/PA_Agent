"""Inspect records/pending for retries, failures, and outcome patterns."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


def main() -> None:
    pending = Path("records/pending")
    issues: list[dict] = []
    for p in sorted(pending.glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        meta = d.get("meta", {})
        exc = d.get("exception")
        s1 = d.get("stage1_messages") or []
        s2 = d.get("stage2_messages") or []
        s2d = d.get("stage2_decision") or {}
        dec = s2d.get("decision") or {}
        term = s2d.get("terminal") or {}
        diag = d.get("stage1_diagnosis") or {}

        s1_asst = sum(1 for m in s1 if m.get("role") == "assistant")
        s2_asst = sum(1 for m in s2 if m.get("role") == "assistant")
        has_incremental = any(
            "阶段一增量更新任务" in str(m.get("content", ""))
            for m in s1
            if m.get("role") == "user"
        )

        issues.append(
            {
                "file": p.name,
                "sym": meta.get("symbol"),
                "tf": meta.get("timeframe"),
                "model": meta.get("model") or meta.get("provider_model"),
                "exc": (exc or {}).get("message") if exc else None,
                "s1_asst": s1_asst,
                "s2_asst": s2_asst,
                "incr": has_incremental,
                "gate": diag.get("gate_result"),
                "order": dec.get("order_type"),
                "terminal": term.get("outcome"),
                "trade_conf": dec.get("trade_confidence"),
                "diag_conf": dec.get("diagnosis_confidence"),
            }
        )

    print("TOTAL", len(issues))
    print("completed stage2", sum(1 for i in issues if i["order"]))
    print("exceptions", sum(1 for i in issues if i["exc"]))
    print("real s1 retries", sum(
        1 for i in issues for _ in [0]
        if False
    ))
    print("terminal:", Counter(i["terminal"] for i in issues if i["terminal"]))
    print("order:", Counter(i["order"] for i in issues if i["order"]))
    print("model:", Counter(i["model"] for i in issues))

    print("\n=== incremental stage1 ===")
    incr = [i for i in issues if i["incr"]]
    print(f"{len(incr)}/{len(issues)} incremental")
    odd = [i["file"] for i in issues if i["s1_asst"] == 2 and not i["incr"]]
    print("s1_asst=2 but not incremental:", odd or "(none)")

    print("\n=== order / terminal / trade_conf ===")
    for i in issues:
        if not i["order"]:
            continue
        print(
            f"{i['file'][:36]:36} {i['order']!s:6} / {i['terminal']!s:6} "
            f"trade={i['trade_conf']} diag={i['diag_conf']}"
        )

    print("\n=== 限价单 with trade_conf < 40 ===")
    for i in issues:
        if i["order"] == "限价单" and (i["trade_conf"] or 0) < 40:
            print(i["file"], "trade_conf", i["trade_conf"])

    print("\n=== exceptions ===")
    for i in issues:
        if i["exc"]:
            print(i["file"], "->", i["exc"][:140])

    print("\n=== stage2 multi-assistant ===")
    multi = [i["file"] for i in issues if i["s2_asst"] > 1]
    print(multi or "(none)")


if __name__ == "__main__":
    main()
