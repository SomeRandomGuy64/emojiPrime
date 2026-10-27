# Installing emoji prime (instructions for an AI coding agent)

You are an AI coding agent (Claude Code, Codex, or similar), and a user has asked you to install emoji prime. Follow these steps in order. Talk to the user in plain language, and ask before anything marked **ask first**.

Repo: https://github.com/SomeRandomGuy64/emojiPrime

## 1. Get the skill

The skill is the folder `skill/emoji-prime/` in this repo. It must end up as `<skills dir>/emoji-prime/SKILL.md`. Where `<skills dir>` is depends on which agent you are:

| Agent | Skills folder |
|---|---|
| Claude Code | `~/.claude/skills/` |
| Codex | `~/.codex/skills/` |
| Anything else | wherever you load `SKILL.md` skills from. If you have no skills system, put the repo somewhere permanent and, whenever the user asks for an emoji prime, read `skill/emoji-prime/SKILL.md` and follow it. |

If the user already cloned the repo, use that clone. Otherwise clone it somewhere permanent (e.g. `~/emojiPrime`). Then either:

- **symlink** `<skills dir>/emoji-prime` → `<clone>/skill/emoji-prime`, so `git pull` updates the skill (preferred on Linux/macOS), or
- **copy** the folder there (on Windows, or if the user doesn't want a clone).

Without git: download `emoji-prime-skill.zip` from https://github.com/SomeRandomGuy64/emojiPrime/releases/latest/download/emoji-prime-skill.zip and unzip it into `<skills dir>` (it unzips to `emoji-prime/`).

If `<skills dir>/emoji-prime` already exists, don't overwrite it: show the user what's there and ask.

## 2. Dependencies

Check each one, and install only what's missing:

- **CLI tools:** `ffmpeg`, `ffprobe`, `mpv` (on PATH). Use the system package manager (apt/dnf/pacman, Homebrew, winget/scoop).
- **Python 3.9+** packages from `skill/emoji-prime/requirements.txt`: `fugashi`, `unidic-lite`, `pillow`, `numpy`, `stable-ts`. Check with `pip show`, then `pip install -r <skills dir>/emoji-prime/requirements.txt`. If the user's Python is externally managed (PEP 668), use their usual approach (a venv, `pipx`, or `--user`) and ask if unsure.
- `stable-ts` pulls in PyTorch, which is a big download. If the machine has an NVIDIA GPU (`nvidia-smi` works), a CUDA build of torch makes word alignment about 10× faster. Mention this, and if the user wants it, install the CUDA build that matches their driver.

Check it works: `python3 <skills dir>/emoji-prime/scripts/emoji_prime.py catalog --search 猫` should print a few いらすとや titles.

## 3. mpv script (ask first)

The skill already gives a command that loads the player script for one run (`mpv --script=...`), so this step is optional. To make it automatic, copy `skill/emoji-prime/mpv/emoji_prime.lua` into the mpv scripts folder:

- Linux/macOS: `~/.config/mpv/scripts/`
- Windows: `%APPDATA%\mpv\scripts\`

It does nothing for videos that have no `<stem>.emojiprime/` folder beside them. It changes the user's mpv setup, so ask before doing it.

## 4. Browser extension (optional, ask first)

The extension plays the same pictures over the YouTube upload of a video. Ask whether the user wants it, and which browser.

- **Chrome / Chromium / Edge / Brave:** download https://github.com/SomeRandomGuy64/emojiPrime/releases/latest/download/youtube-emoji-prime-chrome.zip and unzip it to a permanent folder (e.g. `~/emojiPrime-extension`; Chrome loads it from there every time). Then tell the user to open `chrome://extensions`, turn on **Developer mode**, click **Load unpacked** and pick that folder. You can't click through the browser for them.
- **Firefox (beta, unsigned):** this needs the clone. Run `python3 <clone>/build.py firefox`, then tell the user to open `about:debugging#/runtime/this-firefox`, click **Load Temporary Add-on…**, and pick `<clone>/dist/firefox/manifest.json`. Warn them that a temporary add-on, and the packs stored in it, is removed when Firefox closes. If they use Firefox Developer Edition, Nightly or ESR, they can install it permanently instead: see the Firefox section of the README.

## 5. Tell the user how to use it

Say something like:

> Emoji prime is installed. Give me a Japanese video (a file path) and say "emoji prime this". I'll prepare it, pick the pictures using subagents (this uses your AI usage, not a separate bill), and give you the mpv command to watch it. Japanese subtitles beside the video help a lot. Without them I'll transcribe it with Whisper, which is slow on CPU. For YouTube, download the video too (360p is enough) and tell me its YouTube id, and I'll make a pack for the browser extension.

Don't run a video through it as a test unless the user asks: it spends their usage.
