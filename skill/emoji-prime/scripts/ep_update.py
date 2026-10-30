"""Keeps the installed skill level with the repo's main branch. Never stops the skill: if anything goes wrong it says
so and the installed version carries on. EMOJI_PRIME_NO_UPDATE=1 turns it off."""
import filecmp, json, os, shutil, subprocess, tempfile, urllib.request, zipfile

REPO = "SomeRandomGuy64/emojiPrime"
SKILL_PATH = "skill/emoji-prime"
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARKER = ".installed_commit"
COPIES = [("agents/emoji-prime-answerer.md", "~/.claude/agents/emoji-prime-answerer.md"),
          ("mpv/emoji_prime.lua", "~/.config/mpv/scripts/emoji_prime.lua")]  # install steps that copy a skill file out


def _get(url, timeout):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "emoji-prime"}), timeout=timeout)


def _git(cwd, *args):
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=60, env=env)
    return r.stdout.strip() if r.returncode == 0 else None


def _checkout(skill_dir):
    """The repo's root if the skill is running from a git clone of it (a symlinked install, say), else None."""
    real = os.path.realpath(skill_dir)
    try:
        top = _git(real, "rev-parse", "--show-toplevel")
    except (OSError, subprocess.SubprocessError):
        return None
    return top if top and os.path.realpath(os.path.join(top, SKILL_PATH)) == real else None


def _pull(top):
    """Only fast-forwards a clean main: a clone on another branch or with local changes is someone's work."""
    if _git(top, "rev-parse", "--abbrev-ref", "HEAD") != "main" or _git(top, "status", "--porcelain") != "":
        print("skill: a git checkout on another branch or with local changes, leaving it alone")
        return False
    before = _git(top, "rev-parse", "HEAD")
    if _git(top, "pull", "--ff-only", "-q") is None:
        print("skill: couldn't check for updates (git pull failed); carrying on with this version")
        return False
    if _git(top, "rev-parse", "HEAD") == before:
        print("skill: up to date")
        return False
    print("skill: UPDATED from git; re-read SKILL.md before continuing")
    return True


def _replace(skill_dir, commit):
    """Downloads that commit next to the skill and swaps it in whole, so a failed update changes nothing."""
    parent = os.path.dirname(os.path.realpath(skill_dir))
    with tempfile.TemporaryDirectory(prefix=".emoji-prime-update-", dir=parent) as tmp:
        archive = os.path.join(tmp, "repo.zip")
        with _get(f"https://github.com/{REPO}/archive/{commit}.zip", 120) as r, open(archive, "wb") as f:
            shutil.copyfileobj(r, f)
        with zipfile.ZipFile(archive) as z:
            z.extractall(tmp)
        new = os.path.join(tmp, f"{REPO.split('/')[1]}-{commit}", *SKILL_PATH.split("/"))
        if not os.path.isfile(os.path.join(new, "SKILL.md")) or not os.path.isfile(os.path.join(new, "scripts", "emoji_prime.py")):
            raise RuntimeError("the download doesn't look like the skill")
        with open(os.path.join(new, MARKER), "w", encoding="utf-8") as f:
            f.write(commit + "\n")
        old_dir, real = os.path.join(tmp, "old"), os.path.realpath(skill_dir)
        os.rename(real, old_dir)
        try:
            os.rename(new, real)
        except OSError:
            os.rename(old_dir, real)
            raise
        for src, dst in COPIES:  # a copy the user edited stays theirs
            old, dst = os.path.join(old_dir, src), os.path.expanduser(dst)
            if os.path.isfile(old) and os.path.isfile(dst) and filecmp.cmp(old, dst, shallow=False):
                shutil.copy(os.path.join(real, src), dst)
        reqs = [os.path.join(d, "requirements.txt") for d in (old_dir, real)]
        return os.path.isfile(reqs[0]) and filecmp.cmp(*reqs, shallow=False)


def update(skill_dir=SKILL_DIR):
    """Brings the skill up to date; True if it changed, so the caller knows to re-read SKILL.md."""
    if os.environ.get("EMOJI_PRIME_NO_UPDATE"):
        print("skill: update check turned off (EMOJI_PRIME_NO_UPDATE)")
        return False
    try:
        top = _checkout(skill_dir)
        if top:
            return _pull(top)
        url = f"https://api.github.com/repos/{REPO}/commits?sha=main&path={SKILL_PATH}&per_page=1"
        with _get(url, 10) as r:
            commit = json.load(r)[0]["sha"]
        marker = os.path.join(skill_dir, MARKER)
        have = open(marker, encoding="utf-8").read().strip() if os.path.exists(marker) else None
        if have == commit:
            print("skill: up to date")
            return False
        same_reqs = _replace(skill_dir, commit)
    except Exception as e:
        print(f"skill: couldn't check for updates ({e}); carrying on with this version")
        return False
    print(f"skill: UPDATED to {commit[:7]}; re-read SKILL.md before continuing")
    if not same_reqs:
        print("skill: requirements.txt changed; run pip install -r on it")
    return True
