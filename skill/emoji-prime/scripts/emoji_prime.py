#!/usr/bin/env python3
"""Emoji prime: pictures pop up over a Japanese video as each word is spoken (no English).

    emoji_prime.py prepare    VIDEO [--subs FILE] [--word-times FILE] [--out DIR] [--whisper-model auto]
    emoji_prime.py candidates VIDEO        (after the A_*.md prompts are answered)
    emoji_prime.py build      VIDEO        (after the B_*.md prompts are answered)
    emoji_prime.py auto       VIDEO --llm claude|openrouter [--model M] [--jobs 4]
    emoji_prime.py status     VIDEO
    emoji_prime.py catalog    [--refresh] [--search WORD ...] [-n 8]

Output goes to <video dir>/<video stem>.emojiprime/ (overlay.json + img/), which emoji_prime.lua picks up
automatically; working files are in its _build/ folder. Every step resumes from what's already there.

The two LLM steps are plain prompt files: _build/llm/A_NN.md -> A_NN.json and B_NN.md -> B_NN.json.
Inside Claude Code, the emoji-prime skill answers them with subagents. `auto` instead pipes them through
the `claude` CLI (`claude -p`, uses your Claude login) or OpenRouter (OPENROUTER_API_KEY, costs money).
"""
import argparse, glob, json, os, shutil, subprocess, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from ep_common import clean_emoji, jdump, jload, log  # noqa: E402
import ep_irasutoya as IR  # noqa: E402

CHUNK_A, CHUNK_B, N_CAND = 40, 60, 8
LUA = os.path.join(os.path.dirname(HERE), "mpv", "emoji_prime.lua")

PROMPT_A = """You are annotating a Japanese video for "emoji prime": pictures pop up over the video as words are spoken, so a Japanese learner understands WITHOUT any English.

For every cue in the JSON below (text = the spoken line with spaces removed; words = its content words as dictionary forms), produce:

1. "senses": for EVERY listed word, {"sense": a short Japanese monolingual gloss of the sense used IN THIS LINE, "emoji": 1-3 emoji picturing that sense, or null}. Choose the contextual sense (飲み込む said of a whirlpool swallowing people -> 🌀, not eating). Use null for words that can't be pictured in this sense (abstract or grammar-like uses), for names, for cries and interjection fragments, and for obvious misparses.
2. "rebus": 2-6 emoji conveying the gist of the WHOLE line, including grammar and tone: ❓ question, 🚫 negation, ✋ prohibition, 👉 command, 🙏 want/please, ⏪ past, ‼️ emphasis, plus the speaker's emotion. Screams, interjections and animal or creature cries get the emotion (わあああ -> 😱). Clever combos are encouraged (👂❓ for なに, 🫵🤡 for マヌケ). Give it as chunks [[emoji, anchor], ...] read left to right, where anchor is an EXACT substring (1-6 characters, copied exactly) of that cue's text: the word the chunk stands for, so it can appear the moment it is said. Grammar emoji anchor to their grammar (❓ -> か / の / 何, 🚫 -> ない, ⏪ -> た); an emotion emoji anchors to the interjection or the first word.
3. "queries": 0-2 words to search an illustration catalog (Irasutoya) with, for a picture that conveys the line's gist: a single common Japanese word in dictionary form (竜巻, 驚く, 電話, 喜ぶ, 怒る, お金). Each as {"q": word, "anchor": exact substring of the text}. Use [] for cries, interjection-only and name-only lines.

Never use emoji that show letters, digits or kanji (🆗 🆘 🆓 🆚 🈳 📅 🔟, keycaps and the like) or flags. No English anywhere.

Answer with ONLY a JSON object, no prose and no code fences:
{"<cue>": {"senses": {"<word>": {"sense": "...", "emoji": "..."}}, "rebus": [["😱", "わあ"], ...], "queries": [{"q": "...", "anchor": "..."}]}, ...}
with every cue id.

Cues:
"""

PROMPT_B = """Pick Irasutoya illustrations for "emoji prime" (pictures over a Japanese video that convey meaning without English).

For each item below you get the spoken Japanese line, the word or idea to picture ("target"; for words also the sense used in that line), and numbered candidate illustration titles (0-based). Return the index of the candidate that most clearly depicts that meaning AS USED IN THE LINE, or null if none really fits. Prefer simple, readable pictures of the thing or action itself; reject pictures of a different sense, and anything whose title suggests text or lettering (イラスト文字, 文字, ロゴ, 看板 with words).

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
    spoken = [c for c in cues if c["text"]]
    jdump({"video": video, "work": work, "subs": subs, "whisper_model": a.whisper_model, "youtube": a.youtube},
          os.path.join(build, "state.json"))
    log(f"{len(spoken)} spoken cues, {sum(len(c['words']) for c in spoken)} content words")
    words = a.word_times
    if not words and os.path.exists(os.path.splitext(video)[0] + ".soniox.json"):
        words = os.path.splitext(video)[0] + ".soniox.json"
    if words and not os.path.exists(os.path.join(build, "align.json.done")):
        n, total = M.align_from_words(cues_path, os.path.abspath(words), os.path.join(build, "align.json"))
        log(f"word timings from {words}: {n}/{total} cues matched"
            + ("" if n == total else "; Whisper aligns the rest in the background"))
    start_background(build)
    chunks = [[{"cue": c["cue"], "speaker": c["speaker"], "text": c["text"], "words": list(c["words"])}
               for c in spoken[i:i + a.chunk]] for i in range(0, len(spoken), a.chunk)]
    files = write_prompts(build, "A", PROMPT_A, chunks)
    print(f"\n{len(files)} prompt(s) to answer (step A):")
    for md, out in files:
        print(f"  {md}\n    -> {out}")
    print(f"\nthen: {next_cmd('candidates', video, a.out)}")


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
    load_state(build)
    cues = {str(c["cue"]): c for c in jload(os.path.join(build, "cues.json"))}
    A = read_answers(build, "A")
    plan, n_bad = {}, 0
    for cid, r in A.items():
        c = cues.get(str(cid))
        if not c or not isinstance(r, dict):
            continue
        text = c["text"]
        senses = {}
        for lemma, s in (r.get("senses") or {}).items():
            if lemma in c["words"] and isinstance(s, dict):
                senses[lemma] = {"sense": s.get("sense") or "", "emoji": clean_emoji(s.get("emoji"))}
        rebus = []
        for ch in r.get("rebus") or []:
            if isinstance(ch, list) and len(ch) == 2 and clean_emoji(ch[0]):
                ok = isinstance(ch[1], str) and ch[1] in text
                n_bad += not ok
                rebus.append([clean_emoji(ch[0]), ch[1] if ok else ""])
        queries = [{"q": q["q"], "anchor": q.get("anchor") if q.get("anchor") in text else ""}
                   for q in r.get("queries") or [] if isinstance(q, dict) and isinstance(q.get("q"), str)]
        plan[str(cid)] = {"senses": senses, "rebus": rebus, "queries": queries}
    missing = [k for k, c in cues.items() if c["text"] and k not in plan]
    if missing:
        log(f"warning: no step-A answer for {len(missing)} cue(s): {', '.join(missing[:12])}")
    if n_bad:
        log(f"{n_bad} rebus anchor(s) weren't substrings of their line; those emoji get approximate timing")
    jdump(plan, os.path.join(build, "plan_a.json"))

    search, items, seen = {}, [], {}
    for cid, p in plan.items():
        for lemma, s in p["senses"].items():
            if not s["emoji"] or (lemma, s["sense"]) in seen:
                continue
            seen[(lemma, s["sense"])] = True
            cand = search.setdefault(lemma, IR.search(lemma, N_CAND))
            if cand:
                items.append({"id": f"w{len(items)}", "line": cues[cid]["text"], "target": lemma, "sense": s["sense"],
                              "candidates": [x["title"] for x in cand]})
        for n, q in enumerate(p["queries"]):
            cand = search.setdefault(q["q"], IR.search(q["q"], N_CAND))
            if cand:
                items.append({"id": f"v{cid}_{n}", "line": cues[cid]["text"], "target": q["q"],
                              "candidates": [x["title"] for x in cand]})
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
        try:
            path = IR.fetch_image(cand[idx]["img"])
        except Exception as e:
            log(f"download failed for {it['target']} ({e})")
            continue
        if it["id"].startswith("w"):
            word_img[(it["target"], it["sense"])] = (path, cand[idx]["title"], cand[idx]["img"])
        else:
            cid, n = it["id"][1:].rsplit("_", 1)
            vlog.setdefault(cid, []).append((int(n), path, cand[idx]["title"], cand[idx]["img"]))
    plan = {}
    for cid, p in plan_a.items():
        words = {}
        for lemma, s in p["senses"].items():
            if s["emoji"]:
                img = word_img.get((lemma, s["sense"]))
                words[lemma] = {"emoji": s["emoji"], "sense": s["sense"], "image": img[0] if img else None,
                                "url": img[2] if img else None,
                                "title": img[1] if img else s["emoji"]}
        plan[cid] = {"rebus": p["rebus"], "words": words,
                     "vlog": [{"image": path, "url": url, "title": title, "anchor": p["queries"][n]["anchor"]}
                              for n, path, title, url in sorted(vlog.get(cid, []))]}
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
    O.build(cues, align, place, plan, work, pre=a.pre, stay=a.stay, youtube=a.youtube or st.get("youtube"))
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
    for tag in ("A", "B"):
        mds = sorted(glob.glob(os.path.join(build, "llm", f"{tag}_*.md")))
        todo = [m for m in mds if not os.path.exists(m[:-3] + ".json")]
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
    if not os.path.exists(os.path.join(build, "llm")):
        cmd_prepare(a)
    log(f"step A via {a.llm}")
    answer_all(build, "A", a)
    if not glob.glob(os.path.join(build, "llm", "B_*.md")):
        cmd_candidates(a)
    log(f"step B via {a.llm}")
    answer_all(build, "B", a)
    cmd_build(a)


def cmd_catalog(a):
    IR.fetch_catalog(force=a.refresh)
    print(f"catalog: {IR.CATALOG if os.path.exists(IR.CATALOG) else IR.BUNDLED}")
    for q in a.search or []:  # the same search the candidates step runs
        hits = IR.search(q, n=a.n)
        print(f"## {q} ({len(hits)} shown)")
        for h in hits:
            print(f"{h['title']} | {h['img']}")


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
        p.add_argument("--word-times", help="word timings JSON ({\"words\": [{text, start, end}]}, e.g. a Soniox "
                                            "export) to use instead of Whisper alignment (default: <stem>.soniox.json)")
    pa = sub.choices["auto"]
    pa.add_argument("--llm", choices=["claude", "openrouter"], default="claude")
    pa.add_argument("--model")
    pa.add_argument("--jobs", type=int, default=4)
    pcand = video_cmd("candidates", cmd_candidates)
    for p, default in ((sub.choices["prepare"], CHUNK_A), (pcand, CHUNK_B)):
        p.add_argument("--chunk", type=int, default=default, help="cues/items per prompt (bigger = fewer prompts)")
    pa.add_argument("--chunk", type=int, default=CHUNK_A)
    pbuild = video_cmd("build", cmd_build)
    pbuild.add_argument("--youtube", help="YouTube video id for web.json (default: the one given to prepare)")
    for p in (pbuild, pa):
        p.add_argument("--pre", type=float, default=0.1, help="show pictures this early (s)")
        p.add_argument("--stay", type=float, default=1.0, help="keep pictures up this long after the word (s)")
    video_cmd("status", cmd_status)
    pc = sub.add_parser("catalog")
    pc.add_argument("--refresh", action="store_true", help="rebuild it from Irasutoya's feed (~8 min)")
    pc.add_argument("--search", nargs="+", metavar="WORD", help="search it the way the candidates step does")
    pc.add_argument("-n", type=int, default=8, help="hits per search word")
    pc.set_defaults(fn=cmd_catalog)
    pb = sub.add_parser("_bg")
    pb.add_argument("job", choices=["align", "place"])
    pb.add_argument("build")
    pb.set_defaults(fn=cmd_bg)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
