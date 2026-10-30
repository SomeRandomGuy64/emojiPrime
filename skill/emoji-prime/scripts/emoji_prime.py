#!/usr/bin/env python3
"""Emoji prime: pictures pop up over a Japanese video as each word is spoken (no English).

    emoji_prime.py prepare    VIDEO [--mode high|medium|low] [--subs FILE] [--word-times FILE] [--out DIR]
    emoji_prime.py candidates VIDEO        (after the A_*.md or M_*.md prompts are answered)
    emoji_prime.py build      VIDEO        (after the B_*.md prompts are answered)
    emoji_prime.py auto       VIDEO --llm claude|openrouter [--model M] [--jobs 4]
    emoji_prime.py status     VIDEO
    emoji_prime.py catalog    --search WORD ... [-n 8]
    emoji_prime.py phrases    [WORD]

Output goes to <video dir>/<video stem>.emojiprime/ (overlay.json + img/), which emoji_prime.lua picks up
automatically; working files are in its _build/ folder. Every step resumes from what's already there.

The two LLM steps are plain prompt files: _build/llm/A_NN.md -> A_NN.json and B_NN.md -> B_NN.json.
--mode picks how much of the work the LLM does:
  high    the LLM writes every sense, rebus and illustration search (steps A and B)
  medium  each word's sense comes from the picture dictionary (on the emoji-prime server); the LLM only picks which of a
          word's dictionary senses a line uses, plus one tone emoji per line (step M, no step B)
  low     no LLM: every word gets its most common dictionary sense
In medium and low the rebus is built from the word emoji, the set phrases, idioms (from the server, matched by
lemmas so 我に返った finds 我に返る) and grammar (ない 🚫, た ⏪, か ❓). Medium also gets one gist illustration per line.
Inside Claude Code, the emoji-prime skill answers them with subagents. `auto` instead pipes them through
the `claude` CLI (`claude -p`, uses your Claude login) or OpenRouter (OPENROUTER_API_KEY, costs money).
"""
import argparse, glob, json, os, shutil, subprocess, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from ep_common import clean_emoji, jdump, jload, log  # noqa: E402
import ep_api as API  # noqa: E402
import ep_irasutoya as IR  # noqa: E402

CHUNK_A, CHUNK_B, CHUNK_M, N_CAND = 120, 400, 300, 8  # big chunks: each prompt costs a fixed agent overhead
REBUS_MAX = 6
LUA = os.path.join(os.path.dirname(HERE), "mpv", "emoji_prime.lua")

PROMPT_A = """You are annotating a Japanese video for "emoji prime": pictures pop up over the video as words are spoken, so a Japanese learner understands WITHOUT any English.

For every cue in the JSON below (text = the spoken line with spaces removed; words = its content words as dictionary forms), produce:

1. "s" (senses): for EVERY listed word, [sense, emoji]: sense = a very short Japanese monolingual gloss (2-8 characters) of the sense used IN THIS LINE; emoji = 1-3 emoji picturing that sense, or null. Choose the contextual sense (飲み込む said of a whirlpool swallowing people -> 🌀, not eating). Use null for words that can't be pictured in this sense (abstract or grammar-like uses), for names, for cries and interjection fragments, and for obvious misparses.
2. "r" (rebus): 2-6 emoji conveying the gist of the WHOLE line, including grammar and tone: ❓ question, 🚫 negation, ✋ prohibition, 👉 command, 🙏 want/please, ⏪ past, ‼️ emphasis, plus the speaker's emotion. Screams, interjections and animal or creature cries get the emotion (わあああ -> 😱). Clever combos are encouraged (👂❓ for なに, 🫵🤡 for マヌケ). Give it as chunks [[emoji, anchor], ...] read left to right, where anchor is an EXACT substring (1-6 characters, copied exactly) of that cue's text: the word the chunk stands for, so it can appear the moment it is said. Grammar emoji anchor to their grammar (❓ -> か / の / 何, 🚫 -> ない, ⏪ -> た); an emotion emoji anchors to the interjection or the first word.
3. "q" (queries): 0-2 words to search an illustration catalog (Irasutoya) with, for a picture that conveys the line's gist: a single common Japanese word in dictionary form (竜巻, 驚く, 電話, 喜ぶ, 怒る, お金). Each as [word, anchor], anchor = exact substring of the text. Use [] for cries, interjection-only and name-only lines.

4. Some cues have "set": prebaked set phrases with fixed emoji, as [emoji, the phrase as written in the text]. Put each one into the rebus exactly as given (that emoji, anchored to that phrase), and don't express it again with other emoji. The words inside a set phrase aren't listed, so they need no senses.

Never use emoji that show letters, digits or kanji (🆗 🆘 🆓 🆚 🈳 📅 🔟, keycaps and the like) or flags. No English anywhere.

Answer with ONLY a JSON object, no prose and no code fences:
{"<cue>": {"s": {"<word>": ["<sense>", "<emoji>" or null]}, "r": [["😱", "わあ"], ...], "q": [["<word>", "<anchor>"]]}, ...}
with every cue id.

Cues:
"""

PROMPT_M = """You are choosing word senses for "emoji prime": pictures pop up over a Japanese video as words are spoken, so a Japanese learner understands WITHOUT any English.

For every cue below (text = the spoken line), "w" lists the words whose sense you must choose:
- a list of numbered candidate senses (very short Japanese glosses, 0-based): answer the index of the sense used IN THIS LINE, or null if none fits or the word isn't really there (a name fragment, a misparse, a filler use).
- null (the word isn't in the dictionary): answer [gloss, emoji] (gloss = 2-8 character Japanese gloss of the sense used here, emoji = 1-3 emoji picturing it), or null if it can't be pictured here.

Also give "g": a word to search an illustration catalog (Irasutoya) with, for one picture that conveys the line's gist, as [word, anchor]: word = a single common Japanese word in dictionary form (電話, 驚く, 喜ぶ, お金, 旅行), anchor = an EXACT substring (1-6 characters) of the text where that idea is said. Use null for filler, greetings, cries and very short lines.

Also give "e": ONE emoji for the line's tone or the speaker's emotion when it is strong and clear (😱 a scream, 😂 laughing, 😡 anger, 🥺 pleading, 😮 surprise), else null. Never use emoji that show letters, digits or kanji, or flags.

Answer with ONLY a JSON object, no prose and no code fences: {"<cue>": {"e": "<emoji>" or null, "g": ["<word>", "<anchor>"] or null, "w": {"<word>": index or null or ["<gloss>", "<emoji>"]}}, ...} with every cue id.

Cues:
"""

PROMPT_B = """Pick Irasutoya illustrations for "emoji prime" (pictures over a Japanese video that convey meaning without English).

For each item below you get the spoken Japanese line, the word or idea to picture ("target"; for words also the sense used in that line), and numbered candidate illustration titles (0-based; the usual 「のイラスト」 ending is left off). Return the index of the candidate that most clearly depicts that meaning AS USED IN THE LINE, or null if none really fits. Prefer simple, readable pictures of the thing or action itself; reject pictures of a different sense, and anything whose title suggests text or lettering (イラスト文字, 文字, ロゴ, 看板 with words).

Answer with ONLY a JSON object, no prose and no code fences: {"<id>": index or null, ...} with every id.

Items:
"""


# ---------- paths / state ----------

def paths(video, out=None):
    video = os.path.abspath(video)
    stem = os.path.splitext(os.path.basename(video))[0]
    work = os.path.abspath(out or os.path.join(os.path.dirname(video), stem + ".emojiprime"))
    return video, work, os.path.join(work, "_build")


def next_cmd(name, video, out):
    return f'emoji_prime.py {name} "{video}"' + (f' --out "{out}"' if out else "")


def load_state(build):
    st = os.path.join(build, "state.json")
    if not os.path.exists(st):
        sys.exit("run `emoji_prime.py prepare VIDEO` first")
    return jload(st)


def prompt_file(build, tag, i):
    return os.path.join(build, "llm", f"{tag}_{i:02d}.md"), os.path.join(build, "llm", f"{tag}_{i:02d}.json")


def write_prompts(build, tag, header, chunks):
    d = os.path.join(build, "llm")
    os.makedirs(d, exist_ok=True)
    for old in glob.glob(os.path.join(d, f"{tag}_*.md")):
        os.remove(old)
    files = []
    for i, ch in enumerate(chunks):
        md, out = prompt_file(build, tag, i)
        with open(md, "w", encoding="utf-8") as f:
            f.write(f"<!-- Write the answer (the JSON object only) to: {out} -->\n\n")
            f.write(header + json.dumps(ch, ensure_ascii=False, indent=0))
        files.append((md, out))
    return files


def read_answers(build, tag):
    """Merged JSON answers for tag; exits listing any prompt that has no valid answer yet."""
    merged, missing = {}, []
    for md in sorted(glob.glob(os.path.join(build, "llm", f"{tag}_*.md"))):
        out = md[:-3] + ".json"
        try:
            raw = open(out, encoding="utf-8").read()
            merged.update(json.loads(raw[raw.index("{"):raw.rindex("}") + 1]))
        except (OSError, ValueError):
            missing.append(md)
    if missing:
        sys.exit("these prompts have no valid JSON answer yet:\n  " + "\n  ".join(missing))
    return merged


def prompt_text(md):
    return open(md, encoding="utf-8").read().split("-->", 1)[1].lstrip()


# ---------- steps ----------

def cmd_prepare(a):
    import ep_media as M
    video, work, build = paths(a.video, a.out)
    os.makedirs(build, exist_ok=True)
    subs = os.path.abspath(a.subs) if a.subs else M.find_subs(video, build, a.whisper_model)
    log(f"subtitles: {subs}")
    cues_path = os.path.join(build, "cues.json")
    if not os.path.exists(cues_path):
        jdump(M.tokenize(subs), cues_path)
    cues = jload(cues_path)
    if any("bounds" not in c for c in cues if c["text"]):
        jdump(M.add_bounds(cues), cues_path)
    spoken = [c for c in cues if c["text"]]
    sets = load_phrases(build, cues)
    jdump({"video": video, "work": work, "subs": subs, "whisper_model": a.whisper_model, "youtube": a.youtube,
           "mode": a.mode}, os.path.join(build, "state.json"))
    log(f"{len(spoken)} spoken cues, {sum(len(c['words']) for c in spoken)} content words, "
        f"{sum(len(m) for m in sets.values())} set phrases")
    words = a.word_times
    if not words and os.path.exists(os.path.splitext(video)[0] + ".soniox.json"):
        words = os.path.splitext(video)[0] + ".soniox.json"
    if words and not os.path.exists(os.path.join(build, "align.json.done")):
        n, total = M.align_from_words(cues_path, os.path.abspath(words), os.path.join(build, "align.json"))
        log(f"word timings from {words}: {n}/{total} cues matched"
            + ("" if n == total else "; Whisper aligns the rest in the background"))
    start_background(build)
    if a.mode in ("medium", "low"):
        sets = dict_sets(build, cues, sets)
    if a.mode == "low":
        write_dict_plan(build, spoken, sets, {})
        print(f"\nno LLM steps in low mode; then: {next_cmd('build', video, a.out)}")
        return
    if a.mode == "medium":
        D = load_senses(build, spoken)
        entries = [m_entry(c, sets.get(str(c["cue"]), []), D) for c in spoken]
        chunk = a.chunk or CHUNK_M
        files = write_prompts(build, "M", PROMPT_M, [entries[i:i + chunk] for i in range(0, len(entries), chunk)])
        print(f"\n{len(files)} prompt(s) to answer (step M, sense choices; Haiku is enough):")
    else:
        chunk = a.chunk or CHUNK_A
        chunks = [[a_entry(c, sets.get(str(c["cue"]), [])) for c in spoken[i:i + chunk]]
                  for i in range(0, len(spoken), chunk)]
        files = write_prompts(build, "A", PROMPT_A, chunks)
        print(f"\n{len(files)} prompt(s) to answer (step A):")
    for md, out in files:
        print(f"  {md}\n    -> {out}")
    print(f"\nthen: {next_cmd('candidates', video, a.out)}")


def load_phrases(build, cues):
    """Set-phrase matches per cue, found once and kept in _build/phrases.json (the phrase list is fetched from
    the server, or its cached copy)."""
    path = os.path.join(build, "phrases.json")
    if not os.path.exists(path):
        import ep_media as M
        jdump(API.match_phrases(M.add_bounds([c for c in cues if c["text"]]), API.phrases()), path)
    return jload(path)


def inside(off, ms, length=1):
    return any(off < m["end"] and off + max(length, 1) > m["start"] for m in ms)


def a_entry(c, ms):
    """A cue as step A sees it. Words inside a set phrase are left out: the phrase covers them."""
    e = {"cue": c["cue"], "speaker": c["speaker"], "text": c["text"],
         "words": [w for w, (_, off) in c["words"].items() if not inside(off, ms)]}
    if ms:
        e["set"] = [[m["emoji"], m["form"]] for m in ms]
    return e


def load_senses(build, spoken, extra=()):
    """The picture dictionary's entries for this video's words (plus extra, e.g. step M's gist words):
    {lemma: [[gloss, emoji or null, image url or null, image title or null], ...]}, most common sense first.
    Looked up on the server once and kept in _build/senses.json; words not asked about yet are looked up then."""
    path = os.path.join(build, "senses.json")
    have = jload(path) if os.path.exists(path) else {"asked": [], "senses": {}}
    words = {w for c in spoken for w in c["words"]} | set(extra)
    new = words - set(have["asked"])
    if new:
        have = {"asked": sorted(set(have["asked"]) | new), "senses": {**have["senses"], **API.senses(new)}}
        jdump(have, path)
    return have["senses"]


def dict_sets(build, cues, sets):
    """Set phrases plus idiom matches, for medium/low (in high mode the LLM handles idioms itself). Idioms are
    matched on lemmas with auxiliaries left out, longest first, and never overlap a set phrase."""
    path = os.path.join(build, "idiom_matches.json")
    if os.path.exists(path):
        return jload(path)
    import fugashi
    tagger = fugashi.Tagger()
    by_first = {}
    for d in API.idioms():
        by_first.setdefault(d["lemmas"][0], []).append(d)
    for ds in by_first.values():
        ds.sort(key=lambda d: -len(d["lemmas"]))
    out, n = {}, 0
    for c in cues:
        if not c["text"]:
            continue
        text, toks, pos = c["text"], [], 0
        for w in tagger(text):
            at = text.find(w.surface, pos)
            if at < 0:
                continue
            pos = at + len(w.surface)
            if w.feature.pos1 != "助動詞":
                toks.append(((getattr(w.feature, "lemma", None) or w.surface).split("-")[0], at, pos))
        ms = list(sets.get(str(c["cue"]), []))
        i = 0
        while i < len(toks):
            hit = next((d for d in by_first.get(toks[i][0], [])
                        if [t[0] for t in toks[i:i + len(d["lemmas"])]] == d["lemmas"]), None)
            if hit:
                start, end = toks[i][1], toks[i + len(hit["lemmas"]) - 1][2]
                if not inside(start, ms, end - start):
                    ms.append({"phrase": hit["phrase"], "form": text[start:end], "start": start, "end": end,
                               "emoji": hit["emoji"], "gloss": hit["gloss"]})
                    n += 1
                i += len(hit["lemmas"])
            else:
                i += 1
        if ms:
            out[str(c["cue"])] = sorted(ms, key=lambda m: m["start"])
    jdump(out, path)
    log(f"{n} idiom matches")
    return out


def gist_images(answers, D):
    """Step M's gist words -> illustrations, with no step B: the word's own dictionary illustration if it has one,
    else the first catalog hit whose title starts with the word (電話のイラスト for 電話, never 突沸 for 突然)."""
    words = {g[0] for r in answers.values() if isinstance(r, dict) and isinstance(r.get("g"), list)
             and len(r["g"]) == 2 and isinstance(r["g"][0], str) for g in [r["g"]]}
    found, ask = {}, []
    for w in words:
        img = next(((s[2], s[3]) for s in D.get(w, []) if s[2]), None)
        if img:
            found[w] = img
        else:
            ask.append(w)
    if ask:
        for w, hits in IR.search_many(ask, N_CAND).items():
            h = next((h for h in hits if h["title"].startswith(w)), None)
            if h:
                found[w] = (h["img"], h["title"])
    return found


def m_entry(c, ms, D):
    """A cue as step M sees it: only the words with a real choice (2+ senses, or not in the dictionary)."""
    w = {}
    for lemma, (surf, off) in c["words"].items():
        if inside(off, ms, len(surf)):
            continue
        cand = D.get(lemma)
        if not cand:
            w[lemma] = None
        elif len(cand) > 1:
            w[lemma] = [s[0] for s in cand]
    return {"cue": c["cue"], "text": c["text"], "w": w}


_GRAMMAR = {("助動詞", "ない"): "🚫", ("助動詞", "ぬ"): "🚫", ("助動詞", "ず"): "🚫", ("形容詞", "無い"): "🚫",
            ("助動詞", "た"): "⏪", ("助動詞", "たい"): "🙏", ("動詞", "下さる"): "🙏", ("形容詞", "欲しい"): "🙏",
            ("助詞", "か"): "❓", ("代名詞", "何"): "❓", ("代名詞", "誰"): "❓", ("代名詞", "何処"): "❓",
            ("副詞", "どう"): "❓", ("副詞", "何故"): "❓"}
_TAGGER = None


def grammar_chunks(text):
    """Rebus chunks for grammar, (offset, emoji, anchor), each emoji at most once per line."""
    global _TAGGER
    import fugashi
    _TAGGER = _TAGGER or fugashi.Tagger()
    out, pos, seen = [], 0, set()
    for w in _TAGGER(text):
        at = text.find(w.surface, pos)
        if at < 0:
            continue
        pos = at + len(w.surface)
        f = w.feature
        if f.pos1 == "助詞" and f.pos2 != "終助詞":
            continue  # か as a list particle (AかB) isn't a question
        e = _GRAMMAR.get((f.pos1, (getattr(f, "lemma", None) or w.surface).split("-")[0]))
        after = text[pos:pos + 1]
        if e == "⏪" and w.surface in ("たら", "だら", "たり", "だり"):
            continue  # conditional / listing, not past
        if e == "🚫" and w.surface.startswith("ね") and (at == 0 or text[at - 1] in "、。！？ 　"):
            continue  # ねえ "hey" at the start of a clause, which UniDic reads as ない
        if e == "🚫" and after in "？?か" and after:
            continue  # 〜ない？ is an invitation or a rhetorical question, not a negation
        if e == "❓" and text.startswith(("どうも", "どうぞ"), at):
            continue
        if e and e not in seen:
            seen.add(e)
            out.append((at, e, w.surface))
    q = max(text.rfind("？"), text.rfind("?"))
    if q > 0 and "❓" not in seen:
        out.append((q, "❓", text[max(0, q - 2):q + 1]))
    return out


def dict_plan(c, ms, D, ans, gists=None):
    """A cue's plan from the dictionary: each word's sense is the step-M pick, else the most common one."""
    text, picks = c["text"], (ans.get("w") if isinstance(ans, dict) else None) or {}
    senses, chunks = {}, []
    for lemma, (surf, off) in c["words"].items():
        if inside(off, ms, len(surf)):
            continue
        cand = D.get(lemma)
        p = picks.get(lemma, 0) if lemma in picks or cand else None
        if isinstance(p, list) and len(p) == 2:
            s = [p[0], clean_emoji(p[1]), None, None]
        elif isinstance(p, int) and cand and 0 <= p < len(cand):
            s = cand[p]
        else:
            continue
        e = clean_emoji(s[1])
        if e:
            senses[lemma] = {"sense": s[0], "emoji": e, "img": s[2], "title": s[3]}
            chunks.append((off, 1, [e, surf]))
    for m in ms:
        senses[m["phrase"]] = {"sense": m["gloss"], "emoji": clean_emoji(m["emoji"]), "set": [m["form"], m["start"]]}
        chunks.append((m["start"], 0, [clean_emoji(m["emoji"]), m["form"]]))
    for off, e, anc in grammar_chunks(text):
        if not inside(off, ms, len(anc)):
            chunks.append((off, 2, [e, anc]))
    tone = clean_emoji(ans.get("e")) if isinstance(ans, dict) else None
    if tone:
        chunks.append((-1, 0, [tone, text[:2]]))
    chunks.sort(key=lambda x: (x[0], x[1]))
    room = REBUS_MAX - sum(k != 1 for _, k, _ in chunks)  # grammar, set phrases and tone always stay
    rebus, used = [], set()
    for _, k, ch in chunks:
        if ch[0] in used:  # 待って待って待って: one ✋⏳ is enough
            continue
        used.add(ch[0])
        if k != 1 or room > 0:
            rebus.append(ch)
            room -= k == 1
    g = ans.get("g") if isinstance(ans, dict) else None
    gist = []
    if isinstance(g, list) and len(g) == 2 and gists and g[0] in gists:
        gist = [{"img": gists[g[0]][0], "title": gists[g[0]][1], "anchor": g[1] if g[1] in text else ""}]
    return {"senses": senses, "rebus": rebus, "queries": [], "gist": gist}


def write_dict_plan(build, spoken, sets, answers):
    gist_words = [r["g"][0] for r in answers.values() if isinstance(r, dict) and isinstance(r.get("g"), list)
                  and len(r["g"]) == 2 and isinstance(r["g"][0], str)]
    D = load_senses(build, spoken, gist_words)
    gists = gist_images(answers, D) if answers else {}
    plan = {str(c["cue"]): dict_plan(c, sets.get(str(c["cue"]), []), D, answers.get(str(c["cue"])) or {}, gists)
            for c in spoken}
    jdump(plan, os.path.join(build, "plan_a.json"))
    jdump([], os.path.join(build, "items.json"))
    jdump({}, os.path.join(build, "search.json"))
    n = sum(len([s for s in p["senses"].values() if not s.get("set")]) for p in plan.values())
    log(f"{len(plan)} cues planned from the dictionary: {n} word pictures, "
        f"{sum(bool(s.get('img')) for p in plan.values() for s in p['senses'].values())} of them illustrations, "
        f"{sum(len(p['gist']) for p in plan.values())} gist illustrations")


def short_title(t):
    """Candidate titles for step B, minus the のイラスト that nearly all of them end with (saves tokens)."""
    return t[:-len("のイラスト")] if t.endswith("のイラスト") and len(t) > len("のイラスト") else t


def with_set_chunks(rebus, text, ms):
    """The rebus with each set phrase as its fixed chunk, replacing whatever the LLM anchored inside it."""
    placed, pos, last = [], 0, 0
    for n, (emoji, anc) in enumerate(rebus):
        at = text.find(anc, pos) if anc else -1
        if at < 0 and anc:
            at = text.find(anc)
        if at >= 0:
            pos = last = at
        if at < 0 or not inside(at, ms, len(anc)):
            placed.append((at if at >= 0 else last, n, [emoji, anc]))
    placed += [(m["start"], -1, [clean_emoji(m["emoji"]), m["form"]]) for m in ms]
    return [ch for _, _, ch in sorted(placed, key=lambda x: (x[0], x[1]))]


def start_background(build):
    """Word alignment (Whisper) and placement scoring run detached while the LLM steps happen."""
    for job, f in (("align", "align.json"), ("place", "placement.json")):
        if os.path.exists(os.path.join(build, f + ".done")) or bg_alive(build, job):
            continue
        log(f"{job}: running in the background (log: _build/{job}.log)")
        p = subprocess.Popen([sys.executable, os.path.abspath(__file__), "_bg", job, build],
                             stdout=subprocess.DEVNULL, stderr=open(os.path.join(build, f"{job}.log"), "w"),
                             stdin=subprocess.DEVNULL, start_new_session=os.name != "nt",
                             creationflags=0x00000008 if os.name == "nt" else 0)  # DETACHED_PROCESS
        open(os.path.join(build, f"{job}.pid"), "w").write(str(p.pid))


def bg_alive(build, job):
    try:
        pid = int(open(os.path.join(build, f"{job}.pid")).read())
    except (OSError, ValueError):
        return False
    if os.name == "nt":  # os.kill would terminate it on Windows
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return code.value == 259  # STILL_ACTIVE
    try:
        if os.waitpid(pid, os.WNOHANG)[0] == pid:  # our own child (auto mode) that has exited
            return False
    except ChildProcessError:
        pass
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def cmd_bg(a):
    import ep_media as M
    st = jload(os.path.join(a.build, "state.json"))
    cues = os.path.join(a.build, "cues.json")
    if a.job == "align":
        M.align(cues, st["video"], os.path.join(a.build, "align.json"), st["whisper_model"])
    else:
        M.place(cues, st["video"], os.path.join(a.build, "placement.json"))


def cmd_candidates(a):
    video, work, build = paths(a.video, a.out)
    st = load_state(build)
    cue_list = jload(os.path.join(build, "cues.json"))
    cues = {str(c["cue"]): c for c in cue_list}
    sets = load_phrases(build, cue_list)
    if st.get("mode") in ("medium", "low"):
        answers = read_answers(build, "M") if st.get("mode") == "medium" else {}
        write_dict_plan(build, [c for c in cue_list if c["text"]], dict_sets(build, cue_list, sets), answers)
        print(f"\nno step B in {st['mode']} mode; then: {next_cmd('build', video, a.out)}")
        return
    A = read_answers(build, "A")
    plan, n_bad = {}, 0
    for cid, r in A.items():
        c = cues.get(str(cid))
        if not c or not isinstance(r, dict):
            continue
        text = c["text"]
        senses = {}
        for lemma, s in (r.get("s") or r.get("senses") or {}).items():
            if isinstance(s, list) and len(s) == 2:  # compact [sense, emoji]
                s = {"sense": s[0], "emoji": s[1]}
            if lemma in c["words"] and isinstance(s, dict):
                senses[lemma] = {"sense": s.get("sense") or "", "emoji": clean_emoji(s.get("emoji"))}
        rebus = []
        for ch in r.get("r") or r.get("rebus") or []:
            if isinstance(ch, list) and len(ch) == 2 and clean_emoji(ch[0]):
                ok = isinstance(ch[1], str) and ch[1] in text
                n_bad += not ok
                rebus.append([clean_emoji(ch[0]), ch[1] if ok else ""])
        queries = []
        for q in r.get("q") or r.get("queries") or []:
            if isinstance(q, list) and len(q) == 2:  # compact [word, anchor]
                q = {"q": q[0], "anchor": q[1]}
            if isinstance(q, dict) and isinstance(q.get("q"), str):
                queries.append({"q": q["q"], "anchor": q.get("anchor") if q.get("anchor") in text else ""})
        ms = sets.get(str(cid), [])
        if ms:  # set phrases win over the LLM's take on the same words
            senses = {lm: s for lm, s in senses.items() if not inside(c["words"][lm][1], ms, len(c["words"][lm][0]))}
            for m in ms:
                senses[m["phrase"]] = {"sense": m["gloss"], "emoji": clean_emoji(m["emoji"]), "set": [m["form"], m["start"]]}
            rebus = with_set_chunks(rebus, text, ms)
            queries = [q for q in queries if not (q["anchor"] and inside(text.find(q["anchor"]), ms, len(q["anchor"])))]
        plan[str(cid)] = {"senses": senses, "rebus": rebus, "queries": queries}
    missing = [k for k, c in cues.items() if c["text"] and k not in plan]
    if missing:
        log(f"warning: no step-A answer for {len(missing)} cue(s): {', '.join(missing[:12])}")
    if n_bad:
        log(f"{n_bad} rebus anchor(s) weren't substrings of their line; those emoji get approximate timing")
    jdump(plan, os.path.join(build, "plan_a.json"))

    wanted = [lm for p in plan.values() for lm, s in p["senses"].items() if s["emoji"] and not s.get("set")]
    search = IR.search_many(wanted + [q["q"] for p in plan.values() for q in p["queries"]], N_CAND)
    items, seen = [], {}
    for cid, p in plan.items():
        for lemma, s in p["senses"].items():
            if not s["emoji"] or s.get("set") or (lemma, s["sense"]) in seen:
                continue  # set phrases keep their fixed emoji, so they get no illustration
            seen[(lemma, s["sense"])] = True
            cand = search.get(lemma)
            if cand:
                items.append({"id": f"w{len(items)}", "line": cues[cid]["text"], "target": lemma, "sense": s["sense"],
                              "candidates": [short_title(x["title"]) for x in cand]})
        for n, q in enumerate(p["queries"]):
            cand = search.get(q["q"])
            if cand:
                items.append({"id": f"v{cid}_{n}", "line": cues[cid]["text"], "target": q["q"],
                              "candidates": [short_title(x["title"]) for x in cand]})
    jdump(search, os.path.join(build, "search.json"))
    jdump(items, os.path.join(build, "items.json"))
    files = write_prompts(build, "B", PROMPT_B, [items[i:i + a.chunk] for i in range(0, len(items), a.chunk)])
    print(f"\n{len(items)} illustration choices in {len(files)} prompt(s) to answer (step B):")
    for md, out in files:
        print(f"  {md}\n    -> {out}")
    print(f"\nthen: {next_cmd('build', video, a.out)}")


def cmd_build(a):
    import ep_media as M
    import ep_overlay as O
    video, work, build = paths(a.video, a.out)
    st = load_state(build)
    cues = jload(os.path.join(build, "cues.json"))
    plan_a, search = jload(os.path.join(build, "plan_a.json")), jload(os.path.join(build, "search.json"))
    items = jload(os.path.join(build, "items.json"))
    B = read_answers(build, "B") if items else {}

    word_img, vlog = {}, {}
    for it in items:
        idx = B.get(it["id"])
        cand = search.get(it["target"], [])
        if not isinstance(idx, int) or not 0 <= idx < len(cand):
            continue
        try:  # web-only: the browser loads it by URL, so there's nothing to download
            path = cand[idx]["img"] if a.web_only else IR.fetch_image(cand[idx]["img"])
        except Exception as e:
            log(f"download failed for {it['target']} ({e})")
            continue
        if it["id"].startswith("w"):
            word_img[(it["target"], it["sense"])] = (path, cand[idx]["title"], cand[idx]["img"])
        else:
            cid, n = it["id"][1:].rsplit("_", 1)
            vlog.setdefault(cid, []).append((int(n), path, cand[idx]["title"], cand[idx]["img"]))
    plan, by_id = {}, {str(c["cue"]): c for c in cues}
    for cid, p in plan_a.items():
        words = {}
        for lemma, s in p["senses"].items():
            if s.get("set") and cid in by_id:
                by_id[cid]["words"][lemma] = s["set"]
            if s["emoji"]:
                img = word_img.get((lemma, s["sense"]))
                if not img and s.get("img"):  # medium/low: the dictionary sense's own illustration
                    try:
                        img = (s["img"] if a.web_only else IR.fetch_image(s["img"]), s.get("title") or s["emoji"],
                               s["img"])
                    except Exception as e:
                        log(f"download failed for {lemma} ({e})")
                words[lemma] = {"emoji": s["emoji"], "sense": s["sense"], "image": img[0] if img else None,
                                "url": img[2] if img else None,
                                "title": img[1] if img else s["emoji"]}
        plan[cid] = {"rebus": p["rebus"], "words": words,
                     "vlog": [{"image": path, "url": url, "title": title, "anchor": p["queries"][n]["anchor"]}
                              for n, path, title, url in sorted(vlog.get(cid, []))]}
        for g in p.get("gist", []):  # medium: step M's gist word, already resolved to an illustration
            try:
                path = g["img"] if a.web_only else IR.fetch_image(g["img"])
            except Exception as e:
                log(f"download failed for {g['title']} ({e})")
                continue
            plan[cid]["vlog"].append({"image": path, "url": g["img"], "title": g["title"], "anchor": g["anchor"]})
    log(f"{len(word_img)} word illustrations, {sum(len(v) for v in vlog.values())} sentence illustrations")

    for job in ("align", "place"):  # wait for the background jobs (or run them here if they died)
        done = os.path.join(build, ("align" if job == "align" else "placement") + ".json.done")
        if not os.path.exists(done) and bg_alive(build, job):
            log(f"waiting for {job} (see _build/{job}.log)")
            while bg_alive(build, job) and not os.path.exists(done):
                time.sleep(5)
        if not os.path.exists(done):
            log(f"{job} isn't finished; running it now")
            cuesp = os.path.join(build, "cues.json")
            if job == "align":
                M.align(cuesp, video, os.path.join(build, "align.json"), st["whisper_model"])
            else:
                M.place(cuesp, video, os.path.join(build, "placement.json"))
    align, place = jload(os.path.join(build, "align.json")), jload(os.path.join(build, "placement.json"))
    O.build(cues, align, place, plan, work, pre=a.pre, stay=a.stay, youtube=a.youtube or st.get("youtube"),
            web_only=a.web_only)
    if a.web_only:
        print(f"\nweb pack: {os.path.join(work, 'web.json')}")
        print("  load it from the YouTube Emoji Prime panel on the video's page")
        return
    auto_dir = os.path.join(os.path.dirname(video), os.path.splitext(os.path.basename(video))[0] + ".emojiprime")
    print("\nwatch it:")
    if os.path.abspath(work) == auto_dir:
        print(f"  mpv --script=\"{LUA}\" \"{video}\"")
        print("  (or just `mpv VIDEO` once emoji_prime.lua is in your mpv scripts folder)")
    else:
        print(f"  mpv --script=\"{LUA}\" --script-opts=emoji_prime-overlay=\"{os.path.join(work, 'overlay.json')}\" "
              f"\"{video}\"")
    print("  Shift+E toggles the pictures")


def cmd_status(a):
    video, work, build = paths(a.video, a.out)
    if not os.path.exists(os.path.join(build, "state.json")):
        print("not prepared yet")
        return
    for tag in ("A", "M", "B"):
        mds = sorted(glob.glob(os.path.join(build, "llm", f"{tag}_*.md")))
        todo = [m for m in mds if not os.path.exists(m[:-3] + ".json")]
        if not mds:
            continue
        print(f"step {tag}: {len(mds) - len(todo)}/{len(mds)} prompts answered" + "".join(f"\n  todo: {m}" for m in todo))
    for job, f in (("align", "align.json"), ("place", "placement.json")):
        done = os.path.exists(os.path.join(build, f + ".done"))
        print(f"{job}: {'done' if done else ('running' if bg_alive(build, job) else 'not running')}")
    print(f"overlay: {'built' if os.path.exists(os.path.join(work, 'overlay.json')) else 'not built'}")


# ---------- auto (LLM from the command line) ----------

def ask(prompt, a):
    for attempt in range(3):
        if a.llm == "claude":
            exe = shutil.which("claude") or sys.exit("no `claude` CLI on PATH (install Claude Code)")
            env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
            r = subprocess.run([exe, "-p", "--model", a.model or "sonnet", "--output-format", "text"],
                               input=prompt, capture_output=True, text=True, env=env, timeout=1800)
            out = r.stdout
            if "Not logged in" in out[:300]:
                sys.exit("the claude CLI isn't logged in: run `claude` once and /login")
        else:
            key = os.environ.get("OPENROUTER_API_KEY") or sys.exit("set OPENROUTER_API_KEY")
            body = json.dumps({"model": a.model or "anthropic/claude-sonnet-5.5", "max_tokens": 32000,
                               "messages": [{"role": "user", "content": prompt}]}).encode()
            req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=body,
                                         headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
            res = json.loads(urllib.request.urlopen(req, timeout=1800).read())
            out = res["choices"][0]["message"]["content"]
        try:
            return json.loads(out[out.index("{"):out.rindex("}") + 1])
        except ValueError:
            log(f"  bad JSON from the model (attempt {attempt + 1}), retrying")
    raise RuntimeError("the model never returned valid JSON")


def answer_all(build, tag, a):
    mds = [m for m in sorted(glob.glob(os.path.join(build, "llm", f"{tag}_*.md"))) if not os.path.exists(m[:-3] + ".json")]

    def one(md):
        jdump(ask(prompt_text(md), a), md[:-3] + ".json")
        log(f"  answered {os.path.basename(md)}")

    with ThreadPoolExecutor(a.jobs) as ex:
        list(ex.map(one, mds))


def cmd_auto(a):
    _, _, build = paths(a.video, a.out)
    if not os.path.exists(os.path.join(build, "state.json")):
        cmd_prepare(a)
    if a.mode == "low":
        return cmd_build(a)
    if a.mode == "medium":
        log(f"step M via {a.llm}")
        a.model = a.model or ("haiku" if a.llm == "claude" else "anthropic/claude-haiku-5.5")
        answer_all(build, "M", a)
        cmd_candidates(a)
        return cmd_build(a)
    log(f"step A via {a.llm}")
    answer_all(build, "A", a)
    if not glob.glob(os.path.join(build, "llm", "B_*.md")):
        a.chunk = CHUNK_B
        cmd_candidates(a)
    log(f"step B via {a.llm}")
    answer_all(build, "B", a)
    cmd_build(a)


def cmd_catalog(a):
    res = IR.search_many(a.search, a.n)  # the same search the candidates step runs
    for q in a.search:
        print(f"## {q} ({len(res.get(q, []))} shown)")
        for h in res.get(q, []):
            print(f"{h['title']} | {h['img']}")


def cmd_phrases(a):
    for p in API.phrases():
        if not a.word or any(a.word in f for f in [p["phrase"], *p.get("forms", [])]):
            other = f" ({'|'.join(p['forms'])})" if p.get("forms") else ""
            print(f"{p['phrase']}{other}\t{p['emoji']}\t{p.get('gloss', '')}")


def main():
    ap = argparse.ArgumentParser(description="Emoji prime: pictures over a Japanese video as words are said.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def video_cmd(name, fn, **kw):
        p = sub.add_parser(name, **kw)
        p.add_argument("video")
        p.add_argument("--out", help="output folder (default: <video stem>.emojiprime next to the video)")
        p.set_defaults(fn=fn)
        return p

    for p in (video_cmd("prepare", cmd_prepare), video_cmd("auto", cmd_auto)):
        p.add_argument("--subs", help="Japanese subtitle file (default: sidecar .ja.srt, embedded track, or Whisper)")
        p.add_argument("--whisper-model", default="auto", help="for alignment/transcription (auto: large-v3 on GPU)")
        p.add_argument("--youtube", help="YouTube video id, stored in web.json for the browser extension")
        p.add_argument("--mode", choices=["high", "medium", "low"], default="high",
                       help="how much the LLM does: high (everything), medium (picks dictionary senses), low (nothing)")
        p.add_argument("--word-times", help="word timings JSON ({\"words\": [{text, start, end}]}, e.g. a Soniox "
                                            "export) to use instead of Whisper alignment (default: <stem>.soniox.json)")
    pa = sub.choices["auto"]
    pa.add_argument("--llm", choices=["claude", "openrouter"], default="claude")
    pa.add_argument("--model")
    pa.add_argument("--jobs", type=int, default=4)
    pcand = video_cmd("candidates", cmd_candidates)
    sub.choices["prepare"].add_argument("--chunk", type=int, help=f"cues per prompt (default {CHUNK_A} for step A, "
                                        f"{CHUNK_M} for step M; bigger = fewer prompts)")
    pcand.add_argument("--chunk", type=int, default=CHUNK_B, help="items per prompt (bigger = fewer prompts)")
    pa.add_argument("--chunk", type=int)
    pbuild = video_cmd("build", cmd_build)
    pbuild.add_argument("--youtube", help="YouTube video id for web.json (default: the one given to prepare)")
    pbuild.add_argument("--web-only", action="store_true",
                        help="just web.json for the browser extension: no downloads, no mpv overlay (much faster)")
    pa.set_defaults(web_only=False)
    for p in (pbuild, pa):
        p.add_argument("--pre", type=float, default=0.1, help="show pictures this early (s)")
        p.add_argument("--stay", type=float, default=1.0, help="keep pictures up this long after the word (s)")
    video_cmd("status", cmd_status)
    pc = sub.add_parser("catalog", help="search the Irasutoya catalog the way the candidates step does")
    pc.add_argument("--search", nargs="+", metavar="WORD", required=True)
    pc.add_argument("-n", type=int, default=8, help="hits per search word")
    pc.set_defaults(fn=cmd_catalog)
    pp = sub.add_parser("phrases", help="list the prebaked set phrases")
    pp.add_argument("word", nargs="?", help="only phrases containing this")
    pp.set_defaults(fn=cmd_phrases)
    pb = sub.add_parser("_bg")
    pb.add_argument("job", choices=["align", "place"])
    pb.add_argument("build")
    pb.set_defaults(fn=cmd_bg)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
