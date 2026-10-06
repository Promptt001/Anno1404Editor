# What is this?

A friendly editor for the **minds of your AI rivals** in *Anno 1404 History Edition*.

Every AI opponent in Anno 1404 (Giovanni, the Baroness, Cardinal Lucius,
Hildegard, Willem and the rest) is driven by a list of hidden personality
dials: how big an army they may build, how often their fleets attack, how
quickly they colonize islands, whether they poison your markets, how easily
they declare war. Around **980 values per character**, all sitting inside
your game's `data1.rda`.

This tool lets you see them and turn them. It ships three ready-made
personas, extracted one-to-one from a mod that was **actually played in
game** and confirmed working:

| Persona | Character | What you get |
|---|---|---|
| **The Admiral** | Leif Jorgensen | 20 warships at endgame, raids every ~20 s, never flees |
| **The Spider** | Hildegard | Constant poisoning, revolts, sabotage, and nearly impossible to spy on |
| **The Conqueror** | Willem | 80-unit armies, grabs islands fast, attacks instead of negotiating |

Prefer your own mix? Open any character in the editor window and set every
dial yourself. The game's own documentation for each dial is shown next to
it (translated to English for display; the game files are untouched).

Beyond the AI, two more tabs edit the wider game: **EXTRAS** (production
times, influence radii, housing, norias, trade, speeds, warships, costs)
and **FERTILITY** (which crops new islands can grow in each hemisphere).

## Safety first

The tool is built around one rule: **you can always go back.**

- You provide a pristine copy of `data1.rda` once; it is stored write-once
  and verified before every restore.
- Every save first snapshots the file it is about to replace.
- One click on **Restore Vanilla** puts the game back the way it was.
- Only the four files the editor knows about inside `data1.rda` can change
  (the two AI profile files, `assets.xml`, `randommapgenerator.xml`), and
  other mods' changes, even inside those files, are preserved when you
  save. The tool verifies this on every save.

## Two ways to use it

- **Graphical** (recommended): a point-and-click window. [Install
  it](install.md), then follow the [5-minute walkthrough](walkthrough.md).
- **Command line**: the same actions (`flash`, `apply`, `restore`,
  `relations`, `extras`, `fertility`, ...) for scripting. See the README.

> A note on honesty: the personas were verified on *new* endless games.
> Old saves can have AI values baked in. If a character ignores your
> changes, start a fresh game and they will listen.

Next: [Install](install.md)
