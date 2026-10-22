"""Rebuild metadata skeleton and font comparison from checked-in fonts.

Does not approve fonts/strokes, and will not overwrite reviewed metadata.
"""
import csv
import hashlib
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont
from generate import style_glyphs, tile, polygons

ROOT = Path(__file__).resolve().parents[1]
LETTERS = list(zip("אבגדהוזחטיךכלםמןנסעףפץצקרשת", [
    "אלף","בית","גימל","דלת","הא","וו","זין","חית","טית","יוד","כף סופית","כף","למד",
    "מם סופית","מם","נון סופית","נון","סמך","עין","פא סופית","פא","צדי סופית","צדי","קוף","ריש","שין","תו"]))
FONTS = [
    ("Alef Regular", "print", "fonts/print/alef/Alef-Regular.ttf", "SIL OFL 1.1", "https://github.com/google/fonts/tree/main/ofl/alef"),
    ("Heebo Regular (variable)", "print", "fonts/print/heebo/Heebo[wght].ttf", "SIL OFL 1.1", "https://github.com/google/fonts/tree/main/ofl/heebo"),
    ("Gveret Levin", "script", "fonts/script/gveret/GveretLevin-Regular.ttf", "SIL OFL 1.1", "https://github.com/AlefAlefAlef/gveret-levin"),
    ("Ktav Yad CLM Medium Italic", "script", "fonts/script/ktav-yad/KtavYadCLM-MediumItalic.otf", "GPL-2.0 (embedded copyright)", "https://culmus.sourceforge.io/fancy/ktav-yad.zip"),
    ("Dorian CLM Book", "script", "fonts/script/dorian/DorianCLM-Book.ttf", "GPL-2.0 (embedded copyright)", "https://culmus.sourceforge.io/fancy/dorian.zip")
]


def main():
    rows = []
    config=json.loads((ROOT/"config.json").read_text())
    outlines={s:style_glyphs(config,s) for s in ["print","script"]}
    source = "https://www.ancient-hebrew.org/learn/how-to-write-hebrew.htm"
    script_source = "https://www.yo-yoo.co.il/limodim/daf.php?id=420"
    refs = {
        ("print","א"): (3, "תחילה האלכסון מהפינה השמאלית העליונה לימין למטה; אחריו הענף הימני העליון פנימה ולמטה; לבסוף הענף השמאלי התחתון פנימה ולמטה לשמאל.", ["upper_left","upper_right","center_left"], ["down_right","down_left","down_left"], source+"#Aleph"),
        ("print","ב"): (2, "גג משמאל לימין ואז ירידה בצד ימין; קו תחתון משמאל לימין. דגש אינו חלק מאריח האות ואינו נספר.", ["upper_left","lower_left"], ["right_then_down","right"], source+"#Beyt"),
        ("print","ג"): (2, "קו עליון משמאל לימין וירידה לרגל הימנית; ענף מהאזור המרכזי באלכסון לשמאל למטה.", ["upper_left","middle"], ["right_then_down","down_left"], source+"#Gimel"),
        ("print","ס"): (1, "החץ במקור מתחיל בחלק העליון משמאל לימין ומפנה מטה בצד ימין; המשך ההקפה דורש אימות לפני מיקום סימונים.", ["upper_left"], ["right_then_down"], source+"#Samehh"),
        ("print","ם"): (1, "בגרסת מקור זה: תחילה החלק העליון משמאל לימין ואז מטה בצד ימין; ההקפה מרובעת. יש לאשר גרסת משיכה יחידה לעומת חלוקה לשתי משיכות.", ["upper_left"], ["right_then_down"], source+"#Final-Mem"),
        ("script","א"): (2, "החלק הימני מתחיל באזור הימני העליון ונע שמאלה לעיקול; אחריו הקו השמאלי מלמעלה למטה.", ["upper_right","upper_left"], ["left_into_curve","down"], script_source),
        ("script","ב"): (1, "תחילה באזור העליון השמאלי לכיוון ימין; המשך העיקול כפי שמוצג בדף, עם בדיקה נפרדת של המסלול המלא.", ["upper_left"], ["right_into_curve"], script_source),
        ("script","ג"): (1, "תחילה באזור העליון, באלכסון מטה וימינה, ואז המשך עיקול האות לפי הדוגמה.", ["upper_left"], ["down_right_into_curve"], script_source),
        ("script","ס"): (1, "תחילה בחלק העליון השמאלי, באלכסון מעלה וימינה לפתיחת ההקפה.", ["upper_left"], ["up_right_into_loop"], script_source),
        ("script","ם"): (None, "הצורה הסופית אינה מופיעה בדף הכתב שנבדק. אין להסיק את כיוונה מהאות מ או מהפונט. נדרש מקור מפורש.", [], [], None)
    }
    for style in ["print","script"]:
        font = FONTS[0] if style=="print" else FONTS[2]
        for char,name in LETTERS:
            ref = refs.get((style,char))
            count,description,starts,directions,url = ref or (None,"טרם תועד מקור ברמת האות",[],[],None)
            needs_bridge=len(polygons(tile(config).difference(outlines[style][char])))>1
            rows.append({"name_he":name,"char":char,"style":style,"final_form":char in "ךםןףץ",
                "font_source":font[0], "font_path":font[2], "font_url":font[4],
                "glyph_source_notes":"מתאר מקורי של הפונט; בחירת הפונט מוצעת בלבד. שינוי גאומטרי יחיד אפשרי: offset פרמטרי מתועד וגשרים.",
                "stroke_count":count,"stroke_order_description":description,
                "start_points":[],"direction_arrows":[],
                "reference_start_regions":starts,"reference_initial_directions":directions,
                "needs_bridge":needs_bridge,"tile_id":f"{style}_u{ord(char):04x}",
                "rtl_connector_role":"left_male_right_female; next logical letter is placed one tile width to the left",
                "stroke_source":url,"source_locator": "See docs/stroke_order/pilot_reference.md" if ref else None,
                "stroke_order_status":"draft_reference" if count else "source_needed",
                "approved_by":None,"font_selection_status":"proposed",
                "source_scope":"תעתיק ראשוני של מקור; אינו אישור לתוכנית לימודים ישראלית" if ref else None,
                "israeli_pedagogy_source":script_source if style=="script" and char in "אבגס" else None,
                "bridge_placement_status":"pending" if needs_bridge else "not_needed",
                "approved_font_sha256":None,"approved_geometry_config_sha256":None})
    dest=ROOT/"data/letters_metadata.json"
    if dest.exists():
        raise SystemExit("Metadata already exists; refusing to overwrite review work")
    dest.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+"\n")
    with (ROOT/"data/letters_metadata.csv").open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader()
        for row in rows:
            w.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in row.items()})
    manifest=[]
    im=Image.new("RGB",(1400,930),"#f7f5ef");d=ImageDraw.Draw(im)
    ui=ImageFont.truetype(str(ROOT/FONTS[0][2]),24)
    d.text((35,20),"FONT REVIEW | original glyphs | proposed, awaiting educational review",font=ui,fill="#283d42")
    for idx,(name,style,rel,license,url) in enumerate(FONTS):
        p=ROOT/rel
        ff=TTFont(p)
        missing=[ch for ch,_ in LETTERS if ord(ch) not in ff.getBestCmap()]
        if missing:raise ValueError(f"Missing letters in {name}: {missing}")
        manifest.append({"name":name,"style":style,"path":rel,"license":license,"source":url,
                         "retrieved_on":"2026-10-15","sha256":hashlib.sha256(p.read_bytes()).hexdigest(),
                         "coverage_27":True,"school_approved":False})
        y=90+idx*166
        d.rounded_rectangle((25,y-10,1375,y+140),radius=15,fill="#ffffff")
        d.text((45,y),f"{name} | {license}",font=ui,fill="#283d42")
        samplefont=ImageFont.truetype(str(p),65)
        # Draw isolated letters, no shaping/RTL or missing-glyph fallback involved.
        for j,ch in enumerate("אבגסמךםןףץשת"):
            d.text((1310-j*108,y+42),ch,font=samplefont,fill="#314f4c",anchor="mt")
    im.save(ROOT/"outputs/previews/font_comparison.png")
    (ROOT/"data/font_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
    print(f"Wrote {len(rows)} metadata rows and compared {len(FONTS)} fonts")


if __name__=="__main__":main()
