# AI profile anatomy — how the game stores a character's mind

## The three layers per character

Inside `addondata/config/ai/aiprofiles.xml`, every AI character is
described by up to three `<Asset>` blocks:

| Template | Example GUIDs | What it holds |
|---|---|---|
| **PlayerProfile** | 1650020 (Baroness), 1650026 (Giovanni) | presentation only: voice lines, portrait, NamePool, PreferredSellWares tonnage |
| **EasyCSP / MediumCSP / HardCSP** | 1645020 (Baroness HardCSP), 1645026 (Giovanni HardCSP) | **the personality**: ~980 leaf dials under `<Values>` |
| *(optional extras)* | TalkingProfile, ResidentProfile, ... | per-feature blocks |

The behavioral difference between an "easy" and a "hard" character is
*only* which CSP template asset carries their dials — and the dial values
inside it. A character has one CSP asset per difficulty in general
practice; the ten base-game characters and two Venice addon characters
(Venezia, Vittorio etc. in `config/balancing/addon_01_aiprofiles.xml`) are
all there is.

## Dial structure

Dials live under `<Values>` as nested XML, and are addressed by path:

```
Military/MaxUnitCount
ShipFight/ShipAmountPerLevel/Nobleman
Build/BankBooks/Trade/MaxValuePerLevel/Peasant
Diplomacy/CompetenceUsageRanges/DeclareWar/Min
```

Major categories: `Build`, `Military`, `ShipFight`, `TownAcquisition`,
`Diplomacy`, `Espionage`, `Trade`, `Relationships`, `Reputation`,
`ItemUsage`, `Quest`, `HonourUsage`, ...

## The schema-default fallback (the `*` in comparison tables)

Profiles **omit most dials**. A missing tag does not mean "0" — it means
"fall back to the schema default" defined in
`addondata/config/ai/properties.xml` (`DefaultValues` +
`DefaultContainerValues` blocks). Example: `Military/MaxUnitCount` schema default is 70 — the
Baroness omits the tag and effectively runs 70, while Giovanni explicitly
sets 30 and Willem (in our Conqueror persona) 80.

Effective value = **profile override, else schema default**. The
`Value`/`Source` columns in this tool's UI show exactly this resolution.

The same `properties.xml` contains a German `ValueDefinition` for every
dial — the developers' own documentation, which this tool shows in its
doc pane (and [generates a glossary from](dial_glossary.md)).

## Relationships

`Relationships/Relations` contains up to four lists — `War`, `Ally`,
`Trade`, `AvoidWar` — each a list of *other characters'* **CSP GUIDs**
(the `EasyCSP`/`MediumCSP`/`HardCSP` asset GUIDs, `1645xxx`; in vanilla
data all 264 `ProfileGUID` values in CSP assets point at CSP GUIDs, none at
PlayerProfile GUIDs). Notable vanilla wiring:

- Baroness ↔ Lucius are a **mutual Ally pair**; each lists the other.
- Giovanni is wired as **Trade** partner to both but **Ally to neither**;
  Lucius additionally lists Giovanni under **AvoidWar**. When wars start,
  the merchant stands alone against the pair.
- Baroness's scripted **War** list: Marie d'Artois + Helena Flores.

List dials (repeated `<Item>` siblings) are structural, not scalar —
relations lists (War/Ally/Trade/AvoidWar) are edited through the
DEDICATED relations editor (set_relations + the relations dialog), not
the dial engine (see [edit-engine](edit-engine.md)).

## Military points economics

`Military/MaxMilitaryPoints` (default 80) is a budget shared by **army
units, warships and towers**:

- `MaxUnitCount` = units as **% of military points** (schema default 70)
- `MaxTowerBuild` = towers eat **20% of current military points** (same
  for every character — it is *not* a personality dial)
- `MaxMilitaryPointsInWar` (default 100) raises the ceiling in war

Consequence (verified against in-game observations): Giovanni — tiny unit
cap, all warships on escort duty — has no free points for keeps until war
plus real local demand frees the pool. That's why he "builds no keep
until enemies land". It's budget arithmetic, not a missing trigger.

One more distinction worth knowing: the per-trigger `Messages`/`Reaction`
blocks (e.g. `TROOPS_IN_INFLUENCE`) are **diplomatic reactions and audio
pools, not build orders**. Production is driven by the points/economy
dials, war-independent.

## CRLF and other file facts

- `aiprofiles.xml` and `addon_01_aiprofiles.xml` are **plain CRLF** files. The edit engine preserves
  the file's exact bytes outside the edited values.
- Character identity is `<Standard><Name>/<GUID>` at the **asset tail**,
  not the head — matching assets by template+name alone grabs the wrong
  asset (Relations reference other characters by name/GUID inside your
  own block).
- The human player has **no profile** — nothing in `config/ai/` can
  affect you, which is what makes AI-profile editing player-neutral by
  construction.

Back to [docs index](../index.md)
