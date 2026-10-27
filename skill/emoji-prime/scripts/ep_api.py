"""The emoji-prime web API (api.fazon.nexus): Irasutoya catalog search and the prebaked set phrases.

The catalog (~25k posts) lives on the server, so the skill doesn't ship it. The set phrases are curated in the
emojiPrime repo's data/phrases.tsv; the server pulls them from GitHub, and this module caches its copy in
~/.cache/emoji-prime/phrases.json so a run still works offline. Set EMOJI_PRIME_API to use another server.
"""
import json, os, urllib.error, urllib.request

from ep_common import CACHE, jdump, jload, log

API = os.environ.get("EMOJI_PRIME_API", "https://api.fazon.nexus").rstrip("/") + "/emoji-prime"
PHRASES_CACHE = os.path.join(CACHE, "phrases.json")
SEARCH_BATCH = 500  # the server takes up to 1000 words a request


def _call(path, body=None, headers=None, timeout=120):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(API + path, data=data, headers={"User-Agent": "emoji-prime", **(headers or {})})
    if data is not None:
        req.add_header("Content-Type", "application/json")
    return urllib.request.urlopen(req, timeout=timeout)


def search_many(words, n=8):
    """{word: [{"title", "img"}]}: title hits first (shorter titles first), then label hits, then summary hits."""
    words, out = sorted(set(words)), {}
    for i in range(0, len(words), SEARCH_BATCH):
        try:
            with _call("/search", {"words": words[i:i + SEARCH_BATCH], "n": n}) as r:
                out.update(json.load(r)["results"])
        except (urllib.error.URLError, OSError) as e:
            raise SystemExit(f"couldn't reach the emoji-prime catalog at {API}/search ({e})")
    return out


def phrases():
    """The set phrases: [{"phrase", "forms", "emoji", "gloss"}]. Uses the cached copy if the server can't be reached."""
    cached = jload(PHRASES_CACHE, {}) or None  # (jload raises on a missing file when default is None)
    headers = {"If-None-Match": cached["etag"]} if cached and cached.get("etag") else {}
    try:
        with _call("/phrases", headers=headers, timeout=30) as r:
            d = json.load(r)
            cached = {"etag": r.headers.get("ETag", ""), "phrases": d["phrases"]}
            os.makedirs(CACHE, exist_ok=True)
            jdump(cached, PHRASES_CACHE)
    except urllib.error.HTTPError as e:
        if e.code != 304:
            log(f"set phrases: server said {e.code}; {'using the cached copy' if cached else 'none this run'}")
    except (urllib.error.URLError, OSError) as e:
        log(f"set phrases: offline ({e}); {'using the cached copy' if cached else 'none this run'}")
    return cached["phrases"] if cached else []


def match_phrases(cues, plist):
    """{cue: [{"phrase", "form", "start", "end", "emoji", "gloss"}]}: longest first, never overlapping, and a match
    must start and end on a token boundary (cue["bounds"]) so 食べちゃう never matches ちゃう."""
    forms = {}
    for p in plist:
        for f in [p["phrase"], *p.get("forms", [])]:
            forms.setdefault(f, p)
    longest = max((len(f) for f in forms), default=0)
    out = {}
    for c in cues:
        text, ms, i = c["text"], [], 0
        bounds = set(c.get("bounds") or range(len(text) + 1))
        while i < len(text):
            hit = None
            if i in bounds:
                for j in range(min(len(text), i + longest), i, -1):
                    if j in bounds and text[i:j] in forms:
                        hit = j
                        break
            if hit is None:
                i += 1
                continue
            p = forms[text[i:hit]]
            ms.append({"phrase": p["phrase"], "form": text[i:hit], "start": i, "end": hit, "emoji": p["emoji"],
                       "gloss": p.get("gloss", "")})
            i = hit
        if ms:
            out[str(c["cue"])] = ms
    return out
