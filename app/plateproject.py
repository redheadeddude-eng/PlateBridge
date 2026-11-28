"""Local MakerWorld project converter for Flash Studio."""
import argparse
import json
import hashlib
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
from tempfile import TemporaryDirectory
from zipfile import ZipFile, ZIP_DEFLATED
import xml.etree.ElementTree as ET

CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
MODEL = "3D/3dmodel.model"
SETTINGS = "Metadata/model_settings.config"
PROCESS = ("layer_height", "wall_loops", "sparse_infill_density", "enable_support",
           "sparse_infill_pattern", "top_shell_layers", "bottom_shell_layers")
PRINTERS = ("Creator 5", "AD5X", "Adventurer 5M Pro")
ET.register_namespace("", CORE)

def tag(name):
    return f"{{{CORE}}}{name}"

def validate(archive):
    entries = archive.infolist()
    if len(entries) > 10000 or sum(e.file_size for e in entries) > 1024**3:
        raise ValueError("Archive exceeds the supported size limit.")
    seen = set()
    for entry in entries:
        name = entry.filename
        if (name.startswith("/") or "\\" in name or ":" in name
                or ".." in PurePosixPath(name).parts or name.casefold() in seen):
            raise ValueError("Unsafe or duplicate archive path.")
        seen.add(name.casefold())

def parse(archive, name):
    pieces = []
    with archive.open(name) as reader:
        for chunk in iter(lambda: reader.read(1024 * 1024), b""):
            pieces.append(chunk)
    data = b"".join(pieces)
    if b"\x00" in data or re.search(rb"<!\s*(?:DOCTYPE|ENTITY)", data, re.I):
        raise ValueError("Unsupported XML encoding or declaration.")
    return ET.fromstring(data)

STUDIO_PROFILES = Path("C:/Program Files/Flashforge/Flash Studio Desktop/resources/profiles")
PROJECT_CONFIG = "Metadata/project_settings.config"
PROJECT_PROCESS = set(PROCESS) | set("""
    support_type support_style support_top_z_distance support_bottom_z_distance
    support_interface_spacing support_interface_top_layers support_interface_bottom_layers
    support_on_build_plate_only support_threshold_angle support_object_xy_distance
    initial_layer_line_width initial_layer_print_height ironing_pattern ironing_type
    ironing_flow ironing_spacing top_surface_pattern bottom_surface_pattern wall_sequence
    brim_type brim_width seam_position infill_wall_overlap
""".split())
PRESETS = {
    "Creator 5": ("Flashforge Creator 5 0.4 nozzle", "0.20mm Standard @FF C5", "Generic PLA @FF C5", 4),
    "AD5X": ("Flashforge AD5X 0.4 nozzle", "0.20mm Standard @FF AD5X", "Flashforge PLA Basic @FF AD5X", 4),
    "Adventurer 5M Pro": ("Flashforge Adventurer 5M Pro 0.4 Nozzle", None, "Flashforge PLA Basic", 1),
}
PROFILE_HEADERS = {
    "name", "type", "inherits", "from", "setting_id", "instantiation",
    "compatible_printers", "compatible_prints", "compatible_printers_condition",
    "compatible_prints_condition", "description", "version", "is_custom_defined",
    "default_print_profile", "default_filament_profile",
}


def read_json(archive, name):
    if archive.getinfo(name).file_size > 8 * 1024 * 1024:
        raise ValueError(f"Settings file is too large: {name}")
    data = json.loads(archive.read(name))
    if not isinstance(data, dict):
        raise ValueError(f"Invalid settings file: {name}")
    return data


def studio_preset(kind, name, chain=()):
    if not STUDIO_PROFILES.is_dir():
        return bundled_preset(kind, name)
    if name in chain or "/" in name or "\\" in name or ":" in name:
        raise ValueError(f"Invalid Flash Studio preset inheritance: {name}")
    candidates = [STUDIO_PROFILES / "Flashforge" / kind / f"{name}.json"]
    candidates.extend(vendor / kind / f"{name}.json" for vendor in STUDIO_PROFILES.iterdir()
                      if vendor.is_dir() and vendor.name != "Flashforge")
    for candidate in candidates:
        if candidate.is_file():
            data = json.loads(candidate.read_text(encoding="utf-8-sig"))
            parent = data.get("inherits")
            inherited = studio_preset(kind, parent, (*chain, name)) if parent else {}
            return inherited | data
    return bundled_preset(kind, name)


def bundled_preset(kind, name):
    path = Path(__file__).with_name("printer-presets.json")
    with path.open(encoding="utf-8") as stream:
        preset = json.load(stream).get(kind, {}).get(name)
    if preset is None:
        raise ValueError(f"Flash Studio preset not found: {name}")
    return preset


# Fields that vary with the project palette in native one- and four-filament saves.
CREATOR_FILAMENT_FIELDS = """
activate_air_filtration activate_air_filtration_during_print
activate_air_filtration_on_completion activate_chamber_temp_control adaptive_pressure_advance
adaptive_pressure_advance_bridges adaptive_pressure_advance_model
adaptive_pressure_advance_overhangs additional_cooling_fan_speed additional_fan_full_speed_layer
chamber_minimal_temperature chamber_temperature close_additional_fan_first_x_layers
close_fan_the_first_x_layers complete_print_exhaust_fan_speed cool_plate_temp
cool_plate_temp_initial_layer default_filament_colour dont_slow_down_outer_wall
during_print_exhaust_fan_speed enable_overhang_bridge_fan enable_pressure_advance eng_plate_temp
eng_plate_temp_initial_layer fan_cooling_layer_time fan_max_speed fan_min_speed
filament_adaptive_volumetric_speed filament_adhesiveness_category
filament_change_extrusion_role_gcode filament_change_length filament_colour filament_colour_type
filament_cooling_before_tower filament_cooling_final_speed filament_cooling_initial_speed
filament_cooling_moves filament_cost filament_density filament_deretraction_speed
filament_diameter filament_end_gcode filament_extruder_variant filament_flow_ratio
filament_flush_temp filament_flush_volumetric_speed filament_ids filament_ironing_flow
filament_ironing_inset filament_ironing_spacing filament_ironing_speed filament_is_support
filament_loading_speed filament_loading_speed_start filament_long_retractions_when_cut
filament_map filament_max_volumetric_speed filament_minimal_purge_on_wipe_tower
filament_multi_colour filament_multitool_ramming filament_multitool_ramming_flow
filament_multitool_ramming_volume filament_notes filament_printable filament_ramming_parameters
filament_retract_before_wipe filament_retract_lift_above filament_retract_lift_below
filament_retract_lift_enforce filament_retract_restart_extra
filament_retract_when_changing_layer filament_retraction_distances_when_cut
filament_retraction_length filament_retraction_minimum_travel filament_retraction_speed
filament_self_index filament_settings_id filament_shrink filament_shrinkage_compensation_z
filament_soluble filament_stamping_distance filament_stamping_loading_speed filament_start_gcode
filament_toolchange_delay filament_tower_interface_pre_extrusion_dist
filament_tower_interface_pre_extrusion_length filament_tower_interface_print_temp
filament_tower_interface_purge_volume filament_tower_ironing_area filament_type
filament_unloading_speed filament_unloading_speed_start filament_vendor filament_wipe
filament_wipe_distance filament_z_hop filament_z_hop_types first_x_layer_fan_speed
full_fan_speed_layer hot_plate_temp hot_plate_temp_initial_layer idle_temperature
internal_bridge_fan_speed ironing_fan_speed long_retractions_when_ec nozzle_temperature
nozzle_temperature_initial_layer nozzle_temperature_range_high nozzle_temperature_range_low
nozzle_volume_type overhang_fan_speed overhang_fan_threshold pellet_flow_coefficient
pressure_advance reduce_fan_stop_start_freq required_nozzle_HRC retraction_distances_when_ec
slow_down_for_layer_cooling slow_down_layer_time slow_down_min_speed supertack_plate_temp
supertack_plate_temp_initial_layer support_material_interface_fan_speed
temperature_vitrification textured_cool_plate_temp textured_cool_plate_temp_initial_layer
textured_plate_temp textured_plate_temp_initial_layer volumetric_speed_coefficients
""".split()


def expand_palette(config, count, tools):
    for key in CREATOR_FILAMENT_FIELDS:
        values = config.get(key)
        if isinstance(values, list) and len(values) == 1:
            config[key] = values * count
    config["filament_self_index"] = [str(index + 1) for index in range(count)]
    config["flush_volumes_vector"] = ["140", "140"] * count
    # Flash Studio keeps one square purge table per physical tool.
    table = ["0" if row == col else "280" for row in range(count) for col in range(count)]
    config["flush_volumes_matrix"] = table * tools


def bed_bounds(config):
    corners = [tuple(map(float, point.split("x"))) for point in config["printable_area"]]
    x, y = zip(*corners)
    return (min(x), min(y), max(x) - min(x), max(y) - min(y))


def plate_offsets(layout, source_config, target):
    sx, sy, sw, sh = bed_bounds(source_config)
    tx, ty, tw, th = bed_bounds(target)
    if (sx, sy, sw, sh) == (tx, ty, tw, th):
        return {}
    plates = layout.findall("plate")
    columns = math.isqrt(len(plates) - 1) + 1 if plates else 1
    offsets = {}
    for index, plate in enumerate(plates):
        row, col = divmod(index, columns)
        # Studio lays out plates on a grid with a 20% gap. Preserve each
        # instance's displacement from its own plate centre and its scale.
        dx = tx - sx + (tw - sw) * (0.5 + 1.2 * col)
        dy = ty - sy + (th - sh) * (0.5 - 1.2 * row)
        for instance in plate.findall("model_instance"):
            meta = {m.get("key"): m.get("value") for m in instance.findall("metadata")}
            offsets[meta["object_id"], int(meta["instance_id"])] = dx, dy
    return offsets


def write_model(reader, writer, offsets):
    # Keep original namespace bindings and mesh bytes, even for large inline meshes.
    prefix = b""
    while b"<resources" not in prefix:
        chunk = reader.read(65536)
        if not chunk or len(prefix) > 8 * 1024**2:
            raise ValueError("The project model has an unrecognized 3MF header.")
        prefix += chunk
    header, body = prefix.split(b"<resources", 1)
    header = re.sub(rb'<metadata\s+name=["\'](?:Application|OrcaSlicer)["\']\s*>[^<]*</metadata>', b"", header)
    writer.write(header + b'<metadata name="Application">BambuStudio-02.06.00.51</metadata>\n'
                 b'<metadata name="OrcaSlicer">2.4.2</metadata>\n<resources')
    if not offsets:
        writer.write(body)
        shutil.copyfileobj(reader, writer)
        return
    end = b"</resources>"
    while end not in body:
        keep = len(end) - 1
        writer.write(body[:-keep])
        chunk = reader.read(1024**2)
        if not chunk:
            raise ValueError("The project's model resources are incomplete.")
        body = body[-keep:] + chunk
    resources, tail = body.split(end, 1)
    writer.write(resources + end)
    tail += reader.read()
    counts = {}
    def relocate(match):
        item = match.group()
        object_id = re.search(rb'\bobjectid\s*=\s*(["\'])(\d+)\1', item)[2].decode()
        index = counts.get(object_id, 0)
        counts[object_id] = index + 1
        offset = offsets.get((object_id, index))
        if offset is None:
            return item
        attr = re.search(rb'\btransform=(["\'])(.*?)\1', item)
        matrix = attr[2].split() if attr else b"1 0 0 0 1 0 0 0 1 0 0 0".split()
        for axis, delta in enumerate(offset, start=9):
            matrix[axis] = format(float(matrix[axis]) + delta, ".12g").encode()
        replacement = b'transform="' + b' '.join(matrix) + b'"'
        return (item[:attr.start()] + replacement + item[attr.end():] if attr
                else item[:-2] + b' ' + replacement + b'/>')
    writer.write(re.sub(rb'<item\b[^>]*?/>', relocate, tail))


def material_presets(printer, materials):
    machine, _, pla, _ = PRESETS[printer]
    names = {
        "Creator 5": {"ABS": "Generic ABS @FF C5", "PETG": "Generic PETG @FF C5"},
        "AD5X": {"ABS": "Flashforge ABS Basic @FF AD5X", "PETG": "Flashforge PETG Pro @FF AD5X"},
        "Adventurer 5M Pro": {"ABS": "Flashforge ABS Basic", "PETG": "Flashforge PETG Pro"},
    }[printer] | {"PLA": pla}
    resolved = {}
    for material in set(materials):
        if material not in names:
            raise ValueError(f"No verified {material} material profile for {printer}.")
        preset = studio_preset("filament", names[material])
        if machine not in preset.get("compatible_printers", []) or preset.get("filament_type") != [material]:
            raise ValueError(f"Flash Studio has no compatible {material} preset for {printer}.")
        resolved[material] = preset
    return [resolved[m] for m in materials]


def project_settings(source_config, layout, printer):
    machine_id, process_id, _, _ = PRESETS[printer]
    machine = studio_preset("machine", machine_id)
    process_id = process_id or machine["default_print_profile"]
    process = studio_preset("process", process_id)
    colors = source_config.get("filament_colour", ["#808080"])
    types = source_config.get("filament_type", ["PLA"])
    if not isinstance(colors, list) or not colors:
        raise ValueError("The project has no readable filament palette.")
    if len(colors) > 128:
        raise ValueError("This project exceeds the supported 128-entry palette size.")
    if not isinstance(types, list) or len(types) != len(colors) or not all(isinstance(t, str) for t in types):
        raise ValueError("The source filament colors and material types do not match.")
    filaments = material_presets(printer, types)
    # Preserve editable parts, plate metadata, and source filament indices.
    if any(int(m.get("value") or "0") > len(colors) for m in layout.findall(".//metadata")
           if m.get("key") == "extruder"):
        raise ValueError("An object refers to a missing source filament slot.")
    # Transfer geometry, infill and support choices. Include recognized process
    # settings explicitly customized by the designer. Retain machine limits.
    groups = source_config.get("different_settings_to_system") or [""]
    edited = set(groups[0].split(";")) if isinstance(groups[0], str) else set()
    design_keys = PROJECT_PROCESS | {
        k for k in edited.intersection(process)
        if k not in PROFILE_HEADERS and not any(w in k for w in
            ("gcode", "post_process", "speed", "acceleration", "jerk", "settings_id",
             "filename", "extruder", "temperature", "compatible", "machine", "tower_interface"))
    }
    overrides = {
        key: source_config[key] for key in design_keys
        if isinstance(source_config.get(key), str)
        and source_config[key] != process.get(key)
    }
    config = {key: value for key, value in (process | machine).items()
              if key not in PROFILE_HEADERS}
    if printer == "Creator 5":
        baseline = Path(__file__).with_name("creator5-native.json")
        config = json.loads(baseline.read_text(encoding="utf-8")) | config
    expand_palette(config, len(colors), len(machine["nozzle_diameter"]))
    for key in CREATOR_FILAMENT_FIELDS:
        values = [f.get(key) for f in filaments]
        if all(isinstance(v, list) and len(v) == 1 for v in values):
            config[key] = [v[0] for v in values]
    config["filament_ids"] = [f.get("filament_id", "") for f in filaments]
    config["filament_map"] = ["1"] * len(colors)
    config["filament_self_index"] = [str(i + 1) for i in range(len(colors))]
    config.update(overrides)
    signature = hashlib.sha256(json.dumps([process_id, overrides], sort_keys=True).encode()).hexdigest()[:8]
    project_preset = f"PlateBridge {config['layer_height']}mm {printer} {signature}" if overrides else process_id
    config.update({
        "printer_settings_id": machine_id, "print_settings_id": project_preset,
        "print_compatible_printers": [machine_id],
        "inherits_group": [process_id if overrides else "", *[""] * len(colors), ""],
        "filament_settings_id": [f["name"] for f in filaments],
        "filament_colour": colors, "filament_type": types,
        "version": "02.06.00.51",
        "different_settings_to_system": [
            ";".join(sorted(overrides)), *[""] * len(colors), ""
        ],
    })
    if bed_bounds(source_config) == bed_bounds(machine):
        for axis in ("wipe_tower_x", "wipe_tower_y"):
            if isinstance(source_config.get(axis), list):
                config[axis] = source_config[axis]
    return config, machine, process, overrides


def convert_project(source, requested_output, printer, spool_plan=None):
    with ZipFile(source) as original:
        validate(original)
        if PROJECT_CONFIG not in original.namelist() or SETTINGS not in original.namelist():
            raise ValueError("This file has no MakerWorld project settings. Choose the original Bambu Studio or Orca project 3MF. Mesh-only and PrusaSlicer files use a different format.")
        source_config = read_json(original, PROJECT_CONFIG)
        layout = parse(original, SETTINGS)
        config, machine, process, overrides = project_settings(source_config, layout, printer)
        project_preset = config["print_settings_id"]
        process_id = process["name"]
        machine_id = config["printer_settings_id"]
        offsets = plate_offsets(layout, source_config, machine)
        plan_file = "Metadata/platebridge_spools.json"
        previous = read_json(original, plan_file) if plan_file in original.namelist() else {}
        original_names = {}
        for number, plate in enumerate(layout.findall("plate"), 1):
            mapping = (spool_plan or {}).get(number, {})
            # Single-nozzle feeders choose the actual tray in Studio's send dialog.
            # Expose the user's loading plan there in the plate title as well.
            title = plate.find("metadata[@key='plater_name']")
            old_name = (previous.get("titles") or {}).get(str(number))
            if old_name and title is not None and title.get("value") == old_name["shown"]:
                title.set("value", old_name["original"])
            if mapping and printer != "Creator 5":
                if title is None:
                    title = ET.SubElement(plate, "metadata", key="plater_name")
                original_name = title.get("value", "")
                slots_text = ", ".join(f"C{c}=S{s}" for c,s in sorted(mapping.items()))
                shown = f"{original_name or f'Plate {number}'} · {slots_text}"
                title.set("value", shown)
                original_names[number] = {"original": original_name, "shown": shown}
            if any(not 1 <= color <= len(config["filament_colour"]) or not 1 <= slot <= PRESETS[printer][3]
                   for color, slot in mapping.items()):
                raise ValueError(f"Invalid spool assignment on plate {number}.")
            if mapping and printer == "Creator 5":
                slots = list(config["filament_map"])
                for color, slot in mapping.items():
                    slots[color - 1] = str(slot)
                for key, value in (("filament_maps", " ".join(slots)), ("filament_map_mode", "Manual")):
                    entry = plate.find(f"metadata[@key='{key}']")
                    if entry is None:
                        entry = ET.SubElement(plate, "metadata", key=key)
                    entry.set("value", value)
            for m in plate.findall("metadata"):
                if m.get("key") == "filament_maps" and not (mapping and printer == "Creator 5"):
                    m.set("value", " ".join(config["filament_map"]))
                elif m.get("key") == "filament_map_mode" and not (mapping and printer == "Creator 5"):
                    m.set("value", "Auto For Flush")
                elif m.get("key") in {"gcode_file", "gcode_file_path"}:
                    plate.remove(m)
        with TemporaryDirectory() as temporary:
            staged = Path(temporary) / "project.3mf"
            with ZipFile(staged, "w", ZIP_DEFLATED) as output:
                for item in original.infolist():
                    name = item.filename
                    lower = name.lower()
                    if (lower == "metadata/platebridge_spools.json" or lower.endswith((".gcode", ".gcode.md5", ".gco", ".gx")) or "custom_gcode" in lower
                            or lower.startswith(("metadata/process_settings_", "metadata/print_setting_",
                                                 "metadata/filament_settings_", "metadata/machine_settings_"))
                            or lower in {"metadata/slice_info.config", "metadata/print_profile.config",
                                         "metadata/filament_sequence.json"}):
                        continue
                    if name == PROJECT_CONFIG:
                        output.writestr(name, json.dumps(config, indent=2))
                    elif name == MODEL:
                        with original.open(item) as reader, output.open(name, "w") as writer:
                            write_model(reader, writer, offsets)
                    elif name == SETTINGS:
                        output.writestr(name, ET.tostring(layout, encoding="utf-8", xml_declaration=True))
                    elif lower.endswith(".rels"):
                        links = parse(original, name)
                        removed = False
                        for link in list(links):
                            if ".gcode" in link.get("Target", "").lower():
                                links.remove(link)
                                removed = True
                        if removed:
                            ET.register_namespace("", links.tag[1:].split("}")[0])
                            output.writestr(name, ET.tostring(links, encoding="utf-8", xml_declaration=True))
                        else:
                            output.writestr(name, original.read(item))
                    else:
                        with original.open(item) as reader, output.open(name, "w") as writer:
                            shutil.copyfileobj(reader, writer)
                if spool_plan:
                    output.writestr(plan_file, json.dumps({"printer": printer, "plates": spool_plan, "titles": original_names}))
                if overrides:
                    embedded = dict(overrides, name=project_preset, inherits=process_id,
                                    print_settings_id=project_preset, compatible_printers=[machine_id],
                                    version=process["version"], **{"from": "project"})
                    output.writestr("Metadata/process_settings_1.config", json.dumps(embedded))
            with ZipFile(staged) as check:
                if check.testzip() is not None:
                    raise ValueError("The converted project failed its archive check.")
            requested_output = Path(requested_output)
            attempt = 1
            while True:
                suffix = "" if attempt == 1 else f" ({attempt})"
                destination = requested_output.with_name(f"{requested_output.stem}{suffix}.3mf")
                try:
                    writer = destination.open("xb")
                except FileExistsError:
                    attempt += 1
                    continue
                try:
                    with writer, staged.open("rb") as reader:
                        shutil.copyfileobj(reader, writer)
                except OSError:
                    destination.unlink(missing_ok=True)
                    raise
                return destination


def export_beside_source(source, printer):
    source = Path(source).resolve()
    output = source.with_name(f"{source.stem} {printer}.3mf")
    return [convert_project(source, output, printer)]


