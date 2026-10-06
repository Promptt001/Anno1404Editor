#!/usr/bin/env python3
"""fertility — island crop-fertility editor.

Data layout (as found in vanilla data1.rda):
- Lives in addondata/config/game/randommapgenerator.xml, single
  <FertilityRates> block (~4.3KB), nested key/value pseudo-XML:
      <FertilityRates>
        <k><ResourceAmount>low</ResourceAmount></k>
        <v>
          <k><Fertility>Dates</Fertility></k><v><North>0</North><South>60</South></v>
          ... (16 crops per tier)
        </v>
        ... (3 tiers: low/medium/high)
      </FertilityRates>
- 3 tiers (ResourceAmount low/medium/high) x 16 crops; each crop entry =
  <k><Fertility>NAME</Fertility></k> + <v><North>%</North><South>%</South></v>.
  Vanilla: northern crops have North>0/South=0, southern crops the mirror.
  Setting North>0 on a southern crop makes it generatable in the north.
- Gotchas:
  * The file is cp1252, not UTF-8. ModProject decodes it as latin-1,
    which round-trips every byte losslessly (see core.py).
  * Line endings are plain CRLF. Edits are span-located and never
    re-emit line endings wholesale, so this is never assumed.
  * File is NOT well-formed XML overall: raw binary u32 arrays sit in
    pseudo-CDATA[...] blocks at the head (WorldSizes etc.) — full-file
    xml.etree validation is IMPOSSIBLE; only span-safe targeted edits.
    (Verify edits by re-parsing just the <FertilityRates> block.)
  * The tier <v> CONTAINS nested crop <v>...</v> entries: a non-greedy
    regex over tier bodies stops at the first crop's </v> — tier regions
    MUST be cut at tier-key boundaries (see _tier_regions).
  * <Fertility> tag appears 251x file-wide (48 in this block): NEVER edit
    by bare tag regex over the whole file — always locate the block span
    FIRST, then the tier region, then the (tier, crop) entry span.
  * assets.xml's 21 <Fertility> tags are just the crop NAME a farm
    requires (inside <Farm>) — not rates; do not confuse with this file.

API (same shape as extras.py):
- parse_fertility_rates(text) -> {"tier": {"crop": (north, south)}}
- fertility_catalog(text) -> [{"crop","tier","north","south"}] GUI rows
- set_fertility(text, tier, crop, north=None, south=None)
    -> (new_text, {"north": old_or_None, "south": old_or_None})
  Byte-safe: rewrites ONLY the leaf text spans of the requested fields of
  the one (tier, crop) entry. None = leave exactly as-is. Percentages are
  0-100 ints. Raises FertilityError on unknown tier/crop or bad value.
- apply_fertility(text, changes) — batch form (errors collected, not raised)
- FERT_FILE, FERT_TIERS, FERT_CROPS for wiring.
"""
import re

FERT_FILE = "addondata/config/game/randommapgenerator.xml"

# Vanilla tiers and crops.
FERT_TIERS = ("low", "medium", "high")

FERT_CROPS = ("Almond", "Bees", "Cider", "Clay", "Coffee", "Dates", "Grape",
              "Hemp", "Herbs", "Indigo", "Rose", "Silk", "Spices",
              "Sugarcane", "Wheat", "Wildcard")

# hemisphere grouping for display only (not enforced)
NORTH_CROPS = ("Cider", "Hemp", "Wheat", "Herbs", "Grape", "Bees")
SOUTH_CROPS = ("Dates", "Spices", "Clay", "Rose", "Coffee", "Indigo",
               "Silk", "Almond", "Sugarcane")

_CROP_ENTRY_RE = re.compile(
    r"<k>\s*<Fertility>([^<]+)</Fertility>\s*</k>\s*<v>\s*"
    r"<North>(\d+)</North>\s*<South>(\d+)</South>\s*</v>")
_TIER_KEY_RE = re.compile(r"<k>\s*<ResourceAmount>(\w+)</ResourceAmount>\s*</k>")


from .model import mask_markup_comments


class FertilityError(Exception):
    """Raised on unknown tier/crop, bad percentages, or malformed blocks."""



# ---------------------------------------------------------------- parsing

def _locate_block(text):
    """-> (start, end) span of <FertilityRates>...</FertilityRates>, else None.

    The search runs on the COMMENT-MASKED text (same length — offsets
    identical on the raw text): a commented-out FertilityRates block can
    never capture the locator."""
    mtext = mask_markup_comments(text)
    ms = list(re.finditer(r"<FertilityRates>.*?</FertilityRates>", mtext, re.S))
    if not ms:
        return None
    if len(ms) > 1:
        # Two live (uncommented) blocks: which one the game reads is
        # unknown, so refuse rather than guess.
        raise FertilityError(
            f"{len(ms)} <FertilityRates> blocks in "
            "randommapgenerator.xml — refusing to guess which copy the "
            "game reads")
    m = ms[0]
    return (m.start(), m.end()) if m else None


def _tier_regions(block):
    """-> [(tier, start, end)] — the region AFTER a tier key up to the next
    tier key (or the block's closing tag). The region starts with the outer
    tier <v> and ends with its matching </v> — the LAST </v> before the next
    tier key (nested crop <v>s make non-greedy matching WRONG: it stops at
    the first crop's </v>, which is followed by the next crop's <k> and
    would still pass a naive lookahead)."""
    # Masked: a commented-out tier key inside the block can never
    # create a phantom tier (same-length filler, raw-text offsets valid).
    mblock = mask_markup_comments(block)
    keys = list(_TIER_KEY_RE.finditer(mblock))
    if not keys:
        raise FertilityError("FertilityRates block: no tier entries found")
    seen = {}
    for km in keys:
        seen[km.group(1)] = seen.get(km.group(1), 0) + 1
        if seen[km.group(1)] > 1:
            raise FertilityError(
                f"duplicate tier {km.group(1)!r} in FertilityRates — "
                "refusing to guess which copy the game reads")
    close = mblock.rfind("</FertilityRates>")
    end_default = close if close != -1 else len(block)
    out = []
    for i, km in enumerate(keys):
        start = km.end()
        end = keys[i + 1].start() if i + 1 < len(keys) else end_default
        out.append((km.group(1), start, end))
    return out


def parse_fertility_rates(text):
    """raw file text -> {"tier": {"crop": (north, south)}} (file order kept).
    Parses ONLY the FertilityRates block; duplicate crop within a tier =
    structure error (fail loud, never guess)."""
    sp = _locate_block(text)
    if sp is None:
        raise FertilityError("no <FertilityRates> block in randommapgenerator.xml")
    block = text[sp[0]:sp[1]]
    out = {}
    for tier, start, end in _tier_regions(block):
        region = block[start:end]
        # masked region: a commented-out crop entry inside the tier can
        # never be parsed (same-length filler, raw-text offsets valid).
        mregion = mask_markup_comments(region)
        vm = re.match(r"\s*<v>", mregion)
        if not vm:
            raise FertilityError(f"tier {tier!r}: no <v> body after its key")
        crops = {}
        for cm in _CROP_ENTRY_RE.finditer(mregion):
            crop = cm.group(1)
            if crop in crops:
                raise FertilityError(f"tier {tier}: duplicate crop {crop!r}")
            crops[crop] = (int(cm.group(2)), int(cm.group(3)))
        if not crops:
            raise FertilityError(f"tier {tier!r}: no crop entries found")
        # Every <Fertility> key must have produced an entry above. A key
        # whose entry does not match the strict North/South shape would
        # otherwise be silently omitted, hiding a crop from the editor.
        for km in re.finditer(
                r"<k>\s*<Fertility>([^<]+)</Fertility>\s*</k>", mregion):
            if km.group(1) not in crops:
                raise FertilityError(
                    f"tier {tier}: crop {km.group(1)!r} has a "
                    "<Fertility> key but its entry does not match the "
                    "expected <North>digits</North> + "
                    "<South>digits</South> shape — refusing rather than "
                    "silently omitting it")
        out[tier] = crops
    return out


def fertility_catalog(text):
    """-> [{"crop","tier","north","south"}] rows in file order (tier-major)."""
    rows = []
    for tier, crops in parse_fertility_rates(text).items():
        for crop, (north, south) in crops.items():
            rows.append({"crop": crop, "tier": tier,
                         "north": north, "south": south})
    return rows


# ---------------------------------------------------------------- edit engine

def _validate_pct(v, what):
    if not re.fullmatch(r"\d{1,3}", str(v)):
        raise FertilityError(f"{what} {v!r} must be a whole number 0-100")
    n = int(v)
    if not 0 <= n <= 100:
        raise FertilityError(f"{what} {v!r} out of range 0-100")
    return n


def set_fertility(text, tier, crop, north=None, south=None):
    """Byte-safe edit of one (tier, crop) entry's North/South percentages.
    -> (new_text, {"north": old, "south": old}) (only requested fields).
    Only the requested field's leaf span is rewritten; everything else
    (binary head, other blocks, EOLs, whitespace) stays byte-identical."""
    if tier not in FERT_TIERS:
        raise FertilityError(f"unknown tier {tier!r} (need one of {FERT_TIERS})")
    if crop not in FERT_CROPS:
        raise FertilityError(f"unknown crop {crop!r} (need one of {FERT_CROPS})")
    newvals = {}
    if north is not None:
        newvals["north"] = _validate_pct(north, "North")
    if south is not None:
        newvals["south"] = _validate_pct(south, "South")
    if not newvals:
        raise FertilityError("nothing to edit: north and south both None")
    sp = _locate_block(text)
    if sp is None:
        raise FertilityError("no <FertilityRates> block in randommapgenerator.xml")
    block = text[sp[0]:sp[1]]
    entry_span = None
    for ttier, start, end in _tier_regions(block):
        if ttier != tier:
            continue
        region = block[start:end]
        # Same masked locator as parse_fertility_rates, so a commented-out
        # crop entry can never capture the edit.
        mregion = mask_markup_comments(region)
        for cm in _CROP_ENTRY_RE.finditer(mregion):
            if cm.group(1) == crop:
                # absolute entry span (block-relative, then text-relative)
                entry_span = (start + cm.start(), start + cm.end())
                entry_text = cm.group(0)
                break
        break
    if entry_span is None:
        raise FertilityError(f"tier {tier}: crop {crop!r} entry not found")
    new_entry = entry_text
    old = {}
    for field, val in newvals.items():
        tag = field.capitalize()
        pm = re.search(rf"<{tag}>(\d+)</{tag}>", new_entry)
        if pm is None:
            raise FertilityError(f"entry {tier}/{crop} lacks <{tag}>")
        old[field] = pm.group(1)
        new_entry = re.sub(rf"<{tag}>\d+</{tag}>",
                           f"<{tag}>{val}</{tag}>", new_entry)
    abs_start = sp[0] + entry_span[0]
    abs_end = sp[0] + entry_span[1]
    new_text = text[:abs_start] + new_entry + text[abs_end:]
    return new_text, old


def apply_fertility(file_text, changes):
    """changes: list of (tier, crop, north, south) (None = leave as-is).
    -> (new_text, applied, errors); applied=[(tier, crop, old, new)]"""
    text, applied, errors = file_text, [], []
    for tier, crop, north, south in changes:
        try:
            text, old = set_fertility(text, tier, crop, north, south)
            applied.append((tier, crop, old,
                            {"north": north, "south": south}))
        except FertilityError as e:
            errors.append((tier, crop, str(e)))
    return text, applied, errors
