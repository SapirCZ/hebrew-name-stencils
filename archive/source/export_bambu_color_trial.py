"""Convert the v9 models into Bambu projects with explicit filament assignments.

Uses the installed Bambu CLI and its installed system presets, never the active
user project. Exports and renders only; no slicing, G-code, or printer commands.
"""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np
from PIL import Image
import generate as g

SOURCE = g.ROOT / "outputs/samekh_mem_trial_v9"
OUT = g.ROOT / "outputs/samekh_mem_trial_v10"
BAMBU = "/Applications/BambuStudio.app/Contents/MacOS/BambuStudio"
PRESETS = Path.home() / "Library/Application Support/BambuStudio/system/BBL"
COLORS = ["#E7AEAA", "#294A43"]
NAMES = {
    "samekh_mem_DUAL_COLOR.3mf": ["samekh_body", "samekh_markers", "mem_body", "mem_markers"],
    "samekh_DUAL_COLOR.3mf": ["samekh_body", "samekh_markers"],
    "mem_DUAL_COLOR.3mf": ["mem_body", "mem_markers"],
    "samekh_mem_SINGLE_COLOR.3mf": ["samekh_engraved", "mem_engraved"],
}


def resolve_preset(kind, name, stack=()):
    if name in stack:
        raise ValueError("Preset inheritance loop")
    data = json.loads((PRESETS / kind / (name + ".json")).read_text())
    result = {}
    if data.get("inherits"):
        result.update(resolve_preset(kind, data["inherits"], stack + (name,)))
    for include in data.get("include", []):
        result.update(resolve_preset(kind, include, stack + (name,)))
    result.update({k: v for k, v in data.items() if k not in ["inherits", "include"]})
    return result


def read_assignments(path):
    with ZipFile(path) as bundle:
        config = ET.fromstring(bundle.read("Metadata/model_settings.config"))
        settings = json.loads(bundle.read("Metadata/project_settings.config"))
    parts = [dict((m.get("key"), m.get("value")) for m in part.findall("metadata")
                  if m.get("key") in ["name", "extruder"])
             for obj in config.findall("object") for part in obj.findall("part")]
    return parts, settings


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for path in SOURCE.glob("*.stl"):
        shutil.copy2(path, OUT / path.name)
    for name in ["samekh_mem_preview.jpg", "trial_metadata.json"]:
        shutil.copy2(SOURCE / name, OUT / name)
    reports = {}
    with tempfile.TemporaryDirectory(prefix="hebrew-bambu-color-") as tmp:
        work = Path(tmp)
        datadir = work / "bambu-settings"
        # Profiles match the printer/nozzle/material shown in the user's image.
        presets = [("machine", "Bambu Lab P1S 0.4 nozzle", "printer_settings_id"),
                   ("process", "0.20mm Standard @BBL X1C", "print_settings_id"),
                   ("filament", "Bambu PLA Silk+ @BBL P1S 0.4 nozzle", "filament_settings_id")]
        for kind, name, id_key in presets:
            data = resolve_preset(kind, name)
            data[id_key] = [name] if kind == "filament" else name
            (work / (kind + ".json")).write_text(json.dumps(data, indent=2))

        def cli(args, log_name):
            result = subprocess.run([BAMBU, "--datadir", str(datadir), *map(str, args)],
                                    text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    timeout=60)
            (OUT / log_name).write_text(result.stdout)
            if result.returncode:
                raise RuntimeError(f"Bambu CLI failed ({log_name}): {result.returncode}")

        for filename, names in NAMES.items():
            dual = "DUAL" in filename
            color_count = 2 if dual else 1
            stem = Path(filename).stem
            native, patched = work / filename, work / (stem + "_assigned.3mf")
            cli(["--load-settings", f"{work/'machine.json'};{work/'process.json'}",
                 "--load-filaments", ";".join([str(work / "filament.json")] * color_count),
                 "--export-3mf", native, SOURCE / filename], stem + "_convert.log")
            with ZipFile(native) as bundle:
                data = {n: bundle.read(n) for n in bundle.namelist()}
            config = ET.fromstring(data["Metadata/model_settings.config"])
            parts = [part for obj in config.findall("object") for part in obj.findall("part")]
            if len(parts) != len(names):
                raise ValueError("Unexpected component ordering in native conversion")
            for part, name in zip(parts, names):
                part.find("metadata[@key='name']").set("value", name)
                extruder = part.find("metadata[@key='extruder']")
                if extruder is None:
                    extruder = ET.SubElement(part, "metadata", key="extruder")
                extruder.set("value", "2" if name.endswith("_markers") else "1")
            for obj in config.findall("object"):
                obj.find("metadata[@key='name']").set("value", stem)
            data["Metadata/model_settings.config"] = ET.tostring(config, encoding="utf-8", xml_declaration=True)
            settings = json.loads(data["Metadata/project_settings.config"])
            settings["filament_colour"] = COLORS[:color_count]
            settings["default_filament_colour"] = COLORS[:color_count]
            data["Metadata/project_settings.config"] = json.dumps(settings, indent=2).encode()
            with ZipFile(patched, "w", ZIP_DEFLATED) as bundle:
                for name, contents in data.items():
                    # Old embedded images were created before the color assignment.
                    if not name.endswith(".png"):
                        bundle.writestr(name, contents)
            target = OUT / filename
            cli(["--export-3mf", target, patched], stem + "_roundtrip.log")
            actual, settings = read_assignments(target)
            expected = [{"name": name, "extruder": "2" if name.endswith("_markers") else "1"} for name in names]
            if actual != expected or settings["filament_colour"] != COLORS[:color_count]:
                raise ValueError("Filament assignment did not survive Bambu reopening")
            if settings["printer_model"] != "Bambu Lab P1S" or settings["nozzle_diameter"] != ["0.4"]:
                raise ValueError("Unexpected printer profile")
            reports[filename] = {"parts": actual, "filament_colour": settings["filament_colour"],
                                 "bambu_reopen_and_save_preserved_assignments": True}
        # An actual Bambu render verifies visible color separation, not just XML.
        cli(["--camera-view", "1", "--export-png", "0", "--outputdir", OUT,
             OUT / "samekh_mem_DUAL_COLOR.3mf"], "bambu_render.log")
        rendered = OUT / "plate_1_1.png"
        pixels = np.asarray(Image.open(rendered).convert("RGB"), dtype=float)
        # Shading changes both colors, so compare chromatic directions.
        pink = (pixels[..., 0] > pixels[..., 1] * 1.15) & (pixels[..., 1] > 50)
        green = (pixels[..., 1] > pixels[..., 0] * 1.3) & (pixels[..., 1] > pixels[..., 2])
        if int(pink.sum()) < 10000 or int(green.sum()) < 100:
            raise ValueError("Bambu render lacks the two visible colors")
        rendered.rename(OUT / "bambu_two_color_preview.png")
        # Replace stale embedded thumbnails with renders from the assigned model.
        for filename in NAMES:
            render_dir = work / Path(filename).stem
            render_dir.mkdir()
            cli(["--camera-view", "1", "--export-png", "0", "--outputdir", render_dir,
                 OUT / filename], Path(filename).stem + "_render.log")
            target = OUT / filename
            with ZipFile(target) as bundle:
                data = {n: bundle.read(n) for n in bundle.namelist()}
            with Image.open(render_dir / "plate_1_1.png") as preview:
                import io
                for image_name, size in [("Metadata/plate_1.png", 512), ("Metadata/plate_1_small.png", 128),
                                         ("Metadata/plate_no_light_1.png", 512)]:
                    buf = io.BytesIO()
                    preview.resize((size, size), Image.Resampling.LANCZOS).save(buf, format="PNG")
                    data[image_name] = buf.getvalue()
            with ZipFile(target, "w", ZIP_DEFLATED) as bundle:
                for name, contents in data.items():
                    bundle.writestr(name, contents)
        models = sorted([*OUT.glob("*.stl"), *OUT.glob("*.3mf")])
        # Native project presets cannot be merged in a multi-project CLI load.
        # Check each file in its own process, just as it is opened by the user.
        logs = []
        for model in models:
            cli(["--info", model], "bambu_import.log")
            logs.append((OUT / "bambu_import.log").read_text())
        log = "\n".join(logs)
        (OUT / "bambu_import.log").write_text(log)
        if len(re.findall(r"^manifold = yes$", log, re.MULTILINE)) != len(models):
            raise ValueError("Bambu did not validate every delivered model")
        (OUT / "result.json").unlink(missing_ok=True)
    validation = json.loads((SOURCE / "validation.json").read_text())
    validation["bambu_color_fix"] = {"revision": "v10", "assignments": reports,
        "printer": "Bambu Lab P1S, 0.4 mm", "material_preset": "Bambu PLA Silk+",
        "layer_height_mm": .2, "actual_bambu_render": "bambu_two_color_preview.png",
        "rendered_pink_pixels": int(pink.sum()), "rendered_green_pixels": int(green.sum()),
        "sliced": False, "geometry_changed": False}
    (OUT / "validation.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2) + "\n")
    instructions = (SOURCE / "PRINT_HE.txt").read_text()
    instructions = instructions.replace(
        "2. לבחור את דגם המדפסת, הדיזה והפילמנט. זהו קובץ מודל כללי ללא פרופיל מדפסת וללא G-code.",
        "2. לוודא שהמדפסת, הדיזה והפילמנטים תואמים להגדרות שבעדכון v10 לעיל. אין G-code בקובץ.")
    instructions = instructions.replace(
        "3. להקצות צבע גוף לחלקים samekh_body ו־mem_body וצבע סימונים לחלקים samekh_markers ו־mem_markers.",
        "3. השיוך כבר מוגדר: samekh_body ו־mem_body לפילמנט 1; samekh_markers ו־mem_markers לפילמנט 2.")
    instructions = """עדכון v10 — תיקון שיוך צבעים ל־Bambu Studio

לפתוח את samekh_mem_DUAL_COLOR.3mf כפרויקט (Open Project), ולא כייבוא גאומטריה בלבד.
בקובץ זה גוף שני האריחים משויך לפילמנט 1 (ורוד), והחצים והמספרים לפילמנט 2 (ירוק).
השיוך נשמר ונבדק בפתיחה ושמירה מחדש ב־Bambu, כולל רינדור שמראה את שני הצבעים.
הוגדרו P1S, דיזה 0.4 מ״מ, שכבה 0.20 מ״מ ושני פילמנטים מסוג Bambu PLA Silk+,
בהתאם לפרטי המדפסת והחומר בתמונה שסופקה. לפני Slice יש לוודא התאמה לפילמנטים שבשימוש.
צבעי התצוגה אינם שיוך לסלילי AMS: יש לבחור את הסלילים המתאימים בעת השליחה להדפסה.
בכרטיסיית Objects אפשר לראות body עם מספר 1 ו־markers עם מספר 2.
STL שומר רק גאומטריה. לשני צבעים מומלץ להשתמש ב־3MF שלהלן.
לא בוצעו Slice, יצירת G-code או שליחה למדפסת. צורת האריחים לא השתנתה מ־v9.

הוראות שימוש וגאומטריה:

""" + instructions
    (OUT / "PRINT_HE.txt").write_text(instructions)
    metadata_path = OUT / "trial_metadata.json"
    metadata = json.loads(metadata_path.read_text())
    metadata["bambu_color_revision"] = "v10 explicit filament 1 bodies / filament 2 markers; geometry identical to v9"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    active_path = g.ROOT / "data/active_design.json"
    active = json.loads(active_path.read_text())
    active["print"]["current_print_files"] = "outputs/samekh_mem_trial_v10/ — Bambu projects with explicit 1/2 filament assignments; geometry identical to v9."
    active["print"]["physical_trial_export"].update(
        generator="src/export_bambu_color_trial.py",
        dual_color="outputs/samekh_mem_trial_v10/samekh_mem_DUAL_COLOR.3mf",
        single_color="outputs/samekh_mem_trial_v10/samekh_mem_SINGLE_COLOR.3mf",
        status="Bambu color assignment roundtrip and render verified; unsliced")
    active_path.write_text(json.dumps(active, ensure_ascii=False, indent=2) + "\n")
    (OUT / "SHA256SUMS.txt").write_text("".join(
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n"
        for p in sorted(OUT.iterdir()) if p.is_file() and p.name != "SHA256SUMS.txt"))
    archive = g.ROOT / "hebrew-stencils-samekh-mem-trial-v10.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED) as bundle:
        for p in sorted(OUT.iterdir()):
            if p.is_file():
                bundle.write(p, f"samekh_mem_trial_v10/{p.name}")
    with ZipFile(archive) as bundle:
        if bundle.testzip():
            raise ValueError("Archive integrity failure")
    print(json.dumps({"output": str(OUT), "archive": str(archive), "files_checked": len(models),
                      "bambu_visible_color_pixels": {"pink": int(pink.sum()), "green": int(green.sum())}}))


if __name__ == "__main__":
    main()
