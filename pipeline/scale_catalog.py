"""Design step 14: build the Scale_Selector catalog from config/hazards.yaml (Req 24, 23.12).

Six static entries. Tier 2 for towns with open 311 data (`open_311_towns`), Tier 1 otherwise (24.2).
Only `cape_blizzard`, and `boston_blizzard` once the Boston Voice block has run, are "live" and point
at scored data through `data_endpoint` (24.6). Every other entry is a Configuration_Preview: it lists
the tier, the hazard's lost-lifelines inputs and the need inputs, and carries no score fields (24.5, 23.12).
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
from pipeline.common import CONFIG, ConfigError, _load_yaml
PREVIEW_LABEL = "Configuration preview"
MODES = {"live", "live_if_built", "preview"}
# Where the Web_App fetches the scored data for each live entry.
DATA_ENDPOINTS = {"cape_blizzard": "/api/tracts", "boston_blizzard": "/api/boston/voice"}
def load_hazards(path: Path = CONFIG / "hazards.yaml") -> dict[str, Any]:
    cfg = _load_yaml(Path(path))
    for key in ("hazards", "need_inputs", "open_311_towns", "entries"):
        if key not in cfg:
            raise ConfigError(f"{Path(path).name}: missing key {key!r}")
    return cfg
def catalog(hazards_cfg: dict[str, Any], boston_built: bool) -> list[dict[str, Any]]:
    """Return the catalog entries in config order. `boston_built` is True when ctx has `boston_voice`."""
    hazards, entries = hazards_cfg["hazards"], hazards_cfg["entries"]
    need_inputs = list(hazards_cfg["need_inputs"])
    tier2 = set(hazards_cfg["open_311_towns"])
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for e in entries:
        eid, place, hazard, mode = e.get("id"), e.get("place"), e.get("hazard"), e.get("mode")
        if not eid or not place or eid in seen:
            raise ConfigError(f"hazards.yaml: entry {e!r} needs a unique id and a place")
        if hazard not in hazards:
            raise ConfigError(f"hazards.yaml: entry {eid!r} has unknown hazard {hazard!r}")
        if mode not in MODES:
            raise ConfigError(f"hazards.yaml: entry {eid!r} has unknown mode {mode!r}")
        seen.add(eid)
        live = mode == "live" or (mode == "live_if_built" and boston_built)
        if live and eid not in DATA_ENDPOINTS:
            raise ConfigError(f"hazards.yaml: live entry {eid!r} has no scored data")
        entry: dict[str, Any] = {
            "id": eid, "place": place, "hazard": hazard, "hazard_label": hazards[hazard]["label"],
            "tier": 2 if place in tier2 else 1, "mode": "live" if live else "preview",
            "lost_lifelines_inputs": list(hazards[hazard]["lost_lifelines"]), "need_inputs": need_inputs,
        }
        if live:
            entry["data_endpoint"] = DATA_ENDPOINTS[eid]
        else:
            entry["label"] = PREVIEW_LABEL  # previews never carry score fields
        out.append(entry)
    return out
def step(ctx) -> None:
    """Design step 14: ctx["scale_catalog"] = list of CatalogEntry dicts."""
    ctx["scale_catalog"] = cat = catalog(load_hazards(), "boston_voice" in ctx)
    print("       scale_catalog: " + ", ".join(f"{e['id']} (tier {e['tier']}, {e['mode']})" for e in cat))
