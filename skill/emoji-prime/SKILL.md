---
name: emoji-prime
description: Build an "emoji prime" overlay for a Japanese video, so emoji and Irasutoya illustrations pop up over it in mpv as each word is spoken, with no English. Each line also gets an emoji "rebus" that builds up word by word. Use when the user says "emoji prime", "emoji overlay", "emoji-prime this", "pictures over the video as words are said", or gives a Japanese video/episode to prime with pictures.
---

# Emoji prime

Emoji prime puts pictures over a Japanese video as each word is said:

- Emoji and Irasutoya illustrations for individual words, in the sense used on that line.
- One or two illustrations per sentence.
- A sentence "rebus" strip that builds up emoji by emoji (👂❓ for なに, 💰🚫❓ for お金なかったんじゃ).

Pictures are tilted stickers placed in the emptiest part of the frame. Each appears as its word starts and stays about 1s after it. Nothing is ever in English.

All the mechanical work is in `scripts/emoji_prime.py` in this skill's folder. The two judgement steps are prompt files, and you answer them.

## Workflow

Run every command with `python3 <skill dir>/scripts/emoji_prime.py`. Pass the same `VIDEO` path (and `--out`, if used) to each command.

### 0. Dependencies

Check, and install only what's missing:

- CLI tools: `ffmpeg`, `ffprobe`, `mpv`.
- Python packages: `pip show fugashi unidic-lite pillow numpy stable-ts`.
  - Install with `pip install -r <skill dir>/requirements.txt`.
  - `stable-ts` pulls in PyTorch, which is big. If the user has an NVIDIA GPU, a CUDA build of torch makes alignment about 10× faster.

### 1. Prepare

```
emoji_prime.py prepare VIDEO
```

- **Subtitles:** it finds Japanese subtitles in this order:
  1. a sidecar `.ja.srt` / `.srt` / `.ass` / `.vtt`
  2. an embedded Japanese text track
  3. Whisper transcription (slow on CPU)

  Use `--subs FILE` to pick a file.
- **Tokenizing:** it tokenizes with fugashi/UniDic.
- **Set phrases:** it marks common set phrases (先週, お疲れ様, …) from the shared list on the emoji-prime server. These always get their fixed emoji, so the step-A prompts show them as `set` and the LLM builds the rest around them.
- **Word timings:** if the subtitles came from a transcription service with word timings (e.g. Soniox), pass that JSON with `--word-times FILE` (`{"words": [{"text", "start", "end"}, ...]}`, or a bare list). A sidecar `<stem>.soniox.json` is picked up automatically. Lines are matched ignoring punctuation, and this replaces Whisper alignment. Any lines it can't match still go to Whisper.
- **Background jobs:** it starts word alignment (Whisper, skipped when word timings matched every line) and placement scoring in the background. Alignment takes about 5–10 min per 20-min episode on a GPU, and much longer on CPU.
- **Prompts:** it writes step-A prompts to `_build/llm/A_NN.md`.

Output goes to `<video stem>.emojiprime/` next to the video. If that folder isn't writable, pass `--out DIR`.

Prompts are big on purpose: every subagent pays a fixed overhead, so fewer, larger prompts use far fewer tokens. The defaults are 120 cues per step-A prompt (`prepare --chunk`) and 400 items per step-B prompt (`candidates --chunk`), so a 90-minute stream is about 18 A prompts and 5 B prompts. For a YouTube video, also pass `--youtube VIDEO_ID` so the browser pack records which video it belongs to.

### 2. Answer the step-A prompts

The output of `prepare` lists each `A_NN.md` with the `A_NN.json` it needs. Answer every prompt that has no `.json` yet:

- **Preferred:** one subagent **per prompt**, at most 3 running at once. Don't give one subagent several prompts: each turn resends everything before it, so the cost grows faster than the work.
  - Use the `emoji-prime-answerer` agent type if it's installed. It has only Read and Write, so it carries far less overhead than a general-purpose agent. The install copies `agents/emoji-prime-answerer.md` into `~/.claude/agents/`. If it isn't installed, use a general-purpose agent with model `sonnet`.
  - Step A needs Sonnet (the agent's default).
  - Give each one exactly this, with no paraphrase:
    `Read <A_NN.md path> and do what it asks. Write only the JSON object (no prose, no code fences) to the path given in its first line. Reply only "done".`
- **Without subagents:** read each prompt yourself and write its JSON file.
- Don't edit the prompts. Each one is self-contained: senses and emoji per word, a rebus anchored to the words, and illustration search words.

### 3. Candidates

```
emoji_prime.py candidates VIDEO
```

This checks the A answers and lists any prompt that is still missing an answer. It then searches the Irasutoya catalog on the emoji-prime server (api.fazon.nexus; only the search words are sent) and writes `_build/llm/B_NN.md` (picking illustrations). Answer those like step 2, but with model `haiku`: picking a title by index is easy, and Haiku costs much less of the user's usage.

### 4. Build

```
emoji_prime.py build VIDEO
```

This downloads the chosen illustrations into `~/.cache/emoji-prime/` and waits for the background jobs if they're still running. It then writes `overlay.json` and `img/`, and prints the mpv command.

Useful while waiting: `emoji_prime.py status VIDEO` shows what's done.

It also writes `web.json`, the pack for the **YouTube Emoji Prime** browser extension (text emoji + Irasutoya URLs, ~1 MB for 2 h), so the same pictures can play over the YouTube upload. The extension is in the emojiPrime repo's Releases (https://github.com/SomeRandomGuy64/emojiPrime/releases): the user loads `web.json` from its panel on the video's page.

### 5. Watch

Give the user the printed command:

```
mpv --script=<skill dir>/mpv/emoji_prime.lua VIDEO
```

Shift+E toggles the pictures.

To make it automatic, `emoji_prime.lua` can be copied into the mpv scripts folder:

- Linux/macOS: `~/.config/mpv/scripts/`
- Windows: `%APPDATA%\mpv\scripts\`

Then any video with a `<stem>.emojiprime/` folder beside it shows its pictures. This is a persistent change to their mpv setup, so ask before doing it. The script does nothing for videos without the folder.

## Tuning

These are `build` flags:

- `--pre 0.1`: how early pictures appear, in seconds.
- `--stay 1.0`: how long a picture stays after its word ends.

Re-running `build` is cheap. It doesn't redo the LLM steps or the alignment.

To redo a single step, delete its outputs in `_build/`:

- `A_*.json` or `B_*.json` for the LLM steps
- `align.json*` for the alignment
- `placement.json*` for the placement

Then re-run from that step.

## Without subagents

Agents that can't start subagents answer the `A_NN.md` / `B_NN.md` prompts themselves, one at a time, as in step 2.


Or `emoji_prime.py auto VIDEO` runs every step itself:

- `--llm claude` (default) uses the `claude` CLI headless and needs a logged-in Claude Code.
- `--llm openrouter` uses `OPENROUTER_API_KEY`. This costs money: roughly $1 per 20-min episode with Sonnet.

Only use `auto` when the user asks for it, because it spends their usage.

## Notes

- The idea is Elliot DeBruyn's, from the MattvsJapan Immersion Dojo.
- Japanese only. Any video works if it has Japanese speech: anime, YouTube, drama.
- Irasutoya (いらすとや) illustrations are free for personal use. The tool downloads each one only when it's picked, and doesn't redistribute anything. The catalog (titles and image links) lives on the emoji-prime server. `emoji_prime.py catalog --search WORD` shows what the candidates step would find for a word, and `emoji_prime.py phrases [WORD]` lists the set phrases.
- To add set phrases, follow `phrases/README.md` in the emojiPrime repo: three independent emoji translations, a blind vote, then a PR to `phrases/phrases.tsv`. The server picks up merged phrases within an hour.
- If alignment fails on a line, that line's pictures fall back to timings spread evenly across it.
