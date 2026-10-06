#!/usr/bin/env python3
"""golden_bytes — the engine's byte-shape contract, pinned WITHOUT game data.

Six canonical edit workflows driven through the REAL Session stack
(open -> queue edits -> flash to a fresh target) against the SYNTHETIC
archive (tests/synthetic_rda.py — no game data). The four edited
archive members' exact output BYTES are the golden fixtures.

Why: the real-data byte pins (persona equivalence, hardened content hash)
only run on a machine that owns the game archive. Every behaviour-
neutral refactor must prove, on a data-less box, that it emits the
SAME bytes. A change that still parses, verifies and round-trips green
but alters one emitted byte is a BEHAVIOUR change — this module is
what makes that visible.

The workflows always build from make_synthetic_rda() directly (never
the fixture resolver), so they run byte-identically in synthetic and
real-data suite runs.

Re-record ONLY deliberately — an engine fix that must change emitted
bytes — and justify the diff in CHANGELOG.md:

    python3 tests/golden_bytes.py record

Never re-record to make a failing test pass without understanding
WHY the bytes moved.
"""
import base64
import hashlib
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES_PATH = os.path.join(HERE, "golden_fixtures.json")

# Home isolation BEFORE any annoedit import: never touch the real
# ~/.anno1404gameeditor while recording or checking (same rule as
# tests/fixture.py; kept local so tools/ can import this module too).
if not (os.environ.get("ANN0140_HOME") or os.environ.get("ANN0140_EXPORTS_DIR")
        or os.environ.get("ANN0140_SETTINGS_DIR")
        or os.environ.get("ANN0140_LOG_FILE")):
    os.environ["ANN0140_HOME"] = tempfile.mkdtemp(prefix="golden_home_")
os.environ.setdefault("ANN0140_STRICT_THREADS", "1")

sys.path.insert(0, os.path.join(HERE, os.pardir))
sys.path.insert(0, HERE)

from synthetic_rda import make_synthetic_rda  # noqa: E402

LEIF = "1645021"      # EasyCSP — persona + relations + vanilla target


def _md5(b):
    return hashlib.md5(b).hexdigest()


def _content_md5(entries):
    """md5 over the sorted (name, data) pairs of the DECOMPRESSED
    entries — independent of the zlib stream that packs the archive
    (write_rda output bytes are NOT deterministic across zlib
    versions/builds; the member bytes and this content hash are)."""
    h = hashlib.md5()
    for name in sorted(entries):
        h.update(name.encode("utf-8"))
        h.update(entries[name][0])
    return h.hexdigest()


def _mk_session(W, src):
    from annoedit.session import Session
    s = Session(backup_root=os.path.join(W, "backups"),
                exports_root=os.path.join(W, "exports"),
                persona_dirs=(os.path.abspath(
                    os.path.join(HERE, os.pardir, "annoedit", "presets")),))
    s.open(src)
    return s


def _profile(s, guid=LEIF):
    for q in s.roster:
        if q.guid == guid:
            return q
    raise AssertionError(f"profile {guid} not in roster")


def _flash(s, W, name):
    """Flash the pending changes to a FRESH target and return the
    output archive's full entry map (name -> (bytes, ts))."""
    from annoedit.rda import read_rda
    out = os.path.join(W, name + ".rda")
    s.flash(target=out)
    return read_rda(out)


def _members_only(entries):
    from annoedit.core import ARCHIVE_MEMBERS
    return {m: entries[m][0] for m in ARCHIVE_MEMBERS}


# ------------------------------------------------------- the six shapes

def wf_persona(W):
    """Persona apply (The Admiral on Leif): ~64 dial edits incl.
    insert_after-anchored INSERTS for paths the synthetic profile
    lacks, plus persona relations — the persona build's byte shape."""
    src = make_synthetic_rda(os.path.join(W, "src.rda"))
    s = _mk_session(W, src)
    s.set_mode(_profile(s), "The Admiral")
    return _flash(s, W, "persona")


def wf_hardened(W):
    """Hardened with a provided vanilla baseline: absolute queueing
    over KEY_DIALS, rule='harden' rows, NEVER-EASIER drops at plan
    time against the opened base."""
    src = make_synthetic_rda(os.path.join(W, "src.rda"))
    s = _mk_session(W, src)
    s.provide_vanilla(src)
    s.set_mode(_profile(s), "hardened")
    return _flash(s, W, "hardened")


def wf_vanilla_on_modded(W):
    """Vanilla reset on a MODDED opened archive (variant=1) with a
    provided variant-0 vanilla reference: absolute rule='reset'
    queueing, per-base no-op drops, relations full-list resets."""
    van = make_synthetic_rda(os.path.join(W, "van.rda"))
    mod = make_synthetic_rda(os.path.join(W, "mod.rda"), variant=1)
    s = _mk_session(W, mod)
    s.provide_vanilla(van)
    s.set_mode(_profile(s), "vanilla")
    return _flash(s, W, "vanilla_on_modded")


def wf_relations(W):
    """Manual relations rewrite on Leif (no vanilla War block in the
    synthetic archive): every kind INSERTED as a new block + the
    existing kinds rewritten — the relations writer's byte shape."""
    src = make_synthetic_rda(os.path.join(W, "src.rda"))
    s = _mk_session(W, src)
    s.set_relations(_profile(s),
                    war=["1645024", "1645026"],
                    ally=["1645020"],
                    trade=["1645027"],
                    avoidwar=["1645028"])
    return _flash(s, W, "relations")


def wf_extras(W):
    """EXTRAS edits: a missing-tag INSERT (PrintingHouse
    ProductionTime inside <WareProduction>), a plain replace (Bakery),
    a multi-instance occurrence edit (Noria NoriaEndRadius #2), and an
    ambiguous-name asset addressed by its 'Name [GUID]' display form."""
    src = make_synthetic_rda(os.path.join(W, "src.rda"))
    s = _mk_session(W, src)
    s.set_extra("PrintingHouse", "ProductionTime", 1000)
    s.set_extra("Bakery", "ProductionTime", 25000)
    s.set_extra("Noria", "NoriaEndRadius", 12, occ=1)
    s.set_extra("Warehouse01 [1001]", "PassiveTradeSlots", 9)
    return _flash(s, W, "extras")


def wf_fert(W):
    """Fertility edits: two (tier, crop) pairs, both hemispheres —
    the span-safe randommapgenerator.xml byte shape."""
    src = make_synthetic_rda(os.path.join(W, "src.rda"))
    s = _mk_session(W, src)
    s.set_fertility("high", "Spices", 90, 40)
    s.set_fertility("low", "Almond", 30, 70)
    return _flash(s, W, "fert")


WORKFLOWS = {
    "persona": wf_persona,
    "hardened": wf_hardened,
    "vanilla_on_modded": wf_vanilla_on_modded,
    "relations": wf_relations,
    "extras": wf_extras,
    "fert": wf_fert,
}


# ------------------------------------------------------ record / check

def record():
    """Rebuild every workflow and write the fixture file."""
    out = {}
    for name, fn in WORKFLOWS.items():
        W = tempfile.mkdtemp(prefix="golden_rec_")
        entries = fn(W)
        out[name] = {
            "content_md5": _content_md5(entries),
            "members": {m: {"md5": _md5(b), "b64": base64.b64encode(b).decode("ascii")}
                        for m, b in _members_only(entries).items()},
        }
    doc = {
        "note": "Golden byte fixtures — the engine's emit contract on the "
                "synthetic archive. Re-record deliberately via "
                "'python3 tests/golden_bytes.py record' and justify the "
                "diff in CHANGELOG.md; a byte change is a behaviour change.",
        "workflows": out,
    }
    with open(FIXTURES_PATH, "w") as f:
        json.dump(doc, f, indent=1, sort_keys=True)
        f.write("\n")
    return FIXTURES_PATH


def check():
    """-> list of mismatch dicts (empty = all golden). Each mismatch
    names the workflow + member and the expected/actual md5s."""
    if not os.path.isfile(FIXTURES_PATH):
        return [{"workflow": "(all)", "member": "(fixtures)",
                 "error": f"{FIXTURES_PATH} missing — run "
                          "'python3 tests/golden_bytes.py record' once"}]
    with open(FIXTURES_PATH) as f:
        doc = json.load(f)
    problems = []
    for name, fn in WORKFLOWS.items():
        want = doc["workflows"].get(name)
        if want is None:
            problems.append({"workflow": name, "member": "(fixtures)",
                             "error": "workflow missing from fixtures — "
                                      "re-record"})
            continue
        W = tempfile.mkdtemp(prefix="golden_chk_")
        entries = fn(W)
        got_content = _content_md5(entries)
        if got_content != want["content_md5"]:
            problems.append({"workflow": name, "member": "(content)",
                             "error": f"archive content md5 "
                                      f"{got_content} != fixture "
                                      f"{want['content_md5']} (a NON-member "
                                      "entry changed too — scope leak?)"})
        for m, b in _members_only(entries).items():
            w = want["members"].get(m)
            if w is None:
                problems.append({"workflow": name, "member": m,
                                 "error": "member missing from fixtures"})
                continue
            if _md5(b) == w["md5"]:
                continue
            exp = base64.b64decode(w["b64"])
            problems.append({
                "workflow": name, "member": m,
                "error": f"bytes changed: got md5 {_md5(b)}, fixture "
                         f"{w['md5']} ({len(b)} vs {len(exp)} bytes)",
                "got": b, "expected": exp})
    return problems


if __name__ == "__main__":
    print(record() if sys.argv[1:2] == ["record"] else
          ("OK" if not check() else "MISMATCH"))
