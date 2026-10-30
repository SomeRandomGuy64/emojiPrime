#!/usr/bin/env python3
"""Builds dict/senses.json and dict/idioms.json, the picture dictionary behind the skill's medium and low modes.
The emoji-prime server (fazond) pulls both from this folder on GitHub hourly and serves them to the skill.

    build_dict.py freq    NAME SRT_ROOT ...   lemma frequencies over a subtitle corpus (same tokenizer as the skill)
    build_dict.py jpdb    CSV                 a ranked word list (e.g. AnkiMorphs' JPDB priority file) as lemmas
    build_dict.py rank    NAME[:N] ...        the word order: each word's best rank in any of the named lists
    build_dict.py harvest BUILD_DIR ...       senses and illustrations already picked by high-mode builds
    build_dict.py prompts [--top 10000]       gap-fill prompts (_work/G_NN.md) for frequent words with no harvest
    build_dict.py merge   [--top 10000]       harvest + gap-fill answers -> senses.json
    build_dict.py idioms  BUILD_DIR ...       idiom prompts (_work/I_NN.md), seeded with multi-word rebus chunks
    build_dict.py idioms-merge                idiom answers -> idioms.json (matched by lemma sequence)

senses.json is {lemma: [[gloss, emoji or null, image url or null, image title or null], ...]}, most common sense
first, at most 3. A null emoji is a sense that isn't worth a picture (abstract or grammar-like uses).
"""
import argparse, collections, glob, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "skill", "emoji-prime", "scripts"))
from ep_common import clean_emoji, graphemes, jdump, jload, log, read_srt  # noqa: E402
import ep_media as M  # noqa: E402

WORK = os.path.join(HERE, "_work")
SENSES = os.path.join(HERE, "senses.json")
IDIOMS = os.path.join(HERE, "idioms.json")
MAX_SENSES, CHUNK_G = 3, 800

PROMPT_G = """You are building a picture dictionary for "emoji prime": emoji pop up over a Japanese video as words are spoken, so a learner understands WITHOUT any English.

For every Japanese word below (dictionary forms, as the UniDic tokenizer gives them, so some are written in unusual kanji: 為る, 言う, 居る), list its 1-3 most common senses in CASUAL SPOKEN Japanese (YouTube chat streams, vlogs), most common first. Only list genuinely different senses that would need a different picture; most words have just one.

Each sense is [gloss, emoji]: gloss = a very short Japanese monolingual gloss (2-8 characters); emoji = 1-3 emoji picturing that sense, or null if that sense can't be pictured (abstract, grammar-like or filler uses). Never use emoji that show letters, digits or kanji (🆗 🆘 🆓 🆚 🈳 📅 🔟, keycaps and the like) or flags. No English anywhere.

Some words come with evidence after a "|": the pictures other annotators chose for that word in context, as emoji×count(gloss), ∅ meaning they judged it unpicturable there. Use it to see which senses actually come up and how often (a big ∅ share means the most common use is abstract, so put a null sense first), but merge near-duplicates into one sense and pick the clearest emoji for each.

Answer with ONLY a JSON object, no prose and no code fences: {"<word>": [["<gloss>", "<emoji>" or null], ...], ...} with every word.

Words:
"""


PROMPT_I = """You are building an idiom list for "emoji prime": emoji pop up over a Japanese video as words are spoken, so a learner understands WITHOUT any English. Single words are pictured one by one from a dictionary, which goes wrong for idioms: 我に返る would show 🏠 for 返る, お腹いっぱい would show a stomach and a full cup.

List about 600 Japanese idioms and fixed multi-word expressions common in {domain}, whose meaning a word-by-word picture would get WRONG or badly miss (我に返る, 腹が立つ, 気になる, 顔が広い, 目がない, 手に入れる, あっという間, 仕方がない). Skip expressions whose words already picture the meaning one by one (次の日, 目の前), plain grammar patterns (〜てみる, 〜ておく, ということで), and single words.

Write each in its plain dictionary form, exactly as it would be written in subtitles (kanji where usual, particles included). If a common variant drops or changes a particle (お腹がいっぱい / お腹いっぱい), list both as separate entries.

Each value is [gloss, emoji]: gloss = a very short Japanese monolingual gloss (2-8 characters), emoji = 1-3 emoji picturing the idiom's MEANING. Never use emoji that show letters, digits or kanji, or flags. No English anywhere.
{seeds}
Answer with ONLY a JSON object, no prose and no code fences: {{"<idiom>": ["<gloss>", "<emoji>"], ...}}
"""
DOMAINS = ["casual everyday speech, YouTube chat streams and anime",
           "TV drama, films, news and variety shows (wider vocabulary, some more formal or literary idioms)"]


def phrase_lemmas(tagger, text):
    """The lemma sequence an idiom is matched by. Auxiliaries are left out, so 我に返った matches 我に返る."""
    return [(getattr(w.feature, "lemma", None) or w.surface).split("-")[0] for w in tagger(text)
            if w.feature.pos1 != "助動詞"]


def cmd_idioms(a):
    """Multi-word chunks the high-mode LLM gave one emoji (気をつけて ⚠️, あっという間 ⚡) seed the first prompt."""
    import fugashi
    tagger = fugashi.Tagger()
    seen, first = collections.Counter(), {}
    for build in a.builds:
        for p in jload(os.path.join(build, "plan_a.json"), {}).values():
            for e, anc in p["rebus"]:
                toks = list(tagger(anc or ""))
                if (len([w for w in toks if w.feature.pos1 in M.CONTENT_POS]) >= 2
                        and any(w.feature.pos1 == "助詞" for w in toks)):
                    seen[anc] += 1
                    first.setdefault(anc, e)
    seeds = [f"{anc} {first[anc]}" for anc, n in seen.most_common() if n >= 2][:80]
    for i, domain in enumerate(DOMAINS):
        md = os.path.join(WORK, f"I_{i:02d}.md")
        extra = ("\nAnnotators already grouped these chunks under one emoji while annotating videos (inflected as said). "
                 "Include the real idioms among them, in dictionary form; ignore the rest:\n" + "\n".join(seeds) + "\n") if i == 0 else ""
        with open(md, "w", encoding="utf-8") as f:
            f.write(f"<!-- Write the answer (the JSON object only) to: {md[:-3]}.json -->\n\n")
            f.write(PROMPT_I.format(domain=domain, seeds=extra))
        print(md)


def cmd_idioms_merge(a):
    import fugashi
    tagger = fugashi.Tagger()
    out, seen = [], set()
    for f in sorted(glob.glob(os.path.join(WORK, "I_*.json"))):
        raw = open(f, encoding="utf-8").read()
        for phrase, v in json.loads(raw[raw.index("{"):raw.rindex("}") + 1]).items():
            lemmas = phrase_lemmas(tagger, phrase)
            e = clean_emoji(v[1]) if isinstance(v, list) and len(v) == 2 else None
            real = any(w.feature.pos1 in M.CONTENT_POS and (getattr(w.feature, "lemma", None) or w.surface).split("-")[0]
                       not in M.STOP for w in tagger(phrase))  # なってしまう is grammar, not an idiom
            if len(lemmas) >= 2 and e and real and tuple(lemmas) not in seen:
                seen.add(tuple(lemmas))
                out.append({"phrase": phrase, "lemmas": lemmas, "gloss": v[0], "emoji": e})
    jdump(out, IDIOMS)
    log(f"idioms.json: {len(out)} idioms")


def srt_files(roots):
    """One Japanese SRT per video: variants (.soniox, .tuned, ...) share the stem before the first dot."""
    seen, out = set(), []
    for root in roots:
        for f in sorted(glob.glob(os.path.join(root, "**", "*.srt"), recursive=True)):
            name = os.path.basename(f)
            if any(x in name for x in (".en.", ".ocr.")):
                continue
            key = (os.path.dirname(os.path.realpath(f)), name.split(".")[0])
            if key not in seen and os.path.exists(f) and os.path.getsize(f) > 1000:
                seen.add(key)
                out.append(f)
    return out


def cmd_freq(a):
    import fugashi
    tagger = fugashi.Tagger()
    count, docs = collections.Counter(), collections.Counter()
    files = srt_files(a.roots)
    for n, f in enumerate(files):
        here = set()
        for c in read_srt(f):
            for w in tagger(c["text"]):
                ft = w.feature
                lemma = (getattr(ft, "lemma", None) or w.surface).split("-")[0]
                if ft.pos1 in M.CONTENT_POS and ft.pos2 not in M.SKIP_POS2 and lemma not in M.STOP:
                    count[lemma] += 1
                    here.add(lemma)
        docs.update(here)
        if n % 200 == 0:
            log(f"{n}/{len(files)} files")
    # rank by count, but drop words that only one or two videos ever say (names, misparses, catchphrases)
    jdump({w: [n, docs[w]] for w, n in count.most_common() if docs[w] >= 3}, os.path.join(WORK, f"freq_{a.name}.json"))
    log(f"{len(files)} files, {len(count)} lemmas, {sum(docs[w] >= 3 for w in count)} said in 3+ videos")


def cmd_jpdb(a):
    """A ranked list of words (first CSV column, header skipped) as skill lemmas. Words the tokenizer splits into
    several tokens are compounds the skill would never see whole, so they're dropped."""
    import csv, fugashi
    tagger = fugashi.Tagger()
    out = {}
    with open(a.csv, encoding="utf-8-sig") as f:
        for n, row in enumerate(csv.reader(f)):
            toks = list(tagger(row[0])) if n and row else []
            if len(toks) != 1:
                continue
            ft = toks[0].feature
            lemma = (getattr(ft, "lemma", None) or toks[0].surface).split("-")[0]
            if ft.pos1 in M.CONTENT_POS and ft.pos2 not in M.SKIP_POS2 and lemma not in M.STOP and lemma not in out:
                out[lemma] = [n, 0]
    jdump(out, os.path.join(WORK, "freq_jpdb.json"))
    log(f"{len(out)} lemmas from {a.csv}")


def cmd_rank(a):
    """Merges ranked lists so each domain gets its own frequent words in: a word's rank is its best rank in any
    list (ties broken by the sum), so a top drama/news word gets in even if no YouTuber says it."""
    # NAME:N only trusts a list's top N: the tails of small subtitle corpora are cries and misparses
    names = [n.split(":")[0] for n in a.names]
    caps = [int(n.split(":")[1]) if ":" in n else None for n in a.names]
    lists = [list(jload(os.path.join(WORK, f"freq_{n}.json")))[:c] for n, c in zip(names, caps)]
    best = {}
    for ws in lists:
        for r, w in enumerate(ws):
            b = best.setdefault(w, [r, 0])
            b[0] = min(b[0], r)
            b[1] += r
    order = sorted(best, key=lambda w: tuple(best[w]))
    jdump({w: best[w] for w in order}, os.path.join(WORK, "freq.json"))
    sets = [set(ws) for ws in lists]
    for top in (10000, 25000, 40000):
        log(f"top {top}: " + ", ".join(f"{n} {sum(1 for w in order[:top] if w in ss)}"
                                       for n, ss in zip(names, sets)))


def cmd_harvest(a):
    """Every (lemma, emoji, gloss) pick the high-mode builds made, with the illustration step B chose for it."""
    picks = collections.defaultdict(collections.Counter)
    imgs = collections.defaultdict(collections.Counter)
    for build in a.builds:
        plan = jload(os.path.join(build, "plan_a.json"), {})
        items, search = jload(os.path.join(build, "items.json"), []), jload(os.path.join(build, "search.json"), {})
        B = {}
        for f in glob.glob(os.path.join(build, "llm", "B_*.json")):
            try:
                raw = open(f, encoding="utf-8").read()
                B.update(json.loads(raw[raw.index("{"):raw.rindex("}") + 1]))
            except ValueError:
                pass
        img = {}
        for it in items:
            idx, cand = B.get(it["id"]), search.get(it["target"], [])
            if it["id"].startswith("w") and isinstance(idx, int) and 0 <= idx < len(cand):
                img[(it["target"], it["sense"])] = (cand[idx]["img"], cand[idx]["title"])
        for p in plan.values():
            for lemma, s in p["senses"].items():
                if s.get("set"):
                    continue
                e = clean_emoji(s.get("emoji"))
                picks[lemma][(e, s.get("sense") or "")] += 1
                if e and (lemma, s.get("sense")) in img:
                    imgs[lemma][(graphemes(e)[0],) + img[(lemma, s.get("sense"))]] += 1
        log(f"{os.path.basename(os.path.dirname(build))}: {len(plan)} cues")
    jdump({lm: {"picks": [[e, g, n] for (e, g), n in c.most_common()],
                "img": [[k, u, t, n] for (k, u, t), n in imgs[lm].most_common()]} for lm, c in picks.items()},
          os.path.join(WORK, "harvest.json"))
    log(f"{len(picks)} lemmas harvested")


def clusters(picks):
    """Picks grouped into senses: two emoji strings that share a glyph (🚶🚪 and 🚪) are the same picture idea.
    Returns [[count, emoji, gloss], ...] biggest first, the null (unpictured) group included."""
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            x = parent[x]
        return x
    for e, _, _ in picks:
        if e:
            g = graphemes(e)
            for h in g[1:]:
                parent[find(h)] = find(g[0])
    groups = collections.defaultdict(lambda: [0, collections.Counter(), collections.Counter()])
    for e, gloss, n in picks:
        gr = groups[find(graphemes(e)[0]) if e else None]
        gr[0] += n
        gr[2][gloss] += n
        if e:
            gr[1][e] += n
    return sorted(([n, em.most_common(1)[0][0] if em else None, gl.most_common(1)[0][0]]
                   for n, em, gl in groups.values()), key=lambda x: -x[0])


def resolve(h):
    """Senses straight from the harvest, or None when the picks are too scattered to trust (出る: 25 different
    emoji over 94 picks), which then go to the LLM with their picks as evidence."""
    cl = clusters(h["picks"])
    total = sum(c[0] for c in cl)
    keep = [c for c in cl if c[0] / total >= 0.15][:MAX_SENSES]
    if sum(c[0] for c in keep) / total < 0.8:
        return None
    img = {}
    for k, u, t, _ in h["img"]:
        img.setdefault(k, (u, t))
    out = []
    for n, e, gloss in keep:
        u, t = next((img[g] for g in graphemes(e) if g in img), (None, None)) if e else (None, None)
        out.append([gloss, e, u, t])
    return out


def answered():
    filled = {}
    for f in sorted(glob.glob(os.path.join(WORK, "G_*.json"))):
        raw = open(f, encoding="utf-8").read()
        filled.update(json.loads(raw[raw.index("{"):raw.rindex("}") + 1]))
    return filled


def todo(top):
    """(word, evidence) for the top words that need the LLM: never seen, or seen with scattered picks, and not
    answered by an earlier round of prompts."""
    freq, harvest = jload(os.path.join(WORK, "freq.json")), jload(os.path.join(WORK, "harvest.json"), {})
    done, out = answered(), []
    for w in list(freq)[:top]:
        if w in done:
            continue
        if w not in harvest:
            out.append((w, ""))
        elif resolve(harvest[w]) is None:
            ev = " ".join(f"{e or '∅'}×{n}({g})" for n, e, g in clusters(harvest[w]["picks"])[:10])
            out.append((w, ev))
    return out


def cmd_prompts(a):
    words = todo(a.top)
    for old in glob.glob(os.path.join(WORK, "G_*.md")):
        if not os.path.exists(old[:-3] + ".json"):
            os.remove(old)
    first = len(glob.glob(os.path.join(WORK, "G_*.json")))
    for i in range(0, len(words), CHUNK_G):
        md = os.path.join(WORK, f"G_{first + i // CHUNK_G:02d}.md")
        with open(md, "w", encoding="utf-8") as f:
            f.write(f"<!-- Write the answer (the JSON object only) to: {md[:-3]}.json -->\n\n")
            f.write(PROMPT_G + "\n".join(f"{w} | {ev}" if ev else w for w, ev in words[i:i + CHUNK_G]))
        print(md)
    log(f"{len(words)} words for the LLM ({sum(bool(ev) for _, ev in words)} with scattered picks as evidence)")


def cmd_merge(a):
    freq, harvest = jload(os.path.join(WORK, "freq.json")), jload(os.path.join(WORK, "harvest.json"), {})
    filled = answered()
    out, n_h, n_g = {}, 0, 0
    top = list(freq)[:a.top]
    in_top = set(top)
    for w in top + [w for w in list(harvest) + list(filled) if w not in in_top]:
        ss = resolve(harvest[w]) if w in harvest else None
        if ss:  # what the LLM picked in context beats a context-free guess
            n_h += 1
        elif isinstance(filled.get(w), list):
            img = {}
            for k, u, t, _ in harvest.get(w, {}).get("img", []):
                img.setdefault(k, (u, t))
            ss = []
            for s in filled[w][:MAX_SENSES]:
                if isinstance(s, list) and len(s) == 2:
                    e = clean_emoji(s[1])
                    if e and not any(ord(ch) > 0x2100 for ch in e):  # "|" and other plain symbols aren't emoji
                        e = None
                    u, t = next((img[g] for g in graphemes(e) if g in img), (None, None)) if e else (None, None)
                    ss.append([s[0], e, u, t])
            n_g += bool(ss)
        if ss:
            out[w] = ss
    jdump(out, SENSES)
    log(f"senses.json: {len(out)} words ({n_h} from the harvest, {n_g} from the LLM), "
        f"{sum(len(s) > 1 for s in out.values())} with 2+ senses, "
        f"{sum(s[0][1] is None for s in out.values())} not pictured by default, "
        f"{sum(any(x[2] for x in s) for s in out.values())} with an illustration")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("freq")
    p.add_argument("name")
    p.add_argument("roots", nargs="+")
    p.set_defaults(fn=cmd_freq)
    p = sub.add_parser("jpdb")
    p.add_argument("csv")
    p.set_defaults(fn=cmd_jpdb)
    p = sub.add_parser("rank")
    p.add_argument("names", nargs="+")
    p.set_defaults(fn=cmd_rank)
    p = sub.add_parser("idioms")
    p.add_argument("builds", nargs="+")
    p.set_defaults(fn=cmd_idioms)
    sub.add_parser("idioms-merge").set_defaults(fn=cmd_idioms_merge)
    p = sub.add_parser("harvest")
    p.add_argument("builds", nargs="+", help="<video>.emojiprime/_build folders")
    p.set_defaults(fn=cmd_harvest)
    for name, fn in (("prompts", cmd_prompts), ("merge", cmd_merge)):
        p = sub.add_parser(name)
        p.add_argument("--top", type=int, default=10000)
        p.set_defaults(fn=fn)
    a = ap.parse_args()
    os.makedirs(WORK, exist_ok=True)
    a.fn(a)


if __name__ == "__main__":
    main()
