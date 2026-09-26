"""Free, key-less market sources: CoinGecko, DexScreener, Binance, Fear & Greed.

Every function returns normalized records:
  quote     {symbol, name, chain, address, price, change_1h, change_24h, volume_24h,
             liquidity, fdv, pair_created_at, url, source}
  attention {symbol, name, source, rank, value, chain, address, url}
"""
from ..http import get_json

COINGECKO = "https://api.coingecko.com/api/v3"
DEXSCREENER = "https://api.dexscreener.com"
# data-api.binance.vision serves public market data and is reachable from US
# runners (api.binance.com returns HTTP 451 there).
BINANCE = "https://data-api.binance.vision/api/v3"

LEVERAGED_SUFFIXES = ("UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT")


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- CoinGecko
def coingecko_trending():
    data = get_json(f"{COINGECKO}/search/trending")
    return parse_coingecko_trending(data)


def parse_coingecko_trending(data):
    out = []
    for i, c in enumerate(data.get("coins", [])):
        item = c.get("item", {})
        d = item.get("data") or {}
        out.append({
            "symbol": (item.get("symbol") or "").upper(),
            "name": item.get("name"),
            "source": "coingecko",
            "rank": i + 1,
            "value": item.get("market_cap_rank"),
            "price": _f(d.get("price")),
            "change_24h": _f((d.get("price_change_percentage_24h") or {}).get("usd")),
            "url": f"https://www.coingecko.com/coins/{item.get('id')}",
        })
    return out


# -------------------------------------------------------------- DexScreener
def pair_to_quote(p):
    base = p.get("baseToken") or {}
    return {
        "symbol": (base.get("symbol") or "").upper(),
        "name": base.get("name"),
        "chain": p.get("chainId"),
        "address": base.get("address"),
        "price": _f(p.get("priceUsd")),
        "change_1h": _f((p.get("priceChange") or {}).get("h1")),
        "change_24h": _f((p.get("priceChange") or {}).get("h24")),
        "volume_24h": _f((p.get("volume") or {}).get("h24")),
        "liquidity": _f((p.get("liquidity") or {}).get("usd")),
        "fdv": _f(p.get("fdv")),
        "pair_created_at": p.get("pairCreatedAt"),
        "url": p.get("url"),
        "source": "dexscreener",
    }


def best_pairs_by_token(pairs):
    """Keep the most liquid pair for each base token address."""
    best = {}
    for p in pairs or []:
        addr = ((p.get("baseToken") or {}).get("address") or "").lower()
        if not addr:
            continue
        liq = _f((p.get("liquidity") or {}).get("usd")) or 0
        cur = best.get(addr)
        if cur is None or liq > (_f((cur.get("liquidity") or {}).get("usd")) or 0):
            best[addr] = p
    return {a: pair_to_quote(p) for a, p in best.items()}


def dex_lookup_addresses(addresses):
    """Resolve token contract addresses (any chain) -> {address_lower: quote}."""
    addresses = list(dict.fromkeys(a for a in addresses if a))
    result = {}
    for i in range(0, len(addresses), 30):
        chunk = addresses[i:i + 30]
        data = get_json(f"{DEXSCREENER}/latest/dex/tokens/{','.join(chunk)}")
        result.update(best_pairs_by_token(data.get("pairs")))
    return result


def dex_search_symbol(symbol):
    """Best (most liquid) pair whose base symbol equals `symbol`, or None."""
    data = get_json(f"{DEXSCREENER}/latest/dex/search", params={"q": symbol})
    pairs = [p for p in data.get("pairs") or []
             if ((p.get("baseToken") or {}).get("symbol") or "").upper() == symbol.upper()]
    quotes = best_pairs_by_token(pairs)
    if not quotes:
        return None
    return max(quotes.values(), key=lambda q: q["liquidity"] or 0)


def dex_boosts(limit=30):
    boosts = get_json(f"{DEXSCREENER}/token-boosts/top/v1")[:limit]
    quotes = dex_lookup_addresses([b.get("tokenAddress") for b in boosts])
    out = []
    for i, b in enumerate(boosts):
        q = quotes.get((b.get("tokenAddress") or "").lower())
        if not q:
            continue
        out.append({**q, "source": "dex_boost", "rank": i + 1,
                    "value": b.get("totalAmount"), "url": b.get("url") or q["url"]})
    return out


# ------------------------------------------------------------------ Binance
def binance_tickers():
    return parse_binance_tickers(get_json(f"{BINANCE}/ticker/24hr"))


def parse_binance_tickers(rows, min_quote_volume=5_000_000):
    out = []
    for r in rows:
        s = r.get("symbol", "")
        if not s.endswith("USDT") or s.endswith(LEVERAGED_SUFFIXES):
            continue
        vol = _f(r.get("quoteVolume")) or 0
        if vol < min_quote_volume:
            continue
        out.append({
            "symbol": s[:-4],
            "name": s[:-4],
            "chain": "binance",
            "address": None,
            "price": _f(r.get("lastPrice")),
            "change_1h": None,
            "change_24h": _f(r.get("priceChangePercent")),
            "volume_24h": vol,
            "liquidity": None,
            "fdv": None,
            "pair_created_at": None,
            "url": f"https://www.binance.com/zh-CN/trade/{s[:-4]}_USDT",
            "source": "binance",
        })
    return out


def binance_gainers(tickers, n=20):
    ranked = sorted((t for t in tickers if t["change_24h"] is not None),
                    key=lambda t: t["change_24h"], reverse=True)[:n]
    return [{**t, "source": "binance_gainer", "rank": i + 1, "value": t["change_24h"]}
            for i, t in enumerate(ranked)]


# ------------------------------------------------------------- Fear & Greed
def fear_greed():
    d = get_json("https://api.alternative.me/fng/", params={"limit": 1})["data"][0]
    return {"value": int(d["value"]), "label": d["value_classification"]}
