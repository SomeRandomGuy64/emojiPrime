#!/usr/bin/env python3
"""Smoke-test the Firefox build on real YouTube, headless and muted.

    pip install selenium          (Selenium Manager fetches geckodriver)
    python3 build.py firefox
    python3 extension/test/firefox_smoke.py WEB_JSON YOUTUBE_ID [--at SECONDS] [--shot out.png]

It installs dist/youtube-emoji-prime-firefox.zip as a temporary add-on, opens the video, loads the pack
through the panel, seeks to --at (default: the first moment with an illustration, an emoji and a rebus
on screen) and reports how many stickers are drawn and whether the illustrations loaded.
Headless Firefox often stalls buffering after a seek; the overlay still draws at the seeked time.
"""
import argparse, json, os, sys, time

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def busy_moment(pack_path):
    items = json.load(open(pack_path, encoding="utf-8"))["items"]
    for t in range(0, int(max(i["e"] for i in items))):
        up = [i for i in items if i["s"] <= t + 0.5 <= i["e"]]
        if any("u" in i for i in up) and any("em" in i for i in up) and any(i["k"] == "rebus" for i in up):
            return t + 0.5
    return 60.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pack")
    ap.add_argument("video_id")
    ap.add_argument("--at", type=float)
    ap.add_argument("--shot", default="firefox_smoke.png")
    a = ap.parse_args()
    at = a.at if a.at is not None else busy_moment(a.pack)

    o = Options()
    o.add_argument("-headless")
    o.set_preference("media.volume_scale", "0.0")
    o.set_preference("media.autoplay.default", 0)
    d = webdriver.Firefox(options=o)
    d.set_window_size(1400, 900)
    ok = False
    try:
        d.install_addon(os.path.join(ROOT, "dist", "youtube-emoji-prime-firefox.zip"), temporary=True)
        d.get(f"https://www.youtube.com/watch?v={a.video_id}")
        time.sleep(6)
        for b in d.find_elements(By.CSS_SELECTOR, "button"):  # consent wall: reject non-essential
            if "Reject" in (b.get_attribute("aria-label") or b.text or ""):
                b.click()
                time.sleep(5)
                break
        for _ in range(20):
            if d.find_elements(By.CSS_SELECTOR, ".yep-panel"):
                break
            time.sleep(1)
        else:
            sys.exit("panel never appeared: the content script didn't run")
        d.find_element(By.CSS_SELECTOR, ".yep-file").send_keys(os.path.abspath(a.pack))
        time.sleep(2)
        d.execute_script("document.querySelector('.yep-panel').classList.remove('yep-collapsed')")
        print("pack:", d.execute_script("return document.querySelector('.yep-file-name').textContent"))
        for _ in range(30):  # wait out a skippable ad
            if not d.execute_script("return !!document.querySelector('.ad-showing')"):
                break
            d.execute_script("document.querySelector('.ytp-skip-ad-button,.ytp-ad-skip-button-modern')?.click()")
            time.sleep(1)
        d.execute_script(f"const p=document.getElementById('movie_player');p.mute();p.seekTo({at},true);p.playVideo()")
        n = 0
        for _ in range(10):
            time.sleep(1)
            n = max(n, d.execute_script("return document.querySelectorAll('.yep-sticker').length"))
        imgs = d.execute_script("return [...document.querySelectorAll('img.yep-img, .yep-img img')]"
                                ".map(i => i.complete && i.naturalWidth > 0)")
        print(f"at {at}s: {n} stickers, illustrations loaded: {sum(imgs)}/{len(imgs)}")
        d.save_screenshot(a.shot)
        print("screenshot:", a.shot)
        ok = n > 0 and all(imgs)
    finally:
        d.quit()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
