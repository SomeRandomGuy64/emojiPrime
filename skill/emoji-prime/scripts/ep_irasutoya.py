"""Irasutoya: an offline copy of the post catalog (titles + image URLs), searched locally.

A copy of the catalog ships in data/irasutoya_catalog.json (2026-10-26). `emoji_prime.py catalog --refresh`
rebuilds it from Irasutoya's public Blogger feed (~170 requests, ~8 minutes) into the cache, which then wins.
Illustrations are downloaded only when picked, into the cache.
"""
import json, os, re, time, urllib.request

from ep_common import CACHE, jdump, jload, log, download

DIR = os.path.join(CACHE, "irasutoya")
CATALOG = os.path.join(DIR, "catalog.json")
BUNDLED = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "irasutoya_catalog.json")
FEED = "https://www.irasutoya.com/feeds/posts/summary?alt=json&max-results=150&start-index={}"
_LATIN = re.compile(r"[A-Za-zＡ-Ｚａ-ｚ]")


def _page(i):
    p = os.path.join(DIR, "feed", f"{i:05d}.json")
    if os.path.exists(p):
        return jload(p)
    for attempt in range(5):
        try:
            req = urllib.request.Request(FEED.format(i), headers={"User-Agent": "Mozilla/5.0"})
            d = json.load(urllib.request.urlopen(req, timeout=60))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            jdump(d, p)
            time.sleep(2.5)  # Blogger answers 503 when hit faster
            return d
        except Exception as e:
            log(f"  feed page {i}: {e}; retrying")
            time.sleep(15 * (attempt + 1))
    raise SystemExit(f"couldn't fetch the Irasutoya feed at {i}")


def fetch_catalog(force=False):
    if not force and (os.path.exists(CATALOG) or os.path.exists(BUNDLED)):
        return
    log("building the offline Irasutoya catalog (once, ~8 min)")
    if force:  # the feed is newest-first, so cached pages would shift
        import shutil
        shutil.rmtree(os.path.join(DIR, "feed"), ignore_errors=True)
    cat, i = [], 1
    while True:
        ents = _page(i)["feed"].get("entry", [])
        if not ents:
            break
        for e in ents:
            thumb = e.get("media$thumbnail", {}).get("url", "")
            cat.append({"title": e["title"]["$t"],
                        "summary": re.sub(r"\s+", " ", e.get("summary", {}).get("$t", "")).strip(),
                        "labels": [c["term"] for c in e.get("category", [])],
                        "img": re.sub(r"/s72(-[a-z]+)?/", "/s400/", thumb)})
        i += len(ents)
        if i % 3000 < 150:
            log(f"  {len(cat)} posts")
    jdump(cat, CATALOG)
    log(f"  catalog: {len(cat)} posts")


_CAT = None


def search(q, n=8):
    """Title hits first (shorter titles first), then label hits, then summary hits."""
    global _CAT
    if _CAT is None:
        fetch_catalog()
        _CAT = jload(CATALOG if os.path.exists(CATALOG) else BUNDLED)
    scored = []
    for e in _CAT:
        if not e["img"] or _LATIN.search(e["title"]):
            continue  # Latin letters in the title tend to mean lettering in the picture
        if q in e["title"]:
            s = (0, len(e["title"]))
        elif q in e["labels"]:
            s = (1, len(e["title"]))
        elif q in e["summary"]:
            s = (2, len(e["title"]))
        else:
            continue
        scored.append((s, e))
    scored.sort(key=lambda x: x[0])
    return [{"title": e["title"], "img": e["img"]} for _, e in scored[:n]]


def fetch_image(url):
    dest = os.path.join(DIR, "img", os.path.basename(url.split("?")[0]))
    if not os.path.exists(dest):
        download(url, dest)
        time.sleep(0.3)
    return dest
