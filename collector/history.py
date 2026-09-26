"""Score history across runs: deltas, first-seen, trend lines and "newly hot" detection.

History is a small JSON file next to latest.json:
  {"snapshots": [{"t": iso, "scores": {SYM: score}, "ratings": {SYM: rating}}, ...],
   "alerted": {SYM: iso}}   # last alert per token, for the re-alert cooldown
On GitHub Actions nothing persists between runs, so the previous file is fetched from
the published Pages site (HISTORY_URL) when there is no local copy.
"""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from .http import get_json

MAX_SNAPSHOTS = 96    # 48h at one run per 30 min
TREND_POINTS = 24
ALERT_COOLDOWN_HOURS = 12


def _dt(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def load_history(path):
    path = Path(path)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"[warn] history {path}: {e}")
    url = os.environ.get("HISTORY_URL")
    if url:
        try:
            return get_json(url, retries=1)
        except Exception as e:  # noqa: BLE001 - first deploy has no history yet
            print(f"[warn] history {url}: {e}")
    return {"snapshots": []}


def apply_history(payload, history, max_snapshots=MAX_SNAPSHOTS, cooldown_hours=ALERT_COOLDOWN_HOURS):
    """Annotate payload opportunities in place; return (new_history, newly_hot).

    newly_hot = tokens rated 重点关注 now but not last run, and not alerted within the
    cooldown - so a token flapping (e.g. one source failing for a run) alerts only once.
    """
    snaps = [s for s in history.get("snapshots", []) if s.get("t") and s.get("t") < payload["generated_at"]]
    prev = snaps[-1] if snaps else None

    first_seen = {}
    for s in snaps:
        for sym in s.get("scores", {}):
            first_seen.setdefault(sym, s["t"])

    newly_hot = []
    for o in payload["opportunities"]:
        sym = o["symbol"]
        prev_score = prev["scores"].get(sym) if prev else None
        o["prev_score"] = prev_score
        o["delta"] = round(o["score"] - prev_score, 1) if prev_score is not None else None
        o["is_new"] = prev is not None and prev_score is None
        o["first_seen"] = first_seen.get(sym, payload["generated_at"])
        o["trend"] = [s["scores"].get(sym) for s in snaps[-(TREND_POINTS - 1):]] + [o["score"]]
        if prev is not None and o["rating"] == "重点关注" and prev.get("ratings", {}).get(sym) != "重点关注":
            newly_hot.append(o)

    now = _dt(payload["generated_at"])
    cutoff = now - timedelta(hours=cooldown_hours)
    alerted = {k: v for k, v in (history.get("alerted") or {}).items() if _dt(v) > cutoff}
    newly_hot = [o for o in newly_hot if o["symbol"] not in alerted]
    for o in newly_hot:
        alerted[o["symbol"]] = payload["generated_at"]

    if not payload["opportunities"]:
        # A run where every source failed would make all tokens look "new" next time.
        return {"snapshots": snaps[-max_snapshots:], "alerted": alerted}, newly_hot
    snaps.append({
        "t": payload["generated_at"],
        "scores": {o["symbol"]: o["score"] for o in payload["opportunities"]},
        "ratings": {o["symbol"]: o["rating"] for o in payload["opportunities"] if o["rating"] != "噪音"},
    })
    return {"snapshots": snaps[-max_snapshots:], "alerted": alerted}, newly_hot


def save_history(history, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(history, ensure_ascii=False, separators=(",", ":")))
    tmp.replace(path)
