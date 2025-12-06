# pyright: reportMissingModuleSource=false
# pyright: reportMissingImports=false

import json
import re
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag
from tqdm import tqdm

BASE = "https://hypixel.fandom.com"
CATEGORY_URL = "https://hypixel.fandom.com/wiki/Category:Bed_Wars_maps"
OUTPUT_PATH = r"assets\new_maps.json"


def norm_rush(text: str) -> str:
    text = (text or "").strip().lower()
    # exact "side" maps stay "side"; everything else -> "alt" (diagonal/forward/middle/straight/unknown/etc.)
    return (
        "side"
        if text.startswith("side")
        or text.startswith("unknown")
        or text.startswith("direct side")
        else "alt"
    )


def get_map_links():
    links = set()
    url = CATEGORY_URL
    while url:
        html = requests.get(url, timeout=30).text
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.select("a.category-page__member-link"):
            href = a.get("href")
            # BeautifulSoup Tag.get may return a list; normalize to a string
            if isinstance(href, list):
                href = href[0] if href else None
            if isinstance(href, str) and "Bed_Wars" in href:
                links.add(urljoin(BASE, href))
        # next page if present
        nxt = soup.select_one("a.category-page__pagination-next")
        href = nxt.get("href") if nxt else None
        href = href[0] if isinstance(href, list) and href else href
        url = urljoin(BASE, href) if isinstance(href, str) else None
    return sorted(links)


def parse_map(url):
    html = requests.get(url, timeout=30).text
    soup = BeautifulSoup(html, "html.parser")

    # find the Gameplay Information list
    gi_header = None
    for h in soup.find_all(re.compile("^h[1-4]$", re.I)):
        if "gameplay information" in h.get_text(strip=True).lower():
            gi_header = h
            break
    if not gi_header:
        return None

    # capture the bullet list under the header
    ul = gi_header.find_next(["ul", "ol"])
    if not ul or not isinstance(ul, Tag):
        return None

    rush, min_lim, max_lim = None, None, None
    for li in ul.find_all("li"):
        t = re.sub(r"\s+", " ", li.get_text(" ", strip=True))
        if t.lower().startswith("rush direction:"):
            rush = t.split(":", 1)[1].strip()
        elif t.lower().startswith("minimum build limit:"):
            m = re.search(r"-?\d+", t)
            if m:
                min_lim = int(m.group())
        elif t.lower().startswith("maximum build limit:"):
            m = re.search(r"-?\d+", t)
            if m:
                max_lim = int(m.group())

    if min_lim is None and max_lim is None and rush is None:
        return None

    # map title
    title_el = soup.select_one("#firstHeading") or soup.find("h1")
    name = (
        title_el.get_text(strip=True).replace(" (Bed Wars)", "")
        if title_el
        else url.rsplit("/", 1)[-1]
    )
    name = name.lower().rstrip()

    return name, {
        "rush_direction": norm_rush(rush or ""),
        "min_height": min_lim if min_lim is not None else None,
        "max_height": max_lim if max_lim is not None else None,
    }


def main():
    out = {}
    for i, link in tqdm(enumerate(get_map_links(), 1), desc="scraping", unit="page"):
        try:
            parsed = parse_map(link)
            if parsed:
                name, info = parsed
                out[name] = info
        except Exception:
            # be resilient and keep going
            pass
        time.sleep(0.1)  # gentle on the site
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=4, sort_keys=True)
    print(f"Wrote {len(out)} maps to bedwars_maps.json")


if __name__ == "__main__":
    main()
