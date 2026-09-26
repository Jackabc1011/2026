"""Assemble the JSON the dashboard reads."""
from datetime import datetime, timezone

from . import http
from .brief import generate_brief

MAJORS = ("BTC", "ETH", "SOL", "BNB", "DOGE")


def build_payload(config, fng, tickers, cg, boosts, gainers, tweets, buys, opportunities, demo=False):
    by_sym = {t["symbol"]: t for t in tickers}
    majors = [{"symbol": s, "price": by_sym[s]["price"], "change_24h": by_sym[s]["change_24h"]}
              for s in MAJORS if s in by_sym]
    feed = sorted(tweets, key=lambda t: t.get("created_at") or "", reverse=True)[:120]
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "demo": demo,
        "lookback_hours": config.get("lookback_hours", 24),
        "sources": dict(http.STATUS),
        "market": {"fear_greed": fng, "majors": majors},
        "opportunities": opportunities,
        "kol_feed": [{k: t[k] for k in ("handle", "name", "tag", "text", "url", "created_at",
                                          "engagement", "symbols")} for t in feed],
        "smart_money": sorted(buys, key=lambda b: b.get("time") or "", reverse=True)[:120],
        "trending": {
            "coingecko": cg[:15],
            "dex_boosts": boosts[:15],
            "binance_gainers": gainers[:15],
        },
        "brief": generate_brief(feed, opportunities, config),
    }
