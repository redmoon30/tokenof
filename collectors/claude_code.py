"""Claude Code collector — reads local ~/.claude/projects/*/*.jsonl.

No token, no network. Field mapping per MULTI-SOURCE.md §3.2.

Pitfalls handled (all verified against local data):
  G1: one API request writes multiple lines (text/tool_use blocks), each
      carrying the SAME usage. Must dedup by (message.id, requestId).
  G2: a few records have top-level usage all-zero; truth is in iterations[].
  G3: message.model == "<synthetic>" are local synthesized msgs, exclude.
  G5: isSidechain records are real spend — include them (subagent dimension
      reserved for later, not split here).
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

SOURCE = "claude-code"
HOME = Path.home()
CLAUDE_DIR = HOME / ".claude" / "projects"


def _usage_from_top(u):
    """Return (cache_read, cache_creation, input, output) from top-level usage."""
    return (
        u.get("cache_read_input_tokens", 0) or 0,
        u.get("cache_creation_input_tokens", 0) or 0,
        u.get("input_tokens", 0) or 0,
        u.get("output_tokens", 0) or 0,
    )


def _usage_from_iterations(u):
    iters = u.get("iterations", []) or []
    cr = cc = inp = out = 0
    for it in iters:
        cr += it.get("cache_read_input_tokens", 0) or 0
        cc += it.get("cache_creation_input_tokens", 0) or 0
        inp += it.get("input_tokens", 0) or 0
        out += it.get("output_tokens", 0) or 0
    return cr, cc, inp, out


def _dedup_key(rec):
    return (rec.get("message", {}).get("id"), rec.get("requestId"))


def collect(days: int = 90) -> list:
    """Return list of daily records (schema v2)."""
    if not CLAUDE_DIR.exists():
        print(f"[WARN] {CLAUDE_DIR} not found", file=sys.stderr)
        return []

    jsonl_files = list(CLAUDE_DIR.glob("**/*.jsonl"))
    if not jsonl_files:
        print("[WARN] no jsonl files under ~/.claude/projects", file=sys.stderr)
        return []

    # (date, model) -> {hit, miss, resp, reqs}
    agg = defaultdict(lambda: defaultdict(lambda: {"hit": 0, "miss": 0, "resp": 0, "reqs": 0}))
    seen = set()  # dedup keys

    for fp in jsonl_files:
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
                    if rec.get("type") != "assistant":
                        continue
                    msg = rec.get("message", {})
                    if msg.get("model") == "<synthetic>":
                        continue
                    usage = msg.get("usage")
                    if not usage:
                        continue

                    key = _dedup_key(rec)
                    if key in seen:
                        continue
                    seen.add(key)

                    cr, cc, inp, out = _usage_from_top(usage)
                    if (cr + cc + inp + out) == 0:
                        # G2: fall back to iterations
                        cr, cc, inp, out = _usage_from_iterations(usage)
                    if (cr + cc + inp + out) == 0:
                        continue

                    date = rec.get("timestamp", "")[:10]
                    model = msg.get("model", "unknown")
                    cell = agg[date][model]
                    cell["hit"] += cr
                    cell["miss"] += inp + cc  # input + cache_creation = not-from-cache input
                    cell["resp"] += out
                    cell["reqs"] += 1
        except OSError as e:
            print(f"[WARN] read {fp}: {e}", file=sys.stderr)
            continue

    return _to_records(agg)


def _to_records(agg):
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
                "cost_basis": "unknown",  # subscription; no per-call cost here
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
    return records


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=30)
    args = p.parse_args()
    recs = collect(args.days)
    if not recs:
        print("[INFO] no Claude Code usage found")
    else:
        recent = recs[-args.days:]
        total = sum(r["total_tokens"] for r in recent)
        print(f"[OK] {len(recent)} days, total tokens = {total:,}")
        for r in recent[-5:]:
            print(f"  {r['date']}  {r['total_tokens']:,} tokens  {r['request_count']} reqs  hit_rate={r['cache_hit_rate']:.2%}")
