"""Xilinx .bd block-design parsing."""

import json
from pathlib import Path
from typing import Optional

from ...constants import LIB_DEFAULT
from ...logging_util import log
from ...model import FileType, Name, SourceFile


def parse_x_bd_file(loc: Path, ver: Optional[str]) -> SourceFile:
    """Parse a Xilinx ``.bd`` block design into a :class:`SourceFile`."""
    log.info(f"parsing Xilinx BD file {loc}:")
    with open(loc, "rb") as json_f:
        try:
            bd_dict = json.load(json_f)
        except json.decoder.JSONDecodeError as e:
            raise RuntimeError(f"Xilinx BD {loc} is not valid JSON: {e}") from e
    try:
        design = bd_dict["design"]
        info = design["design_info"]
        sf = SourceFile(
            loc, FileType.X_BD, ver=ver, x_tool_version=info["tool_version"], x_device=info["device"]
        )
        sf.provides.append(Name(LIB_DEFAULT, info["name"]))
    except (KeyError, TypeError) as e:
        # TypeError covers a valid-JSON-but-wrong-shape file (e.g. the top
        # level is a list/string/number, or "design"/"design_info" is not a
        # mapping) -- subscripting those raises TypeError, not KeyError.
        raise RuntimeError(f"Xilinx BD {loc} is missing expected key {e}; this does not look like a valid .bd file") from e

    # By this point `design` is known to be a dict (design["design_info"]
    # above would have raised TypeError otherwise), but nothing below it is
    # guaranteed to be shaped as expected -- guard each level and skip (with a
    # warning naming the file/component) rather than crash on the rest of an
    # otherwise-valid .bd.
    components = design.get("components", {})
    if not isinstance(components, dict):
        log.warning(f"Xilinx BD {loc} has non-mapping 'components' ({type(components).__name__}) - skipping component scan")
        components = {}

    for component_name, component in components.items():
        if not isinstance(component, dict):
            log.warning(
                f"Xilinx BD {loc}: component {component_name!r} is not a mapping "
                f"({type(component).__name__}) - skipping"
            )
            continue
        ref = component.get("reference_info", {})
        if not isinstance(ref, dict):
            ref = {}
        if ref.get("ref_type") == "hdl":
            ref_name = ref.get("ref_name")
            if not isinstance(ref_name, str):
                log.warning(
                    f"Xilinx BD {loc}: component {component_name} has an hdl reference "
                    f"with no valid ref_name - skipping"
                )
                continue
            sf.requires.append(Name(LIB_DEFAULT, ref_name))
            continue
        params = component.get("parameters", {})
        if not isinstance(params, dict):
            params = {}
        if "ACTIVE_SYNTH_BD" not in params:
            continue
        active = params["ACTIVE_SYNTH_BD"]
        file_name = active.get("value") if isinstance(active, dict) else None
        if not isinstance(file_name, str):
            log.warning(f"Xilinx BD {loc}: component {component_name} has a malformed ACTIVE_SYNTH_BD parameter - skipping")
            continue
        file_path = Path(file_name)
        if file_path.suffix != ".bd":
            log.error(
                f"Xilinx BD {loc}: component {component_name} ACTIVE_SYNTH_BD {file_name!r} does not "
                f"end in .bd, skipping"
            )
            continue
        stem = file_path.stem
        if "." in stem:
            # Xilinx BD names cannot contain dots, but Path.stem only strips
            # the last suffix, so a multi-dot filename (e.g. "my.design.bd")
            # still leaves one in the stem. Upstream intent is that the BD
            # name is the stem of the whole filename, so keep using it --
            # just flag the anomaly.
            log.warning(
                f"Xilinx BD {loc}: component {component_name} ACTIVE_SYNTH_BD {file_name!r} has a "
                f"dotted name '{stem}'"
            )
        sf.requires.append(Name(LIB_DEFAULT, stem))
    return sf
