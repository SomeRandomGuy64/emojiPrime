# Vote on emoji translations of set phrases

Three translators worked independently, each turning the same Japanese set phrases into emoji for "emoji prime". Emoji prime shows pictures over a Japanese video as each word is spoken, so a learner understands without any English. For each phrase, pick the translation a viewer would understand fastest and most surely, at a glance, the moment the phrase is said.

- **Judge the meaning in use**, not a literal word-for-word reading.
- **Keep families consistent.** Related phrases (先週 / 今週 / 来週, 昨日 / 今日 / 明日, the greetings) should read as one system. When one translator's system is clearly best for a family, prefer that translator for the whole family.
- **Reject unreadable picks:** anything that shows letters, digits or kanji, 📅 or 📆 (they show a date), or flags.
- **Fix only small flaws.** If every candidate has the same small flaw, you may write a corrected version. Otherwise choose; don't invent.

The input is JSON: `{"<phrase>": {"gloss": "...", "en": "...", "A": "...", "B": "...", "C": "..."}}`.

Write ONLY a JSON object to the output path you were given, with no prose and no code fences, and include every phrase:
{"<phrase>": {"pick": "A" | "B" | "C" | "edit", "emoji": "<the chosen or corrected emoji>"}, ...}

Translations:
