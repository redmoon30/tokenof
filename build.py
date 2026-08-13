#!/usr/bin/env python3
"""Tokenof build — orchestrate collectors, merge into usage_data.json, inject HTML.

Usage:
    python build.py --sources claude-code,codex        # no token needed
    python build.py --sources deepseek --days 120       # needs token
    python build.py --sources all --days 120
    python build.py --sources deepseek --mock           # test data
"""
import argparse
import json
import re
import sys
from pathlib import Path

from collectors import claude_code, codex, deepseek

SCRIPT_DIR = Path(__file__).parent
JSON_PATH = SCRIPT_DIR / "usage_data.json"
HTML_PATH = SCRIPT_DIR / "tokenof-dashboard.html"

ALL_SOURCES = ["deepseek", "claude-code", "codex"]


def collect_all(sources, days, mock):
    records = []
    codex_rate_limits = {}

    for src in sources:
        print(f"[COLLECT] {src} ...")
        if src == "deepseek":
            recs = deepseek.mock(days) if mock else deepseek.collect(days)
            records.extend(recs)
        elif src == "claude-code":
            records.extend(claude_code.collect(days))
        elif src == "codex":
            recs, codex_rate_limits = codex.collect(days)
            records.extend(recs)
        else:
            print(f"[ERROR] unknown source: {src}", file=sys.stderr)
            sys.exit(1)

    return records, codex_rate_limits


def build(sources, days, mock):
    records, rate_limits = collect_all(sources, days, mock)

    data = {
        "fetched_at": _utc_now(),
        "is_mock": mock,
        "sources": sources,
        "codex_rate_limits": rate_limits,
        "daily": records,
    }

    JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Wrote {len(records)} records -> {JSON_PATH}")

    _inject_html(data)
    return data


def _utc_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _inject_html(data):
    """Idempotent injection: regex-replace existing tokenof-data container."""
    if not HTML_PATH.exists():
        print("[WARN] tokenof-dashboard.html not found, skipping HTML injection", file=sys.stderr)
        return
    html = HTML_PATH.read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    block = f'<script id="tokenof-data" type="application/json">{payload}</script>'
    new_html, n = re.subn(
        r'<script id="tokenof-data"[^>]*>.*?</script>',
        lambda _: block,
        html,
        count=1,
        flags=re.S,
    )
    if n == 0:
        print("[ERROR] Could not find tokenof-data container in HTML — template corrupted", file=sys.stderr)
        sys.exit(1)
    HTML_PATH.write_text(new_html, encoding="utf-8")
    print(f"[OK] Injected data into {HTML_PATH}")


def main():
    p = argparse.ArgumentParser(description="Tokenof build")
    p.add_argument("--sources", type=str, default="all", help="comma-separated: deepseek,claude-code,codex / all")
    p.add_argument("--days", type=int, default=90, help="days to fetch (default 90)")
    p.add_argument("--mock", action="store_true", help="use mock data for deepseek (test)")
    args = p.parse_args()

    sources = ALL_SOURCES if args.sources == "all" else [s.strip() for s in args.sources.split(",") if s.strip()]
    if not sources:
        print("[ERROR] no sources specified", file=sys.stderr)
        sys.exit(1)

    data = build(sources, args.days, args.mock)

    # Summary
    total_tokens = sum(r["total_tokens"] for r in data["daily"])
    print(f"[DONE] {len(data['sources'])} sources, {len(data['daily'])} records, {total_tokens:,} total tokens")


if __name__ == "__main__":
    main()
