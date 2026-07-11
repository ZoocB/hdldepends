"""Xilinx .xci IP-core parsing (both XML and JSON instance formats)."""

import json
import xml.etree.ElementTree as xml_et
from pathlib import Path
from typing import List, Optional

from ...constants import LIB_DEFAULT
from ...logging_util import log
from ...model import FileType, Name, SourceFile
from ...util import path_abs_from_dir

#: Coefficient-file parameter keys are matched case-insensitively by substring
#: (Xilinx uses different names for this across IP cores).
_COEF_KEY_MARKERS = ("COEFFICIENT_FILE", "COE_FILE", "COEFFILE")
#: Extensions that distinguish a real coefficient-file value from a
#: placeholder (e.g. "auto", "no_coe_file_loaded").
_COEF_SUFFIXES = (".coe", ".mif")


def _coef_file_dep(loc: Path, folder: Path, coef_file: str, fmt: str) -> Optional[Path]:
    """Resolve one candidate coefficient-file parameter value to a concrete path.

    Returns ``None`` (after logging why) for a placeholder value -- one with
    no ``.coe``/``.mif`` suffix -- or a file that doesn't exist on disk; the
    caller keeps scanning the remaining parameters in either case. ``fmt`` is
    ``"xml"`` or ``"json"``, naming the XCI's own format in the log messages.
    """
    coef_path = Path(coef_file)
    if not coef_path.suffix or coef_path.suffix.lower() not in _COEF_SUFFIXES:
        log.debug(f"Xilinx XCI ({fmt}) {loc} has placeholder coefficient parameter: '{coef_file}' - skipping")
        return None  # keep scanning -- a later parameter may be the real one

    coef_loc = path_abs_from_dir(folder, coef_path)
    if not coef_loc.is_file():
        log.warning(f"Coefficient file referenced in XCI {loc} not found: {coef_loc} - skipping")
        return None  # keep scanning -- a later parameter may be the real one

    log.info(f"Xilinx XCI ({fmt}) {loc} has coefficient file dependency: {coef_file}")
    return coef_loc


# Parse X_XCI: Xilinx XCI IP File {{{
def parse_x_xci_file_xml(loc: Path, xci_f, ver: Optional[str]) -> Optional[SourceFile]:

    log.debug(f"called parse_x_xci_file_xml({loc=})")
    try:
        etree = xml_et.parse(xci_f)  # raises xml_et.ParseError
    except xml_et.ParseError:
        return None

    ns = {"spirit": "http://www.spiritconsortium.org/XMLSchema/SPIRIT/1685-2009", "xilinx": "http://www.xilinx.com"}

    root = etree.getroot()

    def get_elem_text_arr(xml_tag: str) -> List[str]:
        xml_elem_arr = root.findall(".//spirit:" + xml_tag, ns)

        text_arr = []
        for xml_elem in xml_elem_arr:
            if xml_elem.text is None:
                # An empty element (e.g. <spirit:library/>) has no text; skip it
                # rather than crashing -- callers already validate the count and
                # contents of the returned list.
                continue
            text_arr.append(xml_elem.text)
        return text_arr

    xml_lib_arr = get_elem_text_arr("library")
    if len(xml_lib_arr) != 1 or xml_lib_arr[0] != "xci":
        raise RuntimeError("XML Parsing: Expected to find xci under library tag. This may not be an xci file")
    module_name_arr = get_elem_text_arr("instanceName")
    if len(module_name_arr) == 0:
        raise RuntimeError("XML Parsing: could not find .//spirit:instance in xml file")
    if len(module_name_arr) > 1:
        raise RuntimeError("XML Parsing: hdl_depends expected to find only one .//spirit:instance in xml file")
    module_name = module_name_arr[0]

    name = Name(LIB_DEFAULT, module_name)

    x_dev = None
    x_package = None
    x_speed = None
    x_temp = None
    x_tool_version = None

    PP = "PROJECT_PARAM."
    RP = "RUNTIME_PARAM."

    for elem in root.findall(".//spirit:configurableElementValue", ns):
        id = elem.attrib.get("{" + ns["spirit"] + "}referenceId")

        # `val` is always called within this same loop iteration (never stored
        # for later), so the loop variables it needs are bound as defaults --
        # this is purely to satisfy B023 (function-uses-loop-variable), not a
        # behaviour change.
        def val(elem: xml_et.Element = elem, id: Optional[str] = id) -> str:
            result = elem.text
            if elem.text is None:
                if id == PP + "TEMPERATURE_GRADE":
                    log.warning(
                        f"In Xilinx XCI (xml) {loc} got empty {PP}TEMPERATURE_GRADE, assuming temperature grade 'i'\n"
                        f"\t(if this is incorrect please report a bug with the XCI file, correct part "
                        f"number and Vivado version)"
                    )
                    result = "i"

            if not isinstance(result, str):
                raise RuntimeError(f"In Xilinx XCI (xml) {loc} for {id=} we got {result=} expected a string")
            assert isinstance(result, str)
            return result

        if id == PP + "DEVICE":
            x_dev = val()
        if id == PP + "PACKAGE":
            x_package = val()
        if id == PP + "SPEEDGRADE":
            x_speed = val()
        if id == PP + "TEMPERATURE_GRADE":
            x_temp = val()
        if id == RP + "SWVERSION":
            x_tool_version = val()

    missing = [
        param_name
        for value, param_name in (
            (x_dev, PP + "DEVICE"),
            (x_package, PP + "PACKAGE"),
            (x_speed, PP + "SPEEDGRADE"),
            (x_temp, PP + "TEMPERATURE_GRADE"),
            (x_tool_version, RP + "SWVERSION"),
        )
        if value is None
    ]
    if missing:
        raise RuntimeError(f"Xilinx XCI (xml) {loc} is missing required parameter(s): {', '.join(missing)}")
    # `missing` is empty, so all five are set; re-assert for mypy's narrowing.
    assert x_dev is not None and x_package is not None and x_speed is not None
    assert x_temp is not None and x_tool_version is not None

    x_device = f"{x_dev}-{x_package}{x_speed}-{x_temp}"
    x_device = x_device.lower()
    log.info(f"Xilinx XCI (xml) {loc} declares {module_name} (tool_version {x_tool_version}, device {x_device})")

    direct_deps = []
    folder = loc.parent

    # Extract coefficient files
    for elem in root.findall(".//spirit:configurableElementValue", ns):
        id = elem.attrib.get("{" + ns["spirit"] + "}referenceId")
        if id is not None:
            id_upper = id.upper()
            # Check for coefficient file parameters (case-insensitive)
            if any(param in id_upper for param in _COEF_KEY_MARKERS):
                if elem.text is not None and len(elem.text.strip()) > 0:
                    coef_file = elem.text.strip()
                    candidate = _coef_file_dep(loc, folder, coef_file, "xml")
                    if candidate is not None:
                        direct_deps.append(candidate)
                        break  # Only extract one coefficient file

    sf = SourceFile(loc, FileType.X_XCI, ver=ver, x_tool_version=x_tool_version, x_device=x_device)
    sf.provides.append(name)
    sf.direct_deps = direct_deps
    return sf


def parse_x_xci_file_json(loc: Path, xci_f, ver: Optional[str]) -> Optional[SourceFile]:
    try:
        xci_dict = json.load(xci_f)  # throws json.decoder.JSONDecodeError
    except json.decoder.JSONDecodeError:
        return None

    def js_val(js):
        assert len(js) == 1
        return js[0]["value"]

    try:
        ip_inst = xci_dict["ip_inst"]
        module_name = ip_inst["xci_name"]
        param = ip_inst["parameters"]
        prj_param = param["project_parameters"]
        x_device = (
            f"{js_val(prj_param['DEVICE'])}-{js_val(prj_param['PACKAGE'])}"
            f"{js_val(prj_param['SPEEDGRADE'])}-{js_val(prj_param['TEMPERATURE_GRADE'])}"
        )
        run_param = param["runtime_parameters"]
        x_tool_version = js_val(run_param["SWVERSION"])
    except (KeyError, TypeError, AssertionError, IndexError) as e:
        # Valid JSON but not XCI-shaped (e.g. some other Xilinx JSON file):
        # return None so the caller falls through to the XML parser and, if
        # that fails too, its final error naming the file -- not a bare
        # KeyError/AssertionError from deep inside JSON navigation. Logged at
        # debug level so a genuinely XCI-shaped-but-broken file's real cause
        # is still discoverable (with -vv) instead of silently swallowed.
        log.debug(f"Xilinx XCI (json) {loc} does not look like a JSON XCI: {type(e).__name__}: {e}")
        return None

    name = Name(LIB_DEFAULT, module_name)
    x_device = x_device.lower()

    log.info(f"Xilinx XCI (json) {loc} declares {module_name} (tool_version {x_tool_version}, device {x_device})")

    direct_deps = []
    folder = loc.parent

    if "component_parameters" in param:
        comp_param = param["component_parameters"]
        if not isinstance(comp_param, dict):
            # Shape-guard: everything below assumes a {name: [{"value": ...}]}
            # mapping. The 5 required top-level parameters already parsed fine
            # (that's what got us here), so don't lose the whole file over a
            # malformed component_parameters -- just skip the coefficient scan.
            log.warning(
                f"Xilinx XCI (json) {loc} has non-mapping component_parameters "
                f"({type(comp_param).__name__}) - skipping coefficient-file scan"
            )
            comp_param = {}
        # Check for coefficient file parameters (case-insensitive)
        for key in comp_param.keys():
            key_upper = key.upper()
            if any(marker in key_upper for marker in _COEF_KEY_MARKERS):
                try:
                    coef_file = js_val(comp_param[key])
                except (AssertionError, TypeError, KeyError, IndexError) as e:
                    # Malformed parameter shape (e.g. not a single-element
                    # [{"value": ...}] list) -- log and keep scanning the
                    # remaining keys rather than losing the whole,
                    # otherwise-valid XCI parse over one broken parameter.
                    log.warning(
                        f"Xilinx XCI (json) {loc} has malformed component parameter '{key}': "
                        f"{type(e).__name__}: {e} - skipping"
                    )
                    continue
                if not isinstance(coef_file, str):
                    log.warning(
                        f"Xilinx XCI (json) {loc} component parameter '{key}' has non-string "
                        f"value {coef_file!r} - skipping"
                    )
                    continue
                if len(coef_file.strip()) > 0:
                    candidate = _coef_file_dep(loc, folder, coef_file, "json")
                    if candidate is not None:
                        direct_deps.append(candidate)
                        break  # Only extract one coefficient file

    sf = SourceFile(loc, FileType.X_XCI, ver=ver, x_tool_version=x_tool_version, x_device=x_device)
    sf.provides.append(name)
    sf.direct_deps = direct_deps
    return sf


def parse_x_xci_file(loc: Path, ver: Optional[str]) -> SourceFile:
    """Parse a Xilinx ``.xci`` file (JSON first, then XML). Pure: caller registers."""
    log.info(f"parsing Xilinx XCI file {loc}:")
    with open(loc, "rb") as xci_f:
        f_obj = parse_x_xci_file_json(loc, xci_f, ver)
        if f_obj is not None:
            return f_obj
        xci_f.seek(0)
        f_obj = parse_x_xci_file_xml(loc, xci_f, ver)
        if f_obj is not None:
            return f_obj

    raise RuntimeError(f"Could not parse XCI as XML or JSON, {loc}")


# }}}
