"""Offline demo data so the dashboard can be previewed without any network / API key.

All KOLs, tickers, wallets and numbers here are fictional.
"""
import random
from datetime import datetime, timedelta, timezone

from . import http
from .distill import distill
from .payload import build_payload

DEMO_KOLS = [
    ("demo_exchange", "示例·交易所创始人", "交易所", 1.0),
    ("demo_celebrity", "示例·科技名人", "名人", 1.0),
    ("demo_onchain", "示例·链上侦探", "链上", 0.9),
    ("demo_trader", "示例·Meme 交易员", "交易员", 0.8),
    ("demo_media", "示例·行业媒体", "媒体", 0.6),
]
DEMO_TOKENS = [  # symbol, chain, price, 1h, 24h, liquidity, fdv, age_hours
    ("FROGX", "solana", 0.0123, 8.2, 64.0, 820_000, 12_000_000, 40),
    ("NOVA", "base", 1.84, 2.1, 18.5, 3_400_000, 90_000_000, 900),
    ("KITTY", "solana", 0.00041, -3.5, 210.0, 95_000, 41_000_000, 20),
    ("ORBIT", "eth", 12.7, 0.6, 7.9, 9_800_000, 400_000_000, 5000),
    ("BLOOM", "bsc", 0.337, 4.4, 26.0, 1_300_000, 30_000_000, 300),
    ("ZEPH", "arbitrum", 0.92, -1.2, -6.0, 2_100_000, 60_000_000, 3000),
]
TEMPLATES = [
    "Building quietly. ${sym} community is on fire 🔥",
    "链上看到大户持续吸筹 ${sym}，过去 6 小时净流入明显",
    "${sym} looks interesting here, not financial advice",
    "新叙事：{name} 生态资金加速流入，${sym} 领涨",
    "Watching ${sym} and $BTC today",
]


def demo_payload(config):
    rnd = random.Random(42)
    now = datetime.now(timezone.utc)
    iso = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731

    quotes, attention = [], []
    for i, (sym, chain, price, c1, c24, liq, fdv, age) in enumerate(DEMO_TOKENS):
        q = {"symbol": sym, "name": sym.title(), "chain": chain, "address": f"Demo{sym}Address{i}",
             "price": price, "change_1h": c1, "change_24h": c24, "volume_24h": liq * rnd.uniform(1, 6),
             "liquidity": liq, "fdv": fdv, "pair_created_at": (now - timedelta(hours=age)).timestamp() * 1000,
             "url": "https://dexscreener.com", "source": "dexscreener"}
        quotes.append(q)
        if i in (0, 2, 4):
            attention.append({**q, "source": "dex_boost", "rank": i + 1, "value": 500 - i * 60})
        if i in (0, 1, 3):
            attention.append({**q, "source": "coingecko", "rank": i + 2})
    tickers = [
        {"symbol": "BTC", "name": "BTC", "price": 100000.0, "change_24h": 1.8, "change_1h": None, "volume_24h": 2e9, "source": "binance"},
        {"symbol": "ETH", "name": "ETH", "price": 4000.0, "change_24h": 3.1, "change_1h": None, "volume_24h": 1e9, "source": "binance"},
        {"symbol": "SOL", "name": "SOL", "price": 200.0, "change_24h": 5.6, "change_1h": None, "volume_24h": 5e8, "source": "binance"},
        {"symbol": "BNB", "name": "BNB", "price": 900.0, "change_24h": 0.9, "change_1h": None, "volume_24h": 3e8, "source": "binance"},
        {"symbol": "DOGE", "name": "DOGE", "price": 0.25, "change_24h": 9.4, "change_1h": None, "volume_24h": 4e8, "source": "binance"},
    ]
    quotes += tickers
    gainers = [{**t, "source": "binance_gainer", "rank": i + 1, "value": t["change_24h"]}
               for i, t in enumerate(sorted(tickers, key=lambda t: -t["change_24h"]))]

    tweets = []
    picks = ["FROGX", "FROGX", "NOVA", "KITTY", "ORBIT", "FROGX", "BLOOM", "NOVA", "DOGE", "KITTY"]
    for i, sym in enumerate(picks):
        handle, name, tag, weight = DEMO_KOLS[i % len(DEMO_KOLS)]
        text = TEMPLATES[i % len(TEMPLATES)].replace("{sym}", sym).replace("{name}", sym.title())
        syms = [sym] + (["BTC"] if "$BTC" in text else [])
        tweets.append({"handle": handle, "name": name, "tag": tag, "weight": weight, "id": str(i),
                       "text": text, "url": "https://x.com", "created_at": iso(now - timedelta(minutes=37 * i + 5)),
                       "engagement": rnd.randint(50, 20000), "symbols": syms, "addresses": []})

    buys = []
    for i, (sym, wallet) in enumerate([("FROGX", "A"), ("FROGX", "B"), ("NOVA", "A"), ("BLOOM", "C"), ("FROGX", "C")]):
        buys.append({"label": f"示例聪明钱 {wallet}", "wallet": f"DemoWallet{wallet}", "chain": "solana",
                     "weight": 1.0, "symbol": sym, "address": f"Demo{sym}", "amount": rnd.randint(10_000, 900_000),
                     "time": iso(now - timedelta(minutes=50 * i + 12)), "tx_url": "https://solscan.io"})

    http.STATUS.clear()
    for name in ("binance", "coingecko", "dexscreener", "x", "wallets", "fear_greed"):
        http.STATUS[name] = {"ok": True, "count": 0, "error": None, "demo": True}

    opps = distill(tweets, buys, quotes, attention + gainers, config, now=now)
    cg = [a for a in attention if a["source"] == "coingecko"]
    boosts = [a for a in attention if a["source"] == "dex_boost"]
    cfg = {**config, "brief": {"enabled": False}}
    payload = build_payload(cfg, {"value": 63, "label": "Greed"}, tickers, cg, boosts, gainers,
                            tweets, buys, opps, demo=True)
    payload["brief"] = {"model": "demo", "text": (
        "**市场情绪**：偏贪婪（示例数据）。\n\n"
        "**热点叙事**\n- Solana Meme 继续吸金：FROGX 同时出现 KOL 提及、3 个聪明钱买入和热搜。\n"
        "- Base 生态 NOVA 获多位 KOL 讨论，涨幅温和。\n\n"
        "**值得关注**\n- FROGX：多源共振最强；风险是上线不足 2 天。\n"
        "- NOVA：社交+链上双信号；风险是 FDV 偏高。\n\n"
        "**注意**：KITTY 24h 已涨 210% 且流动性低，偏向追高/付费推广。")}
    return payload


def demo_history(payload, points=23):
    """Fictional past snapshots so the demo shows deltas, new entries and trend lines."""
    rnd = random.Random(7)
    now = datetime.fromisoformat(payload["generated_at"].replace("Z", "+00:00"))
    shape = {"FROGX": (35, "rise"), "KITTY": (70, "fall"), "BLOOM": (60, "flat")}
    snaps = []
    for i in range(points, 0, -1):
        t = (now - timedelta(minutes=30 * i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        progress = 1 - i / points
        scores, ratings = {}, {}
        for o in payload["opportunities"]:
            sym = o["symbol"]
            if sym == "NOVA":
                continue  # brand-new this run
            start, kind = shape.get(sym, (o["score"], "flat"))
            if kind == "rise":
                s = start + (o["score"] - 8 - start) * progress
            elif kind == "fall":
                s = start + (o["score"] - start) * progress
            else:
                s = o["score"]
            scores[sym] = round(max(0, s + rnd.uniform(-3, 3)), 1)
            ratings[sym] = "观察" if scores[sym] >= 35 else "噪音"
        snaps.append({"t": t, "scores": scores, "ratings": ratings})
    return {"snapshots": snaps}
