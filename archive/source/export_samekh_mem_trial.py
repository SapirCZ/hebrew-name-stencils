"""Export the requested full Samekh/Mem trial from the reviewed v8 geometry.

This deliberately exports only the two letters requested for a physical trial;
the old font-based pilot's production approval metadata does not describe them.
"""
import argparse
import copy
import hashlib
import json
import re
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np
import trimesh
from PIL import Image, ImageDraw
from shapely import affinity
from shapely.geometry import Polygon
from shapely.ops import unary_union

import generate as g
from card_shapes import shapes
from refine_card_design import font, marks


OUT = g.ROOT / "outputs/samekh_mem_trial_v9"
LETTERS = [("ס", "samekh", 80.0), ("מ", "mem", 12.0)]


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def package_after_import():
    """Require successful Bambu --info results for every delivered mesh file."""
    log_path = OUT / "bambu_import.log"
    log = log_path.read_text(errors="replace")
    blocks = re.split(r"^\[([^\]\n]+\.(?:stl|3mf))\]\s*$", log, flags=re.MULTILINE)
    results = {blocks[i]: blocks[i + 1] for i in range(1, len(blocks), 2)}
    models = sorted([*OUT.glob("*.stl"), *OUT.glob("*.3mf")])
    if len(models) != 10 or set(results) != {p.name for p in models}:
        raise ValueError("Bambu import did not cover all six STL and four 3MF files")
    for path in models:
        if not re.search(r"^manifold = yes\s*$", results[path.name], re.MULTILINE):
            raise ValueError(f"Bambu rejected the mesh: {path.name}")
        if path.stat().st_mtime > log_path.stat().st_mtime:
            raise ValueError("Model changed after its Bambu check")
    validation_path = OUT / "validation.json"
    validation = json.loads(validation_path.read_text())
    validation["bambu_import"] = {
        "method": "Bambu Studio --info with isolated temporary datadir; no slicing",
        "files_checked": [p.name for p in models], "all_manifold": True,
        "log": "bambu_import.log",
    }
    save_json(validation_path, validation)
    payload = sorted(p for p in OUT.iterdir() if p.is_file() and p.name != "SHA256SUMS.txt")
    (OUT / "SHA256SUMS.txt").write_text("".join(
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in payload))
    archive = g.ROOT / "hebrew-stencils-samekh-mem-trial-v9.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED) as bundle:
        for path in sorted(OUT.iterdir()):
            if path.is_file():
                bundle.write(path, f"samekh_mem_trial_v9/{path.name}")
    with ZipFile(archive) as bundle:
        if bundle.testzip() is not None:
            raise ValueError("ZIP integrity check failed")
    print(json.dumps({"archive": str(archive), "files": len(payload) + 1,
                      "size_bytes": archive.stat().st_size, "bambu_models_checked": len(models)}))


def preview(c, visuals):
    ss = 2
    w, h = 1480, 1060
    image = Image.new("RGB", (w * ss, h * ss), "#f7f5ef")
    draw = ImageDraw.Draw(image)

    def text(x, y, message, size=28, color="#283d42", anchor="rt"):
        draw.text((x * ss, y * ss), message, font=font(c, size * ss),
                  anchor=anchor, direction="rtl", fill=color)

    text(w - 40, 28, "ס׳ ומ׳ — זוג שבלונות לניסוי הדפסה", 42)
    text(w - 40, 90, "פתחי אותיות, חצים ומספרים • מחבר פאזל יחיד בכל צד", 26, "#687470")
    for char, body, mark in visuals:
        ox = 880 if char == "ס" else 180
        scale = 8.8
        tf = lambda x, y: ((ox + x * scale) * ss, (215 + (c["height"] - y) * scale) * ss)
        g.paint(draw, body, tf, "#e7aeaa")
        g.paint(draw, mark, tf, "#294a43")
        text(ox + 26 * scale, 155, char + "׳", 36, anchor="mt")
        message = "בדיקת הפתח והגשר שמחזיק את המרכז" if char == "ס" else "בדיקת התנועה הרציפה של חץ 1"
        text(ox + 26 * scale, 804, message, 25, anchor="mt")
    text(w - 40, 884, "גוף האריח: 52×62 מ״מ • עובי: 3.2 מ״מ • מרווח מחבר: 0.20 מ״מ", 27)
    text(w - 40, 937, "בהדפסה האריחים נפרדים; לאחר מכן מחברים בהנחה מלמעלה", 27)
    text(w - 40, 992, "השטח הבהיר הוא פתח; הסימונים נמצאים על החומר המלא", 24, "#687470")
    image.resize((w, h), Image.Resampling.LANCZOS).save(
        OUT / "samekh_mem_preview.jpg", quality=96, subsampling=0, dpi=(220, 220))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    review = json.loads((g.ROOT / "data/review/card_stencil_layout_v8.json").read_text())
    reference = json.loads((g.ROOT / "data/review/user_print_stroke_cards_v6.json").read_text())
    c = copy.deepcopy(review["print_config"])
    if c != json.loads((g.ROOT / "config.card_tiles.json").read_text()):
        raise ValueError("Reviewed geometry and active tile configuration differ")
    source = g.ROOT / "docs/pedagogy/user_reference/hebrew-print-stroke-cards.pdf"
    if hashlib.sha256(source.read_bytes()).hexdigest() != review["source_sha256"]:
        raise ValueError("The approved source PDF changed")
    if not review["shape_and_order_approved_by_user"] or review["revision"] != "v8":
        raise ValueError("This exporter requires the approved card source and v8 layout")
    g.validate_config(c)
    glyphs, _, _ = shapes(c, reference)
    rows = {row["char"]: row for row in review["tiles"]}
    dual_objects, single_objects, visuals, reports, exported_rows = [], [], [], [], []
    bodies = {}
    for char, name, x in LETTERS:
        row = copy.deepcopy(rows[char])
        if row["approval_evidence"] != "גם לצורת האות וגם לסדר המשיכות":
            raise ValueError("Missing user approval for the reference shape and order")
        body = unary_union([g.tile(c).difference(glyphs[char]),
                            *[Polygon(p) for p in row["bridges_mm"]]])
        marker = marks(c, row)
        if not body.buffer(-c["marker_clearance"]).contains(marker):
            raise ValueError(f"Instructional markings approach a cut edge: {char}")
        if len(g.polygons(body)) != 1:
            raise ValueError(f"Unattached body island: {char}")
        base, fill, engraved = g.split_layers(c, body, marker)
        full = g.extrude(body, c["thickness"])
        united = trimesh.boolean.union([base, fill], engine="manifold")
        volume_error = abs(united.volume - full.volume)
        overlap_volume = base.volume + fill.volume - united.volume
        if volume_error > .02 or abs(overlap_volume) > .02:
            raise ValueError(f"Recess/fill mismatch: {char}")
        base_components = len(base.split())
        if base_components != 1:
            raise ValueError(f"Engraving disconnected the body: {char}")
        parts = [("body", base, "#E7AEAA"), ("markers", fill, "#294A43")]
        for suffix, mesh, color in parts:
            mesh.export(OUT / f"{name}_{suffix}.stl")
            placed = mesh.copy()
            placed.apply_translation([x, 8, 0])
            dual_objects.append((f"{name}_{suffix}", placed, color))
        engraved.export(OUT / f"{name}_SINGLE_COLOR.stl")
        g.write_3mf(OUT / f"{name}_DUAL_COLOR.3mf",
                    [(f"{name}_{suffix}", mesh, color) for suffix, mesh, color in parts])
        placed = engraved.copy()
        placed.apply_translation([x, 8, 0])
        single_objects.append((f"{name}_engraved", placed, "#E7AEAA"))
        reports.append({
            "char": char, "file_prefix": name, "stroke_count": row["stroke_count"],
            "body_components": base_components, "full_body_volume_mm3": float(full.volume),
            "recessed_body_volume_mm3": float(base.volume), "marker_fill_volume_mm3": float(fill.volume),
            "union_volume_error_mm3": float(volume_error), "body_fill_overlap_volume_mm3": float(overlap_volume),
            "body_watertight": bool(base.is_watertight), "markers_watertight": bool(fill.is_watertight),
            "body_winding_consistent": bool(base.is_winding_consistent),
            "markers_winding_consistent": bool(fill.is_winding_consistent),
            "minimum_marker_clearance_mm": float(marker.distance(body.boundary)),
            "marker_aperture_overlap_mm2": float(marker.intersection(g.tile(c).difference(body)).area),
            "bridge_count": len(row["bridges_mm"]), "body_floor_below_marks_mm": c["thickness"] - c["marker_depth"],
            "plate_translation_mm": [x, 8, 0],
        })
        row["export_scope"] = "User-requested Samekh/Mem physical trial only, 2026-10-18"
        row["marker_placement_status"] = "exported for requested physical trial; physical result pending"
        exported_rows.append(row)
        visuals.append((char, body, marker))
        bodies[char] = body
    # Assemble Mem on the left and Samekh on the right, at their exact seat.
    seated = affinity.translate(bodies["ס"], xoff=c["width"])
    seat_overlap = bodies["מ"].intersection(seated).area
    side_pull = bodies["מ"].intersection(affinity.translate(seated, xoff=1)).area
    plate_overlap = affinity.translate(bodies["מ"], xoff=12, yoff=8).intersection(
        affinity.translate(bodies["ס"], xoff=80, yoff=8)).area
    if seat_overlap > 1e-8 or plate_overlap > 1e-8 or side_pull < .1:
        raise ValueError("The actual letter pair collides at rest or lacks sideways retention")
    g.write_3mf(OUT / "samekh_mem_DUAL_COLOR.3mf", dual_objects)
    g.write_3mf(OUT / "samekh_mem_SINGLE_COLOR.3mf", single_objects)
    vertices = np.concatenate([mesh.vertices for _, mesh, _ in dual_objects])
    preview(c, visuals)
    save_json(OUT / "trial_metadata.json", {
        "revision": "v9 printable subset of v8", "date": "2026-10-18",
        "source_pdf_sha256": review["source_sha256"],
        "reference_shape_and_order_approval": "גם לצורת האות וגם לסדר המשיכות",
        "trial_authorization": "User requested complete connector trial tiles with Samekh (hole) and Mem (previously problematic).",
        "export_scope": ["ס", "מ"], "config": c, "tiles": exported_rows,
    })
    save_json(OUT / "validation.json", {
        "status": "geometrically validated; unsliced and physically unprinted",
        "tiles": reports, "plate_bounds_mm": [vertices.min(axis=0).tolist(), vertices.max(axis=0).tolist()],
        "plate_footprint_mm": (vertices.max(axis=0) - vertices.min(axis=0)).tolist(),
        "plate_tile_overlap_mm2": plate_overlap, "assembled_tile_overlap_mm2": seat_overlap,
        "side_pull_collision_at_1mm_mm2": side_pull,
        "assembly": "drop vertically into the seat; no Z snap latch",
        "printer_profile": "generic 3MF; choose printer, filament and settings before slicing",
        "physical_fit": "pending",
    })
    (OUT / "PRINT_HE.txt").write_text("""ניסוי ס׳ ומ׳ — שבלונות מלאות עם חיבור פאזל יחיד, 18.10.2026

התחלה מהירה
1. לפתוח ב־Bambu Studio את samekh_mem_DUAL_COLOR.3mf.
2. לבחור את דגם המדפסת, הדיזה והפילמנט. זהו קובץ מודל כללי ללא פרופיל מדפסת וללא G-code.
3. להקצות צבע גוף לחלקים samekh_body ו־mem_body וצבע סימונים לחלקים samekh_markers ו־mem_markers.
   הצבעים שבמודל הם הצעת תצוגה; הם אינם מיפוי אוטומטי לסלילי AMS.
4. לשמור את כל החלקים במיקומם היחסי. לא להוריד את חלקי markers בנפרד למשטח.
5. נקודת התחלה לניסוי: שכבה 0.20 מ״מ, צד שטוח על המשטח, ללא תמיכות. להתאים הגדרות לחומר ולמדפסת.
6. לבצע Slice ולבדוק בתצוגת השכבות את הפתחים, הגשר בס׳ ומילוי הסימונים, לפני שליחה להדפסה.

אם מדפיסים בצבע אחד
לפתוח את samekh_mem_SINGLE_COLOR.3mf. החצים והמספרים שקועים בעומק 0.6 מ״מ.
אין צורך בחלקי markers. קובצי samekh_SINGLE_COLOR.stl ו־mem_SINGLE_COLOR.stl נותנים אותה גאומטריה בנפרד.

STL לשני צבעים
לכל אות יש body.stl ו־markers.stl באותה מערכת צירים. לייבא את השניים יחד כאובייקט עם חלקים נפרדים,
ולשמור את יישור החלקים. קל יותר להשתמש בקובץ 3MF המוכן לזוג או בקובץ DUAL_COLOR של אות בודדת.

מה בודקים אחרי ההדפסה
• גוף אריח 52×62 מ״מ, עובי 3.2 מ״מ; הרוחב כולל לשונית 60.3 מ״מ.
• המחבר: ראש בקוטר 8.4 מ״מ, צוואר 4.2 מ״מ ומרווח תכנוני 0.20 מ״מ.
• שני האריחים מונחים בנפרד בקובץ. לאחר ההדפסה מניחים מ׳ משמאל, ס׳ מימין,
  ומורידים את לשונית ס׳ אל השקע הימני של מ׳ מלמעלה. לאחר ההושבה בודקים התנגדות למשיכה לצדדים.
  אין כאן נעילה בציר הגובה; מפרקים בהרמה. מידת ההידוק בפועל טרם נבדקה.
• בס׳: החלק הפנימי מחובר בגשר מלא ברוחב 1.8 מ״מ. הגשר נחוץ כדי שהמרכז לא ייפול,
  ולכן הפתח לכתיבה נקטע בו. בודקים חוזק ושימוש בעיפרון גם באזור הזה.
• במ׳: חץ 1 רציף — עלייה באלכסון, ירידה מימין ופנייה שמאלה.
• בכל אות: חצים, נקודות התחלה ומספרים על החומר המלא ליד הפתח; לוודא שהם ברורים למשתמשת.

תצוגה ומקור
samekh_mem_preview.jpg מציג את שתי האותיות. הלבן הוא פתח, הוורוד גוף והירוק סימונים.
האותיות וסדר המשיכות מבוססים על כרטיסיות ה־PDF שסופקו ואושרו בצ׳אט.
trial_metadata.json מתעד את המקור, הפריסה והמידות; validation.json מתעד בדיקות גאומטריה.
אלו קובצי ניסוי של שתי האותיות בלבד. לא בוצעו Slice או הדפסה פיזית.
""", encoding="utf-8")
    active_path = g.ROOT / "data/active_design.json"
    active = json.loads(active_path.read_text())
    active["print"]["current_print_files"] = "outputs/samekh_mem_trial_v9/ — complete card-derived Samekh and Mem trial tiles with v8 connectors and markers; other letters remain visual review only."
    active["print"]["physical_trial_export"] = {
        "generator": "src/export_samekh_mem_trial.py", "letters": ["ס", "מ"],
        "dual_color": "outputs/samekh_mem_trial_v9/samekh_mem_DUAL_COLOR.3mf",
        "single_color": "outputs/samekh_mem_trial_v9/samekh_mem_SINGLE_COLOR.3mf",
        "status": "exported for user-requested physical trial; unsliced",
    }
    save_json(active_path, active)
    print(json.dumps({"output": str(OUT), "letters": reports,
                      "seated_overlap_mm2": seat_overlap, "side_pull_collision_mm2": side_pull}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-after-import", action="store_true",
                        help="Validate the saved Bambu --info log and package the existing export")
    args = parser.parse_args()
    if args.package_after_import:
        package_after_import()
    else:
        main()
