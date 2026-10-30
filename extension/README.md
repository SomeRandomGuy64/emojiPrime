# YouTube Emoji Prime (browser extension)

This extension plays an emoji-prime pack (`web.json`, written by the skill's `build` step) over the YouTube upload of a video. It's the browser counterpart of `skill/emoji-prime/mpv/emoji_prime.lua`. Install and usage are in the [main README](../README.md#youtube-browser-extension).

## Layout

| Path | What |
|---|---|
| `src/content.js` | the overlay and the 🖼️ panel, injected into youtube.com |
| `src/panel.css` | panel and sticker styles (class prefix `yep-`) |
| `src/background.js` | fallback image loader (see below) |
| `manifests/<browser>.json` | one manifest per browser; everything else is shared |
| `test/mock.html` | a fake YouTube player for testing without youtube.com |
| `test/firefox_smoke.py` | loads the Firefox build into headless Firefox on real YouTube |

`python3 build.py` at the repo root copies `src/` plus a manifest into `dist/<browser>/` and zips it.

## How it works

- Word pictures, the rebus and illustrations can each be shown or hidden from the panel. This only filters by item kind, so existing packs work as they are.
- The pictures are drawn in a layer sized to the visible video picture, so letterboxing and fullscreen line up. Times come from `video.currentTime`, read every frame while the video plays.
- Emoji are drawn as text with the system emoji font. The rebus strip has one span per chunk, each unhidden at its reveal time.
- Irasutoya pictures load straight from Blogger's image host. If the page refuses one, `background.js` fetches it and hands it back as a data URL.
- Packs live in extension storage per YouTube video id (`unlimitedStorage` is on, since a 2-hour stream's pack is about 1 MB). The sync offset is saved per video, and the size and layer choices globally.

## Firefox

Firefox runs the same `src/`. Its manifest differs from Chrome's in three ways:

- `background.scripts` (an event page) instead of `background.service_worker`, which Firefox MV3 doesn't support.
- A gecko id, `youtube-emoji-prime@fazon.nexus`, which Firefox needs for storage and signing.
- `data_collection_permissions: none`, which AMO requires from Firefox 140.

`chrome.*` callbacks work in Firefox as they are, so the code needs no polyfill.

Still to do:
- Sign it through AMO (an unlisted listing is enough) so release Firefox keeps it installed, then add the `.xpi` to Releases.
- Test watching for a long stretch in headed Firefox, and check that a pack survives a page reload.
- Test the `background.js` image fallback, which has never been triggered in testing.

## Testing

**Firefox:** `test/firefox_smoke.py` (needs `pip install selenium`) loads the Firefox build as a temporary add-on into headless, muted Firefox on real YouTube. It loads a pack through the panel, seeks to a busy moment, and checks that stickers draw and the illustrations load. Run it after `python3 build.py firefox`.

**Chrome:** the extension can't be injected into youtube.com from an automated Chrome, so `test/mock.html` provides a fake `#movie_player` with a stubbed `chrome.storage`.

1. Put a muted `clip.mp4` in `test/`, plus a `pack.js` containing `window.__pack = <contents of web.json>;`. Both are git-ignored.
2. Serve the `extension/` folder over HTTP (for example `python3 -m http.server`).
3. Open `test/mock.html?v=test`.
