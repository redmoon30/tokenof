#!/usr/bin/env python3
"""
Tokenof — DeepSeek 用量資料擷取腳本

從 DeepSeek Platform API 擷取用量資料，標準化後存為 JSON，
供 tokenof-dashboard.html 讀取展示。

使用方式:
    python fetch_usage.py              # 預設擷取 90 天
    python fetch_usage.py --days 180   # 擷取 180 天

需要環境變數:
    DEEPSEEK_PLATFORM_TOKEN — 從 platform.deepseek.com 瀏覽器 Cookie 取得
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


BASE_URL = "https://platform.deepseek.com"
ENDPOINTS = {
    "amount": f"{BASE_URL}/api/v0/usage/amount",
    "cost": f"{BASE_URL}/api/v0/usage/cost",
    "summary": f"{BASE_URL}/api/v0/users/get_user_summary",
}

# Model name display mapping
MODEL_DISPLAY = {
    "deepseek-v4-pro": "V4 Pro",
    "deepseek-v4-flash": "V4 Flash",
    "deepseek-v3": "V3",
    "deepseek-r1": "R1",
    "deepseek-reasoner": "Reasoner",
    "deepseek-chat": "Chat",
}


def load_token() -> str:
    """從環境變數或 .env 檔讀取 Platform Token"""
    token = os.environ.get("DEEPSEEK_PLATFORM_TOKEN", "")
    if token:
        return token

    # Try .env file in script directory
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DEEPSEEK_PLATFORM_TOKEN="):
                _, val = line.split("=", 1)
                val = val.strip().strip('"').strip("'")
                if val:
                    return val

    print("[ERROR] DEEPSEEK_PLATFORM_TOKEN not set", file=sys.stderr)
    print("    Set env var or add to tokenof/.env:", file=sys.stderr)
    print("    DEEPSEEK_PLATFORM_TOKEN=your_token", file=sys.stderr)
    sys.exit(1)


def api_get(url: str, token: str) -> dict:
    """呼叫 DeepSeek Platform API，附上認證"""
    req = Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "Tokenof/1.0")

    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"[ERROR] API error {e.code}: {body[:300]}", file=sys.stderr)
        sys.exit(1)
    except URLError as e:
        print(f"[ERROR] Network error: {e.reason}", file=sys.stderr)
        sys.exit(1)


def normalize_amount(amount_data: dict) -> dict[str, dict]:
    """將 amount API 回應轉為 date -> model -> token breakdown"""
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
                "prompt_cache_hit": usage_map.get("PROMPT_CACHE_HIT_TOKEN", 0),
                "prompt_cache_miss": usage_map.get("PROMPT_CACHE_MISS_TOKEN", 0),
                "response": usage_map.get("RESPONSE_TOKEN", 0),
                "request_count": model_entry.get("request_count", 0),
            }
    return result


def normalize_cost(cost_data: dict) -> dict[str, dict[str, float]]:
    """將 cost API 回應轉為 date -> model -> cost"""
    result: dict[str, dict[str, float]] = {}
    biz_list = cost_data.get("data", {}).get("biz_data", [])
    if not biz_list:
        return result
    days = biz_list[0].get("days", [])
    for day in days:
        date = day.get("date", "")
        if not date:
            continue
        result[date] = {}
        for model_entry in day.get("data", []):
            model_name = model_entry.get("model", "unknown")
            # cost can be string or number
            cost = model_entry.get("cost", 0)
            result[date][model_name] = float(cost) if cost else 0.0
    return result


def normalize_summary(summary_data: dict) -> dict:
    """擷取帳戶摘要（本月花費、餘額）"""
    biz = summary_data.get("data", {}).get("biz_data", {})
    monthly_costs = biz.get("monthly_costs", [])
    monthly_cost = float(monthly_costs[0].get("amount", 0) if monthly_costs else 0)
    return {
        "monthly_cost_cny": monthly_cost,
        # balance endpoint is separate, skip for now
    }


def merge_daily(
    amount_map: dict, cost_map: dict, days: int
) -> list[dict]:
    """合併 amount 和 cost 資料，產出統一的每日記錄"""
    all_dates = sorted(set(amount_map.keys()) | set(cost_map.keys()), reverse=True)
    # Take the most recent N days
    recent_dates = all_dates[:days]

    daily = []
    for date in sorted(recent_dates):  # chronological
        models = {}
        total_tokens = 0
        total_cost = 0.0
        total_hit = 0
        total_miss = 0
        total_response = 0
        total_requests = 0

        # Collect all models from both amount and cost
        all_models = set()
        if date in amount_map:
            all_models.update(amount_map[date].keys())
        if date in cost_map:
            all_models.update(cost_map[date].keys())

        for model in all_models:
            amt = amount_map.get(date, {}).get(model, {})
            cost = cost_map.get(date, {}).get(model, 0.0)

            hit = amt.get("prompt_cache_hit", 0)
            miss = amt.get("prompt_cache_miss", 0)
            resp = amt.get("response", 0)
            reqs = amt.get("request_count", 0)

            models[model] = {
                "prompt_cache_hit": hit,
                "prompt_cache_miss": miss,
                "response": resp,
                "request_count": reqs,
                "cost_cny": round(cost, 4),
            }
            total_hit += hit
            total_miss += miss
            total_response += resp
            total_requests += reqs
            total_cost += cost

        total_tokens = total_hit + total_miss + total_response
        cache_hit_rate = (
            round(total_hit / (total_hit + total_miss), 4)
            if (total_hit + total_miss) > 0
            else 0.0
        )

        daily.append(
            {
                "date": date,
                "models": models,
                "total_tokens": total_tokens,
                "total_cost_cny": round(total_cost, 4),
                "cache_hit_rate": cache_hit_rate,
                "request_count": total_requests,
                "prompt_cache_hit": total_hit,
                "prompt_cache_miss": total_miss,
                "response": total_response,
            }
        )

    return daily


def generate_mock_data(days: int = 90) -> dict:
    """產生假資料供測試 Dashboard 渲染"""
    import random
    from datetime import datetime, timedelta

    random.seed(42)
    today = datetime.now()
    daily = []

    for i in range(days - 1, -1, -1):
        date = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        # Simulate realistic token usage patterns
        is_weekend = (today - timedelta(days=i)).weekday() >= 5
        base_multiplier = 0.5 if is_weekend else 1.0
        jitter = random.uniform(0.7, 1.3)

        flash_hit = int(800_000 * base_multiplier * jitter)
        flash_miss = int(50_000 * base_multiplier * jitter)
        flash_resp = int(200_000 * base_multiplier * jitter)
        flash_cost = round(flash_hit / 1_000_000 * 0.02 + flash_miss / 1_000_000 * 1 + flash_resp / 1_000_000 * 2, 4)

        pro_hit = int(300_000 * base_multiplier * jitter)
        pro_miss = int(30_000 * base_multiplier * jitter)
        pro_resp = int(80_000 * base_multiplier * jitter)
        pro_cost = round(pro_hit / 1_000_000 * 0.025 + pro_miss / 1_000_000 * 3 + pro_resp / 1_000_000 * 6, 4)

        total_hit = flash_hit + pro_hit
        total_miss = flash_miss + pro_miss
        total_resp = flash_resp + pro_resp
        total_tokens = total_hit + total_miss + total_resp
        total_cost = round(flash_cost + pro_cost, 4)

        daily.append({
            "date": date,
            "models": {
                "deepseek-v4-flash": {
                    "prompt_cache_hit": flash_hit,
                    "prompt_cache_miss": flash_miss,
                    "response": flash_resp,
                    "request_count": int(300 * base_multiplier * jitter),
                    "cost_cny": flash_cost,
                },
                "deepseek-v4-pro": {
                    "prompt_cache_hit": pro_hit,
                    "prompt_cache_miss": pro_miss,
                    "response": pro_resp,
                    "request_count": int(100 * base_multiplier * jitter),
                    "cost_cny": pro_cost,
                },
            },
            "total_tokens": total_tokens,
            "total_cost_cny": total_cost,
            "cache_hit_rate": round(total_hit / (total_hit + total_miss), 4) if (total_hit + total_miss) > 0 else 0,
            "request_count": int(400 * base_multiplier * jitter),
            "prompt_cache_hit": total_hit,
            "prompt_cache_miss": total_miss,
            "response": total_resp,
        })

    return {
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "is_mock": True,
        "summary": {"monthly_cost_cny": round(sum(d["total_cost_cny"] for d in daily[-30:]), 2)},
        "daily": daily,
    }


def main():
    parser = argparse.ArgumentParser(description="Tokenof - DeepSeek usage fetcher")
    parser.add_argument("--days", type=int, default=90, help="Days to fetch (default 90)")
    parser.add_argument("--mock", action="store_true", help="Generate mock data for testing")
    parser.add_argument("--output", type=str, default=None, help="Output file path")
    args = parser.parse_args()

    script_dir = Path(__file__).parent
    output_path = Path(args.output) if args.output else script_dir / "usage_data.json"

    if args.mock:
        print("[MOCK] Generating mock data...")
        data = generate_mock_data(args.days)
    else:
        token = load_token()
        print(f"[FETCH] Pulling usage data (last {args.days} days)...")

        # Fetch all three endpoints
        print("  -> /api/v0/usage/amount ...")
        amount_raw = api_get(ENDPOINTS["amount"], token)
        print("  -> /api/v0/usage/cost ...")
        cost_raw = api_get(ENDPOINTS["cost"], token)
        print("  -> /api/v0/users/get_user_summary ...")
        summary_raw = api_get(ENDPOINTS["summary"], token)

        # Normalize
        amount_map = normalize_amount(amount_raw)
        cost_map = normalize_cost(cost_raw)
        summary = normalize_summary(summary_raw)

        # Merge into daily records
        daily = merge_daily(amount_map, cost_map, args.days)

        data = {
            "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "is_mock": False,
            "summary": summary,
            "daily": daily,
        }

    # Write JSON output
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    day_count = len(data["daily"])
    total_cost = sum(d["total_cost_cny"] for d in data["daily"])
    print(f"[OK] Wrote {day_count} days -> {output_path}")
    print(f"     {args.days}-day total cost: {total_cost:.2f} CNY")

    # Inject data into HTML dashboard (idempotent: regex replaces existing container)
    html_path = script_dir / "tokenof-dashboard.html"
    if html_path.exists():
        html = html_path.read_text(encoding="utf-8")
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
            print("[ERROR] Could not find tokenof-data container in HTML — template may be corrupted", file=sys.stderr)
            sys.exit(1)
        html_path.write_text(new_html, encoding="utf-8")
        print(f"[OK] Injected data into {html_path}")
    else:
        print("[WARN] tokenof-dashboard.html not found, skipping HTML injection", file=sys.stderr)


if __name__ == "__main__":
    main()
