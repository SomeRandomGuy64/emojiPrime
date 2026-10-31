# Translate set phrases into emoji (one of three independent translators)

You are one of three translators turning Japanese set phrases into emoji for "emoji prime". Emoji prime shows pictures over a Japanese video as each word is spoken, so a learner understands without any English. The other two translators work separately, and a vote later picks the best translation of each phrase. (This is the method Fred Benenson used for *Emoji Dick*: several independent translations of each sentence, then a vote.)

The input is a TSV. Each row has the phrase, its other spoken forms, a Japanese gloss of what it means, and an English note. The English note is for you only.

For every phrase, give 1–4 emoji that a viewer would read as that phrase at a glance, the moment it's said:

- Picture the **meaning in use**, not the words: a greeting is the gesture or situation it belongs to, not a literal reading of its parts.
- Be **consistent across related phrases**: time words should form one system (for example ⏪ past, ⏩ future, 👇 this one), and so should greetings.
- Fewer emoji are better when they're clear. Clever combos are welcome (👂❓ for なに).
- Never use emoji that show letters or kanji (🆗 🆘 🆓 🆚 🈳 and the like), 📅 and 📆 (they show a date), or flags. No English anywhere.

Write ONLY a JSON object to the output path you were given, with no prose and no code fences, and include every phrase:
{"<phrase>": "<emoji>", ...}

Phrases:
