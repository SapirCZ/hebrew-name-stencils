"""User-requested Noga + Samekh trial, retaining reviewed v8 geometry and colors."""
import argparse
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
from shapely.geometry import Polygon
from shapely.ops import unary_union

import generate as g
from card_shapes import shapes
from export_bambu_color_trial import BAMBU, COLORS, read_assignments, resolve_preset
from refine_card_design import font, marks

OUT = g.ROOT / "outputs/noga_samekh_trial_v11"
LAYOUT = [("נ", "nun", 154, 88), ("ג", "gimel", 86, 88),
          ("ה", "he", 18, 88), ("ס", "samekh", 86, 10)]
DUAL = "noga_samekh_BAMBU_DUAL_v11.3mf"
SINGLE = "noga_samekh_BAMBU_SINGLE_v11.3mf"


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def make_preview(c, visuals):
    ss, width, height = 2, 1800, 1340
    im = Image.new("RGB", (width * ss, height * ss), "#f7f5ef")
    draw = ImageDraw.Draw(im)

    def text(x, y, message, size=28, anchor="rt"):
        draw.text((x * ss, y * ss), message, font=font(c, size * ss),
                  fill="#283d42", direction="rtl", anchor=anchor)

    text(width - 40, 24, f"נגה + ס׳ — ניסיון שבלונות בעובי {c['thickness']:g} מ״מ", 44)
    text(width - 40, 90, "גוף בפילמנט 1 • חצים ומספרים בפילמנט 2 • הרכבה מלמעלה", 28)
    for char, body, marker, xoff, yoff in visuals:
        # Preserve isotropic dimensions in this visual just as in the models.
        tf = lambda x, y: ((160 + (x + xoff - 9.7) * 7.1) * ss,
                          (210 + (150 - y - yoff) * 7.1) * ss)
        g.paint(draw, body, tf, COLORS[0])
        g.paint(draw, marker, tf, COLORS[1])
        text((160 + (26 + xoff - 9.7) * 7.1),
             154 if yoff == 88 else 714, char + "׳", 36, anchor="mt")
    text(width - 40, 1240, "ס׳ כוללת גשר ברוחב 1.8 מ״מ שמחזיק את המרכז הפנימי", 27)
    text(width - 40, 1292, "השטח הבהיר הוא פתח. האריחים נפרדים במשטח; מחברים לאחר ההדפסה.", 25)
    im.resize((width, height), Image.Resampling.LANCZOS).save(
        OUT / "noga_samekh_preview.jpg", quality=96, subsampling=0)


def main(thickness=None, revision="v11", filament_profile="Bambu PLA Silk+ @BBL P1S 0.4 nozzle"):
    global OUT, DUAL, SINGLE
    OUT = g.ROOT / f"outputs/noga_samekh_trial_{revision}"
    DUAL = f"noga_samekh_BAMBU_DUAL_{revision}.3mf"
    SINGLE = f"noga_samekh_BAMBU_SINGLE_{revision}.3mf"
    OUT.mkdir(parents=True, exist_ok=True)
    review = json.loads((g.ROOT / "data/review/card_stencil_layout_v8.json").read_text())
    c = copy.deepcopy(review["print_config"])
    if c != json.loads((g.ROOT / "config.card_tiles.json").read_text()):
        raise ValueError("Active dimensions differ from the reviewed layout")
    if thickness is not None:
        c["thickness"] = thickness
    g.validate_config(c)
    source = g.ROOT / "docs/pedagogy/user_reference/hebrew-print-stroke-cards.pdf"
    if hashlib.sha256(source.read_bytes()).hexdigest() != review["source_sha256"]:
        raise ValueError("Reviewed PDF changed")
    if not review["shape_and_order_approved_by_user"]:
        raise ValueError("Missing reference shape/order approval")
    reference = json.loads((g.ROOT / "data/review/user_print_stroke_cards_v6.json").read_text())
    glyphs, _, _ = shapes(c, reference)
    rows = {r["char"]: r for r in review["tiles"]}
    objects = {DUAL: [], SINGLE: []}
    reports, visuals, bodies = [], [], {}
    for char, name, x, y in LAYOUT:
        row = rows[char]
        body = unary_union([g.tile(c).difference(glyphs[char]),
                            *[Polygon(p) for p in row["bridges_mm"]]])
        marker = marks(c, row)
        if not body.buffer(-c["marker_clearance"]).contains(marker):
            raise ValueError(f"Marks reach a cut edge: {char}")
        base, fill, engraved = g.split_layers(c, body, marker)
        if len(base.split()) != 1:
            raise ValueError(f"Unattached body island: {char}")
        united = trimesh.boolean.union([base, fill], engine="manifold")
        full = g.extrude(body, c["thickness"])
        volume_error = abs(united.volume - full.volume)
        overlap = abs(base.volume + fill.volume - united.volume)
        if max(volume_error, overlap) > .02:
            raise ValueError(f"Recess and inlay do not match: {char}")
        for suffix, mesh, color in [("body", base, COLORS[0]), ("markers", fill, COLORS[1])]:
            mesh.export(OUT / f"{name}_{suffix}.stl")
            placed = mesh.copy()
            placed.apply_translation([x, y, 0])
            objects[DUAL].append((f"{name}_{suffix}", placed, color))
        engraved.export(OUT / f"{name}_SINGLE_COLOR.stl")
        placed = engraved.copy()
        placed.apply_translation([x, y, 0])
        objects[SINGLE].append((f"{name}_engraved", placed, COLORS[0]))
        bodies[char] = body
        visuals.append((char, body, marker, x, y))
        reports.append({"char": char, "file_prefix": name, "stroke_count": row["stroke_count"],
                        "watertight_body_and_markers": bool(base.is_watertight and fill.is_watertight),
                        "body_components": 1, "bridge_count": len(row["bridges_mm"]),
                        "minimum_marker_clearance_mm": marker.distance(body.boundary),
                        "body_fill_overlap_volume_mm3": overlap, "union_volume_error_mm3": volume_error,
                        "plate_translation_mm": [x, y, 0]})
    placed = [affinity.translate(bodies[ch], xoff=x, yoff=y) for ch, _, x, y in LAYOUT]
    if any(a.intersection(b).area > 1e-8 for i, a in enumerate(placed) for b in placed[i + 1:]):
        raise ValueError("Tiles overlap on the print plate")
    # RTL assembled name: He at x=0, Gimel at x=52, Nun at x=104.
    assembly = [affinity.translate(bodies[ch], xoff=x) for ch, x in [("ה", 0), ("ג", 52), ("נ", 104)]]
    if any(a.intersection(b).area > 1e-8 for i, a in enumerate(assembly) for b in assembly[i + 1:]):
        raise ValueError("Assembled Noga tiles collide")
    fit = []
    for left, right in zip(assembly, assembly[1:]):
        collision = left.intersection(affinity.translate(right, xoff=1)).area
        if collision < .1:
            raise ValueError("Connector does not retain against sideways pulling")
        fit.append(collision)
    make_preview(c, visuals)
    color_reports = {}
    with tempfile.TemporaryDirectory(prefix="hebrew-noga-v11-") as tmp:
        work = Path(tmp)
        for kind, name, id_key in [
            ("machine", "Bambu Lab P1S 0.4 nozzle", "printer_settings_id"),
            ("process", "0.20mm Standard @BBL X1C", "print_settings_id"),
            ("filament", filament_profile, "filament_settings_id")]:
            preset = resolve_preset(kind, name)
            preset[id_key] = [name] if kind == "filament" else name
            save_json(work / f"{kind}.json", preset)

        def cli(args, log_name):
            result = subprocess.run([BAMBU, "--datadir", str(work / "settings"), *map(str, args)],
                                    text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
            (OUT / log_name).write_text(result.stdout)
            if result.returncode:
                raise RuntimeError(f"Bambu failed: {log_name}, exit {result.returncode}")

        for filename, parts in objects.items():
            dual = filename == DUAL
            count = 2 if dual else 1
            generic, native, patched = [work / (prefix + filename) for prefix in ["generic_", "native_", "patched_"]]
            g.write_3mf(generic, parts)
            cli(["--load-settings", f"{work/'machine.json'};{work/'process.json'}",
                 "--load-filaments", ";".join([str(work / "filament.json")] * count),
                 "--export-3mf", native, generic], filename + "_convert.log")
            with ZipFile(native) as z:
                data = {n: z.read(n) for n in z.namelist() if not n.endswith(".png")}
            config = ET.fromstring(data["Metadata/model_settings.config"])
            native_parts = [p for o in config.findall("object") for p in o.findall("part")]
            if len(native_parts) != len(parts):
                raise ValueError("Native import changed the part count")
            expected = []
            for part, (name, mesh, _) in zip(native_parts, parts):
                if int(part.find("mesh_stat").get("face_count")) != len(mesh.faces):
                    raise ValueError("Native conversion changed the mesh or reordered parts")
                part.find("metadata[@key='name']").set("value", name)
                extruder = part.find("metadata[@key='extruder']")
                if extruder is None:
                    extruder = ET.SubElement(part, "metadata", key="extruder")
                value = "2" if name.endswith("_markers") else "1"
                extruder.set("value", value)
                expected.append({"name": name, "extruder": value})
            for o in config.findall("object"):
                o.find("metadata[@key='name']").set("value", Path(filename).stem)
            data["Metadata/model_settings.config"] = ET.tostring(config, encoding="utf-8", xml_declaration=True)
            settings = json.loads(data["Metadata/project_settings.config"])
            settings.update(filament_colour=COLORS[:count], default_filament_colour=COLORS[:count],
                            curr_bed_type="Textured PEI Plate")
            # Bambu CLI may retain a larger default purge table after loading
            # two filaments. Resize it while preserving preset values, so its
            # dimensions match the actual slots. Recalculate for actual colors
            # in Studio before printing; this is not a measured purge setting.
            matrix = settings.get("flush_volumes_matrix", [])
            side = round(len(matrix) ** .5)
            if side * side != len(matrix) or side < count:
                raise ValueError("Unexpected default purge table")
            settings["flush_volumes_matrix"] = [matrix[i * side + j] for i in range(count) for j in range(count)]
            settings["flush_volumes_vector"] = settings["flush_volumes_vector"][:2 * count]
            data["Metadata/project_settings.config"] = json.dumps(settings, indent=2).encode()
            with ZipFile(patched, "w", ZIP_DEFLATED) as z:
                for n, contents in data.items():
                    z.writestr(n, contents)
            target = OUT / filename
            cli(["--export-3mf", target, patched], filename + "_roundtrip.log")
            actual, settings = read_assignments(target)
            if actual != expected or settings["filament_colour"] != COLORS[:count]:
                raise ValueError("Color assignments did not survive Bambu reopening")
            if settings["curr_bed_type"] != "Textured PEI Plate":
                raise ValueError("Build plate setting did not survive reopening")
            color_reports[filename] = {"parts": actual, "colors": settings["filament_colour"],
                                       "reopen_and_save_verified": True}
            render_dir = work / ("render_dual" if dual else "render_single")
            render_dir.mkdir()
            cli(["--camera-view", "1", "--export-png", "0", "--outputdir", render_dir, target], filename + "_render.log")
            rendered = render_dir / "plate_1_1.png"
            if dual:
                (OUT / "bambu_noga_preview.png").write_bytes(rendered.read_bytes())
                pixels = np.asarray(Image.open(rendered).convert("RGB"), dtype=float)
                pink = (pixels[..., 0] > pixels[..., 1] * 1.15) & (pixels[..., 1] > 50)
                green = (pixels[..., 1] > pixels[..., 0] * 1.3) & (pixels[..., 1] > pixels[..., 2])
                if pink.sum() < 10000 or green.sum() < 100:
                    raise ValueError("Bambu render does not show both colors")
            with ZipFile(target) as z:
                data = {n: z.read(n) for n in z.namelist()}
            with Image.open(rendered) as image:
                for n, size in [("Metadata/plate_1.png", 512), ("Metadata/plate_1_small.png", 128),
                                ("Metadata/plate_no_light_1.png", 512)]:
                    buffer = io.BytesIO()
                    image.resize((size, size), Image.Resampling.LANCZOS).save(buffer, format="PNG")
                    data[n] = buffer.getvalue()
            with ZipFile(target, "w", ZIP_DEFLATED) as z:
                for n, contents in data.items():
                    z.writestr(n, contents)
        # STL geometry can be checked in one invocation; native projects separately.
        logs = []
        for files in [sorted(OUT.glob("*.stl")), [OUT / DUAL], [OUT / SINGLE]]:
            cli(["--info", *files], "bambu_import.log")
            logs.append((OUT / "bambu_import.log").read_text())
        log = "\n".join(logs)
        (OUT / "bambu_import.log").write_text(log)
        if len(re.findall(r"^manifold = yes$", log, re.MULTILINE)) != 14:
            raise ValueError("Not all twelve STL and two 3MF files passed import")
    vertices = np.concatenate([m.vertices for _, m, _ in objects[DUAL]])
    validation = {"revision": revision, "letters": reports, "all_14_models_bambu_manifold": True,
                  "thickness_mm": c["thickness"], "floor_below_inlay_mm": c["thickness"] - c["marker_depth"],
                  "filament_preset": filament_profile,
                  "color_assignments": color_reports, "actual_bambu_render": "bambu_noga_preview.png",
                  "assembled_name_rtl": "נגה", "plate_bounds_mm": [vertices.min(axis=0).tolist(), vertices.max(axis=0).tolist()],
                  "plate_footprint_mm": (vertices.max(axis=0) - vertices.min(axis=0)).tolist(),
                  "side_pull_collision_at_1mm_mm2": fit, "physical_fit": "pending", "sliced": False}
    save_json(OUT / "validation.json", validation)
    save_json(OUT / "trial_metadata.json", {"date": "2026-10-18", "revision": revision,
        "user_request": "Trial letters for Noga: Nun, Gimel, He, plus Samekh for aperture testing.",
        "export_scope": list("נגהס"), "source_pdf_sha256": review["source_sha256"],
        "config": c, "tiles": [rows[ch] for ch, _, _, _ in LAYOUT]})
    save_json(OUT / "config.trial.json", c)
    (OUT / "PRINT_HE.txt").write_text(f"""נגה + ס׳ — ניסוי הדפסה {revision}, 18.10.2026

לפתוח ב־Bambu Studio את {DUAL} כ־Open Project.
השורה העליונה היא נ׳, ג׳, ה׳ מימין לשמאל. ס׳ נוספת נמצאת מתחתיה לבדיקת הפתח והגשר.
כל ארבעת האריחים נפרדים על המשטח; מחברים אותם אחרי ההדפסה בהנחה מלמעלה.

הגדרות הפרויקט
• מדפסת P1S, דיזה 0.4 מ״מ, משטח Textured PEI, שכבה 0.20 מ״מ.
• פרופיל שני הפילמנטים: {filament_profile}. גוף בפילמנט 1 (ורוד), חצים ומספרים בפילמנט 2 (ירוק).
• לפני Slice לוודא שההגדרות מתאימות לחומר בפועל. לפני שליחה להתאים את הסלילים ב־AMS.
• לעדכן את צבעי הפילמנטים לצבעים בפועל ולחשב מחדש Flushing volumes ב־Bambu Studio.
• לשמור על מיקום החלקים. חלקי markers נמצאים בתוך השקעים בחלק העליון; לא להורידם בנפרד למשטח.
• לא נוצר G-code, לא בוצע Slice ולא נשלח דבר למדפסת.

אפשרויות נוספות
{SINGLE} — ארבעת האריחים בצבע אחד, עם סימונים שקועים בעומק 0.6 מ״מ.
לכל אות מצורפים STL של גוף, מילוי סימונים וגרסה שקועה לצבע אחד:
nun = נ׳; gimel = ג׳; he = ה׳; samekh = ס׳.
לשני צבעים עדיף לפתוח את פרויקט 3MF המוכן. בייבוא STL של גוף ומילוי יש לייבא יחד כחלקי אותו אובייקט.

מידות ובדיקה פיזית
• גוף כל אריח 52×62×{c['thickness']:g} מ״מ; רוחב כולל לשונית 60.3 מ״מ.
• עומק מילוי הסימונים {c['marker_depth']:g} מ״מ; נשארת רצפה בעובי {c['thickness'] - c['marker_depth']:g} מ״מ מתחת לסימונים.
• ראש מחבר 8.4 מ״מ, צוואר 4.2 מ״מ, מרווח תכנוני 0.20 מ״מ.
• סידור המשטח 196.3×140 מ״מ, לפני שוליים ומגדל ניקוי. לוודא מקום למגדל בתצוגת הפריסה לפני Slice.
• מרכיבים את השם נגה: נ׳ מימין, ג׳ באמצע, ה׳ משמאל. מניחים את הלשוניות מלמעלה אל השקעים.
• הראש הרחב נועד להתנגד למשיכה לצדדים; הפירוק בהרמה. מידת ההידוק בפועל עדיין בבדיקה.
• בס׳ יש גשר ברוחב 1.8 מ״מ שמחזיק את המרכז; פתח הכתיבה נקטע בגשר. לבדוק חוזק ושימוש בעיפרון.
• לבדוק שכל החצים והמספרים ברורים, ושהעיפרון נע בנוחות בפתחים.

צורות האותיות, סדר המשיכות ומיקומי הסימונים נשמרו מסקירת הכרטיסיות v8.
ב־validation.json מתועדות בדיקות גוף סגור, חיבור, רווחי סימונים, צבעים וייבוא Bambu.
""")
    active_path = g.ROOT / "data/active_design.json"
    active = json.loads(active_path.read_text())
    active["print"]["current_print_files"] = f"outputs/noga_samekh_trial_{revision}/ — Noga plus Samekh trial, thickness {c['thickness']:g} mm, explicit Bambu filament assignments."
    active["print"]["physical_trial_export"] = {
        "generator": "src/export_noga_trial.py", "letters": list("נגהס"),
        "dual_color": f"outputs/noga_samekh_trial_{revision}/{DUAL}",
        "single_color": f"outputs/noga_samekh_trial_{revision}/{SINGLE}",
        "config": f"outputs/noga_samekh_trial_{revision}/config.trial.json",
        "thickness_mm": c["thickness"], "filament_preset": filament_profile,
        "status": "Bambu import, color roundtrip and render verified; unsliced"}
    save_json(active_path, active)
    (OUT / "SHA256SUMS.txt").write_text("".join(
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n"
        for p in sorted(OUT.iterdir()) if p.is_file() and p.name != "SHA256SUMS.txt"))
    archive = g.ROOT / f"hebrew-stencils-noga-samekh-trial-{revision}.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED) as z:
        for p in sorted(OUT.iterdir()):
            if p.is_file():
                z.write(p, f"noga_samekh_trial_{revision}/{p.name}")
    with ZipFile(archive) as z:
        if z.testzip():
            raise ValueError("ZIP integrity check failed")
    print(json.dumps({"output": str(OUT), "archive": str(archive), "letters": list("נגהס"),
                      "models_checked": 14, "plate_footprint_mm": validation["plate_footprint_mm"]}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--thickness", type=float)
    parser.add_argument("--revision", choices=["v11", "v12"], default="v11")
    parser.add_argument("--filament-profile", default="Bambu PLA Silk+ @BBL P1S 0.4 nozzle")
    args = parser.parse_args()
    main(thickness=args.thickness, revision=args.revision, filament_profile=args.filament_profile)
