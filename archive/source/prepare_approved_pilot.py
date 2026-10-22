"""Apply the user's 2026-10-15 pilot stroke approval and place the markers.

This records a real approval received in this chat; it is limited to the six
pilot definitions. It never grants full-alphabet or physical-test approval.
"""
import hashlib
import json
from generate import ROOT, style_glyphs, outline_body, marker_geometry
from update_metadata import write_rows


def main():
    c=json.loads((ROOT/"config.json").read_text())
    rows=json.loads((ROOT/"data/letters_metadata.json").read_text())
    config_hash=hashlib.sha256(json.dumps({k:v for k,v in c.items() if not k.startswith("font_selection_")},sort_keys=True).encode()).hexdigest()
    if config_hash != "b34b6d5919b67c2e401c47e69a55c548ba5c3580972aaa582f49d09fff08a9e7":
        raise ValueError("This historical approval applies only to the recorded pilot configuration; review changes before recording a new approval")
    expected_fonts={"print":"18f930b583fa8fe6b40b2f8263b7ac6afbac07adc91a12467874e7467d3ace30",
                    "script":"05c443395d48b97f43469da4fb08772a4c612fda306348577dbc40a1267912b1"}
    for style,expected in expected_fonts.items():
        if hashlib.sha256((ROOT/c["fonts"][style]).read_bytes()).hexdigest()!=expected:
            raise ValueError("Font changed since the recorded pilot decision")
    # Each tuple: actual glyph start, separate number position, direction path.
    layouts={
      ("print","א"):[((16,42.5),(8,48),[(11,46),(14,43)]),((35,42.5),(40,49),[(43,46),(39,42)]),((21.5,34.5),(8,34),[(11.5,31),(9.5,24)])],
      ("print","ב"):[((17.5,42.5),(11,49),[(17,48),(35,48),(40,43),(40,36)]),((17.5,20.5),(11,12),[(17,16),(35,16)])],
      ("script","א"):[((33.5,35),(38,41),[(39,39),(35.5,36)]),((25.5,38),(12,44),[(15,41),(12.5,33)])],
      ("script","ב"):[((20,33.5),(12,40),[(18,39),(29,40),(37,37),(40,32),(39,26),(34,22)])],
      ("print","ס"):[((17,43),(11,50),[(18,48),(35,48),(41,44),(42,38)])],
      ("script","ם"):[((25,34.5),(19,43),[(25,41),(33,41),(38,37),(39,31),(35,25)])]
    }
    gs={s:style_glyphs(c,s) for s in ["print","script"]}
    for row in rows:
        key=row["style"],row["char"]
        if key not in layouts:continue
        row["start_points"]=[];row["direction_arrows"]=[]
        for (x,y),(lx,ly),path in layouts[key]:
            row["start_points"].append({"x":x,"y":y,"label_x":lx,"label_y":ly})
            row["direction_arrows"].append({"from":path[0],"to":path[-1],"path":path})
        if key==("script","ם"):
            row["direction_arrows"][0]["additional_paths"]=[[(13,29),(11.5,22)]]
            row["bridge_paths_mm"]=[[(21,40),(29,31)]]
        if key==("print","ס"):
            row["bridge_paths_mm"]=[[(18,47),(21,38)]]
        row.update(stroke_order_status="approved",approved_by="User: מאשרת את ההגדרות לפיילוט (chat reply 2026-10-15)",
                   approval_scope="pilot",approved_font_sha256=hashlib.sha256((ROOT/c["fonts"][row["style"]]).read_bytes()).hexdigest(),
                   approved_geometry_config_sha256=config_hash,
                   marker_placement_status="engineering_pilot; generated after approval of stroke definitions; unprinted",
                   bridge_placement_status="engineering_pilot_pending_physical_review" if row.get("needs_bridge") else "not_needed")
        row["source_scope"]=row["source_scope"].replace("ממתינים לאישור הגדרה ומיקום", "הגדרת המשיכות אושרה לפיילוט; מיקום הסימונים ממתין לניסוי פיזי").replace("ממתין לאישור הגדרה ומיקום", "הגדרת המשיכות אושרה לפיילוט; מיקום הסימונים ממתין לניסוי פיזי").replace("ממתין לבחירת המשתמשת לפיילוט", "המשתמשת אישרה הגדרה זו לפיילוט")
        body,_=outline_body(c,gs[key[0]][key[1]],row.get("bridge_paths_mm"))
        try:marker_geometry(c,row,body,scope="pilot")
        except ValueError as error:
            raise ValueError(f"{key}: {error}") from error
    write_rows(rows)
    print("Recorded six user-approved pilot definitions and checked marker clearance")


if __name__=="__main__":main()
