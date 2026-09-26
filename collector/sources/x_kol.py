"""KOL tweets from X API v2 (X_BEARER_TOKEN) or an RSS bridge such as RSSHub.

Returns tweet records:
  {handle, name, tag, weight, id, text, url, created_at, engagement, symbols, addresses}
"""
import email.utils
import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from ..extract import extract_tokens
from ..http import get_json, get_text

X_API = "https://api.x.com/2"
TAG = re.compile(r"<[^>]+>")


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _record(kol, tid, text, url, created_at, engagement, alias_patterns, ignore):
    symbols, addresses = extract_tokens(text, alias_patterns, ignore)
    return {
        "handle": kol["handle"], "name": kol.get("name", kol["handle"]),
        "tag": kol.get("tag", ""), "weight": float(kol.get("weight", 0.5)),
        "id": tid, "text": text, "url": url, "created_at": created_at,
        "engagement": engagement, "symbols": symbols, "addresses": addresses,
    }


def fetch_x_api(kols, token, lookback_hours, max_per_kol, alias_patterns, ignore):
    headers = {"Authorization": f"Bearer {token}"}
    by_handle = {k["handle"].lower(): k for k in kols}
    users = []
    handles = list(by_handle)
    for i in range(0, len(handles), 100):
        data = get_json(f"{X_API}/users/by", headers=headers,
                        params={"usernames": ",".join(handles[i:i + 100])})
        users += data.get("data", [])

    start = _iso(datetime.now(timezone.utc) - timedelta(hours=lookback_hours))
    tweets = []
    for u in users:
        kol = by_handle.get(u["username"].lower())
        if not kol:
            continue
        data = get_json(
            f"{X_API}/users/{u['id']}/tweets", headers=headers,
            params={
                "max_results": max(5, min(100, max_per_kol)),
                "start_time": start,
                "exclude": "replies",
                "tweet.fields": "created_at,public_metrics,note_tweet",
            },
        )
        tweets += parse_x_timeline(data, kol, alias_patterns, ignore)
    return tweets


def parse_x_timeline(data, kol, alias_patterns=(), ignore=()):
    out = []
    for t in data.get("data", []) or []:
        m = t.get("public_metrics") or {}
        engagement = (m.get("like_count", 0) + 2 * m.get("retweet_count", 0)
                      + m.get("reply_count", 0) + 2 * m.get("quote_count", 0))
        text = (t.get("note_tweet") or {}).get("text") or t.get("text", "")
        out.append(_record(kol, t["id"], text,
                           f"https://x.com/{kol['handle']}/status/{t['id']}",
                           t.get("created_at"), engagement, alias_patterns, ignore))
    return out


def fetch_rss(kols, template, lookback_hours, max_per_kol, alias_patterns, ignore):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    tweets = []
    for kol in kols:
        try:
            xml = get_text(template.format(handle=kol["handle"]))
        except Exception as e:  # noqa: BLE001 - one broken feed shouldn't stop the rest
            print(f"[warn] rss {kol['handle']}: {e}")
            continue
        tweets += parse_rss(xml, kol, cutoff, max_per_kol, alias_patterns, ignore)
    return tweets


def parse_rss(xml, kol, cutoff, max_per_kol=20, alias_patterns=(), ignore=()):
    out = []
    root = ET.fromstring(xml)
    for item in root.iter("item"):
        link = item.findtext("link") or ""
        pub = item.findtext("pubDate")
        try:
            dt = email.utils.parsedate_to_datetime(pub) if pub else None
        except (TypeError, ValueError):
            dt = None
        if dt and dt < cutoff:
            continue
        text = item.findtext("description") or item.findtext("title") or ""
        text = " ".join(html.unescape(TAG.sub(" ", text)).split())
        tid = link.rstrip("/").rsplit("/", 1)[-1]
        out.append(_record(kol, tid, text, link, _iso(dt) if dt else None, 0, alias_patterns, ignore))
        if len(out) >= max_per_kol:
            break
    return out

