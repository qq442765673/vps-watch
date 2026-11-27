#!/usr/bin/env python3
"""Check vendor sites for CN2/CMIN2 deals (runs on GitHub Actions)."""
import re
import sys
import urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"


def get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def clean(s):
    import html as H
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = H.unescape(s)
    return re.sub(r"[ \t]+", " ", s).strip()


SITES = [
    ("BandwagonHost", "https://bandwagonhost.com/"),
    ("BandwagonHost deals", "https://bandwagonhost.com/deals.php"),
    ("GigsGigsCloud", "https://www.gigsgigscloud.com/"),
    ("AkileCloud", "https://akile.io/"),
    ("V.PS", "https://vps.host/"),
    ("IEONET", "https://www.ieonet.com/"),
    ("DediRock", "https://dedirock.com/"),
    ("LightLayer", "https://lightlayer.com/"),
    ("CloudCone", "https://cloudcone.com/"),
    ("LowEndBox", "https://lowendbox.com/"),
    ("LowEndTalk", "https://lowendtalk.com/"),
    ("RackNerd", "https://racknerd.com/"),
]

for name, url in SITES:
    try:
        raw = get(url)
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
        text = clean(text)
        hits = [
            l.strip()[:120]
            for l in text.split("\n")
            if l.strip()
            and re.search(
                r"Black Friday|黑五|CN2|CMIN2|9929|软银|SoftBank|年付|/yr|"
                r"\\$[\d.]+|¥[\d.]+|GB|TB|Mbps|Gbps|补货|上架|Sold Out|售罄|Flash|Deal|促销|"
                r"annual|/year|per year|BlackFriday",
                l,
                re.I,
            )
        ]
        print(f"\n### {name}: {url}")
        for h in hits[:15]:
            print(f"  {h}")
    except Exception as e:
        print(f"\n### {name} ERROR {e}")