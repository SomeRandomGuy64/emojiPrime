# Emoji prime

Emoji prime shows pictures over a Japanese video at the moment each word is spoken, so you can follow what's being said with no English at all:

- **Word pictures:** an emoji or an [Irasutoya](https://www.irasutoya.com/) (いらすとや) illustration for each word, in the sense it has on that line. For example, 飲み込む (nomikomu, "swallow") said of a whirlpool gets 🌀, not 😋.
- **Sentence illustrations:** one or two Irasutoya illustrations that carry the gist of a line.
- **Sentence rebus:** a strip of emoji that builds up word by word, including grammar and tone: ❓ for questions, 🚫 for negation, 🙏 for wanting something. なに (nani, "what?") becomes 👂❓.
- **Set phrases:** about 100 common phrases always get the same emoji, so they become a visual vocabulary. 先週 (senshuu, "last week") is always ⏪🗓️ and お疲れ様 (otsukaresama) is always 🙇💦. See [`phrases/`](phrases).

The pictures are tilted, vlog-style stickers in the emptiest part of the frame. Each appears as its word starts and stays about a second after it ends. They play in **mpv** for local files, and in a **browser extension** for YouTube.

**The idea is Elliot DeBruyn's, from the [MattvsJapan](https://www.youtube.com/@mattvsjapan) Immersion Dojo.** He suggested pictures instead of subtitles, then pushed for more, denser and more complex ones, which is what this became.

## Install

Emoji prime is an AI agent skill. Two of its steps are judgement calls (which sense a word has, and which picture fits it), and an LLM makes them. So the easiest way to install it is to have your agent do it.

### With an AI agent (recommended)

Paste this into **Claude Code**, **Codex**, or any coding agent that can run commands:

```text
Install emoji prime by following https://raw.githubusercontent.com/SomeRandomGuy64/emojiPrime/main/INSTALL.md
```

The agent clones the repo, puts the skill where it loads skills from, checks the dependencies, and asks before touching your mpv or browser setup. Then give it a video:

```text
emoji prime ~/Videos/some_episode.mkv
```

### By hand

1. Copy (or symlink) [`skill/emoji-prime/`](skill/emoji-prime) into your agent's skills folder: `~/.claude/skills/` for Claude Code, `~/.codex/skills/` for Codex. Or download `emoji-prime-skill.zip` from [Releases](https://github.com/SomeRandomGuy64/emojiPrime/releases/latest) and unzip it there.
2. Install `ffmpeg` and `mpv`, then the Python packages:
   ```bash
   pip install -r skill/emoji-prime/requirements.txt
   ```
   `stable-ts` installs PyTorch. A CUDA GPU makes word alignment about 10× faster: roughly 5–10 minutes per 20-minute episode, versus much longer on CPU.
3. Ask your agent to "emoji prime" a video.

### Without an agent

The skill's script can call an LLM itself:

```bash
python3 skill/emoji-prime/scripts/emoji_prime.py auto VIDEO --llm claude        # the `claude` CLI, logged in
OPENROUTER_API_KEY=... python3 skill/emoji-prime/scripts/emoji_prime.py auto VIDEO --llm openrouter   # ~$1 per 20-min episode
```

Or run the steps yourself: `prepare`, then answer the prompt files in `<stem>.emojiprime/_build/llm/` with any LLM (each `X_NN.md` says which `X_NN.json` to write), then `candidates`, answer those, then `build`. `status VIDEO` shows where you are.

## Watch

### mpv

```bash
mpv --script=skill/emoji-prime/mpv/emoji_prime.lua VIDEO
```

Shift+E toggles the pictures. If you copy `emoji_prime.lua` into your mpv scripts folder (`~/.config/mpv/scripts/` on Linux/macOS, `%APPDATA%\mpv\scripts\` on Windows), plain `mpv VIDEO` works for any video with a `<stem>.emojiprime/` folder beside it.

### YouTube (browser extension)

`build` also writes `web.json`, a pack the **YouTube Emoji Prime** extension plays over the YouTube upload of the same video. To make one, download the video (360p is enough; it's only used to find empty parts of the frame) and pass `--youtube VIDEO_ID` to `prepare`. Your agent does this if you tell it the video is on YouTube.

**Chrome / Chromium / Edge / Brave**

1. Download `youtube-emoji-prime-chrome.zip` from [Releases](https://github.com/SomeRandomGuy64/emojiPrime/releases/latest) and unzip it to a folder you'll keep.
2. Open `chrome://extensions`, turn on **Developer mode**, click **Load unpacked**, and pick that folder.

**Using it**

1. Open the video on YouTube. The 🖼️ **Emoji Prime** panel sits at the top right of the player; click **+** to open it.
2. Click **Load web.json pack…** and choose the pack. It's saved for that video, so it loads by itself next time.
3. **Shift+E** toggles the pictures. **Sync offset** shifts them in time if the upload is trimmed differently from your file, and **Size** scales them.

**Firefox (beta)**

The Firefox version runs the same code as the Chrome one and has passed a smoke test on YouTube. It isn't signed by Mozilla yet, and release Firefox only keeps signed add-ons installed, so for now:

1. In a clone of this repo, run `python3 build.py firefox`.
2. Open `about:debugging#/runtime/this-firefox`, click **Load Temporary Add-on…**, and pick `dist/firefox/manifest.json`.

A temporary add-on is removed when Firefox closes. Packs you loaded are stored with it and go too, so keep your `web.json` files. On Firefox Developer Edition, Nightly or ESR you can set `xpinstall.signatures.required` to `false` in `about:config` and install `dist/youtube-emoji-prime-firefox.zip` permanently from `about:addons` → ⚙ → **Install Add-on From File…**.

## Subtitles and timings

Japanese subtitles help a lot. The tool looks for them in this order:

1. a sidecar `.ja.srt`, `.srt`, `.ass` or `.vtt` beside the video
2. an embedded Japanese text track
3. if there are none, it transcribes the audio with Whisper

Image subtitles (PGS) can't be read. `--subs FILE` picks a file.

If your subtitles came from a service with word timings (e.g. Soniox: `{"words": [{"text", "start", "end"}]}`), pass `--word-times FILE` or put it beside the video as `<stem>.soniox.json`. It replaces Whisper alignment for every line it can match.

## Modes: how much usage it spends

`prepare --mode` picks how much of the work an LLM does:

| Mode | What the LLM does | Cost |
|---|---|---|
| `high` (default) | every word's sense and emoji, the sentence rebus, and the illustration picks (steps A and B) | the most; the best result |
| `medium` | picks which of a word's 2–3 dictionary senses each line uses, plus one tone emoji and one gist-illustration word per line (step M, Haiku) | about a fifth of high |
| `low` | nothing: each word gets its most common dictionary sense | free |

Medium and low use the **picture dictionary** in [`dict/`](dict): about 40,000 words, each with up to 3 senses (a short Japanese gloss, an emoji, sometimes an Irasutoya illustration), and about 950 idioms that are pictured as a whole (我に返る 😳💡, not 🏠 for 返る). Their rebus is built from the word emoji, set phrases, idioms and grammar (ない 🚫, た ⏪, か ❓). `dict/build_dict.py` rebuilds the dictionary: word frequency from YouTube and anime subtitles plus JPDB, senses and illustrations harvested from high-mode runs, and Sonnet for the rest.

## The Irasutoya catalog and the emoji-prime server

Picture candidates come from a catalog of all ~25,000 Irasutoya posts: titles, descriptions, labels and image links, but no images. The catalog lives on the emoji-prime server at `api.fazon.nexus`, so the skill stays small and nobody has to download it. The server refreshes it from Irasutoya's public feed every week and also serves the [set phrases](phrases) and the picture dictionary, which it pulls from this repo's `phrases/` and `dict/` every hour.

What the skill sends the server: the Japanese search words for picture candidates (dictionary-form words like 猫 or 驚く), requests for the phrase and idiom lists, and in medium and low mode the video's distinct dictionary-form words, to look up their senses. Lines, timings and video files never leave your machine. Each picked illustration is downloaded straight from Irasutoya's image host into `~/.cache/emoji-prime/` (set `EMOJI_PRIME_CACHE` to move it). The phrase list is cached there too, so a run still works if the server is down. Only picture search needs it.

```bash
python3 skill/emoji-prime/scripts/emoji_prime.py catalog --search 猫 驚く     # what the candidates step would find
python3 skill/emoji-prime/scripts/emoji_prime.py phrases 週                   # the set phrases containing 週
```

`EMOJI_PRIME_API` points the skill at another server. `EMOJI_PRIME_DICT=dict` makes medium and low read the picture dictionary from this repo's `dict/` folder instead (offline, or to try a rebuild before it's pushed).

Irasutoya's illustrations are free for personal use under [their terms](https://www.irasutoya.com/p/terms.html).

## Repo layout

| Path | What |
|---|---|
| [`INSTALL.md`](INSTALL.md) | install steps written for an AI agent |
| [`skill/emoji-prime/`](skill/emoji-prime) | the skill: copy this folder into your skills folder |
| ├ `SKILL.md` | the workflow the agent follows |
| ├ `agents/emoji-prime-answerer.md` | lean Read/Write subagent for answering the prompts (Claude Code: copy to `~/.claude/agents/`) |
| ├ `scripts/emoji_prime.py` | the CLI: `prepare` / `candidates` / `build` / `auto` / `status` / `catalog` |
| ├ `scripts/ep_media.py` | subtitles, tokenizing (fugashi), Whisper alignment, placement scoring |
| ├ `scripts/ep_overlay.py` | timing and layout → `overlay.json`, images and `web.json` |
| ├ `scripts/ep_common.py` | SRT reading, emoji rendering, the sticker look |
| ├ `scripts/ep_irasutoya.py` | illustration download |
| ├ `scripts/ep_api.py` | the emoji-prime server: catalog search, set phrases and their matching |
| └ `mpv/emoji_prime.lua` | the mpv player script |
| [`phrases/`](phrases) | the set phrases and the prompts used to make them |
| [`dict/`](dict) | the picture dictionary (`senses.json`, `idioms.json`) and `build_dict.py`, which builds it |
| [`extension/`](extension) | the YouTube extension: shared `src/`, one manifest per browser in `manifests/` |
| [`build.py`](build.py) | packages the release zips into `dist/` |
| [`extension/test/firefox_smoke.py`](extension/test/firefox_smoke.py) | headless Firefox smoke test on real YouTube |

Each video's output goes in `<stem>.emojiprime/` beside it. `overlay.json` and `img/` are what mpv plays, `web.json` is the browser pack, and `_build/` holds working files, so every step resumes from where it stopped.

## Releasing

```bash
python3 build.py      # dist/emoji-prime-skill.zip + dist/youtube-emoji-prime-<browser>.zip
```

Bump `version` in `extension/manifests/*.json`, then attach the zips to a GitHub release. The zip names carry no version, so `releases/latest/download/<name>` links keep working. The server side (the catalog and phrases API) isn't released from here: it's part of fazond, the fazon.nexus backend.

## Credits

- **Elliot DeBruyn** (MattvsJapan Immersion Dojo): the idea, and the push towards denser pictures.
- **Andrew Balint** (MattvsJapan Immersion Dojo): feedback which led me to use an SQLite database and for letting me know about **Fred Benenson's *Emoji Dick***.
- **Fred Benenson's *Emoji Dick*** for the translate-three-times-then-vote method behind the set phrases.
- **いらすとや** (Takashi Mifune) for the illustrations, and **Noto Color Emoji** for the emoji.
- [fugashi](https://github.com/polm/fugashi) + UniDic for tokenizing, and [stable-ts](https://github.com/jianfch/stable-ts) / Whisper for word alignment.

MIT licence (see [LICENSE](LICENSE)). The licence covers the code only, not Irasutoya's illustrations or the emoji font.
