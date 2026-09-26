import unittest
from datetime import datetime, timedelta, timezone

from collector.distill import distill, momentum_score
from collector.extract import build_alias_patterns, extract_tokens
from collector.sources import market, wallets, x_kol

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
ISO = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
CONFIG = {"half_life_hours": 6, "ignore_symbols": ["USDT"], "scoring": {"top_n": 10}}


class ExtractTest(unittest.TestCase):
    def test_cashtags_aliases_addresses(self):
        pats = build_alias_patterns({"DOGE": ["dogecoin", "狗狗币"], "BTC": ["bitcoin"]})
        text = ("Buying $pepe and $USDT, 狗狗币 to the moon. https://x.com/$FAKE "
                "CA 0x6982508145454Ce325dDbE47a25d4ec3d2311933 and 7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr")
        syms, addrs = extract_tokens(text, pats, ignore=["USDT"])
        self.assertEqual(syms, ["PEPE", "DOGE"])
        self.assertIn("0x6982508145454Ce325dDbE47a25d4ec3d2311933", addrs)
        self.assertIn("7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr", addrs)

    def test_alias_needs_word_boundary(self):
        pats = build_alias_patterns({"SOL": ["solana"]})
        self.assertEqual(extract_tokens("solanart is not solana?", pats)[0], ["SOL"])
        self.assertEqual(extract_tokens("solanart only", pats)[0], [])


class ParserTest(unittest.TestCase):
    def test_x_timeline(self):
        data = {"data": [{"id": "1", "text": "short", "created_at": "2026-09-26T10:00:00.000Z",
                          "note_tweet": {"text": "long form $DOGE"},
                          "public_metrics": {"like_count": 10, "retweet_count": 2, "reply_count": 1, "quote_count": 0}}]}
        kol = {"handle": "elonmusk", "name": "Elon", "weight": 1.0, "tag": "名人"}
        [t] = x_kol.parse_x_timeline(data, kol)
        self.assertEqual(t["symbols"], ["DOGE"])
        self.assertEqual(t["engagement"], 15)
        self.assertEqual(t["url"], "https://x.com/elonmusk/status/1")

    def test_rss(self):
        xml = """<rss><channel>
          <item><title>t</title><description>&lt;p&gt;Long $BNB &amp;amp; chill&lt;/p&gt;</description>
            <link>https://x.com/cz_binance/status/99</link><pubDate>Sat, 26 Sep 2026 11:00:00 GMT</pubDate></item>
          <item><description>old $ETH</description><link>https://x.com/cz_binance/status/1</link>
            <pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate></item></channel></rss>"""
        out = x_kol.parse_rss(xml, {"handle": "cz_binance"}, NOW - timedelta(hours=24))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["symbols"], ["BNB"])
        self.assertEqual(out[0]["text"], "Long $BNB & chill")
        self.assertEqual(out[0]["id"], "99")

    def test_binance(self):
        rows = [
            {"symbol": "PEPEUSDT", "lastPrice": "0.00001", "priceChangePercent": "12.5", "quoteVolume": "90000000"},
            {"symbol": "BTCUPUSDT", "lastPrice": "1", "priceChangePercent": "50", "quoteVolume": "90000000"},
            {"symbol": "ETHBTC", "lastPrice": "0.03", "priceChangePercent": "1", "quoteVolume": "90000000"},
            {"symbol": "TINYUSDT", "lastPrice": "1", "priceChangePercent": "90", "quoteVolume": "1000"},
        ]
        out = market.parse_binance_tickers(rows)
        self.assertEqual([t["symbol"] for t in out], ["PEPE"])
        self.assertEqual(market.binance_gainers(out)[0]["rank"], 1)

    def test_dex_best_pair(self):
        pairs = [
            {"chainId": "solana", "baseToken": {"address": "Mint1", "symbol": "wif"}, "liquidity": {"usd": 10}, "priceUsd": "1"},
            {"chainId": "solana", "baseToken": {"address": "Mint1", "symbol": "wif"}, "liquidity": {"usd": 999},
             "priceUsd": "2", "priceChange": {"h1": 3, "h24": -4}, "volume": {"h24": 5}},
        ]
        q = market.best_pairs_by_token(pairs)["mint1"]
        self.assertEqual((q["symbol"], q["price"], q["change_24h"], q["liquidity"]), ("WIF", 2.0, -4.0, 999.0))

    def test_coingecko(self):
        data = {"coins": [{"item": {"id": "pepe", "name": "Pepe", "symbol": "pepe", "market_cap_rank": 30,
                                    "data": {"price": 0.1, "price_change_percentage_24h": {"usd": 5.5}}}}]}
        [c] = market.parse_coingecko_trending(data)
        self.assertEqual((c["symbol"], c["rank"], c["change_24h"]), ("PEPE", 1, 5.5))

    def test_etherscan_only_inbound_recent(self):
        me = "0xAbC0000000000000000000000000000000000001"
        recent = int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp())
        data = {"status": "1", "result": [
            {"to": me.lower(), "from": "0x1", "timeStamp": str(recent), "tokenSymbol": "PEPE",
             "tokenDecimal": "18", "value": str(5 * 10 ** 18), "contractAddress": "0xpepe", "hash": "0xh"},
            {"to": "0x2", "from": me.lower(), "timeStamp": str(recent), "tokenSymbol": "LINK",
             "tokenDecimal": "18", "value": "1", "contractAddress": "0xlink", "hash": "0xh2"},
            {"to": me.lower(), "from": "0x1", "timeStamp": str(recent), "tokenSymbol": "USDT",
             "tokenDecimal": "6", "value": "1", "contractAddress": "0xusdt", "hash": "0xh3"},
        ]}
        w = {"address": me, "chain": "eth", "label": "A"}
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        [b] = wallets.parse_etherscan(data, w, cutoff, ignore=["USDT"])
        self.assertEqual((b["symbol"], b["amount"]), ("PEPE", 5.0))
        self.assertTrue(b["tx_url"].startswith("https://etherscan.io/tx/"))

    def test_helius_skips_quote_mints(self):
        me = "Wallet1"
        ts = int(datetime.now(timezone.utc).timestamp())
        data = [{"signature": "sig", "timestamp": ts, "tokenTransfers": [
            {"toUserAccount": me, "mint": "MemeMint", "tokenAmount": 1000},
            {"toUserAccount": me, "mint": "So11111111111111111111111111111111111111112", "tokenAmount": 1},
            {"toUserAccount": "someone", "mint": "Other", "tokenAmount": 1}]}]
        out = wallets.parse_helius(data, {"address": me, "label": "S"}, datetime.now(timezone.utc) - timedelta(hours=1))
        self.assertEqual([b["address"] for b in out], ["MemeMint"])


class DistillTest(unittest.TestCase):
    def tweet(self, handle, sym, minutes_ago, weight=1.0):
        return {"handle": handle, "name": handle, "weight": weight, "symbols": [sym], "engagement": 100,
                "created_at": ISO(NOW - timedelta(minutes=minutes_ago)), "text": f"${sym}", "url": "u"}

    def quote(self, sym, c24, liq=5_000_000, age_h=5000):
        return {"symbol": sym, "name": sym, "chain": "solana", "address": sym, "price": 1.0, "change_1h": 2,
                "change_24h": c24, "volume_24h": liq, "liquidity": liq, "fdv": liq * 10,
                "pair_created_at": (NOW - timedelta(hours=age_h)).timestamp() * 1000, "url": "u", "source": "dexscreener"}

    def test_confluence_beats_single_source(self):
        tweets = [self.tweet("a", "AAA", 10), self.tweet("b", "AAA", 30), self.tweet("c", "BBB", 10),
                  self.tweet("d", "BBB", 20), self.tweet("e", "BBB", 40)]
        buys = [{"wallet": "w1", "weight": 1, "symbol": "AAA", "time": ISO(NOW - timedelta(minutes=5))},
                {"wallet": "w2", "weight": 1, "symbol": "AAA", "time": ISO(NOW - timedelta(minutes=50))}]
        quotes = [self.quote("AAA", 20), self.quote("BBB", 20)]
        attention = [{"symbol": "AAA", "source": "coingecko", "rank": 2}]
        res = {r["symbol"]: r for r in distill(tweets, buys, quotes, attention, CONFIG, now=NOW)}
        self.assertGreater(res["AAA"]["score"], res["BBB"]["score"])
        self.assertEqual(res["AAA"]["confluence"], 3)
        self.assertEqual(res["AAA"]["rating"], "重点关注")

    def test_recency_decay(self):
        fresh = distill([self.tweet("a", "NEW", 5)], [], [], [], CONFIG, now=NOW)[0]
        stale = distill([self.tweet("a", "OLD", 18 * 60)], [], [], [], CONFIG, now=NOW)[0]
        self.assertGreater(fresh["components"]["social"], stale["components"]["social"] * 3)

    def test_risks_block_top_rating(self):
        tweets = [self.tweet(h, "RUG", 5) for h in "abc"]
        buys = [{"wallet": "w", "weight": 1, "symbol": "RUG", "time": ISO(NOW)}]
        quotes = [self.quote("RUG", 300, liq=20_000, age_h=3)]
        [r] = distill(tweets, buys, quotes, [{"symbol": "RUG", "source": "dex_boost", "rank": 1}], CONFIG, now=NOW)
        self.assertGreaterEqual(len(r["risks"]), 3)
        self.assertNotEqual(r["rating"], "重点关注")

    def test_ignored_and_signal_less_tokens_dropped(self):
        res = distill([self.tweet("a", "USDT", 5)], [], [self.quote("ZZZ", 50)], [], CONFIG, now=NOW)
        self.assertEqual(res, [])

    def test_momentum(self):
        self.assertEqual(momentum_score({"change_24h": -30, "change_1h": -5}), 0)
        self.assertGreater(momentum_score({"change_24h": 60, "change_1h": 10}), 70)


if __name__ == "__main__":
    unittest.main()
