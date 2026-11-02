#!/usr/bin/env python3
"""VPS deal watcher.

Polls public Telegram channel previews (t.me/s/<channel>) and optional product
pages, pushes new matching posts to a Telegram bot. Stdlib only.

  python3 watch.py --once --dry-run     # test parsing, print alerts
  python3 watch.py --detect-chat        # after messaging your bot once
  python3 watch.py --test               # send a test message
  python3 watch.py                      # loop forever
"""

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"


def log(msg):
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}", flush=True)


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except Exception as e:
        log(f"config read failed: {e}")
        return default


def save_json(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def http_get(url, timeout=12, retries=1):
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            last = e
            if attempt < retries:
                time.sleep(2)
    raise last


def clean_html(s):
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = s.replace("​", "").replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def parse_channel(page):
    """Return [(post_id, data_post, text)] from a t.me/s preview page."""
    out = []
    for block in re.split(r'(?=<div class="tgme_widget_message\b)', page):
        m = re.search(r'data-post="([^"]+)"', block)
        if not m:
            continue
        t = re.search(
            r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
            block,
            re.S,
        )
        if not t:
            continue
        text = clean_html(t.group(1))
        if not text:
            continue
        post = m.group(1)
        try:
            pid = int(post.rsplit("/", 1)[-1])
        except ValueError:
            continue
        out.append((pid, post, text))
    return out


def matches(text, keywords):
    if not keywords:
        return True
    low = text.lower()
    return any(k.lower() in low for k in keywords)


CURRENCY_RATE = {
    "usd": 1.0, "us$": 1.0, "$": 1.0, "美元": 1.0, "美金": 1.0, "刀": 1.0,
    "cny": 1 / 7.3, "rmb": 1 / 7.3, "¥": 1 / 7.3, "元": 1 / 7.3, "人民币": 1 / 7.3,
    "eur": 1.08, "€": 1.08, "欧元": 1.08,
    "cad": 0.73, "c$": 0.73, "加元": 0.73,
    "gbp": 1.27, "£": 1.27, "英镑": 1.27,
}
PERIODS = [
    ("半年", 2), ("semi-annual", 2), ("semi", 2),
    ("整年", 1), ("年付", 1), ("每年", 1), ("annually", 1), ("year", 1), ("yr", 1), ("年", 1),
    ("季付", 4), ("季度", 4), ("quarter", 4), ("qtr", 4), ("季", 4),
    ("月付", 12), ("每月", 12), ("monthly", 12), ("month", 12), ("mo", 12), ("月", 12),
]
PRICE_RE = re.compile(
    r"(?P<cur>US\$|USD|CNY|RMB|EUR|CAD|GBP|C\$|美元|美金|人民币|欧元|加元|英镑|[$¥€£])\s*(?P<amt>\d+(?:\.\d+)?)"
    r"|(?P<amt2>\d+(?:\.\d+)?)\s*(?P<cur2>USD|CNY|RMB|EUR|CAD|GBP|美元|美金|人民币|欧元|加元|英镑|元|刀)",
    re.I,
)


def annual_usd_prices(text, targets):
    """Approximate annual USD prices; only prices near a target keyword count."""
    out = []
    for m in PRICE_RE.finditer(text):
        cur = (m.group("cur") or m.group("cur2") or "").lower()
        amt_s = m.group("amt") or m.group("amt2")
        if not cur or not amt_s:
            continue
        amt = float(amt_s)
        rate = CURRENCY_RATE.get(cur, 1.0)

        if targets:
            window = text[max(0, m.start() - 180): m.end() + 180].lower()
            if not any(t.lower() in window for t in targets):
                continue

        near_start = max(0, m.start() - 24)
        near = text[near_start: m.end() + 24].lower()
        period, best_key = None, None
        for word, mult in PERIODS:
            idx = near.find(word)
            while idx != -1:
                key = (
                    abs((near_start + idx) - m.start()),
                    0 if (near_start + idx) <= m.start() else 1,
                )
                if best_key is None or key < best_key:
                    best_key, period = key, mult
                idx = near.find(word, idx + 1)
        if period is None:
            period = 12 if amt < 15 else 1
        out.append(amt * rate * period)
    return out


def should_push(cfg, ch, text):
    f = cfg.get("filters", {})
    low = text.lower()

    for kw in ch.get("exclude_keywords", f.get("exclude_keywords", [])):
        if kw and kw.lower() in low:
            return False, f"exclude:{kw}"

    targets = ch.get("target_keywords", f.get("target_keywords", []))
    if targets and not any(k.lower() in low for k in targets):
        return False, "no-target"

    max_price = ch.get("max_price_usd", f.get("max_price_usd"))
    if max_price:
        prices = annual_usd_prices(text, targets)
        if prices and min(prices) > float(max_price):
            return False, f"price:${min(prices):.0f}>${float(max_price):.0f}"
        if not prices and not f.get("push_if_no_price", True):
            return False, "no-price"

    return True, ""


def tg_send(cfg, text, dry=False):
    token = cfg["telegram"].get("bot_token", "").strip()
    chat = cfg["telegram"].get("chat_id", "").strip()
    if dry or not token or not chat:
        print("[DRY] " + text.replace("\n", " | "), flush=True)
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode(
        {
            "chat_id": chat,
            "text": text,
            "disable_web_page_preview": "false",
        }
    ).encode()
    try:
        req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            r.read()
        log("telegram ok")
    except Exception as e:
        log(f"telegram send failed: {e}")


def pushplus_send(cfg, text, dry=False):
    pc = cfg.get("pushplus", {})
    token = pc.get("token", "").strip()
    if not pc.get("enabled", True) or not token:
        return
    if dry:
        print("[DRY pushplus] " + text.replace("\n", " | "), flush=True)
        return
    payload = json.dumps(
        {
            "token": token,
            "title": (text.splitlines()[0] if text else "VPS 提醒")[:60],
            "content": text,
            "template": "txt",
        }
    ).encode()
    req = urllib.request.Request(
        "https://www.pushplus.plus/send",
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": UA},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            resp = r.read().decode("utf-8", "replace")
        try:
            if json.loads(resp).get("code") != 200:
                log(f"pushplus failed: {resp[:200]}")
            else:
                log("pushplus ok")
        except Exception:
            log(f"pushplus response: {resp[:200]}")
    except Exception as e:
        log(f"pushplus send failed: {e}")


def notify(cfg, text, dry=False):
    tg_send(cfg, text, dry)
    pushplus_send(cfg, text, dry)


def alert_channel(cfg, ch, post, text, dry):
    body = text if len(text) <= 900 else text[:900] + "…"
    msg = (
        f"🔔 {ch['name']} 有新消息\n\n{body}\n\n"
        f"原帖: https://t.me/{post}"
    )
    if ch.get("buy_url"):
        msg += f"\n购买/活动页: {ch['buy_url']}"
    notify(cfg, msg, dry)
    log(f"alerted {ch['name']} {post}")


def alert_page(cfg, page, dry):
    msg = f"🔔 {page['name']} {page.get('alert_text', '有货了')}\n{page['url']}"
    if page.get("buy_url"):
        msg += f"\n购物车: {page['buy_url']}"
    notify(cfg, msg, dry)
    log(f"alerted page {page['name']}")


def fetch_pairs(pairs, workers=4):
    """Fetch (obj, url) pairs concurrently; return (obj, text, error)."""
    def one(pair):
        obj, url = pair
        try:
            return obj, http_get(url), None
        except Exception as e:
            return obj, None, e

    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(one, pairs))


def poll(cfg, state, dry=False):
    changed = False
    state.setdefault("page_keywords", {})

    ch_pairs = [(ch, f"https://t.me/s/{ch['channel']}") for ch in cfg.get("channels", [])]
    tg_ok = 0
    for ch, page, err in fetch_pairs(ch_pairs):
        if err:
            log(f"{ch['name']}: fetch failed: {err}")
            continue
        tg_ok += 1
        msgs = parse_channel(page)
        if not msgs:
            continue
        channel = ch["channel"]
        last = state["channels"].get(channel)
        if last is None:
            state["channels"][channel] = max(p for p, _, _ in msgs)
            changed = True
            log(f"{ch['name']}: baseline at post {state['channels'][channel]}")
            continue
        new = sorted(m for m in msgs if m[0] > last)
        for pid, post, text in new:
            if matches(text, ch.get("keywords", [])):
                ok, reason = should_push(cfg, ch, text)
                if not ok:
                    log(f"skip {ch['name']} {post}: {reason}")
                    continue
                alert_channel(cfg, ch, post, text, dry)
                state["last_alert"] = f"{ch['name']} {post} @ {datetime.now():%m-%d %H:%M}"
        if new:
            state["channels"][channel] = max(m[0] for m in new)
            changed = True

    if ch_pairs:
        status = "异常" if tg_ok == 0 else "正常"
        if state.get("tg_status") != status:
            state["tg_status"] = status
            changed = True
        if tg_ok == 0:
            state["tg_down_streak"] = state.get("tg_down_streak", 0) + 1
            if state["tg_down_streak"] >= 3 and not state.get("tg_down_alerted"):
                notify(
                    cfg,
                    "⚠️ TG 通道连续 3 轮全部失败，可能 VPN 到期或网络异常。"
                    "网页监控仍在工作。",
                    dry,
                )
                state["tg_down_alerted"] = True
                changed = True
        else:
            state["tg_down_streak"] = 0
            state["tg_down_alerted"] = False

    page_pairs = [(p, p["url"]) for p in cfg.get("pages", [])]
    for p, raw, err in fetch_pairs(page_pairs):
        if err:
            log(f"page {p['name']}: fetch failed: {err}")
            continue

        if p.get("keywords"):
            text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
            text = clean_html(text).lower()
            current = [k for k in p["keywords"] if k.lower() in text]
            prev = state["page_keywords"].get(p["name"])
            strong = {"双十一", "双11", "黑五"}
            if (prev is None and strong & set(current)) or (
                prev is not None and set(current) - set(prev)
            ):
                alert_page(cfg, p, dry)
                state["last_alert"] = f"{p['name']} @ {datetime.now():%m-%d %H:%M}"
            state["page_keywords"][p["name"]] = current
            changed = True
            continue

        text = raw.lower()
        status = None
        if any(x.lower() in text for x in p.get("out_of_stock_any", [])):
            status = False
        elif any(x.lower() in text for x in p.get("in_stock_any", [])):
            status = True
        if status is None:
            continue
        prev = state["pages"].get(p["name"])
        if status and prev is False:
            alert_page(cfg, p, dry)
            state["last_alert"] = f"{p['name']} @ {datetime.now():%m-%d %H:%M}"
        state["pages"][p["name"]] = status
        changed = True

    hb = cfg.get("heartbeat", {})
    if hb.get("enabled"):
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        due = now.hour >= int(hb.get("hour", 9)) and state.get("last_heartbeat") != today
        if due or not state.get("last_heartbeat"):
            notify(
                cfg,
                f"✅ vps-watch 在线\n监控 {len(cfg.get('channels', []))} 个频道\n"
                f"TG 通道: {state.get('tg_status', '未知')}\n"
                f"最近告警: {state.get('last_alert') or '无'}",
                dry,
            )
            state["last_heartbeat"] = today
            changed = True

    if changed and not dry:
        save_json(BASE / "state.json", state)


def detect_chat(cfg):
    token = cfg["telegram"].get("bot_token", "").strip()
    if not token:
        sys.exit("先把 bot_token 填进 config.json")
    try:
        raw = http_get(f"https://api.telegram.org/bot{token}/getUpdates")
    except Exception as e:
        sys.exit(f"getUpdates 失败: {e}")
    data = json.loads(raw)
    if not data.get("ok"):
        sys.exit(f"Telegram 返回错误: {data}")
    chats = []
    for u in data.get("result", []):
        msg = u.get("message") or u.get("channel_post") or {}
        chat = msg.get("chat") or {}
        if chat.get("id"):
            name = chat.get("title") or chat.get("username") or chat.get("first_name", "")
            chats.append((chat["id"], name))
    if not chats:
        sys.exit("没收到消息：先在 Telegram 里给这个 bot 发一句话，再重跑 --detect-chat")
    cid, name = chats[-1]
    cfg["telegram"]["chat_id"] = str(cid)
    save_json(BASE / "config.json", cfg)
    log(f"chat_id = {cid} ({name})，已写入 config.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="run one poll cycle")
    ap.add_argument("--dry-run", action="store_true", help="print alerts, do not send")
    ap.add_argument("--detect-chat", action="store_true")
    ap.add_argument("--test", action="store_true", help="send a test message")
    args = ap.parse_args()

    cfg = load_json(BASE / "config.json", {})
    if not cfg:
        sys.exit("config.json 不存在或为空")

    tg = cfg.setdefault("telegram", {})
    if os.environ.get("TG_BOT_TOKEN"):
        tg["bot_token"] = os.environ["TG_BOT_TOKEN"]
    if os.environ.get("TG_CHAT_ID"):
        tg["chat_id"] = os.environ["TG_CHAT_ID"]
    pp = cfg.setdefault("pushplus", {})
    if os.environ.get("PUSHPLUS_TOKEN"):
        pp["token"] = os.environ["PUSHPLUS_TOKEN"]

    if args.detect_chat:
        detect_chat(cfg)
        return
    if args.test:
        notify(cfg, "✅ vps-watch 已上线，补货/放价会推到这里。", args.dry_run)
        return

    state = load_json(BASE / "state.json", {"channels": {}, "pages": {}})
    state.setdefault("channels", {})
    state.setdefault("pages", {})
    state.setdefault("page_keywords", {})
    state.setdefault("last_heartbeat", "")
    state.setdefault("last_alert", "")

    interval = int(cfg.get("poll_seconds", 60))
    if not cfg["telegram"].get("bot_token"):
        log("telegram.bot_token 未填：当前只打印到日志，不会推送")
    if args.once:
        poll(cfg, state, args.dry_run)
        return
    log(f"watching {len(cfg.get('channels', []))} channels, every {interval}s")
    while True:
        try:
            poll(cfg, state, args.dry_run)
        except Exception as e:
            log(f"poll error: {e}")
        time.sleep(interval)


if __name__ == "__main__":
    main()
