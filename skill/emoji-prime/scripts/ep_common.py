"""Shared bits: paths, subtitle reading, text cleaning, emoji clean-up, sticker rendering."""
import hashlib, json, os, re, sys, time, urllib.request

from PIL import Image, ImageDraw, ImageFilter, ImageFont

CACHE = os.path.expanduser(os.environ.get("EMOJI_PRIME_CACHE", "~/.cache/emoji-prime"))
FONT_URL = "https://github.com/googlefonts/noto-emoji/raw/main/fonts/NotoColorEmoji.ttf"
FONT_PATHS = [
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
    "/usr/share/fonts/noto/NotoColorEmoji.ttf",
    "/usr/share/fonts/google-noto-emoji/NotoColorEmoji.ttf",
    "/usr/share/fonts/noto-emoji/NotoColorEmoji.ttf",
    os.path.expanduser("~/Library/Fonts/NotoColorEmoji.ttf"),
    os.path.expanduser("~/.local/share/fonts/NotoColorEmoji.ttf"),
]
SIZES = [170, 260, 390]  # rendered heights; the mpv script picks the one nearest BOX x video height
BOX = 0.36
SCALE = {"rebus": 0.42, "vlog": 0.72, "word_img": 0.55, "word_emoji": 0.42}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def jload(path, default=None):
    if default is not None and not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def jdump(obj, path):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def download(url, dest):
    if not os.path.exists(dest):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, timeout=120).read()
        with open(dest + ".part", "wb") as f:
            f.write(data)
        os.replace(dest + ".part", dest)
    return dest


# ---------- subtitles + text ----------

_TIME = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)")
_STRIP = [re.compile(r"（[^）]*）"), re.compile(r"\([^)]*\)"), re.compile(r"\[[^\]]*\]"), re.compile(r"<[^>]*>"),
          re.compile(r"\{[^}]*\}")]
_SPEAKER = re.compile(r"^[（(]([^）)]*)[）)]")


def _secs(t):
    h, m, s, ms = _TIME.match(t).groups()
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")[:3]) / 1000


def clean(text):
    """Spoken text only: drop speaker tags, SDH brackets, markup and all whitespace."""
    for rx in _STRIP:
        text = rx.sub("", text)
    return re.sub(r"[\s　]+", "", text)


def read_srt(path):
    """SRT -> [{cue, start, end, speaker, raw, text}]; song lines (♪) are skipped."""
    raw = open(path, encoding="utf-8-sig", errors="replace").read().replace("\r\n", "\n")
    cues = []
    for block in re.split(r"\n\s*\n", raw.strip()):
        lines = block.strip().splitlines()
        ti = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if ti is None:
            continue
        a, b = [p.strip() for p in lines[ti].split("-->")]
        body = [l for l in lines[ti + 1:] if l.strip()]
        if not body or any("♪" in l for l in body):
            continue
        m = _SPEAKER.match(body[0].strip())
        text = "".join(clean(l) for l in body)
        cues.append(dict(cue=len(cues), start=round(_secs(a), 3), end=round(_secs(b.split()[0]), 3),
                         speaker=m.group(1) if m else "", raw=" / ".join(body), text=text))
    return cues


# ---------- emoji ----------

# emoji that render letters, digits or kanji (they'd leak text onto the screen)
_LETTERED = re.compile(r"[\U0001F170-\U0001F1FF\U0001F200-\U0001F2FF㊗㊙™ℹⓂ]"
                       r"|[0-9#*]️?⃣")
_SWAP = {"🆘": "🛟", "🆓": "💸🚫", "🆚": "⚔️", "🈳": "🚫", "📅": "🗓️", "📆": "🗓️", "🆗": "👌", "🆕": "✨",
         "🔝": "⬆️", "🔙": "⏪", "🔜": "⏩", "🔚": "🏁"}
_TEXTY = re.compile(r"[A-Za-z0-9぀-ヿ一-鿿]")


def clean_emoji(s):
    if not isinstance(s, str):
        return None
    for k, v in _SWAP.items():
        s = s.replace(k, v)
    s = _TEXTY.sub("", _LETTERED.sub("", s)).strip()
    return s or None


def graphemes(s):
    """Split an emoji string into glyph clusters (base + VS16 / ZWJ / skin tone)."""
    out = []
    for ch in s:
        if out and (ch in "️‍⃣" or 0x1F3FB <= ord(ch) <= 0x1F3FF or out[-1].endswith("‍")):
            out[-1] += ch
        else:
            out.append(ch)
    return out


_FONT = None


def font():
    global _FONT
    if _FONT is None:
        path = next((p for p in FONT_PATHS if os.path.exists(p)), None)
        if not path:
            path = os.path.join(CACHE, "NotoColorEmoji.ttf")
            if not os.path.exists(path):
                log("downloading Noto Color Emoji (~10 MB, once)")
            download(FONT_URL, path)
        _FONT = ImageFont.truetype(path, 109)  # Noto Color Emoji is a fixed 109 px bitmap font
    return _FONT


def emoji_tile(g):
    im = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((8, 8), g, font=font(), embedded_color=True)
    box = im.getbbox()
    return im.crop(box) if box else None  # None: the font has no glyph for it


def emoji_strip(chunks, shown=None):
    """Emoji chunks -> one transparent RGBA strip. Chunks from `shown` on are drawn invisible
    (they keep their place), so a strip can be revealed chunk by chunk without moving."""
    tiles = []
    for ci, ch in enumerate(chunks):
        for g in graphemes(ch):
            t = emoji_tile(g)
            if t is not None:
                tiles.append(t if shown is None or ci < shown else Image.new("RGBA", t.size))
    if not tiles:
        return None
    gap = 10
    out = Image.new("RGBA", (sum(t.width for t in tiles) + gap * (len(tiles) - 1), max(t.height for t in tiles)))
    x = 0
    for t in tiles:
        out.alpha_composite(t, (x, (out.height - t.height) // 2))
        x += t.width + gap
    return out


# ---------- stickers ----------

def sticker(src, crop=True):
    """Image path or RGBA image -> RGBA with a white outline and a soft shadow, like a vlog sticker."""
    im = src if isinstance(src, Image.Image) else Image.open(src).convert("RGBA")
    if im.getextrema()[3][0] == 255:  # opaque JPG: knock out the near-white background
        im.putdata([(r, g, b, 0 if min(r, g, b) > 245 else a) for r, g, b, a in im.getdata()])
    box = im.getbbox()
    if box and crop:
        im = im.crop(box)
    im.thumbnail((400, 400), Image.LANCZOS)
    pad = 24
    canvas = Image.new("RGBA", (im.width + 2 * pad, im.height + 2 * pad), (0, 0, 0, 0))
    canvas.alpha_composite(im, (pad, pad))
    outline = canvas.getchannel("A").filter(ImageFilter.MaxFilter(11))
    shadow = outline.filter(ImageFilter.GaussianBlur(6)).point(lambda v: v * 0.45)
    out = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    out.paste((0, 0, 0, 255), (4, 6), shadow)
    white = Image.new("RGBA", canvas.size, (255, 255, 255, 255))
    out.alpha_composite(Image.composite(white, Image.new("RGBA", canvas.size), outline))
    out.alpha_composite(canvas)
    return out


def write_bgra(im, path):
    """Premultiplied BGRA raw, the format mpv's overlay-add wants."""
    r, g, b, a = im.split()
    av = a.tobytes()
    prem = [Image.frombytes("L", im.size, bytes(cv * x // 255 for cv, x in zip(c.tobytes(), av))) for c in (b, g, r)]
    with open(path, "wb") as f:
        f.write(Image.merge("RGBA", (*prem, a)).tobytes())


def render(src, angle, stem, scale=1.0, aspect=0.95, crop=True):
    """Sticker at every SIZES height (fit to a box `aspect` wide), tilted. Returns {size: [w, h, file]}."""
    st = sticker(src, crop)
    out = {}
    for size in SIZES:
        s = size * scale / max(st.height, st.width / aspect)
        im = st.resize((max(1, round(st.width * s)), max(1, round(st.height * s))), Image.LANCZOS)
        im = im.rotate(angle, resample=Image.BICUBIC, expand=True)
        f = f"{stem}_{size}.bgra"
        write_bgra(im, f)
        out[str(size)] = [im.width, im.height, os.path.basename(f)]
    return out


def _h(key):
    return int(hashlib.md5(key.encode()).hexdigest(), 16)


def tilt(key):
    """Deterministic tilt: 4-12 degrees either way."""
    h = _h(key)
    return (4 + h % 9) * (1 if (h >> 8) % 2 else -1)


def jitter(key, amount=0.035):
    h = _h(key)
    return ((h % 1000) / 500 - 1) * amount, (((h >> 12) % 1000) / 500 - 1) * amount
