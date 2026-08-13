"""DeepSeek collector — pulls usage from platform.deepseek.com internal API.

Requires DEEPSEEK_PLATFORM_TOKEN (env or .env). This is NOT a public API key:
it is the browser session credential found via DevTools -> Network -> Request
Headers (either `authorization: Bearer <token>` or a cookie).

Auth autodetect (P1-5a): tries `Authorization: Bearer <token>` first; on 401
falls back to `Cookie: <token>`. The working mode is reported on stderr so the
dashboard pipeline knows which header format is in use.

Endpoints (internal, subject to change):
  /api/v0/usage/amount          daily token usage per model
  /api/v0/usage/cost            daily cost per model (CNY)
  /api/v0/users/get_user_summary  account summary (monthly cost)

Output: schema v2 records (see MULTI-SOURCE.md) with source="deepseek",
currency "CNY", cost_basis "platform-billing".
"""

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

SOURCE = "deepseek"
BASE_URL = "https://platform.deepseek.com"
ENDPOINTS = {
    "amount": f"{BASE_URL}/api/v0/usage/amount",
    "cost": f"{BASE_URL}/api/v0/usage/cost",
    "summary": f"{BASE_URL}/api/v0/users/get_user_summary",
}


def load_token() -> str:
    """Read DEEPSEEK_PLATFORM_TOKEN from env or .env (repo root or script dir)."""
    token = os.environ.get("DEEPSEEK_PLATFORM_TOKEN", "")
    if token:
        return token
    for env_path in (Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"):
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("DEEPSEEK_PLATFORM_TOKEN="):
                    _, val = line.split("=", 1)
                    val = val.strip().strip('"').strip("'")
                    if val:
                        return val
    print("[ERROR] DEEPSEEK_PLATFORM_TOKEN not set (env or .env)", file=sys.stderr)
    sys.exit(1)


def api_get(url: str, token: str, params: dict = None) -> dict:
    """GET with auth autodetect: Bearer first, Cookie fallback on 401."""
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{qs}"

    def attempt(header_name):
        req = Request(url)
        req.add_header(header_name, f"Bearer {token}" if header_name == "Authorization" else token)
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", "Tokenof/1.0")
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    try:
        return attempt("Authorization")
    except HTTPError as e:
        if e.code == 401:
            print("[AUTH] Bearer rejected (401); retrying with Cookie header", file=sys.stderr)
            try:
                return attempt("Cookie")
            except HTTPError as e2:
                _die_http(e2)
        _die_http(e)
    except URLError as e:
        print(f"[ERROR] Network error: {e.reason}", file=sys.stderr)
        sys.exit(1)


def _die_http(e: HTTPError):
    body = e.read().decode("utf-8", errors="replace")
    print(f"[ERROR] API error {e.code}: {body[:300]}", file=sys.stderr)
    sys.exit(1)


def normalize_amount(amount_data: dict) -> dict[str, dict]:
    """date -> model -> {hit, miss, resp, reqs}"""
    result: dict[str, dict] = {}
    days = amount_data.get("data", {}).get("biz_data", {}).get("days", [])
    for day in days:
        date = day.get("date", "")
        if not date:
            continue
        result[date] = {}
        for model_entry in day.get("data", []):
            model_name = model_entry.get("model", "unknown")
            usage_list = model_entry.get("usage", [])
            usage_map = {u.get("type"): int(u.get("amount", 0) or 0) for u in usage_list}
            result[date][model_name] = {
                "hit": usage_map.get("PROMPT_CACHE_HIT_TOKEN", 0),
                "miss": usage_map.get("PROMPT_CACHE_MISS_TOKEN", 0),
                "resp": usage_map.get("RESPONSE_TOKEN", 0),
                "reqs": usage_map.get("REQUEST", 0),
            }
    return result


def normalize_cost(cost_data: dict) -> dict[str, dict[str, float]]:
    """date -> model -> cost CNY.

    Cost API daily structure mirrors amount API: each model entry carries a
    usage[] array where every type's `amount` IS the fee (decimal CNY), not a
    token count. Sum all types per model per day.
    """
    result: dict[str, dict[str, float]] = {}
    biz_list = cost_data.get("data", {}).get("biz_data", [])
    if not biz_list:
        return result
    for day in biz_list[0].get("days", []):
        date = day.get("date", "")
        if not date:
            continue
        result[date] = {}
        for model_entry in day.get("data", []):
            model_name = model_entry.get("model", "unknown")
            usage_list = model_entry.get("usage", [])
            day_cost = sum(float(u.get("amount", 0) or 0) for u in usage_list)
            result[date][model_name] = round(day_cost, 4)
    return result


def normalize_summary(summary_data: dict) -> dict:
    """Account summary: monthly cost CNY."""
    biz = summary_data.get("data", {}).get("biz_data", {})
    monthly_costs = biz.get("monthly_costs", [])
    monthly_cost = float(monthly_costs[0].get("amount", 0) if monthly_costs else 0)
    return {"monthly_cost_cny": monthly_cost}


def collect(days: int = 90) -> list:
    """Fetch and normalize into schema v2 daily records.

    DeepSeek usage API is per-month: ?year=YYYY&month=M (M 1-12, no zero-pad).
    We loop over every month covered by the requested window and merge days.
    """
    from datetime import timedelta as _td

    token = load_token()
    print("[FETCH] DeepSeek usage (last %d days)" % days, file=sys.stderr)

    today = datetime.now()
    start = today - _td(days=days - 1)
    today_str = today.strftime("%Y-%m-%d")

    months = []
    y, m = start.year, start.month
    while (y, m) <= (today.year, today.month):
        months.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1

    amount_map: dict = {}
    cost_map: dict = {}
    for y, m in months:
        params = {"year": y, "month": m}
        print(f"  -> amount {y}-{m:02d} ...", file=sys.stderr)
        amount_map.update(normalize_amount(api_get(ENDPOINTS["amount"], token, params)))
        print(f"  -> cost    {y}-{m:02d} ...", file=sys.stderr)
        cost_map.update(normalize_cost(api_get(ENDPOINTS["cost"], token, params)))

    summary = normalize_summary(api_get(ENDPOINTS["summary"], token))

    all_dates = sorted(set(amount_map.keys()) | set(cost_map.keys()))
    recent = [d for d in all_dates if start.strftime("%Y-%m-%d") <= d <= today_str]
    if days > 0 and len(recent) > days:
        recent = recent[-days:]

    records = []
    for date in recent:
        models = {}
        total_hit = total_miss = total_resp = total_reqs = 0
        total_cost = 0.0

        all_models = set()
        if date in amount_map:
            all_models.update(amount_map[date].keys())
        if date in cost_map:
            all_models.update(cost_map[date].keys())

        for model in all_models:
            amt = amount_map.get(date, {}).get(model, {})
            cost = cost_map.get(date, {}).get(model, 0.0)
            hit = amt.get("hit", 0)
            miss = amt.get("miss", 0)
            resp = amt.get("resp", 0)
            reqs = amt.get("reqs", 0)
            models[model] = {
                "prompt_cache_hit": hit,
                "prompt_cache_miss": miss,
                "response": resp,
                "request_count": reqs,
                "cost": round(cost, 4),
                "currency": "CNY",
                "cost_basis": "platform-billing",
            }
            total_hit += hit
            total_miss += miss
            total_resp += resp
            total_reqs += reqs
            total_cost += cost

        records.append({
            "date": date,
            "source": SOURCE,
            "models": models,
            "total_tokens": total_hit + total_miss + total_resp,
            "cache_hit_rate": round(total_hit / (total_hit + total_miss), 4) if (total_hit + total_miss) > 0 else 0.0,
            "request_count": total_reqs,
            "total_cost": round(total_cost, 4),
        })

    # Attach summary as metadata on the module for build pipeline
    collect.summary = summary
    return records


def mock(days: int = 90) -> list:
    """Generate deterministic mock data (schema v2, source=deepseek) for testing."""
    import random
    from datetime import datetime, timedelta

    random.seed(42)
    today = datetime.now()
    records = []

    for i in range(days - 1, -1, -1):
        date = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        is_weekend = (today - timedelta(days=i)).weekday() >= 5
        base = 0.5 if is_weekend else 1.0
        jitter = random.uniform(0.7, 1.3)

        models = {}
        total_hit = total_miss = total_resp = total_reqs = 0
        total_cost = 0.0

        # flash: cheap high-volume model
        f_hit = int(800_000 * base * jitter)
        f_miss = int(50_000 * base * jitter)
        f_resp = int(200_000 * base * jitter)
        f_cost = round(f_hit / 1e6 * 0.02 + f_miss / 1e6 * 1 + f_resp / 1e6 * 2, 4)
        models["deepseek-v4-flash"] = {
            "prompt_cache_hit": f_hit, "prompt_cache_miss": f_miss, "response": f_resp,
            "request_count": int(300 * base * jitter), "cost": f_cost,
            "currency": "CNY", "cost_basis": "platform-billing",
        }
        # pro: expensive reasoning model
        p_hit = int(300_000 * base * jitter)
        p_miss = int(30_000 * base * jitter)
        p_resp = int(80_000 * base * jitter)
        p_cost = round(p_hit / 1e6 * 0.025 + p_miss / 1e6 * 3 + p_resp / 1e6 * 6, 4)
        models["deepseek-v4-pro"] = {
            "prompt_cache_hit": p_hit, "prompt_cache_miss": p_miss, "response": p_resp,
            "request_count": int(100 * base * jitter), "cost": p_cost,
            "currency": "CNY", "cost_basis": "platform-billing",
        }

        for m in models.values():
            total_hit += m["prompt_cache_hit"]
            total_miss += m["prompt_cache_miss"]
            total_resp += m["response"]
            total_reqs += m["request_count"]
            total_cost += m["cost"]

        records.append({
            "date": date, "source": SOURCE, "models": models,
            "total_tokens": total_hit + total_miss + total_resp,
            "cache_hit_rate": round(total_hit / (total_hit + total_miss), 4) if (total_hit + total_miss) > 0 else 0.0,
            "request_count": total_reqs,
            "total_cost": round(total_cost, 4),
        })

    collect.summary = {"monthly_cost_cny": round(sum(r["total_cost"] for r in records[-30:]), 2)}
    return records


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Tokenof DeepSeek collector")
    p.add_argument("--days", type=int, default=90)
    p.add_argument("--mock", action="store_true", help="generate mock data")
    args = p.parse_args()
    recs = collect(args.days) if not args.mock else mock(args.days)
    if not recs:
        print("[INFO] no DeepSeek usage returned")
    else:
        total = sum(r["total_tokens"] for r in recs)
        print(f"[OK] {len(recs)} days, total tokens = {total:,}")
        print(f"     monthly_cost_cny = {collect.summary.get('monthly_cost_cny', 0):.2f}")
        for r in recs[-5:]:
            print(f"  {r['date']}  {r['total_tokens']:,} tokens  {r['request_count']} reqs  hit_rate={r['cache_hit_rate']:.2%}  cost={r.get('total_cost', 0):.4f} CNY")
