"""Anno1404 GameEditor — core package.

Layers:
    rda.py         in-memory RDA V2.0 archive reader/writer
    model.py       AI profile parser + byte-safe XML edit engine
    presets.py     Vanilla / Hardened / persona + custom JSON presets
    extras.py      EXTRAS: global assets.xml dials (production/influence/
                   housing/noria/trade/speed/military/costs families)
    fertility.py   island crop generation rates (randommapgenerator.xml:
                   <FertilityRates> North/South % per crop/tier)
    core.py        ModProject pipeline (open -> edit -> verify -> pack -> flash)
    session.py     display-free controller (open/backup/edit/flash/restore)
    cli.py         headless command-line front-end
    gui/           tkinter GUI (thin views over the tested core)
"""

__version__ = "2.29.1"

from .rda import read_rda, write_rda
from .model import EditError, apply_changes, effective_value
from .presets import hardened_changes, load_custom
from .core import ModProject, hardened_build
from .fertility import FERT_CROPS, FERT_TIERS, FertilityError
from .fertility import parse_fertility_rates, set_fertility

__all__ = [
    "read_rda", "write_rda",
    "EditError", "apply_changes", "effective_value",
    "hardened_changes", "load_custom",
    "ModProject", "hardened_build",
    "FERT_CROPS", "FERT_TIERS", "FertilityError",
    "parse_fertility_rates", "set_fertility",
    "__version__",
]
