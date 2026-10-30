/* YouTube Emoji Prime
 * Browser port of emoji_prime.lua (mpv): pictures pop up over the video as each Japanese word is spoken.
 *
 * Data: a web.json "pack" made by the emoji-prime skill (emoji_prime.py build). Load it from the panel;
 * it's stored per YouTube video id and loads itself the next time you open that video.
 * Pack items (times in seconds, pos = video-relative centre, a = rotation in degrees, sc = size vs box):
 *   {k: "rebus", s, e, p, a, sc, ch: [emoji...], rv: [reveal time per chunk]}
 *   {k: "vlog" | "word", s, e, p, a, sc, u: illustration URL}  or  {..., em: "emoji"}
 */
(() => {
  "use strict";
  if (window.__yepLoaded) return;
  window.__yepLoaded = true;

  const OFFSET_STEP = 0.25;
  const SIZE_STEP = 10;
  const LAYERS = [["word", "Word pictures"], ["rebus", "Rebus"], ["vlog", "Illustrations"]];

  // ----------------------------- state -----------------------------
  let enabled = true;
  let sizePct = 100;            // user size multiplier (%)
  const layers = { word: true, rebus: true, vlog: true }; // which item kinds are shown
  let pack = null;              // {box, items, youtube}
  let packName = "";
  let maxDur = 0;               // longest item, bounds the active-item search
  let offset = 0;               // seconds added to item times (sync), per video
  let videoId = "";
  const live = new Map();       // item index -> element
  const imgCache = new Map();   // url -> data: URL (fallback loads only)
  let rafId = null;

  let player = null;
  let video = null;
  let layerEl = null;
  let osdEl = null;
  let osdTimer = null;
  let panelEl = null;

  // ----------------------------- storage -----------------------------
  const store = {
    get: (keys) => new Promise((ok) => { try { chrome.storage.local.get(keys, (r) => ok(r || {})); } catch (_) { ok({}); } }),
    set: (obj) => { try { chrome.storage.local.set(obj); } catch (_) {} },
    remove: (keys) => { try { chrome.storage.local.remove(keys); } catch (_) {} },
  };
  store.get(["enabled", "sizePct", "layers"]).then((r) => {
    if (typeof r.enabled === "boolean") enabled = r.enabled;
    if (typeof r.sizePct === "number") sizePct = r.sizePct;
    if (r.layers) Object.assign(layers, r.layers);
    updatePanel();
  });

  // ----------------------------- helpers -----------------------------
  function osd(msg, ms = 1400) {
    if (!osdEl) return;
    osdEl.textContent = msg;
    osdEl.classList.add("yep-show");
    clearTimeout(osdTimer);
    osdTimer = setTimeout(() => osdEl.classList.remove("yep-show"), ms);
  }

  function currentVideoId() {
    try { return new URL(location.href).searchParams.get("v") || ""; } catch (_) { return ""; }
  }

  // The video's visible picture inside the player (object-fit: contain letterboxing).
  function contentRect() {
    const pr = player.getBoundingClientRect();
    const vr = video.getBoundingClientRect();
    const vw = video.videoWidth || 16, vh = video.videoHeight || 9;
    const s = Math.min(vr.width / vw, vr.height / vh);
    const w = vw * s, h = vh * s;
    return { left: vr.left - pr.left + (vr.width - w) / 2, top: vr.top - pr.top + (vr.height - h) / 2, w, h };
  }

  // ----------------------------- pack -----------------------------
  function setPack(p, name) {
    clearAll();
    pack = p;
    packName = name || "";
    maxDur = 0;
    if (pack) {
      pack.items.sort((x, y) => x.s - y.s);
      for (const it of pack.items) maxDur = Math.max(maxDur, it.e - it.s);
    }
    updatePanel();
  }

  function validPack(p) {
    return p && p.format === "emoji-prime-web" && Array.isArray(p.items) && typeof p.box === "number";
  }

  async function loadStoredPack() {
    const id = currentVideoId();
    if (id === videoId) return;
    videoId = id;
    setPack(null);
    offset = 0;
    if (!id) return;
    const r = await store.get([`pack:${id}`, `offset:${id}`]);
    if (id !== videoId) return; // navigated again meanwhile
    const saved = r[`pack:${id}`];
    if (typeof r[`offset:${id}`] === "number") offset = r[`offset:${id}`];
    if (saved && validPack(saved.pack)) {
      setPack(saved.pack, saved.name);
      osd(`🖼️ Emoji Prime: ${saved.pack.items.length} pictures loaded`);
    }
    updatePanel();
  }

  function loadPackText(raw, name) {
    let p;
    try { p = JSON.parse(raw); } catch (_) { osd("Not a JSON file"); return; }
    if (!validPack(p)) { osd("Not an emoji-prime web.json pack"); return; }
    const id = currentVideoId();
    if (!id) { osd("Open the YouTube video first, then load its pack"); return; }
    if (p.youtube && p.youtube !== id) osd(`⚠ This pack was made for video ${p.youtube}; loaded anyway`, 3000);
    else osd(`Loaded ${p.items.length} pictures`);
    store.set({ [`pack:${id}`]: { pack: p, name } });
    setPack(p, name);
    draw(true);
  }

  // ----------------------------- drawing -----------------------------
  function clearAll() {
    for (const el of live.values()) el.remove();
    live.clear();
  }

  function firstIndexAfter(t) { // first item with s > t
    const items = pack.items;
    let lo = 0, hi = items.length;
    while (lo < hi) { const m = (lo + hi) >> 1; if (items[m].s <= t) lo = m + 1; else hi = m; }
    return lo;
  }

  function setImage(img, url) {
    img.referrerPolicy = "no-referrer";
    if (imgCache.has(url)) { img.src = imgCache.get(url); return; }
    img.onerror = () => { // page refused it: fetch through the extension instead
      img.onerror = null;
      try {
        chrome.runtime.sendMessage({ type: "yep-fetch", url }, (r) => {
          if (r && r.ok) { imgCache.set(url, r.dataUrl); img.src = r.dataUrl; } else img.remove();
        });
      } catch (_) { img.remove(); }
    };
    img.src = url;
  }

  function makeEl(it) {
    let el;
    if (it.k === "rebus") {
      el = document.createElement("div");
      el.className = "yep-sticker yep-rebus";
      for (const ch of it.ch) {
        const s = document.createElement("span");
        s.textContent = ch;
        s.className = "yep-chunk";
        el.appendChild(s);
      }
    } else if (it.u) {
      el = document.createElement("img");
      el.className = "yep-sticker yep-img";
      el.alt = "";
      el.draggable = false;
      setImage(el, it.u);
    } else {
      el = document.createElement("div");
      el.className = "yep-sticker yep-emoji";
      el.textContent = it.em;
    }
    layerEl.appendChild(el);
    return el;
  }

  function place(el, it, rect) {
    const box = pack.box * rect.h * it.sc * (sizePct / 100);
    el.style.left = `${it.p[0] * rect.w}px`;
    el.style.top = `${it.p[1] * rect.h}px`;
    el.style.transform = `translate(-50%, -50%) rotate(${it.a || 0}deg)`;
    const outline = Math.max(1.5, box / 70);
    el.style.setProperty("--yep-o", `${outline.toFixed(1)}px`);
    if (it.k === "rebus") {
      const n = Math.max(1, Array.from(it.ch.join("")).length);
      el.style.fontSize = `${Math.min(box * 0.8, (box * 3.2) / n)}px`;
    } else if (it.u) {
      el.style.maxHeight = `${box * 0.9}px`;
      el.style.maxWidth = `${box * 0.86}px`;
    } else {
      const n = Math.max(1, Array.from(it.em).length);
      el.style.fontSize = `${Math.min(box * 0.7, (box * 1.8) / n)}px`;
    }
  }

  function draw(force = false) {
    if (!layerEl || !video) return;
    if (!pack || !enabled) { if (live.size) clearAll(); return; }
    const t = video.currentTime - offset;
    const items = pack.items;
    const end = firstIndexAfter(t);
    const want = new Set();
    for (let i = end - 1; i >= 0 && items[i].s >= t - maxDur; i--) {
      if (t < items[i].e && layers[items[i].k]) want.add(i);
    }
    for (const [i, el] of live) if (!want.has(i)) { el.remove(); live.delete(i); }
    const rect = contentRect();
    layerEl.style.left = `${rect.left}px`;
    layerEl.style.top = `${rect.top}px`;
    layerEl.style.width = `${rect.w}px`;
    layerEl.style.height = `${rect.h}px`;
    for (const i of want) {
      const it = items[i];
      let el = live.get(i);
      const fresh = !el;
      if (fresh) { el = makeEl(it); live.set(i, el); }
      if (fresh || force || el.dataset.h !== String(rect.h)) { place(el, it, rect); el.dataset.h = String(rect.h); }
      if (it.k === "rebus") {
        const kids = el.children;
        for (let j = 0; j < kids.length; j++) kids[j].classList.toggle("yep-hidden", t < it.rv[j]);
      }
    }
    if (panelEl) panelEl.querySelector(".yep-now").textContent = live.size ? `${live.size} on screen` : "";
  }

  function tick() {
    rafId = null;
    draw();
    if (video && !video.paused) rafId = requestAnimationFrame(tick);
  }
  function startRaf() { if (rafId == null) rafId = requestAnimationFrame(tick); }

  // ----------------------------- controls -----------------------------
  function setEnabled(v) {
    enabled = v;
    store.set({ enabled });
    osd(`Emoji Prime: ${enabled ? "on" : "off"}`);
    draw(true);
    updatePanel();
  }
  function setLayer(k, v) {
    layers[k] = v;
    store.set({ layers });
    draw(true);
    updatePanel();
  }
  function setOffset(v) {
    offset = Math.round(v * 100) / 100;
    if (videoId) store.set({ [`offset:${videoId}`]: offset });
    draw(true);
    updatePanel();
  }
  function setSize(v) {
    sizePct = Math.max(30, Math.min(300, Math.round(v)));
    store.set({ sizePct });
    draw(true);
    updatePanel();
  }

  function isTypingTarget(el) {
    if (!el) return false;
    const tag = (el.tagName || "").toLowerCase();
    return tag === "input" || tag === "textarea" || tag === "select" || el.isContentEditable;
  }
  function onKeyDown(e) {
    if (isTypingTarget(e.target) || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.shiftKey && (e.key === "E" || e.code === "KeyE")) {
      e.preventDefault();
      e.stopPropagation();
      setEnabled(!enabled);
    }
  }

  // ----------------------------- panel -----------------------------
  function buildPanel() {
    if (panelEl) return panelEl;
    const p = document.createElement("div");
    p.className = "yep-panel yep-collapsed";
    p.innerHTML = `
      <div class="yep-head">
        <span class="yep-title">🖼️ Emoji Prime</span>
        <button class="yep-collapse" title="Expand">+</button>
      </div>
      <div class="yep-body">
        <label class="yep-toggle"><input type="checkbox" class="yep-enable"> <span>Pictures <span class="yep-hint">(Shift+E)</span></span></label>
        <div class="yep-layers">
          ${LAYERS.map(([k, name]) => `<label class="yep-toggle"><input type="checkbox" class="yep-layer-on" data-k="${k}"> <span>${name}</span></label>`).join("")}
        </div>
        <div class="yep-row">
          <label>Sync offset</label>
          <span class="yep-stepper">
            <button class="yep-btn yep-off-dn">–</button>
            <span class="yep-val"><input type="number" class="yep-num yep-off" step="0.25"> s</span>
            <button class="yep-btn yep-off-up">+</button>
          </span>
        </div>
        <div class="yep-row">
          <label>Size</label>
          <span class="yep-stepper">
            <button class="yep-btn yep-size-dn">–</button>
            <span class="yep-val"><input type="number" class="yep-num yep-size" step="10"> %</span>
            <button class="yep-btn yep-size-up">+</button>
          </span>
        </div>
        <button class="yep-btn yep-wide yep-load">Load web.json pack…</button>
        <input type="file" class="yep-file" accept=".json,application/json" hidden>
        <div class="yep-file-name"></div>
        <div class="yep-status"><span class="yep-now"></span></div>
        <button class="yep-btn yep-wide yep-forget">Forget this video's pack</button>
      </div>`;
    const toggleCollapse = () => {
      p.classList.toggle("yep-collapsed");
      p.querySelector(".yep-collapse").textContent = p.classList.contains("yep-collapsed") ? "+" : "–";
    };
    p.querySelector(".yep-collapse").addEventListener("click", toggleCollapse);
    p.querySelector(".yep-enable").addEventListener("change", (e) => setEnabled(e.target.checked));
    for (const box of p.querySelectorAll(".yep-layer-on")) {
      box.addEventListener("change", (e) => setLayer(box.dataset.k, e.target.checked));
    }
    p.querySelector(".yep-off-up").addEventListener("click", () => setOffset(offset + OFFSET_STEP));
    p.querySelector(".yep-off-dn").addEventListener("click", () => setOffset(offset - OFFSET_STEP));
    p.querySelector(".yep-size-up").addEventListener("click", () => setSize(sizePct + SIZE_STEP));
    p.querySelector(".yep-size-dn").addEventListener("click", () => setSize(sizePct - SIZE_STEP));
    const bindNumber = (sel, commit) => {
      const input = p.querySelector(sel);
      input.addEventListener("change", () => {
        const v = parseFloat(input.value);
        if (Number.isFinite(v)) commit(v); else updatePanel();
      });
      let before = "";
      input.addEventListener("focus", () => { before = input.value; });
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") input.blur();
        else if (e.key === "Escape") { input.value = before; input.blur(); }
      });
      for (const type of ["keydown", "keyup", "keypress"]) input.addEventListener(type, (e) => e.stopPropagation());
    };
    bindNumber(".yep-off", setOffset);
    bindNumber(".yep-size", setSize);
    const fileInput = p.querySelector(".yep-file");
    p.querySelector(".yep-load").addEventListener("click", () => fileInput.click());
    fileInput.addEventListener("change", (e) => {
      const f = e.target.files && e.target.files[0];
      if (!f) return;
      const reader = new FileReader();
      reader.onload = () => loadPackText(String(reader.result || ""), f.name);
      reader.readAsText(f);
      fileInput.value = "";
    });
    p.querySelector(".yep-forget").addEventListener("click", () => {
      if (!videoId) return;
      store.remove([`pack:${videoId}`, `offset:${videoId}`]);
      offset = 0;
      setPack(null);
      osd("Pack removed for this video");
    });
    // keep clicks in the panel from toggling play/pause
    for (const type of ["click", "mousedown", "dblclick"]) p.addEventListener(type, (e) => e.stopPropagation());

    const head = p.querySelector(".yep-head");
    let dragging = false, sx = 0, sy = 0, ox = 0, oy = 0;
    head.addEventListener("mousedown", (e) => {
      if (e.target.classList.contains("yep-collapse")) return;
      dragging = true; sx = e.clientX; sy = e.clientY;
      const r = p.getBoundingClientRect(); const pr = player.getBoundingClientRect();
      ox = r.left - pr.left; oy = r.top - pr.top;
      e.preventDefault();
    });
    document.addEventListener("mousemove", (e) => {
      if (!dragging) return;
      p.style.left = Math.max(0, ox + e.clientX - sx) + "px";
      p.style.top = Math.max(0, oy + e.clientY - sy) + "px";
      p.style.right = "auto";
    });
    document.addEventListener("mouseup", () => { dragging = false; });
    panelEl = p;
    return p;
  }

  function updatePanel() {
    if (!panelEl) return;
    const q = (s) => panelEl.querySelector(s);
    q(".yep-enable").checked = enabled;
    for (const box of panelEl.querySelectorAll(".yep-layer-on")) {
      box.checked = layers[box.dataset.k];
      box.disabled = !enabled;
    }
    q(".yep-layers").classList.toggle("yep-off-all", !enabled);
    const setNum = (el, v) => { if (document.activeElement !== el) el.value = v; };
    setNum(q(".yep-off"), offset.toFixed(2));
    setNum(q(".yep-size"), String(sizePct));
    q(".yep-file-name").textContent = pack ? `📦 ${packName || "pack"} — ${pack.items.length} pictures` : "No pack for this video";
    q(".yep-forget").style.display = pack ? "" : "none";
  }

  // ----------------------------- attach / SPA handling -----------------------------
  function onSeekOrPause() { draw(true); }
  function onTimeUpdate() { if (video.paused) draw(); }
  function attach() {
    const pl = document.querySelector("#movie_player") || document.querySelector(".html5-video-player");
    const vid = pl ? pl.querySelector("video") : document.querySelector("video");
    if (!pl || !vid) return;
    if (video === vid && player === pl && panelEl && panelEl.isConnected && layerEl && layerEl.isConnected) {
      loadStoredPack();
      return;
    }
    if (video) {
      video.removeEventListener("play", startRaf);
      video.removeEventListener("seeked", onSeekOrPause);
      video.removeEventListener("pause", onSeekOrPause);
      video.removeEventListener("timeupdate", onTimeUpdate);
    }
    player = pl;
    video = vid;
    video.addEventListener("play", startRaf);
    video.addEventListener("seeked", onSeekOrPause);
    video.addEventListener("pause", onSeekOrPause);
    video.addEventListener("timeupdate", onTimeUpdate);
    for (const [ref, cls] of [["layer", "yep-layer"], ["osd", "yep-osd"]]) {
      const el = ref === "layer" ? layerEl : osdEl;
      if (!el || !el.isConnected || el.parentElement !== player) {
        const n = el && el.isConnected ? el : document.createElement("div");
        n.className = cls;
        player.appendChild(n);
        if (ref === "layer") layerEl = n; else osdEl = n;
      }
    }
    if (!panelEl || !panelEl.isConnected || panelEl.parentElement !== player) {
      buildPanel();
      player.appendChild(panelEl);
    }
    clearAll();
    updatePanel();
    loadStoredPack();
    if (!video.paused) startRaf();
  }

  const mo = new MutationObserver(() => { if (!layerEl || !layerEl.isConnected || !panelEl || !panelEl.isConnected) attach(); });
  mo.observe(document.documentElement, { childList: true, subtree: true });
  document.addEventListener("yt-navigate-finish", () => setTimeout(attach, 300));
  window.addEventListener("resize", () => draw(true));
  document.addEventListener("fullscreenchange", () => setTimeout(() => draw(true), 200));
  document.addEventListener("keydown", onKeyDown, true);

  attach();
  const attachInterval = setInterval(() => {
    if (!panelEl || !panelEl.isConnected || !video || !video.isConnected) attach();
    else if (currentVideoId() !== videoId) loadStoredPack();
  }, 1500);
  window.addEventListener("beforeunload", () => clearInterval(attachInterval));
})();
