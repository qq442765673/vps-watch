#!/usr/bin/env python3
"""Manual TG dump for review (dispatch-only workflow)."""
import html
import re
import sys
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


def get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def clean(s):
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    return re.sub(r"[ \t]+", " ", s).strip()


def tg(channel):
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


for name, ch in CHANNELS:
    try:
        posts = tg(ch)
    except Exception as e:
        print(f"\n### {name} ERROR {e}", flush=True)
        continue
    print(f"\n### {name} latest={len(posts)}", flush=True)
    for post, text in posts[-8:]:
        one = " ".join(text.split())
        print(f"[{post}] {one[:600]}", flush=True)