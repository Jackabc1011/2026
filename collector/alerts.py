"""Push alerts when a token is newly rated 重点关注.

Channels (all optional, via environment variables):
  TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID   Telegram bot message
  ALERT_WEBHOOK_URL                       Slack / Discord / 飞书 / 钉钉 incoming webhook (auto-detected by host)
"""
import os

from .http import SESSION


def format_alert(o, dashboard_url=None):
    m = o.get("market") or {}
    delta = f"（{o['delta']:+.0f}）" if o.get("delta") is not None else ""
    lines = [f"🚨 Alpha 雷达：{o['symbol']} 升级为「重点关注」",
             f"综合分 {o['score']:.0f}{delta} · 共振 {o['confluence']}/4"]
    if m.get("price") is not None:
        ch = f" · 24h {m['change_24h']:+.1f}%" if m.get("change_24h") is not None else ""
        lines.append(f"价格 ${m['price']:.6g}{ch}")
    lines += [f"✅ {s}" for s in o.get("signals", [])[:4]]
    lines += [f"⚠️ {r}" for r in o.get("risks", [])]
    if m.get("url"):
        lines.append(m["url"])
    if dashboard_url:
        lines.append(f"面板：{dashboard_url}")
    lines.append("仅供参考，不构成投资建议")
    return "\n".join(lines)


def send_alerts(opportunities, env=None):
    env = env if env is not None else os.environ
    if not opportunities:
        return 0
    tg_token, tg_chat = env.get("TELEGRAM_BOT_TOKEN"), env.get("TELEGRAM_CHAT_ID")
    hook = env.get("ALERT_WEBHOOK_URL")
    if not ((tg_token and tg_chat) or hook):
        print(f"[info] {len(opportunities)} 个新重点关注，未配置提醒渠道")
        return 0

    sent = 0
    for o in opportunities[:5]:  # cap per run to avoid spam
        text = format_alert(o, env.get("DASHBOARD_URL"))
        try:
            if tg_token and tg_chat:
                r = SESSION.post(f"https://api.telegram.org/bot{tg_token}/sendMessage", timeout=15,
                                 json={"chat_id": tg_chat, "text": text, "disable_web_page_preview": True})
                r.raise_for_status()
            if hook:
                r = SESSION.post(hook, json=webhook_body(hook, text), timeout=15)
                r.raise_for_status()
            sent += 1
        except Exception as e:  # noqa: BLE001 - alerts must never break collection
            msg = str(e).replace(tg_token or "\0", "***").replace(hook or "\0", "<webhook>")
            print(f"[warn] alert {o['symbol']} failed: {msg[:200]}")
    return sent


def webhook_body(hook, text):
    """Each chat app wants a different JSON shape; pick by the webhook host."""
    if "feishu" in hook or "larksuite" in hook:
        return {"msg_type": "text", "content": {"text": text}}
    if "dingtalk" in hook:
        return {"msgtype": "text", "text": {"content": text}}
    if "discord" in hook:
        return {"content": text[:2000]}
    return {"text": text}  # Slack and most generic webhooks
