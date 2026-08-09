---
description: Generate an act's enemy compendium JSON from the STS2 wiki via an Opus subagent
argument-hint: <ActName>   (e.g. Underdocks, Overgrowth, Hive, Glory)
---

Generate the enemy compendium for the Slay the Spire 2 act **$1** and install it at
`sts2-agent/compendium/enemies/<act_lowercase>.json`.

If that file already exists, it is fully replaced — StS2 is in early access and
encounters change between patches. Do NOT read or preserve the old file's
entries; the act is regenerated from scratch. (The loader in
`sts2-agent/compendium/__init__.py` merges every `enemies/*.json` automatically,
so no code changes are needed.)

## Step 1 — spawn the fetch agent

Spawn ONE background subagent via the Agent tool with `subagent_type:
"general-purpose"` and `model: "opus"`. Its prompt must contain all of the
following (substitute the act name):

---

Build the enemy compendium JSON for the "$1" act of Slay the Spire 2 from the
game's wiki. This is benchmark reference data injected into an LLM agent's
combat prompts — accuracy matters, fabrication is unacceptable.

**Sources, in order of authority:**

1. **Raw Lua data modules — the primary source of truth for ALL numbers**
   (HP, damage, hits, block, buff amounts, ascension scaling):
   - `https://slaythespire.wiki.gg/wiki/Module:Enemies/StS2_data/$1` (regulars)
   - `https://slaythespire.wiki.gg/wiki/Module:Enemies/StS2_data/Elites`
   - `https://slaythespire.wiki.gg/wiki/Module:Enemies/StS2_data/Bosses`
   (Elites/Bosses modules are shared across acts — filter to this act's roster.)
   Discover further modules via `Special:PrefixIndex` if needed;
   `Module:Powers/StS2_data/*` and `Module:Cards/StS2_data/*` document power
   keywords and status cards. Try appending `?action=raw` for clean source.
2. **The act overview page** `https://slaythespire.wiki.gg/wiki/Slay_the_Spire_2:$1`
   — for the complete roster: regulars, elites, bosses, and summon/minion
   relationships. Cover the WHOLE roster; do not skip bosses.
3. **Individual enemy pages** `https://slaythespire.wiki.gg/wiki/Slay_the_Spire_2:{Enemy_Name}`
   — fetch ONLY for what the modules don't carry: AI patterns, encounter
   compositions, power/mechanic prose. Some enemies share a page or have none
   (404) — fall back to the group page or the data module and record it.

**Known traps (all have caused real errors before):**
- Rendered pages show ascension values via `{{Asc|LEVEL|VALUE|...}}` — param 1
  is the LEVEL, param 2 the VALUE. Scrapers have repeatedly returned the level
  as the value, and at least one rendered page mislabels which ascension a
  stat scales at. When rendered page and data module disagree, THE MODULE WINS.
- `curl` is blocked by the wiki's bot protection (returns a Cloudflare page
  with exit code 0). Use WebFetch only.
- Broad WebFetch prompts make the summarizer elide move lists ("[6 additional
  intents listed]"). Use tightly-scoped prompts per enemy/module section.

**Output** — write ONE file: `C:\Users\cooli\vakuu\sts2-agent\compendium\enemies\<act_lowercase>.json`
(full overwrite if it exists). Schema — match the existing act files exactly
(read `sts2-agent/compendium/enemies/underdocks.json` as the reference):

- Top level: `_meta` (`source`, `note` on ascension-prefix conventions plus any
  act-specific scaling exceptions, `summons`, `missing`) and `enemies`.
- `enemies` keys are IN-GAME DISPLAY NAMES with spaces ("Sludge Spinner",
  "Two-Tailed Rat"). Size/variant forms get separate entries as the game
  displays them (e.g. "Leaf Slime (S)").
- Per entry: `tier` ("regular" | "elite" | "boss" | "minion"), `act` (number),
  `hp` ("38-40" or single value), ascension overrides as prefixed fields
  (`a8_hp`, `a9_moves` — a full replacement list, not a diff; use the actual
  ascension level the module documents, even when unusual), optional `powers`
  (innate powers with amounts and effect text), `moves` (one string per move:
  "Stomp — 13 dmg", "Windup Punch — 2 dmg × 3"), `pattern`, and for minions
  `summoned_by`.
- `_meta.summons` maps each summoner's display name to its minion display
  names. Include `tier: "minion"` entries for every summon.

**`pattern` and every other field contain LOAD-BEARING FIGHT INFORMATION
ONLY.** Move order, cycles, probabilities, never-repeat rules, opener offsets,
phase/stun thresholds, encounter compositions, death sequences, non-obvious
mechanic timing. NO coaching, NO strategy advice, NO consequences-for-the-
player framing: nothing shaped like "so you should…", "…is what punishes
you", "kill this first", "X is wasted", "plays around", "better than". Do not
restate a `powers` entry or a `moves` effect inside `pattern`. State
mechanics; the agent being benchmarked must derive the tactics itself.

**Rules:** every number must come from the fetched sources — omit fields the
sources don't document rather than inventing values, recording each gap in
`_meta.missing` with a short reason. Validate the JSON parses (quick python
check) before finishing. Final report: coverage per enemy (full/partial/
missing), which modules you verified against, summon relationships, and
anything a human should double-check.

---

## Step 2 — after the agent completes

1. Parse the file and confirm entry count covers the act page's full roster
   (regulars + elites + bosses + minions).
2. Nudge-scan every `pattern` for coaching remnants (phrases like "so ",
   "you should", "punishes", "kill this", "is wasted", "better than",
   "plan ", "bank ") and cull any that slipped through — load-bearing fight
   info only.
3. Integration test: import `compendium` from `sts2-agent`, call
   `format_enemies_section` with a couple of the act's display names
   (including one summoner, to confirm minion blocks auto-append) and
   `format_enemy_block(name, 9)` to confirm an ascension override applies.
4. Report to the user: entry count, coverage gaps from `_meta.missing`, and
   any flags from the agent's report that need human verification.
