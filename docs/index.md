# Anno1404 GameEditor — documentation

An open-source editor for the hidden AI personalities and game tuning
inside *Anno 1404 History Edition*'s `addon/data1.rda`: safe, reversible,
and without shipping any game data.

## Getting started

1. [What is this?](getting-started/what-is-this.md): the idea, the
   personas, the safety story
2. [Install](getting-started/install.md): requirements, tkinter, finding
   your `data1.rda`, a 5-minute sanity check
3. [The 5-minute walkthrough](getting-started/walkthrough.md): pick a
   persona, fine-tune, review, save, watch it work, restore

## Technical reference

- [The RDA V2.0 archive format](technical/rda-format.md): header, blocks,
  directory entries, encryption, and the forward-slash rule that keeps
  the game from crashing
- [AI profile anatomy](technical/ai-profiles-anatomy.md): the asset
  layers, dial paths, the schema-default fallback, Relationships, the
  military-points economy
- [The edit engine](technical/edit-engine.md): byte-exact editing rules
  and the "never easier" Hardened rule
- [Safety and verification](technical/safety-and-verification.md): the
  backup subsystem, the save pipeline, every verification gate, known
  limits
- [Dial glossary](technical/dial_glossary.md): every AI dial with type,
  range, default and the developers' own (German) description; generated
  by `tools/gen_glossary.py`

## Shipped personas

| File | Persona | Character |
|---|---|---|
| `annoedit/presets/the_admiral.json` | The Admiral | Leif Jorgensen |
| `annoedit/presets/the_spider.json` | The Spider | Hildegard von Lewenstein |
| `annoedit/presets/the_conqueror.json` | The Conqueror | Willem van der Mark |

Each is extracted one-to-one from a build that was played in game and
confirmed working (the "AI Hard Trio v1" build), including its War and
AvoidWar relations. `Hardened` (computed from the hardest vanilla values)
is available for every other character.

Release history: [CHANGELOG.md](../CHANGELOG.md).
