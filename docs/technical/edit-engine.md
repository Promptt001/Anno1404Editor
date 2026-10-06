# The edit engine — byte-exact XML editing the game accepts

The engines (`annoedit/model.py` for AI profiles, `annoedit/extras.py` for
`assets.xml`, `annoedit/fertility.py` for `randommapgenerator.xml`, and
relations in `annoedit/core.py`) never re-serialize XML. They splice the
**raw text**, so every byte outside an edited value stays exactly as the
game wrote it. Each rule below exists because the game, or a real build,
demanded it.

## 1. Locate by identity, never by stored offset

A character's identity is `<Standard><Name>`/`<GUID>` at the **end** of its
`<Asset>` block. Searching for "the first `<Template>HardCSP</Template>`
after a name match" grabs the wrong asset, because a profile references
*other* characters by name and GUID inside its own Relations. The engine
therefore locates a profile by its `<Standard>` identity block, and it does
so afresh for every edit: any edit shifts the byte offsets of everything
after it, so cached positions would go stale.

## 2. Comments and CDATA are invisible

Modded files often contain commented-out copies of assets. Every locator
runs on a *masked* copy of the text in which comments, CDATA and
processing instructions are replaced by same-length filler. The masked
text has identical offsets, so a span found there is valid on the real
text, and an edit can never land inside a comment. Two live assets with the
same identity are refused rather than guessed between.

## 3. Walk the child axis

`annoedit/spans.py` indexes the XML into nodes that know their exact byte
spans, and every lookup walks **direct children only**. This matters
because tag names repeat at different depths: Lucius has
`<TownAcquisition>` both as a `Diplomacy/CompetenceUsageRanges` sub-block
and as a full category. A path such as `Diplomacy/Max` is never satisfied
by a `<Max>` nested deeper down; if a link is missing at the right depth,
the remaining chain is inserted *there*.

## 4. Insert only what is missing, never duplicate

Profiles omit most dials, and the game then uses the schema default (see
[AI profile anatomy](ai-profiles-anatomy.md)). Setting such a dial inserts
the leaf. Setting a dial the profile already has rewrites its value in
place. A second copy of a tag would give the game an ambiguous read, so the
engine never creates one:

- self-closed categories (`<ShipFight/>`, `<Diplomacy/>`, ...) are expanded
  in place rather than given a sibling;
- a container or list at the leaf position is refused (`EditError`);
- list structure (`Item`/`Profiles`, everything under `Relations`) is never
  treated as a dial. Relations have their own editor (`set_relations`),
  which rewrites one kind's list in place.

Inserted leaves mirror their siblings' indentation and line endings, and
can be anchored after a specific sibling (`insert_after`), which is how
the personas reproduce the verified build byte for byte.

## 5. Verify every edit independently

After each batch of edits, an **oracle** checks the result with a different
method than the one that produced it: a separate ElementTree parse of the
edited asset must equal the old asset with exactly the requested changes
applied, and the bytes before and after the asset must be untouched. A
relations edit must leave every dial unchanged, and vice versa. Only then
is the edit committed to the working text.

## 6. Values the game can actually read

Pending edits are validated when you type them, against the DataType the
schema declares: integers (including fixed-point `RealInt`) are whole
32-bit numbers, Booleans keep the file's own `0/1` or `true/false`
spelling, `Choice`/`Flags` values must come from the enumeration in
`config/game/datasets.xml`, and text-like types are refused. Schema
Min/Max ranges produce a warning with confirmation, not a block.

## 7. Never easier (the Hardened rule)

The **Hardened** preset sets each key dial to the hardest value found
anywhere in vanilla (the three hard profiles plus the schema default,
whichever is extreme in the dial's "harder" direction). A character
already at or beyond the target keeps their value: Hardened never makes a
character easier. Example: Guy's `Prop_Poisen` is 50 in vanilla; Hardened
leaves it at 50 rather than lowering it to Lucius's 40.

Direction matters: for most dials higher is harder, but for several,
**lower** is the aggressive direction: attack intervals
(`ShipAttackIntervall`), war-declaration thresholds (`DeclareWar/Min`),
`ColonizeDelayTime`, `DontBuy`, `Prop_NoAction`, `ShipGroupFleePercentage`
(0 = never disengages), `DeclareWarMinPlayTime`. The `KEY_DIALS` table in
`presets.py` encodes the direction for all 40 key dials. When a stored
vanilla copy exists, Hardened derives its targets from it rather than from
a possibly modded open archive.

## 8. Line endings and encodings

The AI profile files are plain CRLF and are edited as UTF-8. `assets.xml`
and `randommapgenerator.xml` are cp1252 with raw binary blocks; they are
decoded as latin-1, which maps every byte to exactly one character and
back, so arbitrary bytes round-trip exactly. Nothing is ever written
through a text-mode file handle that could translate line endings.

## Proof of equivalence

Applying the three persona presets to a vanilla archive **reproduces the
in-game-verified build exactly**: dials, relations and the full asset text,
byte for byte (`PersonaEquivalenceTests`, which runs when the real archive
and the reference build are available). Without game data, the
golden-bytes fixtures (`tests/golden_bytes.py`) pin the exact output of six
canonical workflows on the synthetic archive.

Back to [docs index](../index.md)
