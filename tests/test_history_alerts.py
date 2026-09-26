import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

from collector.alerts import format_alert, send_alerts, webhook_body
from collector.history import apply_history


def payload(t, scores):
    return {"generated_at": t, "opportunities": [
        {"symbol": s, "score": sc, "rating": r, "confluence": 3, "signals": ["KOL 提及"], "risks": [],
         "market": {"price": 1.23, "change_24h": 5.0, "url": "https://dexscreener.com/x"}}
        for s, (sc, r) in scores.items()]}


class HistoryTest(unittest.TestCase):
    def test_first_run_has_no_deltas_or_alerts(self):
        p = payload("2026-09-26T10:00:00Z", {"AAA": (70, "重点关注")})
        hist, hot = apply_history(p, {"snapshots": []})
        o = p["opportunities"][0]
        self.assertEqual((o["delta"], o["is_new"], hot), (None, False, []))
        self.assertEqual(len(hist["snapshots"]), 1)

    def test_delta_new_and_newly_hot(self):
        h1, _ = apply_history(payload("2026-09-26T10:00:00Z", {"AAA": (40, "观察"), "BBB": (60, "重点关注")}),
                              {"snapshots": []})
        p = payload("2026-09-26T10:30:00Z", {"AAA": (62, "重点关注"), "BBB": (58, "重点关注"), "CCC": (20, "噪音")})
        h2, hot = apply_history(p, h1)
        by = {o["symbol"]: o for o in p["opportunities"]}
        self.assertEqual(by["AAA"]["delta"], 22)
        self.assertTrue(by["CCC"]["is_new"])
        self.assertEqual(by["AAA"]["trend"], [40, 62])
        self.assertEqual(by["AAA"]["first_seen"], "2026-09-26T10:00:00Z")
        self.assertEqual([o["symbol"] for o in hot], ["AAA"])  # BBB was already 重点关注
        self.assertEqual(len(h2["snapshots"]), 2)

    def test_same_timestamp_is_replaced_and_capped(self):
        hist = {"snapshots": [{"t": f"2026-09-26T{h:02d}:00:00Z", "scores": {}, "ratings": {}} for h in range(10)]}
        p = payload("2026-09-26T05:00:00Z", {"AAA": (10, "噪音")})
        new, _ = apply_history(p, hist, max_snapshots=3)
        self.assertEqual([s["t"] for s in new["snapshots"]],
                         ["2026-09-26T03:00:00Z", "2026-09-26T04:00:00Z", "2026-09-26T05:00:00Z"])

    def test_empty_run_not_recorded(self):
        h1, _ = apply_history(payload("2026-09-26T10:00:00Z", {"AAA": (60, "重点关注")}), {"snapshots": []})
        h2, _ = apply_history(payload("2026-09-26T10:30:00Z", {}), h1)
        p = payload("2026-09-26T11:00:00Z", {"AAA": (61, "重点关注")})
        _, hot = apply_history(p, h2)
        self.assertEqual(len(h2["snapshots"]), 1)
        self.assertEqual(hot, [])
        self.assertFalse(p["opportunities"][0]["is_new"])

    def test_flapping_token_alerts_once_within_cooldown(self):
        h, hot = apply_history(payload("2026-09-26T10:00:00Z", {"AAA": (40, "观察")}), {"snapshots": []})
        h, hot = apply_history(payload("2026-09-26T10:30:00Z", {"AAA": (60, "重点关注")}), h)
        self.assertEqual([o["symbol"] for o in hot], ["AAA"])
        h, hot = apply_history(payload("2026-09-26T11:00:00Z", {"AAA": (40, "观察")}), h)   # a source failed
        h, hot = apply_history(payload("2026-09-26T11:30:00Z", {"AAA": (60, "重点关注")}), h)
        self.assertEqual(hot, [])                                                          # still cooling down
        h, hot = apply_history(payload("2026-09-27T00:00:00Z", {"AAA": (40, "观察")}), h)
        h, hot = apply_history(payload("2026-09-27T00:30:00Z", {"AAA": (60, "重点关注")}), h)
        self.assertEqual([o["symbol"] for o in hot], ["AAA"])                              # 13h later: alert again


class AlertTest(unittest.TestCase):
    def test_format(self):
        o = payload("t", {"AAA": (70, "重点关注")})["opportunities"][0] | {"delta": 12.0}
        text = format_alert(o, "https://me.github.io/radar/")
        self.assertIn("AAA 升级为「重点关注」", text)
        self.assertIn("（+12）", text)
        self.assertIn("面板：https://me.github.io/radar/", text)

    def test_webhook_shapes(self):
        self.assertEqual(webhook_body("https://open.feishu.cn/x", "hi"), {"msg_type": "text", "content": {"text": "hi"}})
        self.assertEqual(webhook_body("https://oapi.dingtalk.com/x", "hi"), {"msgtype": "text", "text": {"content": "hi"}})
        self.assertEqual(webhook_body("https://discord.com/api/webhooks/x", "hi"), {"content": "hi"})
        self.assertEqual(webhook_body("https://hooks.slack.com/x", "hi"), {"text": "hi"})

    def test_no_channel_sends_nothing(self):
        o = payload("t", {"AAA": (70, "重点关注")})["opportunities"][0]
        self.assertEqual(send_alerts([o], env={}), 0)

    def test_telegram_send_and_token_redacted_on_error(self):
        o = payload("t", {"AAA": (70, "重点关注")})["opportunities"][0]
        env = {"TELEGRAM_BOT_TOKEN": "123:SECRET", "TELEGRAM_CHAT_ID": "42"}
        with mock.patch("collector.alerts.SESSION.post") as post:
            self.assertEqual(send_alerts([o], env=env), 1)
            url, = post.call_args.args
            self.assertEqual(url, "https://api.telegram.org/bot123:SECRET/sendMessage")
            self.assertEqual(post.call_args.kwargs["json"]["chat_id"], "42")
        buf = io.StringIO()
        with mock.patch("collector.alerts.SESSION.post", side_effect=RuntimeError("bad url .../bot123:SECRET/x")), \
                redirect_stdout(buf):
            self.assertEqual(send_alerts([o], env=env), 0)
        self.assertNotIn("SECRET", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
