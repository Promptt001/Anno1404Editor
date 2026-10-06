"""gui.logic — pure, tkinter-free helpers used by the GUI and its tests.

Sort_key and the picker's file filter are pure logic
but they lived in modules that `import tkinter` at the top, so on any
machine without python3-tk the "non-GUI" tests error instead of passing.
They live here now; widgets.py and picker.py re-export them so existing
imports keep working wherever tkinter exists.
"""
import os
import re


def sort_key(value):
    """Numeric-aware sort key for one table cell: numbers sort numerically
    (so 90000 > 12000, not lexically), everything else alphabetically
    after them. Used by every sortable heading (dial table, EXTRAS,
    fertility)."""
    s = "" if value is None else str(value)
    m = re.match(r"\s*-?\d+(?:\.\d+)?", s)
    if m:
        return (0, float(m.group()), s)
    return (1, 0.0, s.lower())


def differs_from_vanilla(current, vanilla):
    """True when the CURRENT (opened archive) value differs from the
    VANILLA reference value: the non-vanilla row classification used by
    the dial/EXTRAS/fertility tables.

    Comparison rules (deliberate):
      * no vanilla reference copy stored (vanilla is None) -> ALWAYS
        False: without a trustworthy reference the highlight stays off
        rather than guess (the fallback reference is the opened archive
        itself, so every compare would be equal anyway);
      * missing on one side only (a leaf vanilla has but the opened
        archive lacks, or the reverse) -> True (a mod added/removed it);
      * string-normalized equality otherwise (leading/trailing blanks
        never count as a diff — '40 ' == '40').
    """
    if vanilla is None:
        return False
    if isinstance(current, (list, tuple)) or isinstance(vanilla, (list, tuple)):
        # EXTRAS occurrence lists: compare length + per-occurrence strings
        # (a mod that changed ONE level or ADDED a level is non-vanilla)
        if not isinstance(current, (list, tuple)) or not isinstance(vanilla, (list, tuple)):
            return True
        if len(current) != len(vanilla):
            return True
        return any(str(a).strip() != str(b).strip() for a, b in zip(current, vanilla))
    if current is None:
        return vanilla != ""
    if vanilla == "":
        return current != ""
    return str(current).strip() != str(vanilla).strip()


def fertility_row_differs(current, reference):
    """True when the fertility CURRENT (opened archive) row differs
    from the VANILLA reference row: the non-vanilla classification
    used by the fertility table.

    `current` is the opened archive's row for the crop ({} when the
    opened archive lacks it — a mod REMOVED it -> non-vanilla);
    `reference` is the vanilla catalog row (its north/south are the
    stock N/S rates). Occurrence of a missing current row must be
    judged by the CALLER against a stored vanilla copy only.
    """
    if not current:
        return True
    return (current.get("north") != reference.get("north")
            or current.get("south") != reference.get("south"))


def wanted_file(path, suffixes=(".rda",)):
    """The picker's file filter: accept plain .rda-suffixed names
    plus the export store's data1.rda_<name> files and the vanilla copy
    data1.rda_vanilla (splitext gives those extension ".rda_<name>")."""
    if not suffixes:
        return True
    name = os.path.basename(path).lower()
    if name == "data1.rda" or name.startswith("data1.rda_"):
        return True
    return os.path.splitext(path)[1].lower() in tuple(
        s.lower() for s in suffixes)
