"""Distill raw signals into ranked token opportunities.

Four dimensions, each 0-100:
  social       KOL mentions, weighted by KOL trust, engagement and recency
  smart_money  distinct configured wallets buying, weighted by wallet trust and recency
  momentum     price action (24h / 1h change) of the most liquid market
  attention    trending lists: CoinGecko trending, DexScreener boosts, Binance gainers

composite = weighted sum x (1 + bonus x (active dimensions - 1)), capped at 100,
then reduced by 10% per risk flag (max 4).
A token only becomes "重点关注" when several independent dimensions agree.
"""
import math
from datetime import datetime, timezone

DIMENSIONS = ("social", "smart_money", "momentum", "attention")


def parse_time(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def decay(ts, now, half_life_hours):
    t = parse_time(ts) if isinstance(ts, str) else ts
    if t is None:
        return 0.5
    age_h = max(0.0, (now - t).total_seconds() / 3600)
    return 0.5 ** (age_h / half_life_hours)


def saturate(raw, k):
    """Map an unbounded positive score to 0-100 (k = raw value that gives ~63)."""
    return 100 * (1 - math.exp(-raw / k)) if raw > 0 else 0.0


def _sig(x):
    return 1 / (1 + math.exp(-x))


def momentum_score(q):
    if not q:
        return 0.0
    c24, c1 = q.get("change_24h"), q.get("change_1h")
    if c24 is None and c1 is None:
        return 0.0
    parts, weights = [], []
    if c24 is not None:
        parts.append(_sig(c24 / 25))
        weights.append(0.6)
    if c1 is not None:
        parts.append(_sig(c1 / 6))
        weights.append(0.4)
    s = sum(p * w for p, w in zip(parts, weights)) / sum(weights)
    # 0.5 (flat) -> 0, strongly up -> 100; falling prices give 0
    return max(0.0, (s - 0.5) * 200)


class Token:
    def __init__(self, symbol):
        self.symbol = symbol
        self.name = None
        self.quotes = []
        self.mentions = []
        self.buys = []
        self.attention = []

    def best_quote(self):
        if not self.quotes:
            return None
        # Prefer the deepest market: CEX volume or DEX liquidity.
        return max(self.quotes, key=lambda q: (q.get("liquidity") or 0) + (q.get("volume_24h") or 0) * 0.1)


def distill(tweets, buys, quotes, attention, config, now=None):
    now = now or datetime.now(timezone.utc)
    sc = config.get("scoring", {})
    weights = sc.get("weights", {"social": 0.35, "smart_money": 0.30, "momentum": 0.20, "attention": 0.15})
    bonus = sc.get("confluence_bonus", 0.1)
    half_life = config.get("half_life_hours", 6)
    ignore = {s.upper() for s in config.get("ignore_symbols", [])}

    tokens: dict[str, Token] = {}

    def tok(symbol):
        symbol = (symbol or "").upper()
        if not symbol or symbol in ignore:
            return None
        if symbol not in tokens:
            tokens[symbol] = Token(symbol)
        return tokens[symbol]

    for q in quotes:
        t = tok(q.get("symbol"))
        if t:
            t.quotes.append(q)
            t.name = t.name or q.get("name")
    for a in attention:
        t = tok(a.get("symbol"))
        if t:
            t.attention.append(a)
            t.name = t.name or a.get("name")
            if a.get("price") is not None or a.get("liquidity") is not None:
                t.quotes.append(a)
    for tw in tweets:
        for s in tw.get("symbols", []):
            t = tok(s)
            if t:
                t.mentions.append(tw)
    for b in buys:
        t = tok(b.get("symbol"))
        if t:
            t.buys.append(b)

    results = []
    for t in tokens.values():
        if not (t.mentions or t.buys or t.attention):
            continue  # plain market data with no signal isn't an opportunity

        # --- social
        social_raw, kol_names = 0.0, {}
        for tw in t.mentions:
            eng = 1 + math.log10(1 + (tw.get("engagement") or 0)) / 4
            social_raw += tw["weight"] * decay(tw.get("created_at"), now, half_life) * eng
            kol_names[tw["handle"]] = tw["name"]
        social = saturate(social_raw, 1.2)

        # --- smart money: count each wallet once, at its most recent buy
        latest = {}
        for b in t.buys:
            cur = latest.get(b["wallet"])
            if cur is None or (b.get("time") or "") > (cur.get("time") or ""):
                latest[b["wallet"]] = b
        smart_raw = sum(b["weight"] * decay(b.get("time"), now, half_life) for b in latest.values())
        smart = saturate(smart_raw, 1.0)

        # --- momentum
        q = t.best_quote()
        momentum = momentum_score(q)

        # --- attention
        att_raw, att_signals = 0.0, []
        for a in t.attention:
            rank = a.get("rank") or 30
            if a["source"] == "coingecko":
                att_raw += max(0.2, 1 - (rank - 1) / 15)
                att_signals.append(f"CoinGecko 热搜 #{rank}")
            elif a["source"] == "dex_boost":
                att_raw += 0.4 * max(0.2, 1 - (rank - 1) / 30)  # paid promotion: discounted
                att_signals.append(f"DEX 推广榜 #{rank}（付费）")
            elif a["source"] == "binance_gainer":
                att_raw += 0.8 * max(0.2, 1 - (rank - 1) / 20)
                att_signals.append(f"币安涨幅榜 #{rank}")
        attention_score = saturate(att_raw, 0.8)

        comps = {"social": social, "smart_money": smart, "momentum": momentum, "attention": attention_score}
        active = [d for d in DIMENSIONS if comps[d] >= (40 if d == "momentum" else 10)]
        base = sum(weights.get(d, 0) * comps[d] for d in DIMENSIONS)
        composite = min(100.0, base * (1 + bonus * max(0, len(active) - 1)))

        signals = []
        if t.mentions:
            names = "、".join(list(kol_names.values())[:4])
            signals.append(f"KOL 提及：{names}（{len(t.mentions)} 条）")
        if latest:
            signals.append(f"聪明钱买入：{len(latest)} 个钱包")
        signals += att_signals
        if q and q.get("change_1h") is not None and q["change_1h"] >= 5:
            signals.append(f"1h 拉升 +{q['change_1h']:.1f}%")

        risks = risk_flags(t, q, sc, now)
        composite *= 1 - sc.get("risk_penalty", 0.1) * min(len(risks), 4)
        confluence = len(active)
        if composite >= 55 and confluence >= 3 and len(risks) <= 1:
            rating = "重点关注"
        elif composite >= 35 and confluence >= 2:
            rating = "观察"
        else:
            rating = "噪音"

        results.append({
            "symbol": t.symbol,
            "name": t.name or t.symbol,
            "score": round(composite, 1),
            "components": {k: round(v, 1) for k, v in comps.items()},
            "confluence": confluence,
            "rating": rating,
            "signals": signals,
            "risks": risks,
            "market": q and {k: q.get(k) for k in (
                "chain", "address", "price", "change_1h", "change_24h", "volume_24h",
                "liquidity", "fdv", "pair_created_at", "url", "source")},
            "mentions": [{k: tw.get(k) for k in ("handle", "name", "text", "url", "created_at", "engagement")}
                         for tw in sorted(t.mentions, key=lambda x: x.get("created_at") or "", reverse=True)[:6]],
            "buys": sorted(latest.values(), key=lambda b: b.get("time") or "", reverse=True),
        })

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[: sc.get("top_n", 40)]


def risk_flags(t, q, sc, now):
    risks = []
    if not q:
        return ["无行情数据，无法核实"]
    liq = q.get("liquidity")
    if q.get("source") != "binance" and liq is not None and liq < sc.get("min_liquidity_usd", 100_000):
        risks.append(f"流动性低（${liq:,.0f}）")
    created = q.get("pair_created_at")
    if created:
        age_h = (now.timestamp() * 1000 - created) / 3_600_000
        if age_h < sc.get("new_pair_hours", 72):
            risks.append(f"新币，上线 {age_h:.0f} 小时")
    if (q.get("change_24h") or 0) >= sc.get("overheated_change_24h", 80):
        risks.append(f"24h 已涨 {q['change_24h']:.0f}%，追高风险")
    if q.get("fdv") and liq and q["fdv"] / liq > 100:
        risks.append("FDV/流动性比过高，易被砸盘")
    if t.attention and not t.mentions and not t.buys and all(a["source"] == "dex_boost" for a in t.attention):
        risks.append("热度仅来自付费推广")
    return risks
