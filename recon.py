#!/usr/bin/env python3
"""One-off recon: dump recent TG posts and key pages for manual review."""
import html
import re
import sys
import time
import urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
CHANNELS = [
    ("DMIT", "dmitnews"),
    ("VMRack", "vmrackvps"),
    ("VMISS", "vmiss_com"),
    ("ZgoCloud", "zgovps"),
    ("CloudIPLC", "iplcnews"),
    ("六六云", "six_clouds"),
    ("VmShell", "vmshell"),
    ("HostYun", "hostyun"),
    ("ByteVirt", "bytevirt"),
]
PAGES = [
    ("VMRack activity", "https://www.vmrack.net/activity/2026-spring"),
    ("VMRack deals", "https://www.vmrack.net/zh-CN/deploy-new-instance/vps-activation-deals?id=2052274755"),
    ("HostYun home", "https://www.hostyun.com/"),
    ("六六云公告", "https://666clouds.com/announcements"),
]


def get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def clean(s):
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def tg_posts(channel):
    page = get(f"https://t.me/s/{channel}")
    out = []
    for block in re.split(r'(?=<div class="tgme_widget_message\b)', page):
        m = re.search(r'data-post="([^"]+)"', block)
        t = re.search(
            r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', block, re.S
        )
        if m and t:
            text = clean(t.group(1))
            if text:
                out.append((m.group(1), text))
    return out


def main():
    for name, channel in CHANNELS:
        try:
            posts = tg_posts(channel)
        except Exception as e:
            print(f"\n### {name} ({channel}) ERROR {e}", flush=True)
            continue
        print(f"\n### {name} ({channel}) latest={len(posts)}", flush=True)
        for post, text in posts[-8:]:
            one = " ".join(text.split())
            print(f"[{post}] {one[:700]}", flush=True)
        time.sleep(1)

    for name, url in PAGES:
        try:
            raw = get(url)
            text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
            text = clean(text)
        except Exception as e:
            print(f"\n### {name} ERROR {e}", flush=True)
            continue
        print(f"\n### {name}\n{text[:1500]}\n", flush=True)


if __name__ == "__main__":
    sys.exit(main())