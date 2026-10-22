"""Five controlled print trials on one P1S plate; no printer communication.

All trials share the reviewed Mem, an engineering ring aperture, original and
thickened 4mm digits, and a flat inspection patch. Only the large upper-right
ID and the documented per-object setting differ. These are engineering coupons,
not newly approved handwriting teaching cards.
"""
import copy
import hashlib
import io
import json
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np
import trimesh
from PIL import Image, ImageDraw
from shapely import affinity
from shapely.geometry import Point, box
from shapely.ops import unary_union

import generate as g
from card_shapes import shapes
from export_bambu_color_trial import BAMBU, resolve_preset
from refine_card_design import font, marks
from review_print_arrows import number_shape

OUT = g.ROOT / "outputs/print_comparison_v13"
FILENAME = "print_comparison_1-5_BAMBU_v13.3mf"
COLORS = ["#282828", "#FFFFFF"]
VARIANTS = [
    {"id": 1, "x": 100, "y": 160, "label": "בסיס להשוואה", "reference": None,
     "settings": {"top_surface_speed": "200,200", "outer_wall_speed": "200,200", "ironing_type": "no ironing", "wall_generator": "classic"}},
    {"id": 2, "x": 14, "y": 160, "label": "משטח עליון איטי", "reference": 1,
     "settings": {"top_surface_speed": "60,60", "outer_wall_speed": "200,200", "ironing_type": "no ironing", "wall_generator": "classic"}},
    {"id": 3, "x": 100, "y": 86, "label": "גם היקפים איטיים", "reference": 2,
     "settings": {"top_surface_speed": "60,60", "outer_wall_speed": "40,40", "ironing_type": "no ironing", "wall_generator": "classic"}},
    {"id": 4, "x": 14, "y": 86, "label": "גם גיהוץ", "reference": 2,
     "settings": {"top_surface_speed": "60,60", "outer_wall_speed": "200,200", "ironing_type": "topmost", "wall_generator": "classic"}},
    {"id": 5, "x": 100, "y": 12, "label": "גם Arachne לקווים דקים", "reference": 2,
     "settings": {"top_surface_speed": "60,60", "outer_wall_speed": "200,200", "ironing_type": "no ironing", "wall_generator": "arachne"}},
]


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def metadata(element):
    return {m.get("key"): m.get("value") for m in element.findall("metadata") if m.get("key")}


def set_metadata(element, key, value):
    item = element.find(f"metadata[@key='{key}']")
    if item is None:
        item = ET.SubElement(element, "metadata", key=key)
    item.set("value", str(value))


def preview(c, visuals):
    ss, width, height, scale = 2, 1860, 1580, 5.3
    im = Image.new("RGB", (width * ss, height * ss), "#f7f5ef")
    d = ImageDraw.Draw(im)

    def text(x, y, value, size=28, anchor="rt", color="#283d42"):
        d.text((x * ss, y * ss), value, font=font(c, size * ss), direction="rtl", anchor=anchor, fill=color)

    text(width - 40, 24, "משטח השוואה — חמש גרסאות של אותו אריח", 43)
    text(width - 40, 91, "מספר הגרסה גדול בפינה הימנית העליונה • כל האריחים בעובי 2.4 מ״מ", 27)
    for variant, body, marker in visuals:
        xoff, yoff = variant["x"], variant["y"]
        tf = lambda x, y: ((95 + (x + xoff - 5.7) * scale) * ss,
                          (225 + (222 - y - yoff) * scale) * ss)
        g.paint(d, body, tf, COLORS[0])
        g.paint(d, marker, tf, COLORS[1])
        text(95 + (xoff + 30 - 5.7) * scale, 225 + (222 - yoff - 62) * scale - 47,
             f"גרסה {variant['id']}", 29, anchor="mt")
    y = 230
    lines = [
        ("1 — בסיס", "משטח עליון: 200 מ״מ/ש׳", "היקף חיצוני: 200 מ״מ/ש׳"),
        ("2 — משטח עליון איטי", "משטח עליון: 60 מ״מ/ש׳", "משווים לגרסה 1"),
        ("3 — גם היקפים איטיים", "כמו 2, היקף חיצוני: 40 מ״מ/ש׳", "משווים לגרסה 2"),
        ("4 — גם גיהוץ", "כמו 2, בתוספת גיהוץ עליון", "משווים לגרסה 2"),
        ("5 — גם Arachne", "כמו 2, יצירת קירות ברוחב משתנה", "משווים לגרסה 2"),
    ]
    for heading, a, b in lines:
        text(1810, y, heading, 33)
        text(1810, y + 55, a, 26)
        text(1810, y + 100, b, 25, color="#687470")
        y += 185
    text(1810, 1210, "בכל אריח:", 29)
    text(1810, 1260, "מ׳ עם החצים, פתח עגול עם גשר", 25)
    text(1810, 1305, "משטח שטוח וספרות 1 ו־2", 25)
    text(1810, 1350, "למטה מימין: רגילות; מעליהן: מעובות", 24)
    text(width - 40, 1455, "קצב שכבה אחיד: 0.20 מ״מ • שחור: גוף • לבן: סימונים • אריחי בדיקה הנדסיים", 28)
    text(width - 40, 1512, "לא לשנות את הגדרות האובייקטים אחרי הפתיחה; המהירויות בפועל כפופות להאצה ולקירור", 25)
    im.resize((width, height), Image.Resampling.LANCZOS).save(OUT / "comparison_guide.jpg", quality=96, subsampling=0)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    original = json.loads((g.ROOT / "outputs/noga_samekh_trial_v12/config.trial.json").read_text())
    c = copy.deepcopy(original)
    c.update(width=68.0, height=62.0, thickness=2.4)
    g.validate_config(c)
    review = json.loads((g.ROOT / "data/review/card_stencil_layout_v8.json").read_text())
    row = next(r for r in review["tiles"] if r["char"] == "מ")
    reference = json.loads((g.ROOT / "data/review/user_print_stroke_cards_v6.json").read_text())
    source = g.ROOT / "docs/pedagogy/user_reference/hebrew-print-stroke-cards.pdf"
    if hashlib.sha256(source.read_bytes()).hexdigest() != review["source_sha256"]:
        raise ValueError("Reviewed PDF changed")
    # Keep Mem at its reviewed original size and location; only widen the panel.
    glyphs, _, _ = shapes(original, reference)
    loop = Point(54, 43).buffer(6.5, quad_segs=64).difference(Point(54, 43).buffer(6.5 - 2.631578947, quad_segs=64))
    bridge = box(53.1, 43, 54.9, 51)
    body = g.tile(c).difference(glyphs["מ"]).difference(loop).union(bridge)
    common_parts = [marks(original, row)]
    for y, growth in [(8, 0), (17, .12)]:
        for digit, x in [(1, 44), (2, 50)]:
            common_parts.append(number_shape(c, digit, x, y).buffer(growth, quad_segs=16) if growth
                                else number_shape(c, digit, x, y))
    common_marks = unary_union(common_parts)
    id_config = copy.deepcopy(c)
    id_config["marker_number_height"] = 7.0
    id_config["font_axes"]["print"]["wght"] = 700
    parts, groups, visuals, geometry_reports = [], [], [], []
    full = g.extrude(body, c["thickness"])
    for variant in VARIANTS:
        number = number_shape(id_config, variant["id"], 0, 52)
        number = affinity.translate(number, xoff=65 - number.bounds[2])
        marker = common_marks.union(number)
        if not body.buffer(-c["marker_clearance"]).contains(marker):
            raise ValueError(f"Marker reaches a cut edge in version {variant['id']}")
        base, fill, _ = g.split_layers(c, body, marker)
        if len(base.split()) != 1:
            raise ValueError("Unattached island after engraving")
        united = trimesh.boolean.union([base, fill], engine="manifold")
        if max(abs(united.volume - full.volume), abs(base.volume + fill.volume - united.volume)) > .02:
            raise ValueError("Inlay mismatch")
        group = []
        for suffix, mesh, color in [("body", base, COLORS[0]), ("markers", fill, COLORS[1])]:
            mesh.export(OUT / f"version_{variant['id']}_{suffix}.stl")
            shifted = mesh.copy()
            shifted.apply_translation([variant["x"], variant["y"], 0])
            group.append(len(parts))
            parts.append((f"version_{variant['id']}_{suffix}", shifted, color))
        groups.append(group)
        visuals.append((variant, body, marker))
        geometry_reports.append({"version": variant["id"], "body_watertight": bool(base.is_watertight),
            "inlay_watertight": bool(fill.is_watertight), "body_components": 1,
            "minimum_marker_clearance_mm": marker.distance(body.boundary), "id_height_mm": 7,
            "id_font_weight": 700, "only_id_differs_in_measurement_geometry": True})
    placed = [affinity.translate(body, xoff=v["x"], yoff=v["y"]) for v in VARIANTS]
    if any(a.intersection(b).area > 1e-8 for i, a in enumerate(placed) for b in placed[i + 1:]):
        raise ValueError("Plate objects intersect")
    for variant in VARIANTS[1:]:
        ref = VARIANTS[variant["reference"] - 1]
        changed = [k for k in variant["settings"] if variant["settings"][k] != ref["settings"][k]]
        if len(changed) != 1:
            raise ValueError("Each comparison must isolate one setting")
        variant["changed_key"] = changed[0]
    preview(c, visuals)
    with tempfile.TemporaryDirectory(prefix="hebrew-comparison-v13-") as tmp:
        work = Path(tmp)
        generic, native, assigned = [work / n for n in ["generic.3mf", "native.3mf", "assigned.3mf"]]
        g.write_3mf(generic, parts, groups=groups)
        for kind, name, key in [("machine", "Bambu Lab P1S 0.4 nozzle", "printer_settings_id"),
                                ("process", "0.20mm Standard @BBL X1C", "print_settings_id"),
                                ("filament", "Generic PLA", "filament_settings_id")]:
            preset = resolve_preset(kind, name)
            preset[key] = [name] if kind == "filament" else name
            save_json(work / f"{kind}.json", preset)

        def cli(args, log):
            result = subprocess.run([BAMBU, "--datadir", str(work / "settings"), *map(str, args)],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
            (OUT / log).write_text(result.stdout)
            if result.returncode:
                raise RuntimeError(f"Bambu failed with {result.returncode}: {log}")

        cli(["--arrange", "0", "--load-settings", f"{work/'machine.json'};{work/'process.json'}", "--load-filaments",
             f"{work/'filament.json'};{work/'filament.json'}", "--export-3mf", native, generic], "native_export.log")
        with ZipFile(native) as z:
            data = {n: z.read(n) for n in z.namelist() if not n.endswith(".png")}
        config = ET.fromstring(data["Metadata/model_settings.config"])
        objects = config.findall("object")
        if len(objects) != 5:
            raise ValueError("The trials must import as five independent multipart objects")
        for obj, variant, group in zip(objects, VARIANTS, groups):
            set_metadata(obj, "name", f"{variant['id']} - {variant['label']}")
            for key, value in variant["settings"].items():
                set_metadata(obj, key, value)
            native_parts = obj.findall("part")
            if len(native_parts) != 2:
                raise ValueError("Expected body and markers in each trial")
            for part, index in zip(native_parts, group):
                name, mesh, _ = parts[index]
                if int(part.find("mesh_stat").get("face_count")) != len(mesh.faces):
                    raise ValueError("Object ordering or triangulation changed")
                set_metadata(part, "name", name)
                set_metadata(part, "extruder", "2" if name.endswith("markers") else "1")
        data["Metadata/model_settings.config"] = ET.tostring(config, encoding="utf-8", xml_declaration=True)
        settings = json.loads(data["Metadata/project_settings.config"])
        settings.update(filament_colour=COLORS, default_filament_colour=COLORS, curr_bed_type="Textured PEI Plate",
            top_surface_speed=["200", "200"], outer_wall_speed=["200", "200"],
            small_perimeter_speed=["50%", "50%"], small_perimeter_threshold=["6", "6"],
            ironing_type="no ironing", ironing_flow="10%", ironing_spacing="0.15", ironing_speed="30",
            wall_generator="classic", flush_volumes_matrix=["0", "280", "280", "0"],
            flush_volumes_vector=["140", "140", "140", "140"],
            wipe_tower_x=["195"], wipe_tower_y=["185"])
        data["Metadata/project_settings.config"] = json.dumps(settings, indent=2).encode()
        with ZipFile(assigned, "w", ZIP_DEFLATED) as z:
            for n, contents in data.items():
                z.writestr(n, contents)
        target = OUT / FILENAME
        cli(["--arrange", "0", "--export-3mf", target, assigned], "roundtrip.log")
        with ZipFile(target) as z:
            config = ET.fromstring(z.read("Metadata/model_settings.config"))
            settings = json.loads(z.read("Metadata/project_settings.config"))
        expected_names = []
        for obj in config.findall("object"):
            actual = metadata(obj)
            variant = VARIANTS[int(actual["name"].split(" - ")[0]) - 1]
            for key, value in variant["settings"].items():
                if actual.get(key) != value:
                    raise ValueError(f"Per-object setting lost: {variant['id']} {key}: {actual.get(key)}")
            if [metadata(p).get("extruder") for p in obj.findall("part")] != ["1", "2"]:
                raise ValueError("Color mapping lost")
            expected_names.append(actual["name"])
        cli(["--camera-view", "1", "--export-png", "0", "--outputdir", work, target], "render.log")
        rendered = work / "plate_1_1.png"
        (OUT / "bambu_comparison_preview.png").write_bytes(rendered.read_bytes())
        # Use the actual assigned-model render as the project thumbnail.
        with ZipFile(target) as z:
            data = {n: z.read(n) for n in z.namelist()}
        with Image.open(rendered) as im:
            for name, size in [("Metadata/plate_1.png", 512), ("Metadata/plate_1_small.png", 128),
                               ("Metadata/plate_no_light_1.png", 512)]:
                buffer = io.BytesIO()
                im.resize((size, size), Image.Resampling.LANCZOS).save(buffer, format="PNG")
                data[name] = buffer.getvalue()
        with ZipFile(target, "w", ZIP_DEFLATED) as z:
            for n, contents in data.items():
                z.writestr(n, contents)
        cli(["--info", target], "bambu_import.log")
        if "manifold = yes" not in (OUT / "bambu_import.log").read_text():
            raise ValueError("Bambu manifold check failed")
        # Slicing is diagnostic only. Its G-code stays in this temporary folder.
        slice_dir = work / "slice"
        slice_dir.mkdir()
        cli(["--arrange", "0", "--slice", "0", "--outputdir", slice_dir, "--export-3mf", "diagnostic_sliced.3mf", target], "diagnostic_slice.log")
        gcode = (slice_dir / "plate_1.gcode").read_text()
        header = "\n".join(gcode.splitlines()[:14])
        (OUT / "slice_estimate.txt").write_text(header + "\n")
        with ZipFile(slice_dir / "diagnostic_sliced.3mf") as z:
            sliced_config = ET.fromstring(z.read("Metadata/model_settings.config"))
        # Map G-code OBJECT_ID to trial names via native plate instance IDs.
        object_names = {obj.get("id"): metadata(obj)["name"] for obj in sliced_config.findall("object")}
        identify_names = {}
        for instance in sliced_config.findall("plate/model_instance"):
            info = metadata(instance)
            identify_names[int(info["identify_id"])] = object_names[info["object_id"]]
        stats = {name: {"top_speeds_mm_s": [], "outer_speeds_mm_s": [], "ironing_moves": 0}
                 for name in expected_names}
        object_id, feature, feed, layer = None, "", 0, 0
        for line in gcode.splitlines():
            if line.startswith("; OBJECT_ID:"):
                object_id = int(line.split(":")[1])
            elif line.startswith("; FEATURE:"):
                feature = line.split(":", 1)[1].strip()
            elif line.startswith("; Z_HEIGHT:"):
                layer = float(line.split(":")[1])
            elif re.match(r"^G[123] ", line):
                values = {key: float(value) for key, value in re.findall(r"([XYEF])(-?(?:\d+(?:\.\d*)?|\.\d+))", line.split(";")[0])}
                feed = values.get("F", feed)
                name = identify_names.get(object_id)
                if name not in stats or values.get("E", 0) <= 0 or not any(k in values for k in ["X", "Y"]) or layer < .4:
                    continue
                if feature == "Top surface":
                    stats[name]["top_speeds_mm_s"].append(feed / 60)
                if feature == "Outer wall":
                    stats[name]["outer_speeds_mm_s"].append(feed / 60)
                if feature == "Ironing":
                    stats[name]["ironing_moves"] += 1
        observed = {}
        for name, stat in stats.items():
            observed[name] = {"top_surface_max_mm_s": max(stat["top_speeds_mm_s"], default=0),
                "outer_wall_max_mm_s": max(stat["outer_speeds_mm_s"], default=0),
                "ironing_moves": stat["ironing_moves"]}
        # Assertions are tied to actual emitted toolpaths, not only stored XML.
        by_id = {int(name.split(" - ")[0]): stat for name, stat in observed.items()}
        if by_id[1]["top_surface_max_mm_s"] <= by_id[2]["top_surface_max_mm_s"] or not by_id[2]["top_surface_max_mm_s"]:
            raise ValueError(f"Surface-speed contrast absent in sliced paths: {observed}")
        if by_id[3]["outer_wall_max_mm_s"] > 40.1 or by_id[3]["outer_wall_max_mm_s"] <= 0:
            raise ValueError("Slow-wall setting not present in sliced paths")
        if by_id[4]["ironing_moves"] <= 0 or any(by_id[i]["ironing_moves"] for i in [1, 2, 3, 5]):
            raise ValueError(f"Ironing not restricted to version 4: {observed}")
    vertices = np.concatenate([mesh.vertices for _, mesh, _ in parts])
    validation = {"status": "geometry, independent objects, roundtrip settings and local slicing verified",
        "geometry": geometry_reports, "variants": VARIANTS, "observed_slicer_paths": observed,
        "plate_bounds_mm": [vertices.min(axis=0).tolist(), vertices.max(axis=0).tolist()],
        "plate_footprint_mm": (vertices.max(axis=0) - vertices.min(axis=0)).tolist(),
        "thickness_mm": 2.4, "layer_height_mm": .2, "filament_profile": "Generic PLA",
        "physical_results": "pending", "gcode_delivered": False, "printer_commands_sent": False}
    save_json(OUT / "validation.json", validation)
    save_json(OUT / "config.trial.json", c)
    save_json(OUT / "experiment.json", {"source_pdf_sha256": review["source_sha256"],
        "reviewed_mem_layout": "data/review/card_stencil_layout_v8.json",
        "purpose": "Engineering comparison coupon, not an added teaching letter",
        "features": ["unchanged full-size reviewed Mem and arrows", "2.6316mm annular aperture and 1.8mm island bridge",
                     "flat bottom inspection area", "4mm regular digits and the same digits expanded .12mm per edge",
                     "7mm bold upper-right version ID", "full-size existing puzzle connector"],
        "fixed_settings": {"small_perimeter_threshold_mm": 6, "small_perimeter_speed": "50% of outer wall",
                           "ironing_flow": "10%", "ironing_spacing_mm": .15, "ironing_speed_mm_s": 30},
        "variants": VARIANTS})
    (OUT / "PRINT_HE.txt").write_text(f"""משטח השוואה 1–5 — v13

לפתוח את {FILENAME} כ־Open Project ב־Bambu Studio.
חמישה אובייקטים עצמאיים, בכל אחד גוף בפילמנט 1 וסימונים בפילמנט 2.
מספר גרסה 1–5 גדול ומודגש בפינה הימנית העליונה של כל אריח.
המספרים הקטנים 1 ו־2 ליד החצים הם שלבי מ׳; מספר הגרסה הגדול משמש לזיהוי הניסוי.

ההשוואות
1 — בסיס: משטח עליון 200 מ״מ/ש׳, היקף חיצוני 200, Classic, ללא גיהוץ.
2 — כמו 1, משטח עליון 60 מ״מ/ש׳. להשוות ל־1.
3 — כמו 2, היקף חיצוני 40 מ״מ/ש׳. להשוות ל־2.
4 — כמו 2, גיהוץ עליון מופעל. להשוות ל־2.
5 — כמו 2, Arachne במקום Classic. להשוות ל־2.
כל השוואה לעיל משנה פרמטר אחד ביחס לגרסת הייחוס שצוינה.
אלה ערכי ניסוי, לא קביעה מה אידיאלי לפני שראינו את ההדפסה.

קבוע בכל הגרסאות
עובי 2.4 מ״מ; שכבה 0.20; P1S עם דיזה 0.4; Textured PEI; שני Generic PLA.
פתח מ׳ וחציה בגודל המקורי, פתח טבעתי ברוחב 2.63 עם גשר 1.8, ומשטח שטוח בתחתית.
מימין למטה זוג 1 ו־2 רגילים בגובה 4 מ״מ, ומעליהם אותו זוג מעובה ב־0.12 מ״מ לכל צד.
מחבר פאזל בגודל המקורי, עם מרווח 0.20 מ״מ. רוחב הפנל 68 מ״מ, גובהו 62, ורוחב כולל לשונית 76.3.
סף היקפים קטנים 6 מ״מ ומהירותם 50% ממהירות ההיקף החיצוני, זהים בכל הגרסאות.
בגרסה 4 הגיהוץ הוא 30 מ״מ/ש׳, 10% זרימה ומרווח 0.15 מ״מ; בשאר הגרסאות כבוי.
אין ערבוב של גובהי שכבה באותו משטח. ההגדרות הן לאובייקטים שלמים, כולל הגוף והסימונים.

לפני ההדפסה
• לשמור על הגדרות האובייקטים; לא לייבא כגאומטריה בלבד ולא למזג את חמשת האובייקטים.
• לבחור את שני הפילמנטים האמיתיים. אם קיימים פרופילים מכוילים לשחור וללבן, להשתמש בהם בעקביות לכל הניסוי.
• לעדכן צבעים ולחשב מחדש Flushing volumes לשחור/לבן לפני Slice; ערכי הבסיס אינם כיול טיהור לסלילים שלך.
• לבצע Slice ולוודא שהאריחים ומגדל הניקוי בתוך המשטח, ולבדוק בתצוגת המהירויות שהגרסאות שונות.
• להדפיס במצב Standard; שינוי מהירות כולל במהלך ההדפסה ישנה את ההשוואה.
• אין G-code בחבילה ולא נשלח דבר למדפסת. בוצע Slice מקומי בלבד לבדיקת הפרמטרים.

אחרי ההדפסה
לצלם עם המספר הגדול גלוי, תחת אותה תאורה ובאותו כיוון.
להשוות את השטח השטוח ללא רווחים או רכסים, קריאות הספרות הרגילות והמעובות,
חדות החצים, גבול שחור/לבן, נוחות העיפרון בפתחים וחוזק/דיוק המחברים.
לבדוק גם אם גיהוץ ב־4 שיפר את המשטח או מרח את גבולות הסימונים.
לדרג כל סעיף מ־1 עד 5 בדף RESULTS_HE.csv; אין צורך לבחור מנצח אחד לכל התכונות.
הדגמים הם אריחי בדיקה הנדסיים. כיוון החצים במ׳ נשמר; הפתח הטבעתי הוא מאפיין בדיקה נוסף.
""")
    (OUT / "RESULTS_HE.csv").write_text("גרסה,משטח עליון 1-5,ספרות רגילות 1-5,ספרות מעובות 1-5,חדות חץ 1-5,מחבר 1-5,נוחות כתיבה 1-5,הערות\n" +
        "".join(f"{i},,,,,,,\n" for i in range(1, 6)), encoding="utf-8-sig")
    active_path = g.ROOT / "data/active_design.json"
    active = json.loads(active_path.read_text())
    active["print"]["current_print_experiment"] = {"generator": "src/export_print_comparison.py",
        "project": f"outputs/print_comparison_v13/{FILENAME}", "variants": 5,
        "status": "prepared and sliced locally; physical results pending",
        "features": "Identical Mem-based engineering coupons with prominent upper-right 1–5 IDs"}
    save_json(active_path, active)
    (OUT / "SHA256SUMS.txt").write_text("".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n"
        for p in sorted(OUT.iterdir()) if p.is_file() and p.name != "SHA256SUMS.txt"))
    archive = g.ROOT / "hebrew-stencils-print-comparison-v13.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED) as z:
        for p in sorted(OUT.iterdir()):
            if p.is_file():
                z.write(p, f"print_comparison_v13/{p.name}")
    with ZipFile(archive) as z:
        if z.testzip() or any(n.endswith(".gcode") for n in z.namelist()):
            raise ValueError("Archive verification failed")
    print(json.dumps({"project": str(OUT / FILENAME), "archive": str(archive), "observed_paths": observed,
                      "plate_footprint_mm": validation["plate_footprint_mm"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
