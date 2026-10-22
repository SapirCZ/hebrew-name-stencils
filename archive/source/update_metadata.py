"""Synchronize configured fonts and audited bridges without approving strokes."""
import csv
import hashlib
import json
from generate import ROOT, style_glyphs, outline_body


def write_rows(rows):
    json_path=ROOT/"data/letters_metadata.json"
    csv_path=ROOT/"data/letters_metadata.csv"
    fields=list(dict.fromkeys(k for row in rows for k in row))
    json_path.with_suffix(".json.tmp").write_text(json.dumps(rows,ensure_ascii=False,indent=2)+"\n")
    with csv_path.with_suffix(".csv.tmp").open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for row in rows:
            w.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in row.items()})
    json_path.with_suffix(".json.tmp").replace(json_path)
    csv_path.with_suffix(".csv.tmp").replace(csv_path)


def main():
    c=json.loads((ROOT/"config.json").read_text())
    rows=json.loads((ROOT/"data/letters_metadata.json").read_text())
    gs={s:style_glyphs(c,s) for s in ["print","script"]}
    for r in rows:
        style=r["style"]
        r.update(font_source="Heebo Regular" if style=="print" else "Gveret Levin",
                 font_path=c["fonts"][style],font_url="https://github.com/google/fonts/tree/main/ofl/heebo" if style=="print" else "https://github.com/AlefAlefAlef/gveret-levin",
                 font_axes=c["font_axes"][style],font_selection_status="approved",
                 current_font_sha256=hashlib.sha256((ROOT/c["fonts"][style]).read_bytes()).hexdigest(),
                 glyph_source_notes="מקור הפונט שנבחר על ידי המשתמשת; קנה מידה אחיד ושמירת כלל מילוי nonzero; גשרים מתועדים בנפרד.")
        _,bs=outline_body(c,gs[style][r["char"]],r.get("bridge_paths_mm"))
        r["needs_bridge"]=bool(bs)
        if bs and r["bridge_placement_status"]=="not_needed":r["bridge_placement_status"]="pending"
        if not bs:r["bridge_placement_status"]="not_needed"
        r.setdefault("reference_family",None)
        r.setdefault("reference_family_source",None)
        r.setdefault("reference_family_source_locator",None)
    for r in rows:
        if r.get("stroke_order_status")=="approved":
            continue
        if r["style"]=="print" and r["char"]=="א":
            url="https://gkushnir.com/product/נהנים-לכתוב-בדפוס/"
            r.update(stroke_count=3,stroke_source=url,israeli_pedagogy_source=url,
                     source_locator="דוגמה הכרת האות וכתיבתה; תמונת 353815214539011.jpg, שלוש מסגרות מימין",
                     stroke_order_description="1. אלכסון עליון־שמאלי לימין למטה. 2. ענף מימין למעלה אל המפגש. 3. ענף מהמפגש לשמאל למטה.",
                     stroke_order_status="draft_reference",source_scope="מקור ישראלי של חיה קושניר; השלבים נבדקו חזותית, ממתינים לאישור הגדרה ומיקום.")
        if r["style"]=="print" and r["char"] in "בס":
            url="https://ugabuga.co.il/letters/"+("bet" if r["char"]=="ב" else "samech")
            r.update(stroke_count=2 if r["char"]=="ב" else 1,stroke_source=url,israeli_pedagogy_source=url,
                     source_locator="SVG ההדגמה הגלוי בעמוד, aria-label איך כותבים את האות; נבדק סדר פקודות M/H/V/Q/Z",
                     stroke_order_description="גג משמאל לימין ואז מטה בצד ימין; הרמת עט וקו בסיס משמאל לימין." if r["char"]=="ב" else "מהגג משמאל לימין; ירידה בצד ימין, הקפה בתחתית לשמאל וחזרה למעלה בכיוון השעון ברצף.",
                     reference_start_regions=["upper_left","lower_left"] if r["char"]=="ב" else ["upper_left"],
                     reference_initial_directions=["right_then_down","right"] if r["char"]=="ב" else ["right_then_clockwise"],
                     stroke_order_status="draft_reference",source_scope="אתר תרגול ישראלי; אינו תקן או מדריך משרד החינוך. הכיוון נבדק בהדגמה ונמצא תואם גם למקור ההשוואה החיצוני. ממתין לבחירת המשתמשת לפיילוט.")
        if r["style"]=="script":
            groups={"נופל":"יוןנמ","קשת":"רבהחקת","כד":"כךדסםפצז","אריה":"אגלףעץ","שולף":"טש"}
            r["reference_family"]=next(name for name,chars in groups.items() if r["char"] in chars)
            r["reference_family_source"]="https://www.netzart-fedorov.com/clients/kushnir/Ktav-madrich.zip"
            r["reference_family_source_locator"]="Ktav-madrich.pdf, page 10; family membership only, not a complete stroke definition"
            if r["char"]=="ם":
                url="https://www.netzart-fedorov.com/clients/kushnir/Ktav-madrich.zip"
                r.update(stroke_count=1,stroke_source=url,israeli_pedagogy_source=url,
                         source_locator="Ktav-madrich.pdf, page 28, clock diagram and paragraph marked ם",
                         stroke_order_description="מתחילים בחלק העליון־שמאלי של הלולאה (עמדת שעה 10), מקיפים בכיוון השעון, חוזרים לנקודה ויורדים ממנה בקו ישר מטה, ברצף.",
                         reference_start_regions=["loop_upper_left_10_oclock"],
                         reference_initial_directions=["clockwise_loop_then_down_from_start"],
                         stroke_order_status="draft_reference",source_scope="מקור ישראלי מפורש: חיה קושניר, מדריך למורה, עמ׳ 28; ממתין לאישור הגדרה ומיקום.")
    write_rows(rows)
    print("Updated 54 font/bridge records and Israeli source references for print alef and script final mem")


if __name__=="__main__":main()
