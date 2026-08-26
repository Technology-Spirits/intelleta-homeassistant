"""Shared test scaffolding.

⛔ WHY MODULES ARE LOADED BY PATH RATHER THAN IMPORTED NORMALLY.

`custom_components/intelleta/__init__.py` imports Home Assistant, because that
is what it is for. Importing anything from the package therefore drags the whole
of Home Assistant in — a large install, slow to set up in CI, and completely
beside the point for logic that deliberately imports nothing.

So the pure modules are loaded straight from their file. The pay-off is a suite
that runs in well under a second and cannot go red for a reason unrelated to
what it is testing — and it keeps honest pressure on those modules to stay
dependency-free, because the day one of them imports Home Assistant, this stops
working and somebody has to justify it.

⚠ Modules that genuinely need Home Assistant (the config flow, the entities) are
tested elsewhere, against a real installation. Do not reach for this helper to
avoid that.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

COMPONENT = Path(__file__).resolve().parent.parent / "custom_components" / "intelleta"


def load(module_name: str) -> ModuleType:
    """Load `custom_components/intelleta/<module_name>.py` in isolation."""
    path = COMPONENT / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(f"intelleta_isolated_{module_name}", path)
    if spec is None or spec.loader is None:  # pragma: no cover - a broken path is a broken test
        raise ImportError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
