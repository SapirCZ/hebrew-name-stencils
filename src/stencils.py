"""Portable Hebrew name and alphabet exports; all dimensions are millimeters.

The reviewed v8 shapes/guide paths are kept. No source PDF, internet access,
installed system font, Bambu installation, or private roster is needed.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import math
import unicodedata
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np
import trimesh
from PIL import Image, ImageDraw, ImageFont
from shapely import affinity
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

import generate as g
from card_shapes import shapes
from review_print_arrows import number_shape

ROOT = Path(__file__).resolve().parents[1]
ORDER = "אבגדהוזחטיכךלמםנןסעפףצץקרשת"
MARGIN = 5.0
LETTER_GAP = 6.0
DIGIT_EXPANSION = .12
CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"


def save_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_name(value):
    value = unicodedata.normalize("NFC", value)
    value = " ".join(value.split())
    if not value or len(value) > 40:
        raise ValueError("יש להזין שם בן 1–40 תווים.")
    invalid = sorted(set(value) - set(ORDER + " "))
    if invalid:
        raise ValueError("נתמכות אותיות עבריות ורווחים בלבד, ללא ניקוד: " + ", ".join(invalid))
    return value


@lru_cache(maxsize=8)
def load_design(thickness=1.8):
    if not math.isfinite(thickness) or not 1.8 <= thickness <= 3.2:
        raise ValueError("העובי הנתמך הוא 1.8–3.2 מ״מ.")
    review = json.loads((ROOT / "data/review/card_stencil_layout_v8.json").read_text(encoding="utf-8"))
    reference = json.loads((ROOT / "data/review/user_print_stroke_cards_v6.json").read_text(encoding="utf-8"))
    if review["source_sha256"] != reference["source_sha256"]:
        raise ValueError("Reviewed geometry sources disagree")
    c = copy.deepcopy(review["print_config"])
    c["thickness"] = thickness
    glyphs, _, _ = shapes(c, reference)
    rows = {r["char"]: r for r in review["tiles"]}
    markers = {}
    for ch, row in rows.items():
        parts = []
        for arrow in row["arrows"]:
            points = arrow["guide_path_mm"]
            parts.extend([g.arrow_geometry(c, points), Point(points[0]).buffer(.78, quad_segs=20)])
        parts.extend(number_shape(c, n["number"], n["x"], n["y"]).buffer(DIGIT_EXPANSION, quad_segs=16)
                     for n in row["number_labels"])
        markers[ch] = unary_union(parts)
    return c, rows, glyphs, markers, review["source_sha256"]


def make_name(name, thickness=1.8):
    name = validate_name(name)
    c, rows, glyphs, markers, source_hash = load_design(thickness)
    used = set(name) - {" "}
    envelopes = {ch: glyphs[ch].union(markers[ch]).bounds for ch in used}
    word_gap = 12.0
    width = sum(envelopes[ch][2] - envelopes[ch][0] if ch != " " else word_gap for ch in name)
    width += LETTER_GAP * (len(name) - 1) + 2 * MARGIN
    if width > 240:
        raise ValueError(f"רוחב השם {width:.1f} מ״מ; המקסימום הוא 240. נסו לפצל לשתי שבלונות.")
    # Preserve the reviewed v16 name baseline without a private roster/layout
    # dependency. Descenders may require extra space for a particular name.
    defaults = json.loads((ROOT / "data/design_defaults.json").read_text(encoding="utf-8"))
    y_shift = max(defaults["name_baseline_translation_mm"],
                  MARGIN - min(envelopes[ch][1] for ch in used))
    height = max(52., float(math.ceil(max(envelopes[ch][3] for ch in used) + y_shift + MARGIN)))
    right, cuts, guides, placements = width - MARGIN, [], [], []
    for ch in name:
        if ch == " ":
            right -= word_gap + LETTER_GAP
            continue
        bounds = envelopes[ch]
        dx = right - bounds[2]
        bridges = unary_union([Polygon(p) for p in rows[ch]["bridges_mm"]])
        aperture = glyphs[ch].difference(bridges)
        cuts.append(affinity.translate(aperture, xoff=dx, yoff=y_shift))
        guides.append(affinity.translate(markers[ch], xoff=dx, yoff=y_shift))
        placements.append({"char": ch, "translation_mm": [dx, y_shift], "stroke_count": rows[ch]["stroke_count"]})
        right -= bounds[2] - bounds[0] + LETTER_GAP
    outline = box(3, 3, width - 3, height - 3).buffer(3, quad_segs=24)
    body, mark = outline.difference(unary_union(cuts)), unary_union(guides)
    return finish(c, body, mark, dict(kind="name", name=name, width_mm=width, height_mm=height,
                  letter_placements=placements, source_sha256=source_hash))


def make_tile(ch, thickness=2.4):
    if ch not in ORDER or len(ch) != 1:
        raise ValueError("Expected one supported Hebrew letter")
    c, rows, glyphs, markers, source_hash = load_design(thickness)
    bridges = unary_union([Polygon(p) for p in rows[ch]["bridges_mm"]])
    body = g.tile(c).difference(glyphs[ch].difference(bridges))
    return finish(c, body, markers[ch], dict(kind="puzzle_tile", name=ch,
                  width_mm=c["width"], height_mm=c["height"], source_sha256=source_hash,
                  stroke_count=rows[ch]["stroke_count"]))


def finish(c, body, mark, metadata):
    if not isinstance(body, Polygon) or not body.is_valid:
        raise ValueError("Body contains an unattached island")
    clearance = mark.distance(body.boundary)
    if not body.buffer(-c["marker_clearance"]).contains(mark):
        raise ValueError(f"Insufficient marker clearance: {clearance:.4f} mm")
    base, fill, single = g.split_layers(c, body, mark)
    if len(base.split()) != 1:
        raise ValueError("Engraved body has disconnected pieces")
    expected = body.area * c["thickness"]
    if abs(base.volume + fill.volume - expected) > .03:
        raise ValueError("Body/marker volumes do not tile the full solid")
    for mesh in [base, fill]:
        if not mesh.is_watertight or not mesh.is_winding_consistent or mesh.volume <= 0:
            raise ValueError("Invalid mesh")
    metadata.update(thickness_mm=c["thickness"], marker_depth_mm=c["marker_depth"],
        floor_below_markers_mm=c["thickness"] - c["marker_depth"],
        minimum_marker_clearance_mm=clearance, body_connected=True, meshes_watertight=True,
        status="geometry validated; generated model has not been physically tested",
        alphabet_review="v8", digit_expansion_per_edge_mm=DIGIT_EXPANSION)
    return dict(config=c, body=body, markers=mark, base=base, fill=fill, single=single, metadata=metadata)


def preview(item, target):
    body, mark = item["body"], item["markers"]
    x0, y0, x1, y1 = body.bounds
    scale = min(14., 1900 / (x1 - x0))
    w, h = int((x1-x0)*scale + 50), int((y1-y0)*scale + 90)
    im = Image.new("RGB", (w, h), "#f7f5ef")
    draw = ImageDraw.Draw(im)
    tf = lambda x, y: (25 + (x-x0)*scale, 65 + (y1-y)*scale)
    g.paint(draw, body, tf, "#282828")
    g.paint(draw, mark, tf, "#ffffff")
    font = ImageFont.truetype(str(ROOT / "fonts/print/heebo/Heebo[wght].ttf"), 28)
    draw.text((w-20, 12), item["metadata"]["name"], font=font, anchor="rt", fill="#283d42")
    im.save(target)
    return im


def metadata(parent, key, value):
    ET.SubElement(parent, "metadata", key=key, value=str(value))


def bambu_project(target, item, dual=True):
    """A native Bambu project containing regular Core meshes and explicit parts.

    The shipped resolved profile contains no account, printer credentials or
    external dependencies. Local Bambu CLI verification is recorded separately.
    """
    c = item["config"]
    objects = [("body", item["base"].copy(), "#282828")]
    if dual:
        objects.append(("markers", item["fill"].copy(), "#FFFFFF"))
    minx, miny, maxx, maxy = item["body"].bounds
    # Reserve the tower at y=10..45, and keep both meshes at their original Z.
    dx, dy = (256-(maxx-minx))/2-minx, 100-miny
    for _, mesh, _ in objects:
        mesh.apply_translation([dx, dy, 0])
    g.write_3mf(target, objects)
    with ZipFile(target) as z:
        files = {n: z.read(n) for n in z.namelist()}
    model = ET.fromstring(files["3D/3dmodel.model"])
    for el in model.findall(f"{{{CORE}}}metadata"):
        if el.get("name") == "Title":
            el.text = "Hebrew stencil - " + item["metadata"]["name"]
    ET.SubElement(model, f"{{{CORE}}}metadata", name="Application").text = "BambuStudio-02.08.02.61"
    ET.SubElement(model, f"{{{CORE}}}metadata", name="BambuStudio:3mfVersion").text = "1"
    files["3D/3dmodel.model"] = ET.tostring(model, encoding="utf-8", xml_declaration=True)
    config = ET.Element("config")
    assembly = len(objects) + 2
    obj = ET.SubElement(config, "object", id=str(assembly))
    metadata(obj, "name", item["metadata"]["name"])
    metadata(obj, "extruder", 1)
    for index, (name, mesh, _) in enumerate(objects):
        part = ET.SubElement(obj, "part", id=str(index+2), subtype="normal_part")
        metadata(part, "name", name)
        metadata(part, "extruder", index+1)
        ET.SubElement(part, "mesh_stat", face_count=str(len(mesh.faces)), edges_fixed="0",
                      degenerate_facets="0", facets_removed="0", facets_reversed="0", backwards_edges="0")
    plate = ET.SubElement(config, "plate")
    for key, value in [("plater_id", 1), ("plater_name", "Hebrew stencil"), ("locked", "false"),
                       ("thumbnail_file", "Metadata/plate_1.png")]:
        metadata(plate, key, value)
    inst = ET.SubElement(plate, "model_instance")
    for key, value in [("object_id", assembly), ("instance_id", 0), ("identify_id", 0)]:
        metadata(inst, key, value)
    ET.SubElement(config, "assemble")
    files["Metadata/model_settings.config"] = ET.tostring(config, encoding="utf-8", xml_declaration=True)
    settings = json.loads((ROOT / "profiles/P1S_PLA_candidate.json").read_text(encoding="utf-8"))
    settings["enable_prime_tower"] = "1" if dual else "0"
    # Leave the resolved two-filament profile intact: only extruder 1 is used
    # for single-color geometry. No detached marker parts are emitted in it.
    files["Metadata/project_settings.config"] = json.dumps(settings, indent=2).encode()
    content_types = ET.fromstring(files["[Content_Types].xml"])
    content_ns = "http://schemas.openxmlformats.org/package/2006/content-types"
    for extension, kind in [("png", "image/png"), ("config", "application/octet-stream")]:
        ET.SubElement(content_types, f"{{{content_ns}}}Default", Extension=extension, ContentType=kind)
    files["[Content_Types].xml"] = ET.tostring(content_types, encoding="utf-8", xml_declaration=True)
    with io.BytesIO() as buf:
        preview_image = Image.new("RGB", (128, 128), "#f7f5ef")
        preview_image.save(buf, format="PNG")
        files["Metadata/plate_1.png"] = buf.getvalue()
    with ZipFile(target, "w", ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)


def export_item(item, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    for name in ["body", "markers", "single"]:
        item[{"body": "base", "markers": "fill", "single": "single"}[name]].export(output / f"{name}.stl")
    preview(item, output / "preview.png")
    bambu_project(output / "DUAL_COLOR.3mf", item, dual=True)
    bambu_project(output / "SINGLE_COLOR.3mf", item, dual=False)
    # Embed a preview of this exact model, rather than a stale template image.
    with Image.open(output / "preview.png") as im:
        buf = io.BytesIO()
        im.thumbnail((512, 512))
        im.save(buf, format="PNG")
        thumbnail = buf.getvalue()
    for path in output.glob("*.3mf"):
        with ZipFile(path) as z:
            files = {n: z.read(n) for n in z.namelist()}
        files["Metadata/plate_1.png"] = thumbnail
        with ZipFile(path, "w", ZIP_DEFLATED) as z:
            for name, content in files.items():
                z.writestr(name, content)
    save_json(output / "model.json", item["metadata"])
    (output / "PRINT_HE.txt").write_text(
        "שבלונת עברית — " + item["metadata"]["name"] + "\n\n"
        "לשני צבעים: לפתוח DUAL_COLOR.3mf כ־Open Project ב־Bambu Studio.\n"
        "הגוף בפילמנט 1, הסימונים בפילמנט 2. הסימונים ממלאים שקעים ואינם בולטים מעל פני השבלונה.\n"
        "לצבע אחד: SINGLE_COLOR.3mf או single.stl. הסימונים נשארים שקועים.\n"
        "body.stl ו־markers.stl הם חלקים נפרדים לייבוא כאובייקט אחד; לשמור על היישור המקורי.\n"
        "פרויקט 3MF כולל P1S, דיזה 0.4, Textured PEI, PLA רגיל, שכבה 0.20.\n"
        "להתאים מדפסת, משטח, פילמנטים, צבעים ונפחי ניקוי לציוד בפועל ולבצע Slice לפני הדפסה.\n"
        "Arachne + גיהוץ עליון הם שילוב ניסיוני שנבחר מתוצאות נפרדות; אינם פרופיל מכויל לכל מדפסת.\n"
        "עובי 1.8 מ״מ ונוחות כתיבה/עמידות ממתינים לבדיקה פיזית. אין G-code בחבילה.\n",
        encoding="utf-8")
    return output


def archive_output(folder, target):
    folder, target = Path(folder), Path(target)
    with ZipFile(target, "w", ZIP_DEFLATED) as z:
        for p in sorted(folder.rglob("*")):
            if p.is_file() and p.resolve() != target.resolve():
                z.write(p, p.relative_to(folder))
    return target


def main():
    parser = argparse.ArgumentParser(description="Hebrew stencil generator — מחולל שבלונות")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--name", help="שם בעברית, לדוגמה נגה")
    action.add_argument("--alphabet", action="store_true", help="כל 27 אריחי הדפוס")
    parser.add_argument("--thickness", type=float, help="עובי: 1.8–3.2 מ״מ; ברירת מחדל שם1.8, אריח2.4")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.name:
            item = make_name(args.name, args.thickness if args.thickness is not None else 1.8)
            export_item(item, args.output)
            print(json.dumps(item["metadata"], ensure_ascii=False, indent=2))
        else:
            reports = []
            for index, ch in enumerate(ORDER, 1):
                item = make_tile(ch, args.thickness if args.thickness is not None else 2.4)
                export_item(item, args.output / f"{index:02d}_U{ord(ch):04X}")
                reports.append(item["metadata"])
                print(f"{index:02d}/27 {ch}", flush=True)
            save_json(args.output / "alphabet.json", reports)
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
