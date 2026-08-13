"""Codex collector — reads local ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl.

No token, no network. Field mapping per MULTI-SOURCE.md §4.2.

Pitfalls handled (verified against local data):
  G1: total_token_usage is SESSION cumulative — use last_token_usage per event.
  G2: input_tokens ALREADY includes cached_input_tokens — miss = input - cached.
  G3: model lives in turn_context and may change mid-session — track latest.
  G4: rate_limits (used_percent/resets_at) is the real subscription signal.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

SOURCE = "codex"
HOME = Path.home()
CODEX_DIR = HOME / ".codex" / "sessions"


def collect(days: int = 90) -> tuple:
    """Return (records, rate_limits) — records is schema v2 list, rate_limits is the latest quota snapshot."""
    if not CODEX_DIR.exists():
        print(f"[WARN] {CODEX_DIR} not found", file=sys.stderr)
        return [], {}

    jsonl_files = sorted(CODEX_DIR.glob("**/rollout-*.jsonl"))
    if not jsonl_files:
        print("[WARN] no rollout-*.jsonl under ~/.codex/sessions", file=sys.stderr)
        return [], {}

    agg = defaultdict(lambda: defaultdict(lambda: {"hit": 0, "miss": 0, "resp": 0, "reqs": 0}))
    rate_limits = {}  # latest rate_limits snapshot (not per-day)

    for fp in jsonl_files:
        current_model = "unknown"
        try:
            with open(fp, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    rtype = rec.get("type")
                    payload = rec.get("payload", {})

                    if rtype == "turn_context":
                        m = payload.get("model")
                        if m:
                            current_model = m
                        continue

                    if rtype != "event_msg":
                        continue
                    if payload.get("type") != "token_count":
                        continue

                    info = payload.get("info", {})
                    last = info.get("last_token_usage", {})
                    if not last:
                        continue

                    cached = last.get("cached_input_tokens", 0) or 0
                    inp = last.get("input_tokens", 0) or 0
                    out = last.get("output_tokens", 0) or 0
                    miss = max(inp - cached, 0)  # G2

                    date = rec.get("timestamp", "")[:10]
                    cell = agg[date][current_model]
                    cell["hit"] += cached
                    cell["miss"] += miss
                    cell["resp"] += out
                    cell["reqs"] += 1

                    # Capture latest rate_limits (G4)
                    rl = payload.get("rate_limits", {})
                    if rl:
                        rate_limits = {
                            "plan_type": rl.get("plan_type"),
                            "used_percent": (rl.get("primary") or {}).get("used_percent"),
                            "resets_at": (rl.get("primary") or {}).get("resets_at"),
                            "window_minutes": (rl.get("primary") or {}).get("window_minutes"),
                        }
        except OSError as e:
            print(f"[WARN] read {fp}: {e}", file=sys.stderr)
            continue

    records = []
    for date in sorted(agg):
        models = {}
        total_hit = total_miss = total_resp = total_reqs = 0
        for model, c in agg[date].items():
            models[model] = {
                "prompt_cache_hit": c["hit"],
                "prompt_cache_miss": c["miss"],
                "response": c["resp"],
                "request_count": c["reqs"],
                "cost": 0.0,
                "currency": "USD",
                "cost_basis": "unknown",
            }
            total_hit += c["hit"]
            total_miss += c["miss"]
            total_resp += c["resp"]
            total_reqs += c["reqs"]
        records.append({
            "date": date,
            "source": SOURCE,
            "models": models,
            "total_tokens": total_hit + total_miss + total_resp,
            "cache_hit_rate": round(total_hit / (total_hit + total_miss), 4) if (total_hit + total_miss) > 0 else 0.0,
            "request_count": total_reqs,
        })
    return records, rate_limits


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=30)
    args = p.parse_args()
    recs, rate_limits = collect(args.days)
    if not recs:
        print("[INFO] no Codex usage found")
    else:
        recent = recs[-args.days:]
        total = sum(r["total_tokens"] for r in recent)
        print(f"[OK] {len(recent)} days, total tokens = {total:,}")
        for r in recent[-5:]:
            print(f"  {r['date']}  {r['total_tokens']:,} tokens  {r['request_count']} reqs  hit_rate={r['cache_hit_rate']:.2%}")
    if rate_limits:
        print(f"[INFO] latest rate_limits: {rate_limits}")
