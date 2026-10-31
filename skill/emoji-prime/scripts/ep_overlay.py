"""Turn the resolved picture plan into overlay.json + premultiplied BGRA images for emoji_prime.lua.

Every picture appears when its word is spoken (--pre s early) and stays --stay s after it ends.
The sentence rebus is one strip per cue that builds up chunk by chunk as each anchor word is said.
"""
import os, shutil

from ep_common import BOX, SCALE, SIZES, emoji_strip, graphemes, jdump, jitter, log, render, tilt
from ep_irasutoya import DIGITS, fetch_image

MIN_IDEA = 2.5  # seconds an idea strip needs to be read
IDEA_GAP = 2.5  # a cue further than this from the strip's end doesn't continue its idea
EMPTY = 5.0  # edge score under which a cell counts as empty
STRIP_W, STRIP_H = 0.18, 0.08  # half size of the widest idea strip, as fractions of the video
PIC_W, PIC_H = 0.1, 0.15  # half size of the largest tilted picture
ROW_STEP, ROW_SCALE = 0.056, 0.5  # a row of digit stickers: spacing (fraction of the width) and size
STRIP_STEP, STRIP_DIGIT, STRIP_EMOJI = 0.072, 0.6, 0.5  # the same for an idea strip with digits in it


def span(words, text, start, end, off, length):
    """Spoken time of chars [off, off+length) of a cue: aligned words, else a proportional guess."""
    hit = [w for w in words if w[0] < off + length and w[1] > off]
    if hit:
        return hit[0][2], hit[-1][3]
    n = max(1, len(text))
    return start + (end - start) * off / n, start + (end - start) * min(n, off + length) / n


def row_scale(base, row, cap, width):
    """The extension fits a row by code points, which joined emoji (keycaps, 🏃‍➡️) inflate, so a pack sets each row's
    size itself: the scale that makes the row as big as its visible emoji count deserves."""
    return round(base * min(cap, width / len(graphemes(row))) / min(cap, width / len(row)), 3)


def row_parts(row, web_only, step=ROW_STEP):
    """A picture with digits in it as stickers side by side, the digits as Irasutoya images: 1️⃣7️⃣ -> [1, 7]. Each part
    is a word payload, with dx its offset from the row's centre. None if the row has no digits."""
    glyphs = [str(k) for g in graphemes(row) for k in ([1, 0] if g == "🔟" else [g[0]] if g[0].isdigit() else [g])]
    if not any(g.isdigit() for g in glyphs):
        return None
    parts = []
    for k, g in enumerate(glyphs):
        dx = round((k - (len(glyphs) - 1) / 2) * step, 3)
        if g.isdigit():
            url = DIGITS[g]
            parts.append({"image": url if web_only else fetch_image(url), "url": url, "title": g, "dx": dx})
        else:
            parts.append({"emoji": g, "dx": dx})
    return parts


def idea_spot(place):
    """Where every idea strip goes. A strip is about two cells wide, so take two neighbouring cells that are both
    empty across the whole video, lowest row first (nearest the talking head's eye line and the subtitles)."""
    scores = {}
    for spots in place.values():
        for x, y, sc in spots:
            scores.setdefault((x, y), []).append(sc)
    med = {k: sorted(v)[len(v) // 2] for k, v in scores.items()}
    pairs = []
    for y in sorted({k[1] for k in med}):
        xs = sorted(k[0] for k in med if k[1] == y)
        pairs += [(max(med[(a, y)], med[(b, y)]), (a + b) / 2, y) for a, b in zip(xs, xs[1:])]
    if not pairs:
        return (0.5, 0.14)
    empty = [p for p in pairs if p[0] < EMPTY]
    _, x, y = max(empty, key=lambda p: (p[2], -p[0])) if empty else min(pairs)
    return (round(x, 3), y)


def in_strip(spot, strip):
    """A picture centred on this cell can't be moved clear of the strip with a small nudge."""
    return abs(spot[0] - strip[0]) < STRIP_W + PIC_W and abs(spot[1] - strip[1]) < 0.12


def clear_of(pos, strip, half=PIC_W):
    """The picture's position, moved the short way out of the strip's space if jitter pushed it in."""
    dx, dy = STRIP_W + half - abs(pos[0] - strip[0]), STRIP_H + PIC_H - abs(pos[1] - strip[1])
    if dx <= 0 or dy <= 0:
        return pos
    if dx < dy:
        return [round(pos[0] + (dx if pos[0] > strip[0] else -dx), 3), pos[1]]
    return [pos[0], round(pos[1] + (dy if pos[1] > strip[1] else -dy), 3)]


def web_export(items):
    """Browser version (for the Chrome extension): text emoji instead of bitmaps, Irasutoya by URL, and one
    item per rebus strip with a reveal time per chunk. a = CSS rotation (clockwise), sc = size vs BOX."""
    out, strips = [], {}
    for it in items:
        w = it.get("web") or {}
        if it["kind"] == "rebus":
            st = strips.get(it["group"])
            if st is None:
                st = strips[it["group"]] = {"s": it["start"], "e": it["end"], "k": "rebus", "p": it["pos"],
                                            "a": -it["angle"], "sc": w["sc"], "ch": w["ch"],
                                            "rv": [None] * len(w["ch"])}
                out.append(st)
            st["s"], st["e"] = min(st["s"], it["start"]), max(st["e"], it["end"])
            for j in range(w["shown"]):
                if st["rv"][j] is None or it["start"] < st["rv"][j]:
                    st["rv"][j] = it["start"]
        elif w.get("u") or w.get("em"):
            d = {"s": it["start"], "e": it["end"], "k": it["kind"], "p": it["pos"], "a": -it["angle"], "sc": w["sc"]}
            d.update({"u": w["u"]} if w.get("u") else {"em": w["em"]})
            out.append(d)
    for st in strips.values():  # chunks never shown (cut by the next strip) stay hidden
        st["rv"] = [t if t is not None else st["e"] + 1 for t in st["rv"]]
    out.sort(key=lambda d: d["s"])
    return out


def build(cues, align, place, plan, out_dir, pre=0.1, stay=1.0, min_on=1.2, youtube=None, web_only=False,
          rebus="word"):
    """plan: {cue: {"rebus": [[emoji, anchor]], "vlog": [{"image", "anchor", "title"}],
                    "words": {lemma: {"emoji", "image", "sense"}}}}
    web_only: write just web.json (the browser draws emoji and loads illustrations by URL), no images, no
    overlay.json; an existing mpv build in out_dir is left as it was.
    rebus: "word" builds a strip up chunk by chunk; "idea" shows one straight strip per chunk, whole, in one fixed
    spot that the other pictures stay out of for the whole video."""
    img_dir = os.path.join(out_dir, "img")
    if not web_only:
        shutil.rmtree(img_dir, ignore_errors=True)
        os.makedirs(img_dir)
    events = []  # [start, end, cue, kind, payload, group]
    strip, open_idea = idea_spot(place) if rebus == "idea" else None, None
    for c in cues:
        cid, text = str(c["cue"]), c["text"]
        p = plan.get(cid)
        if not text or not p:
            continue
        words = align.get(cid) or []
        last = max((w[3] for w in words), default=c["end"])
        tm = lambda off, ln: span(words, text, c["start"], c["end"], off, ln)  # noqa: E731

        chunks = [ch for ch in p.get("rebus", []) if ch[0]]
        if strip and chunks:
            pos, prev = 0, None
            for k, (row, anc) in enumerate(chunks):
                at = text.find(anc, pos) if anc else -1
                if at < 0 and anc:
                    at = text.find(anc)
                t0 = tm(at, len(anc))[0] if at >= 0 else (prev if prev is not None else c["start"])
                prev = t0 = max(t0, prev) if prev is not None else t0
                if at >= 0:
                    pos = at
                end, parts = max(last + stay, t0 + MIN_IDEA), row_parts(row, web_only, STRIP_STEP)
                row = graphemes(row)
                open_idea = [t0 - pre, end, cid, "rebus", (row, len(row)), f"r{cid}_{k}"]
                if parts:  # digits are images, so this strip is a row of stickers instead of one line of text
                    open_idea = [t0 - pre, end, cid, "word", {"emoji": "", **parts[0], "strip": True}, f"r{cid}_{k}"]
                    events += [[t0 - pre, end, cid, "word", {"emoji": "", **p, "strip": True}, f"r{cid}_{k}"]
                               for p in parts[1:]]
                events.append(open_idea)
        elif strip:  # no chunk: the cue continues the idea on screen
            if open_idea and c["start"] - open_idea[1] < IDEA_GAP:
                for e in events[::-1]:
                    if e[5] != open_idea[5]:
                        break
                    e[1] = max(e[1], last + stay)
        elif chunks:
            times, pos = [], 0
            for _, anc in chunks:
                at = text.find(anc, pos) if anc else -1
                if at < 0 and anc:
                    at = text.find(anc)
                t0 = tm(at, len(anc))[0] if at >= 0 else (times[-1] if times else c["start"])
                times.append(max(t0, times[-1]) if times else t0)  # the strip only grows left to right
                if at >= 0:
                    pos = at
            emoji = [e for e, _ in chunks]
            for k in range(len(chunks)):
                if k + 1 < len(chunks) and times[k + 1] - times[k] < 0.05:
                    continue  # revealed together with the next chunk
                end = times[k + 1] - pre if k + 1 < len(chunks) else max(last + stay, times[0] + min_on)
                events.append([times[k] - pre, end, cid, "rebus", (emoji, k + 1), f"r{cid}"])

        for v in p.get("vlog", []):
            anc = v.get("anchor") or ""
            at = text.find(anc) if anc else -1
            t0, t1 = tm(at, len(anc)) if at >= 0 else (c["start"], last)
            events.append([t0 - pre, max(t1 + stay, t0 + min_on), cid, "vlog", v, None])

        for lemma, wp in p.get("words", {}).items():
            surface, off = c["words"][lemma]
            t0, t1 = tm(off, len(surface))
            word = dict(wp, lemma=lemma)
            parts = None if wp.get("image") else row_parts(wp["emoji"], web_only)
            for part in parts or [word]:
                events.append([t0 - pre, max(t1 + stay, t0 + min_on), cid, "word",
                               {**word, "image": None, **part, "n": len(parts)} if parts else word,
                               f"n{cid}_{off}" if parts else None])

    # one rebus on screen at a time: a new line's strip cuts the previous one
    is_strip = lambda e: e[3] == "rebus" or (e[3] == "word" and e[4].get("strip"))  # noqa: E731
    first = {}
    for e in sorted(events, key=lambda e: e[0]):
        if is_strip(e):
            first.setdefault(e[5], e[0])
    order = sorted(first.items(), key=lambda x: x[1])
    nxt = {g: order[i + 1][1] for i, (g, _) in enumerate(order[:-1])}
    for e in events:
        if is_strip(e) and e[5] in nxt:
            e[1] = min(e[1], nxt[e[5]])
    events = sorted((e for e in events if e[1] > e[0] + 0.05), key=lambda e: e[0])

    items, active, group_spot, rendered = [], [], {}, {}
    for start, end, cid, kind, v, group in events:
        start = max(0.0, start)
        active = [it for it in active if it["end"] > start]
        src = None if kind == "rebus" else (os.path.basename(v["image"]) if v.get("image") else v["emoji"])
        same = src and "dx" not in v and next((it for it in active if it["src"] == src and not it.get("strip")), None)
        if same:  # already up (another layer, or the last line): keep it up instead of showing it twice
            same["end"] = round(max(same["end"], end), 3)
            continue
        spots = [tuple(s[:2]) for s in place.get(cid) or [[0.5, 0.38, 0]]]
        if strip:
            spots = [s for s in spots if not in_strip(s, strip)] or spots
        on_strip = kind == "rebus" or v.get("strip")
        if strip and on_strip:
            spot, blocks = strip, []
        elif group in group_spot:
            spot, blocks = group_spot[group]
        else:
            taken = {tuple(b) for it in active if group is None or it["group"] != group for b in it["blocks"]}
            free = [s for s in spots if s not in taken] or spots
            if kind == "rebus":  # wide strip: middle columns, and it blocks its row neighbours too
                mid = [s for s in free if 0.2 < s[0] < 0.8] or [s for s in spots if 0.2 < s[0] < 0.8] or free
                spot = mid[0]
                blocks = [s for s in spots if s[1] == spot[1] and abs(s[0] - spot[0]) < 0.25]
            else:
                spot, blocks = free[0], [free[0]]
            if group:
                group_spot[group] = (spot, blocks)

        stem = os.path.join(img_dir, f"p{len(items):05d}")
        if kind == "rebus":
            emoji, shown = v
            if web_only:  # the browser draws emoji itself: nothing to render
                img = "" if any(emoji[:shown]) else None
            else:
                im = emoji_strip(emoji, shown)
                img = render(im, 0 if strip else tilt(group) / 2, stem, SCALE["rebus"], aspect=3.4, crop=False) if im else None
            if img is None:
                continue
            angle = 0 if strip else tilt(group) / 2
            label = "".join(emoji[:shown])
            web = {"ch": emoji, "shown": shown, "sc": row_scale(SCALE["rebus"], "".join(emoji), 0.8, 3.2)}
        else:
            key = (kind, src, "dx" in v and angle)
            angle = tilt(f"{cid}:{src}") if "dx" not in v else 0 if v.get("strip") else tilt(group) / 3
            size = (SCALE["vlog"] if kind == "vlog" else STRIP_DIGIT if v.get("strip") else ROW_SCALE if "dx" in v
                    else SCALE["word_img"])
            if v.get("image"):
                web = {"u": v.get("url"), "sc": size}
            else:
                web = {"em": v["emoji"], "sc": STRIP_EMOJI if v.get("strip") else
                       row_scale(SCALE["word_emoji"], v["emoji"], 0.7, 1.8)}
            if web_only:
                rendered[key] = ""
            if key not in rendered:  # same picture again later: reuse the files
                if v.get("image"):
                    rendered[key] = render(v["image"], angle, stem, size)
                else:
                    im = emoji_strip([v["emoji"]])
                    rendered[key] = render(im, angle, stem, SCALE["word_emoji"]) if im else None
            img = rendered[key]
            if img is None:
                continue
            label = v.get("title") or v.get("lemma") or ""
        dx, dy = (0, 0) if strip and on_strip else jitter(f"{cid}:{group or len(items)}")
        pos = [round(spot[0] + dx, 3), round(spot[1] + dy, 3)]
        half = v.get("n", 1) * ROW_STEP / 2 + 0.02 if "dx" in v else PIC_W
        if strip and not on_strip:
            pos = clear_of(pos, strip, half)
        if on_strip and "dx" in v:
            pos = [round(pos[0] + v["dx"], 3), pos[1]]
        elif "dx" in v:  # the row stays whole on screen
            pos = [round(min(max(pos[0], half), 1 - half) + v["dx"], 3), pos[1]]
        it = dict(start=round(start, 3), end=round(end, 3), cue=int(cid), kind=kind, label=label, src=src,
                  group=group, blocks=[list(b) for b in blocks],
                  pos=pos, img=img, angle=angle, web=web, strip=bool(v and isinstance(v, dict) and v.get("strip")))
        items.append(it)
        active.append(it)
    items.sort(key=lambda x: x["start"])
    web_items = web_export(items)
    for it in items:
        it.pop("web", None)
        it.pop("strip", None)
    if not web_only:  # mpv's overlay needs the rendered images
        jdump({"mode": "vlog", "box": BOX, "sizes": SIZES, "items": items}, os.path.join(out_dir, "overlay.json"))
    jdump({"format": "emoji-prime-web", "version": 1, "box": BOX, "youtube": youtube, "items": web_items},
          os.path.join(out_dir, "web.json"))
    by = {}
    for i in items:
        by[i["kind"]] = by.get(i["kind"], 0) + 1
    log(f"overlay: {len(items)} items ({by.get('rebus', 0)} rebus steps, {by.get('vlog', 0)} sentence "
        f"illustrations, {by.get('word', 0)} word pictures)")
    return len(items)
