"""Optional: have Claude distill tweets + rankings into a short Chinese market brief."""
import json
import os

PROMPT = """你是一名加密货币研究员。下面是过去 {hours} 小时内：
1) 被跟踪 KOL（赵长鹏、马斯克、链上分析师等）的推文；
2) 按多源信号打分后的币种机会榜（含风险标记）。

请输出一份简洁的中文简报（Markdown，不超过 350 字），包含：
- **市场情绪**：一句话
- **热点叙事**：2~3 条，说明是哪些 KOL / 数据支撑
- **值得关注**：最多 3 个币种，每个一句理由 + 一句主要风险
- **注意**：点出明显的喊单、付费推广或追高风险

只根据给定数据作答，不要编造价格或事件；不构成投资建议。

<tweets>
{tweets}
</tweets>

<opportunities>
{opps}
</opportunities>"""


def generate_brief(tweets, opportunities, config):
    cfg = config.get("brief", {})
    if not cfg.get("enabled") or not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    import anthropic

    tw = [{"kol": t["name"], "time": t.get("created_at"), "text": t["text"][:400],
           "engagement": t.get("engagement")} for t in tweets[:60]]
    ops = [{k: o[k] for k in ("symbol", "score", "rating", "signals", "risks", "components")}
           for o in opportunities[:15]]
    client = anthropic.Anthropic()
    try:
        response = client.beta.messages.create(
            model=cfg.get("model", "claude-opus-5"),
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": PROMPT.format(
                hours=config.get("lookback_hours", 24),
                tweets=json.dumps(tw, ensure_ascii=False),
                opps=json.dumps(ops, ensure_ascii=False))}],
        )
    except anthropic.RateLimitError as e:
        print(f"[warn] brief rate limited: {e}")
        return None
    except anthropic.APIStatusError as e:
        print(f"[warn] brief failed: HTTP {e.status_code} {e.message}")
        return None
    except anthropic.APIConnectionError as e:
        print(f"[warn] brief connection error: {e}")
        return None

    if response.stop_reason == "refusal":
        print("[warn] brief request was declined")
        return None
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    return {"text": text, "model": response.model} if text else None
