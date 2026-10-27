# Set phrases

[`phrases.tsv`](phrases.tsv) is a list of common Japanese set phrases (先週, お疲れ様, なんでやねん, …), each with fixed emoji. Wherever one is said, emoji prime shows those emoji instead of asking the LLM again. That way 先週 reads ⏪🗓️ in every video, and the pictures become a visual vocabulary you learn once.

The emoji-prime server (api.fazon.nexus) pulls this file from `main` every hour, so a merged change goes live without a release.

## Format

The columns are tab-separated. Lines starting with `#` are comments.

| Column | What |
|---|---|
| phrase | The canonical form. |
| other forms | Other ways it's spoken or written, separated by `\|`: kana spellings, polite/plain forms, Kansai-ben (ほんま, おおきに). A form may appear in only one row. |
| emoji | 1–4 emoji. Never use emoji that show letters, digits or kanji, 📅/📆, or flags. |
| gloss | A short Japanese monolingual gloss. It's used as the word's sense. |
| English | For maintainers only. It's never shown on screen. |

A phrase only matches on token boundaries, so ちゃう (違う in Kansai) is safe as a form in its own right but would also catch 食べちゃう if added bare. Leave out forms that are also ordinary words with other meanings.

## Adding phrases: the Emoji Dick method

The current emoji were made the way Fred Benenson made [*Emoji Dick*](https://lccn.loc.gov/2012454709), his crowd-translated *Moby-Dick*: several independent translations of each line, then a vote.

1. Put the new rows in a TSV without the emoji column: phrase, forms, gloss, English.
2. Give [`prompts/phrase_translate.md`](prompts/phrase_translate.md) plus the TSV to three separate subagents or models. They must not see each other's answers. Each one writes `{phrase: emoji}`.
3. Shuffle the three answers per phrase so the voter can't tell who wrote what, and give them to a fourth agent with [`prompts/phrase_vote.md`](prompts/phrase_vote.md).
4. Add the winners to `phrases.tsv` and open a PR.

In Claude Code, "add these set phrases to emoji prime: …" is enough. The agent can follow these steps.
