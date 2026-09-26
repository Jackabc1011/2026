"""Tiny HTTP helper: JSON GET with retries, and a per-run source status log."""
import time

import requests

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "alpha-radar/1.0 (+https://github.com)"

# name -> {"ok": bool, "count": int, "error": str|None}
STATUS: dict[str, dict] = {}


def get_json(url, params=None, headers=None, retries=2, timeout=20):
    last = None
    for attempt in range(retries + 1):
        try:
            r = SESSION.get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code == 429 or r.status_code >= 500:
                last = f"HTTP {r.status_code}"
                time.sleep(2 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            last = str(e)
            time.sleep(1 + attempt)
    raise RuntimeError(f"GET {url} failed: {last}")


def get_text(url, timeout=20):
    r = SESSION.get(url, timeout=timeout)
    r.raise_for_status()
    return r.text


def run_source(name, fn, *args, **kwargs):
    """Run one data source; never let a single failure break the whole run."""
    try:
        result = fn(*args, **kwargs)
        STATUS[name] = {"ok": True, "count": len(result), "error": None}
        return result
    except Exception as e:  # noqa: BLE001 - we want to record any failure
        STATUS[name] = {"ok": False, "count": 0, "error": str(e)[:300]}
        print(f"[warn] source {name} failed: {e}")
        return []


def skip_source(name, reason):
    STATUS[name] = {"ok": False, "count": 0, "error": reason, "skipped": True}
