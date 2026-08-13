"""Tokenof collectors — each returns a list of daily records (schema v2).

Schema v2 daily record:
{
  "date": "YYYY-MM-DD",
  "source": "deepseek" | "claude-code" | "codex",
  "models": {
    "<model>": {
      "prompt_cache_hit": int,   # tokens read from cache
      "prompt_cache_miss": int,  # input tokens NOT read from cache
      "response": int,           # output tokens
      "request_count": int,
      "cost": float,             # 0.0 if unknown
      "currency": "CNY" | "USD",
      "cost_basis": "metered" | "notional" | "unknown"
    }
  },
  "total_tokens": int,
  "cache_hit_rate": float,       # 0.0 - 1.0
  "request_count": int
}
"""
from datetime import datetime, timezone
from pathlib import Path


def today_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_week_key(date_str):
    """Return the Monday of the ISO week for a YYYY-MM-DD date."""
    d = datetime.fromisoformat(date_str)
    monday = d.fromordinal(d.toordinal() - (d.weekday()))
    return monday.strftime("%Y-%m-%d")
