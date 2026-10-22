"""Make a distributable ZIP from an explicit project allowlist, with checksums."""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = {"src", "data", "fonts", "profiles", "docs", "tests", "examples", "downloads", "archive", "validation"}
TOP_FILES = {"README.md", "STATUS_HE.md", "THIRD_PARTY.md", "LICENSE.md", "requirements.txt",
             "requirements.lock.txt", ".gitignore", "config.json", "config.card_tiles.json", "QUICK_START_HE.txt"}


def included(path):
    rel = path.relative_to(ROOT)
    if any(p in {"__pycache__", ".venv", ".git", "local"} for p in rel.parts):
        return False
    if path.suffix in {".pyc", ".log", ".gcode"} or path.name.endswith(".gcode.3mf") or path.name == ".DS_Store":
        return False
    return rel.parts[0] in DIRECTORIES or str(rel) in TOP_FILES


def package(target):
    target = Path(target).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in ROOT.rglob("*") if p.is_file() and included(p))
    manifest = {"release_date": "2026-10-22", "root": "hebrew_stencils", "files": [
        {"path": str(p.relative_to(ROOT)), "bytes": p.stat().st_size,
         "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in files]}
    (ROOT / "FILES.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "SHA256SUMS.txt").write_text("".join(f"{row['sha256']}  {row['path']}\n" for row in manifest["files"]), encoding="utf-8")
    files.extend([ROOT / "FILES.json", ROOT / "SHA256SUMS.txt"])
    with ZipFile(target, "w", ZIP_DEFLATED) as z:
        for p in files:
            if p.suffix == ".3mf":
                with ZipFile(p) as model:
                    if model.testzip() or any(name.endswith(".gcode") for name in model.namelist()):
                        raise ValueError(f"Invalid model or embedded G-code: {p}")
            z.write(p, "hebrew_stencils/" + str(p.relative_to(ROOT)))
    with ZipFile(target) as z:
        if z.testzip():
            raise ValueError("Archive failed integrity check")
    print(json.dumps({"archive": str(target), "files": len(files), "size_bytes": target.stat().st_size}, ensure_ascii=False))
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    package(parser.parse_args().output)
