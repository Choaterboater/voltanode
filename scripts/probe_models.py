"""Probe OpenRouter's free-tier models and report which actually work.

Fetches the live model list, filters to free (price=0) chat models,
optionally pings each with a trivial prompt, and prints:
  - a sorted table of working models by latency
  - a ready-to-paste ``OPENROUTER_FALLBACK_MODELS=...`` line

Usage::

    # Just list free models, no probing (fast)
    python scripts/probe_models.py --list-only

    # Probe every free model end-to-end (slow — 5-30 min depending on count)
    python scripts/probe_models.py

    # Probe a specific subset
    python scripts/probe_models.py --only inclusionai/ring-2.6-1t:free,...

    # Cap how many to probe (default 30 to keep runtime reasonable)
    python scripts/probe_models.py --max 50

Reads OPENROUTER_API_KEY from environment (or trading-bot-backend/.env).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / "trading-bot-backend" / ".env"

OPENROUTER_API = "https://openrouter.ai/api/v1"
TRIVIAL_PROMPT = "Reply with exactly: OK"
PROBE_TIMEOUT = 30.0


def load_env_api_key() -> Optional[str]:
    """Read OPENROUTER_API_KEY from env, falling back to the .env file."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key
    if not ENV_PATH.exists():
        return None
    try:
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return None


def fetch_free_models() -> List[Dict]:
    """List every free chat model currently on OpenRouter (no auth needed)."""
    r = requests.get(f"{OPENROUTER_API}/models", timeout=15)
    r.raise_for_status()
    data = r.json().get("data", [])
    free: List[Dict] = []
    for m in data:
        pricing = m.get("pricing", {}) or {}
        # Both prompt + completion must be "0" (string) for true free
        prompt_price = str(pricing.get("prompt", "")).strip()
        completion_price = str(pricing.get("completion", "")).strip()
        if prompt_price == "0" and completion_price == "0":
            free.append({
                "id": m.get("id"),
                "name": m.get("name"),
                "context_length": m.get("context_length"),
                "architecture": (m.get("architecture") or {}).get("modality"),
            })
    return free


def probe_one(model_id: str, api_key: str) -> Dict:
    """Send the trivial prompt and time the call. Returns a result dict."""
    t0 = time.time()
    try:
        r = requests.post(
            f"{OPENROUTER_API}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model_id,
                "messages": [{"role": "user", "content": TRIVIAL_PROMPT}],
                "temperature": 0.0,
                "max_tokens": 12,
            },
            timeout=PROBE_TIMEOUT,
        )
        latency_ms = (time.time() - t0) * 1000
        if r.status_code >= 400:
            return {
                "model": model_id,
                "ok": False,
                "latency_ms": latency_ms,
                "error": f"HTTP {r.status_code}",
                "status": r.status_code,
            }
        content = r.json()["choices"][0]["message"].get("content", "")
        return {
            "model": model_id,
            "ok": True,
            "latency_ms": latency_ms,
            "content": (content or "").strip()[:40],
            "status": r.status_code,
        }
    except Exception as e:
        return {
            "model": model_id,
            "ok": False,
            "latency_ms": (time.time() - t0) * 1000,
            "error": str(e)[:80],
        }


def main() -> int:
    ap = argparse.ArgumentParser(description="Probe OpenRouter free models")
    ap.add_argument("--list-only", action="store_true",
                    help="Just list free models, don't probe.")
    ap.add_argument("--only", default="",
                    help="Comma-separated subset of model IDs to probe instead "
                         "of the full free list.")
    ap.add_argument("--max", type=int, default=30,
                    help="Cap probe count (default 30). Set 0 for unlimited.")
    args = ap.parse_args()

    print(f"fetching free models from {OPENROUTER_API}/models ...")
    try:
        free = fetch_free_models()
    except Exception as e:
        print(f"FAILED to fetch model list: {e}")
        return 1

    print(f"found {len(free)} free models on OpenRouter")
    if args.list_only:
        for m in sorted(free, key=lambda x: (x.get("context_length") or 0) * -1):
            ctx = m.get("context_length") or 0
            print(f"  {m['id']:<55}  ctx={ctx:>7}  {m.get('name','')[:50]}")
        return 0

    api_key = load_env_api_key()
    if not api_key:
        print("ERROR: OPENROUTER_API_KEY not found in env or .env")
        return 2

    # Pick target list
    if args.only:
        targets = [s.strip() for s in args.only.split(",") if s.strip()]
        print(f"probing {len(targets)} explicit models")
    else:
        ids = [m["id"] for m in free]
        if args.max > 0 and len(ids) > args.max:
            print(f"capping probe to first {args.max} (use --max 0 for all)")
            ids = ids[:args.max]
        targets = ids

    results: List[Dict] = []
    for i, mid in enumerate(targets, 1):
        print(f"[{i:>3}/{len(targets)}] probing {mid} ...", end=" ", flush=True)
        r = probe_one(mid, api_key)
        results.append(r)
        if r["ok"]:
            print(f"OK   {r['latency_ms']:.0f}ms  '{r['content']}'")
        else:
            print(f"FAIL  {r.get('error', '?')}")
        # Tiny pause so we don't slam OpenRouter's rate limiter
        time.sleep(0.5)

    # Report
    working = [r for r in results if r["ok"]]
    failing = [r for r in results if not r["ok"]]
    working.sort(key=lambda x: x["latency_ms"])

    print(f"\n=== RESULTS: {len(working)} working / {len(failing)} failing ===\n")
    print("Working (sorted by latency):")
    for r in working:
        print(f"  {r['latency_ms']:>7.0f}ms   {r['model']}")
    if failing:
        print("\nFailing:")
        for r in failing:
            print(f"  {r['model']:<55}  {r.get('error','?')}")

    if working:
        chain = ",".join(r["model"] for r in working)
        print(f"\n=== Suggested .env line (top {min(len(working), 15)} by latency) ===")
        top = ",".join(r["model"] for r in working[:15])
        print(f"OPENROUTER_FALLBACK_MODELS={top}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
