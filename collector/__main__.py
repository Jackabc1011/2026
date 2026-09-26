"""Run the collector: python -m collector [--config config.yaml] [--demo] [--loop MINUTES]"""
import argparse
import json
import os
import time
from pathlib import Path

import yaml

from . import http
from .distill import distill
from .extract import build_alias_patterns
from .payload import build_payload
from .sources import market, wallets, x_kol

def collect(config):
    http.STATUS.clear()
    ignore = config.get("ignore_symbols", [])
    lookback = config.get("lookback_hours", 24)
    alias_patterns = build_alias_patterns(config.get("aliases"))

    # ---- market
    fng = None
    try:
        fng = market.fear_greed()
        http.STATUS["fear_greed"] = {"ok": True, "count": 1, "error": None}
    except Exception as e:  # noqa: BLE001
        http.STATUS["fear_greed"] = {"ok": False, "count": 0, "error": str(e)[:300]}
    tickers = http.run_source("binance", market.binance_tickers)
    gainers = market.binance_gainers(tickers)
    cg = http.run_source("coingecko", market.coingecko_trending)
    boosts = http.run_source("dexscreener", market.dex_boosts)

    # ---- KOL tweets
    kols = config.get("kols", [])
    max_per = config.get("max_tweets_per_kol", 20)
    if os.environ.get("X_BEARER_TOKEN"):
        tweets = http.run_source("x", x_kol.fetch_x_api, kols, os.environ["X_BEARER_TOKEN"],
                                 lookback, max_per, alias_patterns, ignore)
    elif config.get("rss_template"):
        tweets = http.run_source("x", x_kol.fetch_rss, kols, config["rss_template"],
                                 lookback, max_per, alias_patterns, ignore)
    else:
        tweets = []
        http.skip_source("x", "未配置 X_BEARER_TOKEN 或 rss_template")

    # ---- smart money
    if config.get("wallets"):
        buys = http.run_source("wallets", wallets.fetch_wallet_buys, config["wallets"], lookback,
                               os.environ.get("ETHERSCAN_API_KEY"), os.environ.get("HELIUS_API_KEY"), ignore)
    else:
        buys = []
        http.skip_source("wallets", "config.yaml 未配置钱包")

    # ---- resolve contract addresses (tweets + Solana buys) to symbols & markets
    quotes = list(tickers)
    addrs = [a for t in tweets for a in t["addresses"]] + [b["address"] for b in buys if not b.get("symbol")]
    if addrs:
        resolved = http.run_source("dex_resolve", market.dex_lookup_addresses, addrs[:120])
        resolved = resolved or {}
        for t in tweets:
            for a in t["addresses"]:
                q = resolved.get(a.lower())
                if q and q["symbol"] not in t["symbols"]:
                    t["symbols"].append(q["symbol"])
        for b in buys:
            q = resolved.get((b.get("address") or "").lower())
            if q and not b.get("symbol"):
                b["symbol"] = q["symbol"]
        quotes += list(resolved.values())

    # ---- look up markets for symbols that are mentioned / bought but not yet priced
    priced = {q["symbol"] for q in quotes} | {q["symbol"] for q in boosts}
    wanted = [s for t in tweets for s in t["symbols"]] + [b["symbol"] for b in buys if b.get("symbol")]
    missing = [s for s in dict.fromkeys(wanted) if s not in priced][:15]
    for s in missing:
        try:
            q = market.dex_search_symbol(s)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] dex search {s}: {e}")
            continue
        if q:
            quotes.append(q)

    opportunities = distill(tweets, buys, quotes, cg + boosts + gainers, config)
    return build_payload(config, fng, tickers, cg, boosts, gainers, tweets, buys, opportunities)


def write(payload, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
    tmp.replace(path)
    ok = [k for k, v in payload["sources"].items() if v.get("ok")]
    print(f"wrote {path}: {len(payload['opportunities'])} opportunities, "
          f"{len(payload['kol_feed'])} tweets, sources ok: {', '.join(ok) or 'none'}")


def main():
    ap = argparse.ArgumentParser(description="Alpha 雷达数据采集")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--out", help="输出 JSON 路径（默认取 config.output）")
    ap.add_argument("--demo", action="store_true", help="不联网，用模拟数据生成面板")
    ap.add_argument("--loop", type=float, metavar="MINUTES", help="每隔 N 分钟重复采集")
    args = ap.parse_args()

    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    out = args.out or config.get("output", "docs/data/latest.json")
    while True:
        if args.demo:
            from .demo import demo_payload
            payload = demo_payload(config)
        else:
            payload = collect(config)
        write(payload, out)
        if not args.loop:
            break
        time.sleep(args.loop * 60)


if __name__ == "__main__":
    main()
