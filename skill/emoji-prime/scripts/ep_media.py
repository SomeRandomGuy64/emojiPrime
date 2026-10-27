"""Everything that touches the video: finding/making subtitles, tokenizing, word alignment, placement."""
import json, os, re, subprocess, tempfile

from ep_common import jdump, jload, log, read_srt

CONTENT_POS = {"名詞", "動詞", "形容詞", "形状詞", "副詞"}
SKIP_POS2 = {"固有名詞", "数詞"}  # names and numbers aren't worth a picture
# function-like lemmas that would only waste the LLM's time
STOP = {"為る", "居る", "有る", "成る", "呉れる", "下さる", "遣る", "貰う", "仕舞う", "無い", "事", "物", "様", "為",
        "訳", "筈", "所", "方", "達", "奴", "其れ", "此れ", "彼れ", "何", "そう", "こう", "ああ", "どう"}
GRID_X = [0.12, 0.31, 0.5, 0.69, 0.88]
GRID_Y = [0.14, 0.38, 0.62]  # the bottom quarter is left for subtitles
PLACE_BOX = 0.22
CENTRE_PENALTY = 0.25


# ---------- subtitles ----------

def find_subs(video, out_dir, transcribe_model):
    """A Japanese SRT for the video: sidecar file, else an embedded text track, else Whisper."""
    base = os.path.splitext(video)[0]
    for suffix in (".ja.srt", ".jp.srt", ".jpn.srt", ".ja-JP.srt", ".srt"):
        if os.path.exists(base + suffix):
            return base + suffix
    for ext in (".ja.ass", ".ja.vtt", ".ass", ".vtt"):
        if os.path.exists(base + ext):
            out = os.path.join(out_dir, "subs.ja.srt")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", base + ext, out], check=True)
            return out
    out = os.path.join(out_dir, "subs.ja.srt")
    if os.path.exists(out):
        return out
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "s", "-show_entries",
                                       "stream=index,codec_name:stream_tags=language", "-of", "json", video],
                                      capture_output=True, text=True).stdout or "{}")
    for s in probe.get("streams", []):
        lang = s.get("tags", {}).get("language", "")
        if lang in ("jpn", "ja", "jp") and s.get("codec_name") in ("subrip", "ass", "ssa", "mov_text", "webvtt"):
            log(f"using the embedded Japanese subtitle track #{s['index']}")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", video, "-map", f"0:{s['index']}", out], check=True)
            return out
    log(f"no Japanese subtitles found: transcribing with Whisper {transcribe_model} (slow on CPU)")
    transcribe(video, out, transcribe_model)
    return out


def _whisper(model_name):
    import stable_whisper, torch
    torch.backends.cudnn.enabled = False  # avoids cuDNN crashes on some torch/CUDA combos; costs little here
    if model_name == "auto":
        model_name = "large-v3" if torch.cuda.is_available() else "small"
    return stable_whisper.load_model(model_name)


def transcribe(video, out, model_name):
    model = _whisper(model_name)
    res = model.transcribe(video, language="ja", vad=True, verbose=None)
    res.to_srt_vtt(out, word_level=False, segment_level=True)


# ---------- tokens ----------

def tokenize(srt):
    """Cues with their content words: {lemma: [surface, char offset in the cue's text]}."""
    import fugashi
    tagger = fugashi.Tagger()
    cues = read_srt(srt)
    for c in cues:
        words, pos = {}, 0
        for w in tagger(c["text"]):
            at = c["text"].find(w.surface, pos)
            if at >= 0:
                pos = at + len(w.surface)
            f = w.feature
            lemma = (getattr(f, "lemma", None) or w.surface).split("-")[0]  # ケーブル-cable -> ケーブル
            if f.pos1 not in CONTENT_POS or f.pos2 in SKIP_POS2 or lemma in STOP or at < 0:
                continue
            words.setdefault(lemma, [w.surface, at])
        c["words"] = words
    return cues


# ---------- alignment (background) ----------

def align(cues_path, video, out, model_name):
    """Word timings per cue: {cue: [[char start, char end, t0, t1], ...]}. Resumable."""
    cues = [c for c in jload(cues_path) if c["text"]]
    res = jload(out, {})
    todo = [c for c in cues if str(c["cue"]) not in res]
    if todo:
        model = _whisper(model_name)
        tmp = tempfile.mkdtemp()
        for n, c in enumerate(todo):
            a0 = max(0.0, c["start"] - 0.3)
            wav = os.path.join(tmp, "cue.wav")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{a0:.3f}", "-t", f"{c['end'] + 0.3 - a0:.3f}",
                            "-i", video, "-ac", "1", "-ar", "16000", wav], check=True)
            words = []
            try:
                r = model.align(wav, c["text"], language="ja", verbose=None)
                k = 0
                for seg in r.segments:
                    for w in seg.words:
                        words.append([k, k + len(w.word), round(a0 + w.start, 3), round(a0 + w.end, 3)])
                        k += len(w.word)
            except Exception as e:
                log(f"cue {c['cue']}: alignment failed ({e}); its pictures get proportional timing")
            res[str(c["cue"])] = words
            if n % 25 == 0:
                jdump(res, out)
                log(f"aligned {n}/{len(todo)}")
    jdump(res, out)
    open(out + ".done", "w").close()


_PUNCT = re.compile(r"[\s　、。，．,.!?！？…・「」『』（）()〜~]")


def align_from_words(cues_path, words_path, out):
    """Word timings from an existing transcript's word list instead of Whisper. words_path is JSON with
    {"words": [{"text", "start", "end"}, ...]} (Soniox export) or a bare list of those. Each cue's text is
    found in the word stream near its start time, ignoring punctuation and spaces on both sides (subtitle
    files often drop or change punctuation). Returns (matched, total); unmatched cues are left out, so the
    Whisper job can still align just those."""
    data = jload(words_path)
    chars, times = [], []  # one entry per non-punctuation character of the word stream
    for w in data["words"] if isinstance(data, dict) else data:
        for ch in _PUNCT.sub("", w["text"]):
            chars.append(ch)
            times.append((w["start"], w["end"]))
    stream = "".join(chars)
    cues = [c for c in jload(cues_path) if c["text"]]
    res, ptr = jload(out, {}), 0
    for c in cues:
        keep = [k for k, ch in enumerate(c["text"]) if not _PUNCT.match(ch)]
        norm = "".join(c["text"][k] for k in keep)
        if not norm:
            continue
        lo = next((i for i in range(ptr, len(times)) if times[i][0] >= c["start"] - 2), ptr)
        at = stream.find(norm, max(0, lo - 50), lo + 400 + len(norm) * 3)
        if at < 0:
            continue
        res[str(c["cue"])] = [[k, k + 1, round(times[at + j][0], 3), round(times[at + j][1], 3)]
                              for j, k in enumerate(keep)]
        ptr = at + len(norm)
    jdump(res, out)
    n = sum(1 for c in cues if str(c["cue"]) in res)
    if n == len(cues):
        open(out + ".done", "w").close()
    return n, len(cues)


# ---------- placement (background) ----------

def place(cues_path, video, out):
    """Score grid spots per cue by edge density over 3 frames (lower = emptier). {cue: [[x, y, score]...]}."""
    import numpy as np
    W, H = 320, 240

    def frame(t):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", video, "-frames:v", "1",
                              "-vf", f"scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                             capture_output=True).stdout
        if len(raw) != W * H:
            return np.zeros((H, W), np.float32)
        img = np.frombuffer(raw, np.uint8).reshape(H, W).astype(np.float32)
        return np.abs(np.diff(img, axis=1))[:-1, :] + np.abs(np.diff(img, axis=0))[:, :-1]

    res = {}
    bw, bh = PLACE_BOX * H * 0.9, PLACE_BOX * H
    for c in jload(cues_path):
        s, e = c["start"], c["end"]
        maps = [frame(t) for t in (s + 0.2, (s + e) / 2, max(s + 0.2, e - 0.2))]
        spots = []
        for y in GRID_Y:
            for x in GRID_X:
                x0, y0 = max(0, int(x * W - bw / 2)), max(0, int(y * H - bh / 2))
                x1, y1 = int(x * W + bw / 2), int(y * H + bh / 2)
                score = max(float(m[y0:y1, x0:x1].mean()) for m in maps)
                if abs(x - 0.5) < 0.05:
                    score *= 1 + CENTRE_PENALTY  # characters are usually framed in the middle
                spots.append([x, y, round(score, 2)])
        res[str(c["cue"])] = sorted(spots, key=lambda p: p[2])
    jdump(res, out)
    open(out + ".done", "w").close()
