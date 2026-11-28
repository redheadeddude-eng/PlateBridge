"""Read editable 3MF geometry and compare the actual export profiles."""
from array import array
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from itertools import batched
import math
from pathlib import Path
import posixpath
from xml.parsers import expat
from zipfile import ZipFile

import plateproject as core


IDENTITY = (1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0)


def matrix(value):
    m = tuple(map(float, value.split())) if value else IDENTITY
    if len(m) != 12 or not all(map(math.isfinite, m)):
        raise ValueError("Invalid placement in the source model.")
    return m


def compose(local, parent):
    product = [sum(local[i + j] * parent[j * 3 + k] for j in range(3))
               for i in (0, 3, 6, 9) for k in range(3)]
    for i in range(9, 12):
        product[i] += parent[i]
    return product


@lru_cache(maxsize=4096)
def paint_colors(encoded):
    """Read the leaf material numbers in a Bambu triangle subdivision tree."""
    digits = iter(reversed(encoded))
    pending = 1
    colors = set()
    while pending:
        nibble = int(next(digits), 16)
        pending -= 1
        split = nibble & 3
        if split:
            pending += split + 1
        else:
            color = nibble >> 2
            if color == 3:
                extra = int(next(digits), 16)
                color = 3 + extra if extra < 15 else 18 + int(next(digits), 16)
            colors.add(color)
    if next(digits, None) is not None:
        raise ValueError("Unknown paint encoding")
    return colors


@dataclass
class Mesh:
    points: array = field(default_factory=lambda: array("d"))
    parts: list = field(default_factory=list)
    colors: set = field(default_factory=set)
    uncertain: bool = False


def read_models(archive):
    models, builds = {}, []
    for name in archive.namelist():
        if not name.lower().endswith(".model"):
            continue
        current = None
        def start(tag, attrs):
            nonlocal current
            tag = tag.rsplit("|", 1)[-1]
            if tag == "model" and attrs.get("unit", "millimeter") != "millimeter":
                raise ValueError("Plate measurements currently require a millimeter project.")
            if tag == "object":
                current = Mesh()
                models[name, attrs["id"]] = current
            elif tag == "vertex" and current is not None:
                current.points.extend((float(attrs["x"]), float(attrs["y"]), float(attrs["z"])))
            elif tag == "triangle" and current is not None:
                paint = attrs.get("paint_color")
                if paint:
                    try:
                        current.colors.update(paint_colors(paint))
                    except (ValueError, StopIteration):
                        current.uncertain = True
                else:
                    current.colors.add(0)
                if "pid" in attrs:
                    current.uncertain = True
            elif tag == "component" and current is not None:
                path = next((v for k, v in attrs.items() if k.endswith("|path")), "")
                target = (path.lstrip("/") if path.startswith("/") else
                          posixpath.normpath(posixpath.join(posixpath.dirname(name), path)) if path else name)
                current.parts.append(((target, attrs["objectid"]), matrix(attrs.get("transform"))))
            elif tag == "item" and name == core.MODEL:
                builds.append((attrs["objectid"], matrix(attrs.get("transform")), attrs.get("printable") != "0"))
        def end(tag):
            nonlocal current
            if tag.rsplit("|", 1)[-1] == "object":
                current = None
        def reject(*args):
            raise ValueError("Unsupported XML declaration in the model.")
        parser = expat.ParserCreate(namespace_separator="|")
        parser.StartElementHandler, parser.EndElementHandler = start, end
        parser.StartDoctypeDeclHandler = reject
        with archive.open(name) as stream:
            parser.ParseFile(stream)
    return models, builds


def metadata(node):
    return {m.get("key"): m.get("value") for m in node.findall("metadata")}


def measured_object(models, obj_id, placement, settings, palette_size):
    axes = [array("d") for _ in range(3)]
    colors, uncertain = set(), False
    policies = {p.get("id"): p for p in settings.findall("part")} if settings is not None else {}
    meta = metadata(settings) if settings is not None else {}
    base = int(meta.get("extruder") or 1) or 1

    def collect(key, transform, base_color, ancestors):
        nonlocal uncertain
        if key in ancestors or len(ancestors) > 64:
            raise ValueError("The project contains a circular component reference.")
        mesh = models[key]
        part = policies.get(key[1])
        if part is not None:
            if part.get("subtype", "normal_part") != "normal_part":
                if part.get("subtype") == "modifier_part":
                    uncertain = True
                return
            base_color = int(metadata(part).get("extruder") or 0) or base_color
        if mesh.points:
            colors.update(c or base_color for c in mesh.colors or {0})
            uncertain |= mesh.uncertain
            a,b,c,d,e,f,g,h,i,x,y,z = transform
            ax, ay, az = axes
            for u,v,w in batched(mesh.points, 3):
                ax.append(a*u+d*v+g*w+x)
                ay.append(b*u+e*v+h*w+y)
                az.append(c*u+f*v+i*w+z)
        for child, local in mesh.parts:
            collect(child, compose(local, transform), base_color, ancestors | {key})

    collect((core.MODEL, obj_id), placement, base, set())
    if not axes[0]:
        raise ValueError(f"Could not measure printable object {obj_id}.")
    bounds = [(min(a), max(a)) for a in axes]
    if not all(math.isfinite(v) for ends in bounds for v in ends):
        raise ValueError("The model contains invalid vertex coordinates.")
    uncertain |= any(c < 1 or c > palette_size for c in colors)
    return meta.get("name") or f"Object {obj_id}", axes, bounds, colors.intersection(range(1, palette_size+1)), uncertain


def rotation_hint(axes, sizes, limits):
    if all(s <= limit + 0.01 for s, limit in zip(sizes, limits)):
        return "Recenter this part on its plate."
    # Evaluate the geometry after rotating it, rather than rotating its bounding box.
    for axis, axis_name in enumerate("XYZ"):
        if sizes[axis] > limits[axis] + 0.01:
            continue
        u, v = (axis + 1) % 3, (axis + 2) % 3
        for degrees in (90, 45, -45, 30, -30, 60, -60):
            a = math.radians(degrees)
            co, si = math.cos(a), math.sin(a)
            left, right = math.inf, -math.inf
            low, high = math.inf, -math.inf
            for p, q in zip(axes[u], axes[v]):
                x, y = p*co-q*si, p*si+q*co
                left, right = min(left,x), max(right,x)
                low, high = min(low,y), max(high,y)
                if right-left > limits[u]+0.01 or high-low > limits[v]+0.01:
                    break
            else:
                return f"Rotate {degrees}° about {axis_name} and recenter. Check other parts and supports."
    return "No tested single-axis turn fits at full size."


def fit_object(name, axes, bounds, plate_origin, bed, height, hint_cache):
    # Local coordinates measured from the centre of the source plate are
    # invariant under PlateBridge's target-grid translation.
    limits = (bed[2], bed[3], height)
    sizes = tuple(hi-lo for lo,hi in bounds)
    problems = []
    for idx, (lo, hi) in enumerate(bounds):
        origin = plate_origin[idx] if idx < 2 else 0
        edge = origin - limits[idx]/2 if idx < 2 else 0
        for delta, label in ((edge-lo, ("left","front","below bed")[idx]),
                             (hi-edge-limits[idx], ("right","back","above bed")[idx])):
            if delta > 0.05:
                problems.append(f"{delta:.1f} mm {label}")
    if not problems:
        return None
    if limits not in hint_cache:
        hint_cache[limits] = rotation_hint(axes, sizes, limits)
    return f"{name} · {', '.join(problems)}. {hint_cache[limits]}"


def inspect_project(path):
    with ZipFile(path) as archive:
        core.validate(archive)
        if core.PROJECT_CONFIG not in archive.namelist() or core.SETTINGS not in archive.namelist():
            raise ValueError("Choose an editable Bambu Studio or Orca project 3MF.")
        source = core.read_json(archive, core.PROJECT_CONFIG)
        layout = core.parse(archive, core.SETTINGS)
        previous = (core.read_json(archive, "Metadata/platebridge_spools.json")
                    if "Metadata/platebridge_spools.json" in archive.namelist() else {})
        models, builds = read_models(archive)
    targets, errors, fits = {}, {}, {}
    for printer in core.PRINTERS:
        try:
            cfg, machine, *_ = core.project_settings(source, layout, printer)
            targets[printer] = cfg
            fits[printer] = core.bed_bounds(machine), float(machine["printable_height"])
        except ValueError as e:
            errors[printer] = str(e)
    sx,sy,sw,sh = core.bed_bounds(source)
    counts, instances = Counter(), {}
    for obj, transform, printable in builds:
        instances[obj, counts[obj]] = transform, printable
        counts[obj] += 1
    objects = {o.get("id"):o for o in layout.findall("object")}
    plates = []
    entries = layout.findall("plate")
    if not entries:
        raise ValueError("No editable plates were found.")
    cols = math.isqrt(len(entries)-1)+1
    for index, entry in enumerate(entries):
        meta = metadata(entry)
        center = (sx+sw/2+(index%cols)*sw*1.2, sy+sh/2-(index//cols)*sh*1.2)
        plate = {"name":meta.get("plater_name") or f"Plate {index+1}", "colors":set(),
                 "uncertain":False, "issues":{k:[] for k in fits}, "parts":0}
        for inst in entry.findall("model_instance"):
            info = metadata(inst)
            obj = info["object_id"]
            trans, printable = instances[obj, int(info["instance_id"])]
            if not printable:
                continue
            name, axes, bounds, colors, uncertain = measured_object(
                models, obj, trans, objects.get(obj), len(source["filament_colour"]))
            plate["parts"] += 1
            plate["colors"].update(colors)
            plate["uncertain"] |= uncertain
            hints = {}
            for printer, (bed, height) in fits.items():
                issue = fit_object(name, axes, bounds, center, bed, height, hints)
                if issue:
                    plate["issues"][printer].append(issue)
        if source.get("enable_support") == "1" and plate["parts"]:
            for key in ("support_filament","support_interface_filament"):
                slot = int(source.get(key) or 0)
                if 0 < slot <= len(source["filament_colour"]):
                    plate["colors"].add(slot)
        plate["colors"] = sorted(plate["colors"])
        plates.append(plate)
    return dict(source=source, targets=targets, errors=errors, plates=plates, previous=previous)


def differences(report, printer):
    source, target = report["source"], report["targets"][printer]
    main = ["layer_height","enable_support","support_type","sparse_infill_density",
            "wall_loops","filament_type","filament_colour","filament_settings_id","printer_settings_id"]
    keys = main + sorted((set(source) | set(target)) - set(main))
    for key in keys:
        same = key in source and key in target and source[key] == target[key]
        if key in main or not same:
            status = ("Kept" if same else "Source only" if key not in target
                      else "Added" if key not in source else "Changed")
            yield key, source.get(key), target.get(key), status
