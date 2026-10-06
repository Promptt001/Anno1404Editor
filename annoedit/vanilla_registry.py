"""Known-vanilla integrity registry (a hash is not game data).

Per-member SHA-256 of the four tracked members (+ properties.xml, the
schema-defaults file the effective-value engine reads) for the current
Steam/Uplay *Anno 1404 History Edition* vanilla ``addon/data1.rda``
build, plus its whole-file md5. Sourced from a verified pristine copy;
keep this table in sync if the game patches (verify a candidate by
whole-file md5 first, then per-member).

Use:
    classify(path_or_bytes) -> 'verified' | 'unknown' | ...

This makes the vanilla trust anchor verifiable: ``provide_vanilla``
can say "verified vanilla" vs "unknown build", the reference columns
become provably vanilla, and restore can verify per-member. A file
that fails the whole-file md5 but matches all members is merely a
different packing order — member hashes are authoritative.
"""

import hashlib

#: Whole-file md5 of the verified pristine vanilla addon/data1.rda.
WHOLE_FILE_MD5 = "aa4546d0d9f405400142acd2df8247b8"

#: Per-member SHA-256 (over the UNCOMPRESSED member bytes).
MEMBERS_SHA256 = {
    "addondata/config/ai/aiprofiles.xml":
        "cb25564897c6d4686e2f7005a7d007e1fb33f967dda32f524ecf89ebaa7784f7",
    "addondata/config/balancing/addon_01_aiprofiles.xml":
        "6d7fda2bc7d1fc1c5cf581bc8c96f036abd889f5fef4eb8ceda610e145f73f72",
    "addondata/config/game/assets.xml":
        "8a95e04ef2989242a44fd2f3fa3c7c821435ee82cd34584c40d6ae10a17c8514",
    "addondata/config/game/randommapgenerator.xml":
        "d704aabf74cb04b15b7578f916f3e9355dab6a0adda21e724b841a1e1d811ed9",
    "addondata/config/ai/properties.xml":
        "dcd169a6dad5a0ffb6ba7c4b63eb7a00a4a16dfaa0fab1177a3507675bda08be",
}


def whole_file_class(archive_path):
    """-> 'verified' | 'unknown' by the whole-file md5."""
    h = hashlib.md5()
    with open(archive_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return "verified" if h.hexdigest() == WHOLE_FILE_MD5 else "unknown"


def member_class(entries):
    """-> 'verified' | 'modded' | 'partial' for a parsed entries map.

    Only members present in the archive are compared. 'modded' = at least
    one present member differs; 'partial' = none of the known members is
    present (a stripped/odd build; treat with the same caution as
    'modded'); otherwise 'verified'.
    """
    hits = 0
    for name, sha in MEMBERS_SHA256.items():
        if name not in entries:
            continue
        if hashlib.sha256(entries[name][0]).hexdigest() != sha:
            return "modded"
        hits += 1
    return "verified" if hits else "partial"


def vanilla_report(entries):
    """-> dict(class=..., matched=..., missing=..., mismatched=[...])
    for logging + GUI display."""
    matched, missing, mismatched = [], [], []
    for name, sha in MEMBERS_SHA256.items():
        if name not in entries:
            missing.append(name)
        elif hashlib.sha256(entries[name][0]).hexdigest() == sha:
            matched.append(name)
        else:
            mismatched.append(name)
    if mismatched:
        cls = "modded"
    elif matched:
        cls = "verified"
    else:
        cls = "partial"
    return {"class": cls, "matched": matched, "missing": missing,
            "mismatched": mismatched}
