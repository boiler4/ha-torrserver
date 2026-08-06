"""Test bootstrap that loads the API module without Home Assistant installed."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
CUSTOM_COMPONENTS = ROOT / "custom_components"
INTEGRATION = CUSTOM_COMPONENTS / "torrserver"

custom_components = ModuleType("custom_components")
custom_components.__path__ = [str(CUSTOM_COMPONENTS)]
sys.modules.setdefault("custom_components", custom_components)

torrserver = ModuleType("custom_components.torrserver")
torrserver.__path__ = [str(INTEGRATION)]
sys.modules.setdefault("custom_components.torrserver", torrserver)
