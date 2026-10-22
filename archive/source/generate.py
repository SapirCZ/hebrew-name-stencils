"""Font-derived stencil research prototype. All lengths in mm; +Y is up.

Engineering output is deliberately unmarked. Educational exports require a
reviewed font selection AND per-letter stroke/marker approval in metadata.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

import numpy as np
import trimesh
import manifold3d
from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont
from shapely import affinity
from shapely.geometry import Polygon, LineString, Point, box
from shapely.ops import nearest_points, unary_union, polygonize
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
CHARS = "אבגדהוזחטיךכלםמןנסעףפץצקרשת"
PILOT = [("print", "א"), ("print", "ב"), ("script", "א"),
         ("script", "ב"), ("print", "ס"), ("script", "ם")]


def polygons(g):
    if isinstance(g, Polygon):
        return [g] if not g.is_empty else []
    return [p for part in getattr(g, "geoms", []) for p in polygons(part)]


class OutlinePen(BasePen):
    """Flatten Beziers adaptively, at <= 0.5 font-unit control-polygon error."""
    def __init__(self, glyphset):
        super().__init__(glyphset)
        self.rings = []
        self.points = []

    def _moveTo(self, p):
        self.points = [p]

    def _lineTo(self, p):
        self.points.append(p)

    def flatten(self, pts, depth=0):
        a, b = np.array(pts[0]), np.array(pts[-1])
        chord = LineString([a, b]) if np.linalg.norm(a-b) else Point(a)
        if depth >= 16 or max(chord.distance(Point(p)) for p in pts) <= .5:
            self.points.append(tuple(b))
            return
        levels = [np.array(pts, dtype=float)]
        while len(levels[-1]) > 1:
            q = levels[-1]
            levels.append((q[:-1] + q[1:]) / 2)
        self.flatten([q[0] for q in levels], depth+1)
        self.flatten([q[-1] for q in reversed(levels)], depth+1)

    def _qCurveToOne(self, p1, p2):
        self.flatten([self.points[-1], p1, p2])

    def _curveToOne(self, p1, p2, p3):
        self.flatten([self.points[-1], p1, p2, p3])

    def _closePath(self):
        if len(self.points) >= 3:
            self.rings.append(self.points)
        self.points = []

    def _endPath(self):
        raise ValueError("Font has an open contour")


def font_contours(rings):
    """Use the font's nonzero winding rule, preserving overlapping strokes."""
    contours=[]
    for ring in rings:
        p=Polygon(ring)
        if not p.is_valid:
            raise ValueError("Invalid glyph contour")
        coords=list(p.exterior.coords)
        signed=sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(coords,coords[1:]))
        contours.append((p,1 if signed>0 else -1))
    faces=polygonize(unary_union([p.boundary for p,_ in contours]))
    return unary_union([face for face in faces if sum(sign for p,sign in contours if p.covers(face.representative_point()))!=0])


def glyph(path, char, axes=None):
    with TTFont(path) as font:
        name = font.getBestCmap().get(ord(char))
        if name is None:
            raise ValueError(f"Missing glyph {char!r} in {path}")
        if axes and "fvar" not in font:
            raise ValueError("Variation coordinates supplied for a static font")
        gs = font.getGlyphSet(location=axes or None)
        pen = OutlinePen(gs)
        gs[name].draw(pen)
    result=font_contours(pen.rings)
    if result.is_empty or not result.is_valid:
        raise ValueError(f"Invalid glyph: {char}")
    return result


def validate_config(c):
    for name in ["width", "height", "thickness", "corner_radius", "connector_radius",
                 "connector_neck", "connector_projection", "bridge_width", "minimum_wall",
                 "glyph_window_width", "glyph_window_height", "marker_line_width"]:
        if not math.isfinite(c[name]) or c[name] <= 0:
            raise ValueError(f"{name} must be positive")
    for name in ["marker_head_length", "marker_head_width", "marker_corner_radius"]:
        if name in c and (not math.isfinite(c[name]) or c[name] <= 0):
            raise ValueError(f"{name} must be positive")
    if not 0 < c["marker_depth"] < c["thickness"]-c["minimum_wall"]:
        raise ValueError("Marker recess leaves insufficient floor")
    if not 0 < c["connector_clearance"] < 1:
        raise ValueError("Connector clearance must be in (0, 1) mm")
    if c["connector_neck"] < c["minimum_wall"] or c["bridge_width"] < c["minimum_wall"]:
        raise ValueError("Neck/bridge narrower than minimum wall")
    if c["connector_projection"] >= 2*c["connector_radius"]:
        raise ValueError("Connector head must overlap tile edge")
    for f in c["connector_y_fractions"]:
        if not c["connector_radius"]+c["corner_radius"] < f*c["height"] < c["height"]-c["connector_radius"]-c["corner_radius"]:
            raise ValueError("Connector overlaps rounded corner")
    if c["corner_radius"]*2 >= min(c["width"], c["height"]):
        raise ValueError("Corner radius is too large")
    if c["glyph_bottom"] < c["minimum_wall"] or c["glyph_bottom"]+c["glyph_window_height"] > c["height"]-c["minimum_wall"]:
        raise ValueError("Glyph window extends outside tile")


def tile(c):
    w, h, r = c["width"], c["height"], c["corner_radius"]
    outer = box(r, r, w-r, h-r).buffer(r, quad_segs=24)
    # Left-facing male connects to the right socket of the next letter to its left.
    cr, proj, neck = c["connector_radius"], c["connector_projection"], c["connector_neck"]
    male = unary_union([unary_union([Point(cr-proj, h*f).buffer(cr, quad_segs=32),
                        box(cr-proj, h*f-neck/2, 1, h*f+neck/2)]) for f in c["connector_y_fractions"]])
    socket = affinity.translate(male, xoff=w).buffer(c["connector_clearance"], quad_segs=16)
    result = outer.union(male).difference(socket)
    if not isinstance(result, Polygon) or not result.is_valid:
        raise ValueError("Invalid connector parameters")
    return result


def style_glyphs(c, style):
    font = ROOT / c["fonts"][style]
    gs = {ch: glyph(font, ch, c.get("font_axes",{}).get(style)) for ch in CHARS}
    ymin = min(g.bounds[1] for g in gs.values())
    ymax = max(g.bounds[3] for g in gs.values())
    scale = min(c["glyph_window_width"] / max(g.bounds[2]-g.bounds[0] for g in gs.values()),
                c["glyph_window_height"] / (ymax-ymin))
    # One common isotropic scale and baseline for the entire font/style.
    out = {}
    for ch, g in gs.items():
        g = affinity.scale(g, scale, scale, origin=(0, 0))
        g = affinity.translate(g, xoff=c["width"]/2-(g.bounds[0]+g.bounds[2])/2,
                               yoff=c["glyph_bottom"]-ymin*scale)
        if c["glyph_offset"]:
            g = g.buffer(c["glyph_offset"], quad_segs=16)
        out[ch] = g
    return out


def bridge_body(outer, aperture, width):
    raw = outer.difference(aperture)
    parts = sorted(polygons(raw), key=lambda p: -p.area)
    main, bridges = parts[0], []
    for island in parts[1:]:
        # A shortest boundary-to-boundary segment can attach at a sharp tip and
        # leave a vanishingly thin joint. Run into the island interior instead.
        b = island.representative_point()
        a, _ = nearest_points(main, b)
        av, bv = np.array(a.coords[0]), np.array(b.coords[0])
        unit = (bv-av) / np.linalg.norm(bv-av)
        bridge = LineString([av-unit*width*2, bv]).buffer(width/2, cap_style=1).intersection(outer)
        main = unary_union([main, island, bridge])
        bridges.append(bridge)
    if not isinstance(main, Polygon) or not main.is_valid:
        raise ValueError("Bridge failed to attach island")
    return main, bridges


def outline_body(c, g, bridge_paths=None):
    outer = tile(c)
    if not outer.buffer(-c["minimum_wall"]).contains(g):
        raise ValueError("Letter too close to edge/socket")
    if bridge_paths:
        bridges=[LineString(p).buffer(c["bridge_width"]/2).intersection(outer) for p in bridge_paths]
        body=unary_union([outer.difference(g),*bridges])
        if len(polygons(body))!=1:
            raise ValueError("Specified bridges leave a detached island")
    else:
        body, bridges = bridge_body(outer, g, c["bridge_width"])
    # A connected peninsula can still have a fragile root. Add explicit
    # structural bridges to eroded islands, preserving the source glyph itself.
    # All such bridges are logged and require pedagogical placement review.
    for _ in range(8):
        eroded=sorted(polygons(body.buffer(-c["minimum_wall"]/2+.01)),key=lambda p:-p.area)
        if len(eroded)==1:
            break
        if not eroded:
            raise ValueError("Body disappears under minimum-wall check")
        strong=eroded[0]
        for weak in eroded[1:]:
            b=weak.representative_point()
            a,_=nearest_points(strong,b)
            av,bv=np.array(a.coords[0]),np.array(b.coords[0])
            unit=(bv-av)/np.linalg.norm(bv-av)
            bridge=LineString([av-unit*c["bridge_width"],bv]).buffer(c["bridge_width"]/2).intersection(outer)
            body=body.union(bridge)
            bridges.append(bridge)
    else:
        raise ValueError("Structural bridges did not resolve thin wall")
    if len(polygons(body.buffer(-c["minimum_wall"]/2+.01)))!=1:
        raise ValueError("Body has a wall narrower than the configured minimum")
    return body, bridges


def extrude(g, height, z=0):
    if g.is_empty:
        raise ValueError("Cannot export empty geometry")
    paths=[list(r.coords)[:-1] for p in polygons(g) for r in [p.exterior,*p.interiors]]
    solid=manifold3d.CrossSection(paths,manifold3d.FillRule.EvenOdd).extrude(height)
    mesh=solid.to_mesh()
    m=trimesh.Trimesh(vertices=np.asarray(mesh.vert_properties)[:,:3],faces=np.asarray(mesh.tri_verts),process=True)
    m.apply_translation([0, 0, z])
    if not m.is_watertight or not m.is_winding_consistent or m.volume <= 0:
        raise ValueError("Mesh failed manifold/volume checks")
    return m


def require_approval(c, row, scope="production"):
    if c.get("font_selection_status") != "approved" or not c.get("font_selection_reviewer"):
        raise ValueError("Font selection requires human approval")
    if row.get("stroke_order_status") != "approved" or not row.get("approved_by"):
        raise ValueError(f"Stroke order requires human approval: {row['tile_id']}")
    if row.get("approval_scope") not in (["pilot","production"] if scope=="pilot" else ["production"]):
        raise ValueError("Stroke approval does not cover this export scope")
    if not row.get("stroke_source") or not row.get("stroke_count"):
        raise ValueError("Missing stroke evidence/count")
    if not row.get("israeli_pedagogy_source"):
        raise ValueError("An Israeli teaching source must be recorded before educational export")
    if len(row["direction_arrows"]) != row["stroke_count"] or len(row["start_points"]) != row["stroke_count"]:
        raise ValueError("Missing approved per-stroke marker placement")
    font_hash = hashlib.sha256((ROOT/c["fonts"][row["style"]]).read_bytes()).hexdigest()
    if row.get("approved_font_sha256") != font_hash:
        raise ValueError("Reviewed font file does not match configured font")
    config_geometry = {k:v for k,v in c.items() if not k.startswith("font_selection_")}
    config_hash = hashlib.sha256(json.dumps(config_geometry,sort_keys=True).encode()).hexdigest()
    if row.get("approved_geometry_config_sha256") != config_hash:
        raise ValueError("Geometry changed since review")


def smooth_arrow_path(path, radius):
    """Round guide corners while retaining both endpoints and end tangents."""
    points=np.asarray(path,dtype=float)
    if len(points)<2 or not np.isfinite(points).all() or any(np.linalg.norm(b-a)<1e-6 for a,b in zip(points,points[1:])):
        raise ValueError("Arrow guide needs distinct finite points")
    result=[points[0]]
    for a,b,d in zip(points,points[1:],points[2:]):
        incoming,outgoing=b-a,d-b
        cut=min(radius,np.linalg.norm(incoming)*.4,np.linalg.norm(outgoing)*.4)
        enter=b-incoming/np.linalg.norm(incoming)*cut
        leave=b+outgoing/np.linalg.norm(outgoing)*cut
        for t in np.linspace(0,1,9):
            result.append((1-t)**2*enter+2*(1-t)*t*b+t*t*leave)
    result.append(points[-1])
    return LineString(result)


def arrow_geometry(c, path):
    guide=smooth_arrow_path(path,c.get("marker_corner_radius",1.8))
    if guide.length < 3:
        raise ValueError("Arrow too short")
    tip=np.asarray(guide.coords[-1])
    tangent=tip-np.asarray(guide.interpolate(max(0,guide.length-.15)).coords[0])
    tangent/=np.linalg.norm(tangent)
    normal=np.array([-tangent[1],tangent[0]])
    head_length=min(c.get("marker_head_length",2.8),guide.length*.65)
    half_width=c.get("marker_head_width",3.4)/2
    head=Polygon([tip,tip-head_length*tangent+half_width*normal,tip-head_length*tangent-half_width*normal])
    # Trim the shaft under the head so its round cap cannot protrude past the tip.
    from shapely.ops import substring
    shaft=substring(guide,0,guide.length-head_length*.55).buffer(c["marker_line_width"]/2,quad_segs=16)
    arrow=shaft.union(head)
    if not isinstance(arrow,Polygon) or not arrow.is_valid:
        raise ValueError("Arrow head must remain connected to its curved shaft")
    return arrow


def marker_geometry(c, row, body, scope="production"):
    require_approval(c, row, scope=scope)
    shapes = []
    for i, (start, arrow) in enumerate(zip(row["start_points"], row["direction_arrows"]), 1):
        # Labels and arrows use tile coordinates, separate from the traced opening.
        number = glyph(ROOT / c["fonts"]["print"], str(i), c.get("font_axes",{}).get("print"))
        x0, y0, x1, y1 = number.bounds
        s = c["marker_number_height"]/(y1-y0)
        number = affinity.scale(number, s, s, origin=(0, 0))
        number = affinity.translate(number, start["label_x"]-x0*s, start["label_y"]-y0*s)
        shapes.append(number)
        paths=[arrow["path"] if "path" in arrow else [arrow["from"],arrow["to"]], *arrow.get("additional_paths",[])]
        for path in paths:
            shapes.append(arrow_geometry(c,path))
    markers = unary_union(shapes)
    if not body.buffer(-c["marker_clearance"]).contains(markers):
        raise ValueError("Markers touch aperture, bridge edge, or tile boundary")
    return markers


def split_layers(c, body, markers):
    full = extrude(body, c["thickness"])
    fill = extrude(markers, c["marker_depth"], c["thickness"]-c["marker_depth"])
    base = trimesh.boolean.difference([full, fill], engine="manifold")
    for part in [base, fill]:
        if not part.is_watertight or not part.is_winding_consistent or part.volume <= 0:
            raise ValueError("Invalid recessed body or marker fill mesh")
    # For single filament preserve recessed marks by exporting the engraved base.
    return base, fill, base.copy()


def write_3mf(path, objects, groups=None):
    """Generic 3MF Core assemblies, material-separated; no printer preset.

    Optional groups retain independent multipart objects for per-object settings.
    Existing callers continue to receive one assembly containing all parts.
    """
    if groups is None:
        groups = [list(range(len(objects)))]
    if any(not group for group in groups) or sorted(i for group in groups for i in group) != list(range(len(objects))):
        raise ValueError("3MF groups must partition all parts exactly once")
    ns = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
    ET.register_namespace("", ns)
    def sub(parent, tag, **attrs):
        return ET.SubElement(parent, f"{{{ns}}}{tag}", {k:str(v) for k,v in attrs.items()})
    model = ET.Element(f"{{{ns}}}model", {"unit":"millimeter", "{http://www.w3.org/XML/1998/namespace}lang":"en-US"})
    sub(model, "metadata", name="Title").text = "Engineering prototype - review pending"
    res = sub(model, "resources")
    materials = sub(res, "basematerials", id=1)
    for name, _, color in objects:
        sub(materials, "base", name=name, displaycolor=color)
    for idx, (name, mesh, _) in enumerate(objects):
        obj = sub(res, "object", id=idx+2, type="model", name=name, pid=1, pindex=idx)
        mesh_el = sub(obj, "mesh")
        verts, tris = sub(mesh_el, "vertices"), sub(mesh_el, "triangles")
        for x,y,z in mesh.vertices:
            sub(verts, "vertex", x=f"{x:.7f}", y=f"{y:.7f}", z=f"{z:.7f}")
        for a,b,d in mesh.faces:
            sub(tris, "triangle", v1=a, v2=b, v3=d)
    for group_index, group in enumerate(groups):
        assembly_id = len(objects)+2+group_index
        assembly = sub(res, "object", id=assembly_id, type="model")
        comps = sub(assembly, "components")
        for idx in group:
            sub(comps, "component", objectid=idx+2)
    build = sub(model, "build")
    for group_index in range(len(groups)):
        sub(build, "item", objectid=len(objects)+2+group_index)
    with ZipFile(path, "w", ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
        z.writestr("3D/3dmodel.model", ET.tostring(model, encoding="utf-8", xml_declaration=True))


def paint(draw, g, transform, fill):
    for p in polygons(g):
        draw.polygon([transform(x,y) for x,y in p.exterior.coords], fill=fill)
        for ring in p.interiors:
            draw.polygon([transform(x,y) for x,y in ring.coords], fill="#f7f5ef")


def preview(c, items, path, marker_sets=None):
    antialias=3
    scale, cellw, cellh = 5*antialias, 330*antialias, 385*antialias
    im = Image.new("RGB", (cellw*3, cellh*2+65*antialias), "#f7f5ef")
    d = ImageDraw.Draw(im)
    font = ImageFont.truetype(str(ROOT/c["fonts"]["print"]), 17*antialias)
    d.text((20*antialias,15*antialias), "APPROVED STROKE PILOT | two-color inlay | unprinted" if marker_sets else "ENGINEERING STUDY | no teaching marks | dimensions in mm", fill="#283d42", font=font)
    for i,(label,body,bridges) in enumerate(items):
        col, row = i%3, i//3
        ox, oy = col*cellw+42*antialias, row*cellh+85*antialias
        tf = lambda x,y: (ox+x*scale, oy+(c["height"]-y)*scale)
        paint(d, body, tf, "#e7aeaa")
        if marker_sets:
            paint(d,marker_sets[i],tf,"#294a43")
        else:
            for b in bridges:paint(d, b, tf, "#9cb9ac")
        d.text((ox-15*antialias, oy+320*antialias), label, font=font, fill="#283d42")
    im.resize((im.width//antialias,im.height//antialias),Image.Resampling.LANCZOS).save(path)


def alphabet_preview(c, style, items, path):
    cellw,cellh,scale=300,365,4.3
    im=Image.new("RGB",(cellw*7,cellh*4+90),"#f7f5ef")
    d=ImageDraw.Draw(im)
    ui=ImageFont.truetype(str(ROOT/c["fonts"]["print"]),20)
    d.text((25,15),f"{style.upper()} | Heebo Regular 400 / Gveret Levin | UNMARKED ENGINEERING",font=ui,fill="#283d42")
    d.text((25,45),"Green = structural bridges pending teaching review. Letter order proceeds right to left.",font=ui,fill="#283d42")
    for i,(name,body,bridges) in enumerate(items):
        col,row=6-i%7,i//7
        ox,oy=col*cellw+42,row*cellh+100
        tf=lambda x,y:(ox+x*scale,oy+(c["height"]-y)*scale)
        paint(d,body,tf,"#e7aeaa" if style=="print" else "#c8d8d0")
        for bridge in bridges:paint(d,bridge,tf,"#729d86")
        d.text((ox-15,oy+285),name.split("_")[-1].upper().replace("U","U+",1),font=ui,fill="#283d42")
    im.save(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=Path, default=ROOT/"config.json")
    ap.add_argument("--production", action="store_true", help="Requires approved metadata for all 54 letters")
    ap.add_argument("--all", action="store_true", help="Generate all 54 unmarked engineering tiles")
    ap.add_argument("--pilot", action="store_true", help="With --production, export the six approved pilot letters only")
    args = ap.parse_args()
    c = json.loads(args.config.read_text())
    validate_config(c)
    metadata = json.loads((ROOT/"data/letters_metadata.json").read_text())
    expected = {(s,ch) for s in ["print","script"] for ch in CHARS}
    if len(metadata) != 54 or {(r["style"],r["char"]) for r in metadata} != expected or len({r["tile_id"] for r in metadata}) != 54:
        raise ValueError("Metadata must contain exactly 54 unique tiles")
    if args.pilot and args.all:
        ap.error("--pilot and --all are mutually exclusive")
    selected = [(r["style"],r["char"]) for r in metadata] if (args.production and not args.pilot) or args.all else PILOT
    rows = {(r["style"],r["char"]):r for r in metadata}
    if args.production:
        for key in selected:
            require_approval(c, rows[key], scope="pilot" if args.pilot else "production")
    out = ROOT/"outputs"/("production_pilot" if args.production and args.pilot else "production" if args.production else "engineering_full" if args.all else "engineering")
    out.mkdir(parents=True, exist_ok=True)
    gs = {style:style_glyphs(c, style) for style in ["print", "script"]}
    reports, previews, objects = [], [], []
    marker_sets=[]
    marked_parts=[]
    plate_objects={"print":[],"script":[]}
    style_previews={"print":[],"script":[]}
    for style, char in selected:
        row = rows[style,char]
        body, bridges = outline_body(c, gs[style][char], row.get("bridge_paths_mm"))
        name = row["tile_id"]
        folder = out/style
        folder.mkdir(exist_ok=True)
        mesh = extrude(body, c["thickness"])
        if args.production:
            if bridges and not args.pilot and row.get("bridge_placement_status") != "approved":
                raise ValueError(f"Bridge positions require review against pen lifts: {name}")
            markers = marker_geometry(c, row, body, scope="pilot" if args.pilot else "production")
            marker_sets.append(markers)
            base, fill, single = split_layers(c, body, markers)
            marked_parts.append((name,base,fill))
            for suffix, part in [("body",base),("markers",fill),("single_color_engraved",single)]:
                part.export(folder/f"{name}_{suffix}.stl")
            write_3mf(folder/f"{name}.3mf", [("body",base,"#E7AEAA"),("marker_fill",fill,"#294A43")])
        else:
            mesh.export(folder/f"{name}_UNMARKED_ENGINEERING.stl")
        placement = mesh.copy()
        # Six sample pieces on a generic 201 x 140 mm plate, not interlocked.
        placement.apply_translation([8+(len(objects)%3)*(c["width"]+12), 5+(len(objects)//3)*(c["height"]+10),0])
        objects.append((name,placement,"#E7AEAA"))
        previews.append((f"{name} | {c['width']:g} x {c['height']:g} x {c['thickness']:g}",body,bridges))
        style_previews[style].append((name,body,bridges))
        plate_objects[style].append((name,mesh))
        aperture = tile(c).difference(body)
        font_path = ROOT/c["fonts"][style]
        reports.append({"tile_id":name, "char":char, "style":style,
                        "font_sha256":hashlib.sha256(font_path.read_bytes()).hexdigest(),
                        "watertight":bool(mesh.is_watertight), "winding_consistent":bool(mesh.is_winding_consistent),
                        "solid_components":len(mesh.split(only_watertight=False)), "volume_mm3":float(mesh.volume),
                        "bridge_count":len(bridges), "bridge_footprints_mm":[list(b.exterior.coords) for b in bridges],
                        "bounds_mm":mesh.bounds.tolist(),
                        "opening_probe_mm":c["minimum_opening_probe"],
                        "opening_probe_survives":not aperture.buffer(-c["minimum_opening_probe"]/2).is_empty,
                        "teaching_marks":args.production,"physical_test":"pending", "bambu_gui_test":"pending"})
    if not args.production and not args.all:
        write_3mf(out/"pilot_UNMARKED_ENGINEERING.3mf",objects)
        preview(c,previews,ROOT/"outputs/previews/pilot.png")
        # Manufacturing coupon: generic digit/arrow to test recess and AMS inlay.
        coupon = box(0,0,30,18).buffer(-2).buffer(2)
        num = glyph(ROOT/c["fonts"]["print"],"1",c.get("font_axes",{}).get("print"))
        x0,y0,x1,y1=num.bounds
        num=affinity.scale(num,5/(y1-y0),5/(y1-y0),origin=(0,0))
        num=affinity.translate(num,4-num.bounds[0],6-num.bounds[1])
        mark=unary_union([num,LineString([(12,9),(22,9)]).buffer(.5),Polygon([(25,9),(21,11),(21,7)])])
        base,fill,single=split_layers(c,coupon,mark)
        for name,part in [("body",base),("markers",fill),("single_color_engraved",single)]:
            part.export(out/f"manufacturing_coupon_{name}.stl")
        write_3mf(out/"manufacturing_coupon_dual_color.3mf",[("body",base,"#E7AEAA"),("marker_fill",fill,"#294A43")])
    if args.all and not args.production:
        plates=out/"plates";plates.mkdir(exist_ok=True)
        for style,entries in plate_objects.items():
            for start in range(0,len(entries),4):
                pieces=[]
                for i,(name,original) in enumerate(entries[start:start+4]):
                    part=original.copy()
                    part.apply_translation([8+(i%2)*(c["width"]+12),5+(i//2)*(c["height"]+10),0])
                    pieces.append((name,part,"#E7AEAA" if style=="print" else "#C8D8D0"))
                write_3mf(plates/f"{style}_plate_{start//4+1:02d}_UNMARKED.3mf",pieces)
            alphabet_preview(c,style,style_previews[style],ROOT/f"outputs/previews/alphabet_{style}.png")
    if args.production and args.pilot:
        preview(c,previews,ROOT/"outputs/previews/pilot_marked.png",marker_sets=marker_sets)
        plates=out/"plates";plates.mkdir(exist_ok=True)
        for start in range(0,len(marked_parts),4):
            pieces=[]
            for i,(name,base,fill) in enumerate(marked_parts[start:start+4]):
                shift=[8+(i%2)*(c["width"]+12),5+(i//2)*(c["height"]+10),0]
                for suffix,part,color in [("body",base,"#E7AEAA"),("markers",fill,"#294A43")]:
                    shifted=part.copy();shifted.apply_translation(shift)
                    pieces.append((name+"_"+suffix,shifted,color))
            write_3mf(plates/f"pilot_plate_{start//4+1:02d}_DUAL_COLOR.3mf",pieces)
    (out/"validation.json").write_text(json.dumps({"status":"engineering_only" if not args.production else "unprinted_production_candidate","config":c,"tiles":reports},ensure_ascii=False,indent=2)+"\n")
    print(f"Generated {len(reports)} tiles in {out}")


if __name__ == "__main__":
    main()
