// Fallback image loader: if the page refuses to load an Irasutoya image directly,
// the content script asks here and gets it back as a data: URL.
chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (!msg || msg.type !== "yep-fetch") return;
  fetch(msg.url, { referrerPolicy: "no-referrer" })
    .then((r) => { if (!r.ok) throw new Error(r.status); return r.blob(); })
    .then((b) => new Promise((ok) => { const fr = new FileReader(); fr.onload = () => ok(fr.result); fr.readAsDataURL(b); }))
    .then((dataUrl) => reply({ ok: true, dataUrl }))
    .catch((e) => reply({ ok: false, error: String(e) }));
  return true; // async reply
});
