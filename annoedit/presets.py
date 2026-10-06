#!/usr/bin/env python3
"""presets — the built-in presets.

'vanilla'  : no dial edits (install a vanilla archive to reset).
'hardened' : generic difficulty boost — for a curated list of key dials, set the
             character to the hardest value found ANYWHERE in vanilla: the three
             hard profiles (Baroness 1645020, Lucius 1645024, Giovanni 1645026)
             plus the ai/properties.xml schema default where that is higher/ lower.
             Values are computed at runtime from the loaded archive, so the preset
             self-adapts to the archive it is applied to.
'custom'   : explicit dial list from a JSON preset file / GUI.

Per-dial DIRECTION: for most dials a higher value = harder AI, but for several a
LOWER value is the aggressive direction (attack intervals, DeclareWar threshold,
ColonizeDelayTime, DontBuy, Prop_NoAction, ShipGroupFleePercentage=0 never
disengages, DeclareWarMinPlayTime). The map below encodes each dial's direction.
"""

# (dial path, direction)  direction: 'max' higher=harder | 'min' lower=harder
KEY_DIALS = [
    ("Military/MaxUnitCount", "max"),
    ("Military/MaxMilitaryPoints", "max"),
    ("Military/MaxMilitaryPointsInWar", "max"),
    ("ShipFight/ShipAttackIntervall", "min"),
    ("ShipFight/ShipRatioToPlayer", "max"),
    ("ShipFight/ShipHuntDuration", "max"),
    ("ShipFight/MaxOffensiveShipPercentage", "max"),
    ("ShipFight/ShipSecurityPercentage", "max"),
    ("ShipFight/ShipGroupFleePercentage", "min"),
    ("ShipFight/RepairHitpointPercentage", "max"),
    ("ShipFight/StopWaitingMinStrengthPercentage", "min"),
    ("ShipFight/ShipPatrolSize", "max"),
    ("ShipFight/ShipAmountPerLevel/Peasant", "max"),
    ("ShipFight/ShipAmountPerLevel/Citizen", "max"),
    ("ShipFight/ShipAmountPerLevel/Patrician", "max"),
    ("ShipFight/ShipAmountPerLevel/Nobleman", "max"),
    ("TownAcquisition/PreferMainAttack", "max"),
    ("TownAcquisition/Prios/HighAttack", "max"),
    ("TownAcquisition/Prios/ColoTarget", "max"),
    ("TownAcquisition/Prios/DontBuy", "min"),
    ("TownAcquisition/BudgetPerMinute", "max"),
    ("TownAcquisition/TownAquisitionInterval", "min"),
    ("Build/ColonizeDelayTime", "min"),
    ("Build/BuildingSpeed", "max"),
    ("Build/ResidentByLevel/Nobleman", "max"),
    ("Build/BankBooks/Trade/MaxValuePerLevel/Peasant", "max"),
    ("Build/BankBooks/Trade/MaxValuePerLevel/Citizen", "max"),
    ("Build/BankBooks/Trade/MaxValuePerLevel/Patrician", "max"),
    ("Build/BankBooks/Trade/MaxValuePerLevel/Nobleman", "max"),
    ("Build/MaxEspionageBuildings", "max"),
    ("Espionage/EspionageActionIntervall", "min"),
    ("Espionage/Prop_Poisen", "max"),
    ("Espionage/Prop_Revolt", "max"),
    ("Espionage/Prop_Thief", "max"),
    ("Espionage/Prop_FireRaiser", "max"),
    ("Espionage/Prop_NoAction", "min"),
    ("Espionage/SpyDetectValue", "max"),
    ("Espionage/SpyMarketplaceDec", "max"),
    ("Diplomacy/CompetenceUsageRanges/DeclareWar/Min", "min"),
    ("Diplomacy/DeclareWarMinPlayTime", "min"),
]

# Hard profiles that define the vanilla ceiling (vanilla GUIDs)
HARD_GUIDS = ("1645020", "1645024", "1645026")


def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def hardened_target(path, direction, hard_dials, defaults):
    """Hardest vanilla value for one dial: extreme over hard profiles + default.
    All ai dial values in this archive are integers (ms times, percentages,
    counts); a non-integer extreme is formatted as-is (defensive, never
    expected on data1.rda)."""
    values = []
    for d in hard_dials:
        v = _num(d.get(path))
        if v is not None:
            values.append(v)
    v = _num(defaults.get(path))
    if v is not None:
        values.append(v)
    if not values:
        return None
    extreme = max(values) if direction == "max" else min(values)
    if all(float(x).is_integer() for x in values):
        return str(int(extreme))
    return str(extreme)


def hardened_changes(profile, all_profiles, defaults):
    """-> changes dict path->str for ONE profile.
    Uses effective value (profile override or schema default fallback).
    Excluding profiles is the caller's job (hardened_build).
    Note: TownAcquisition priority dials live under <Prios>.
    ShipAmountPerLevel/Peasant has no hard-profile/default value in vanilla
    and is skipped by design."""
    from .model import effective_value
    hard_dials = [p.dials for p in all_profiles if p.guid in HARD_GUIDS]
    changes = {}
    for path, direction in KEY_DIALS:
        target = hardened_target(path, direction, hard_dials, defaults)
        if target is None:
            continue  # dial unknown to this archive (name drift) — skip silently
        current, source = effective_value(profile.dials, defaults, path)
        if current is None:
            changes[path] = target  # dial not in profile NOR schema — explicit write
            continue
        cur, tgt = _num(current), _num(target)
        # A non-numeric value (corrupt or hand-edited) is skipped.
        if cur is None or tgt is None:
            continue
        # Never make a dial easier: skip if already at/beyond the extreme.
        if direction == "max" and cur >= tgt:
            continue
        if direction == "min" and cur <= tgt:
            continue
        changes[path] = target
    return changes


def load_custom(json_path):
    """JSON preset: {"characters": {"<Name>": {"dials": {"Path": value},
    "relations": {"War": [...], ...}}}}

    -> {name: {"dials": {path: str(value)},
               "relations": {kind: [guid, ...]}}}
    """
    import json
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    out = {}
    for name, spec in (data.get("characters") or {}).items():
        entry = {"dials": {k: str(v)
                           for k, v in (spec.get("dials") or {}).items()},
                 "relations": {}}
        for kind, guids in (spec.get("relations") or {}).items():
            entry["relations"][str(kind)] = [str(g) for g in guids]
        out[name] = entry
    return out
