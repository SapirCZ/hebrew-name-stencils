"""Stencil review from the user-approved PDF shapes; all marks stay on solid material."""
import json
import math
import hashlib
import copy

import numpy as np
from PIL import Image,ImageDraw,ImageFont
from shapely.geometry import LineString,Point
from shapely.ops import substring,unary_union

import generate as g
from card_shapes import shapes
from review_print_arrows import number_shape,ORDER


def lines(geom):
    if isinstance(geom,LineString):return [geom] if geom.length>3 else []
    return [line for part in getattr(geom,'geoms',[]) for line in lines(part)]


PREFERRED={('א',1):1,('א',2):1,('א',3):-1,('ב',1):1,('ב',2):-1,
           ('ג',1):1,('ג',2):-1,('ד',1):1,('ד',2):-1,('ז',1):1,('ז',2):-1,
           ('ה',1):1,('ה',2):-1,('ח',1):1,('ח',2):-1,('ט',1):-1,
           ('ס',1):1,('ם',1):1,('ש',1):1,('ש',2):1,('פ',2):1,('ף',2):1,
           ('ק',2):-1,('ת',2):-1,('מ',1):-1}


def guide_candidate(c,source,body,occupied,char,index):
    safe=body.buffer(-c['marker_clearance'])
    center_safe=safe.buffer(-.82)
    if occupied:center_safe=center_safe.difference(unary_union(occupied).buffer(1.1))
    preferred=PREFERRED.get((char,index),1)
    candidates=[]
    for sign in [preferred,-preferred]:
        for distance in [3.95,4.3,4.7,5.1,5.5]:
            offset=source.offset_curve(sign*distance,quad_segs=24,join_style=1)
            for full in lines(offset):
                # Keep a gap between the arrowhead and the starting dot of loops.
                if full.is_ring:full=substring(full,0,full.length-4)
                for piece in lines(full.intersection(center_safe)):
                    if full.project(Point(piece.coords[0]))>full.project(Point(piece.coords[-1])):
                        piece=LineString(list(piece.coords)[::-1])
                    for trim in [0,.8,1.6,2.4,3.2,4.5,6]:
                        if piece.length-trim<4:continue
                        line=substring(piece,0,piece.length-trim)
                        path=list(line.coords)
                        if len(path)>100:
                            path=[line.interpolate(i/99,normalized=True).coords[0] for i in range(100)]
                        try:arrow=g.arrow_geometry(c,path)
                        except ValueError:continue
                        dot=Point(path[0]).buffer(.78,quad_segs=20)
                        mark=arrow.union(dot)
                        if not safe.contains(mark):continue
                        if occupied and mark.intersects(unary_union(occupied).buffer(.55)):continue
                        # Prefer a long, contiguous parallel guide and the side
                        # selected to avoid the source's branch intersections.
                        source_position=source.project(Point(path[0]))
                        end_position=source.project(Point(path[-1]))
                        covered=end_position-source_position
                        if source.is_ring and covered<0:covered+=source.length
                        score=max(0,covered)-(distance-3.95)*2+(2 if sign==preferred else 0)
                        candidates.append((score,path,mark,sign,distance,line.length/source.length,source_position))
    if not candidates:raise ValueError(f'No safe guide: {char} stroke {index}')
    # Starting direction matters more than drawing a long arrow after skipping
    # the first part of a stroke, especially for Mem and Tsadi.
    near_start=[row for row in candidates if row[-1]<=3.5]
    chosen=max(near_start or candidates,key=lambda x:x[0])
    return chosen[:-1]


def label_candidate(c,index,path,safe,occupied,char):
    tail=np.array(path[0]);candidates=[]
    for dx in range(-9,10,2):
        for dy in range(-9,10,2):
            if abs(dx)+abs(dy)<4:continue
            candidates.append((dx,dy))
    candidates.sort(key=lambda v:math.hypot(v[0]+3,v[1]-3))
    if char=='ד' and index==2:
        candidates=[(-6,-5),(-6,-7),(-5,-5),*candidates]
    full=unary_union(occupied)
    for dx,dy in candidates:
        x,y=tail+np.array([dx,dy]);digit=number_shape(c,index,x,y)
        if safe.contains(digit) and not digit.intersects(full.buffer(.7)):
            return digit,{'number':index,'x':float(x),'y':float(y)}
    raise ValueError('No safe label')


def main():
    c=json.loads((g.ROOT/'config.json').read_text())
    ref=json.loads((g.ROOT/'data/review/user_print_stroke_cards_v6.json').read_text())
    source_snapshot=g.ROOT/'docs/pedagogy/user_reference/hebrew-print-stroke-cards.pdf'
    source_bytes=source_snapshot.read_bytes() if source_snapshot.exists() else open(ref['source_pdf'],'rb').read()
    if hashlib.sha256(source_bytes).hexdigest()!=ref['source_sha256']:
        raise ValueError('User PDF changed; re-import before reviewing')
    glyphs,source_paths,transforms=shapes(c,ref)
    by={r['char']:r for r in ref['cards']}
    visuals=[];records=[]
    for ch in ORDER:
        raw=glyphs[ch]
        bridge_paths=None
        if ch in 'סם':
            # Across the closure corner, where tracing begins and ends.
            first=source_paths[ch][0];start=np.array(first.coords[0])
            bridge_paths=[[(start+[-2.4,2.4]).tolist(),(start+[3.4,-3.4]).tolist()]]
        body,bridges=g.outline_body(c,raw,bridge_paths)
        occupied=[];arrow_rows=[]
        for i,path in enumerate(source_paths[ch],1):
            # Mem's inward offset would make a tight triangular loop. Show its
            # initial rising movement clearly, while the aperture carries the
            # complete continuous source stroke.
            guide_source=LineString(list(path.coords)[:2]) if ch=='מ' and i==1 else path
            score,guide,mark,side,distance,coverage=guide_candidate(c,guide_source,body,occupied,ch,i)
            coverage=LineString(guide).length/path.length
            occupied.append(mark)
            arrow_rows.append({'number':i,'source_path_mm':list(path.coords),'source_start_mm':path.coords[0],
                               'guide_path_mm':guide,'guide_offset_side':side,'guide_offset_mm':distance,
                               'guide_length_fraction':coverage,
                               'guide_scope':'initial rising segment' if ch=='מ' and i==1 else 'continuous parallel segment'})
        label_rows=[]
        for i,row in enumerate(arrow_rows,1):
            digit,place=label_candidate(c,i,row['guide_path_mm'],body.buffer(-c['marker_clearance']),occupied,ch)
            occupied.append(digit);label_rows.append(place)
        marks=unary_union(occupied)
        if not body.buffer(-c['marker_clearance']).contains(marks):raise ValueError(f'Marker inside aperture: {ch}')
        visuals.append((ch,body,marks))
        records.append({'char':ch,'style':'print','shape_source':'user_pdf_centerline_strokes',
                        'source_page':by[ch]['source_page'],'stroke_count':by[ch]['stroke_count'],
                        'reference_shape_and_order_status':'approved by user 2026-10-18',
                        'approval_evidence':'גם לצורת האות וגם לסדר המשיכות',
                        'marker_placement_status':'draft review; not physical print approval',
                        'coordinate_transform':transforms[ch],'arrows':arrow_rows,'number_labels':label_rows,
                        'bridges_mm':[list(b.exterior.coords) for b in bridges],
                        'all_marks_on_solid':True,'minimum_material_clearance_mm':c['marker_clearance']})
        print(ch,'guides',len(arrow_rows),'length fractions',[round(a['guide_length_fraction'],2) for a in arrow_rows],flush=True)
    out=g.ROOT/'data/review/card_stencil_layout_v7.json'
    out.write_text(json.dumps({'status':'stencil visual review','date':'2026-10-18',
               'source_pdf':ref['source_pdf'],'source_sha256':ref['source_sha256'],
               'shape_and_order_approved_by_user':True,'marker_positions_pending_visual_review':True,
               'letter_shapes_are_pdf_vectors_not_fonts':True,'print_config':c,'tiles':records},ensure_ascii=False,indent=2)+'\n')
    render(c,visuals,g.ROOT/'outputs/previews/print_card_stencil_review_v7.jpg')
    render(c,[next(v for v in visuals if v[0]==ch) for ch in 'אדוזג'],g.ROOT/'outputs/previews/print_card_stencil_focus_v7.jpg',focus=True)
    print('Saved',out,flush=True)


def render(c,items,path,focus=False):
    cols=3 if focus else 7;rows=math.ceil(len(items)/cols)
    cw=510 if focus else 390;ch=600 if focus else 460;scale=7.2 if focus else 5.5
    ss=2;header=140;footer=85;width=cols*cw;height=header+rows*ch+footer
    im=Image.new('RGB',(width*ss,height*ss),'#f7f5ef');d=ImageDraw.Draw(im)
    fp=str(g.ROOT/c['fonts']['print'])
    title=ImageFont.truetype(fp,38*ss);sub=ImageFont.truetype(fp,24*ss);label=ImageFont.truetype(fp,28*ss)
    d.text(((width-35)*ss,23*ss),'שבלונות לפי הכרטיסיות — סקיצת מיקום החצים',font=title,anchor='rt',direction='rtl',fill='#283d42')
    d.text(((width-35)*ss,79*ss),'הפתח בלבן; החצים, נקודות ההתחלה והמספרים על החומר המלא',font=sub,anchor='rt',direction='rtl',fill='#687470')
    for i,(char,body,marks) in enumerate(items):
        col,row=cols-1-i%cols,i//cols;ox=col*cw+(65 if focus else 50);oy=header+row*ch+8
        tf=lambda x,y:((ox+x*scale)*ss,(oy+(c['height']-y)*scale)*ss)
        g.paint(d,body,tf,'#e7aeaa');g.paint(d,marks,tf,'#294a43')
        d.text(((col*cw+cw/2)*ss,(oy+c['height']*scale+26)*ss),char+'׳',font=label,anchor='mt',direction='rtl',fill='#283d42')
    d.text(((width-35)*ss,(height-58)*ss),'צורת האות וסדר המשיכות לפי הקובץ שאישרת • מיקום הסימונים לבדיקה',font=sub,anchor='rt',direction='rtl',fill='#687470')
    im.resize((width,height),Image.Resampling.LANCZOS).save(path,quality=96,subsampling=0,dpi=(220,220))


if __name__=='__main__':main()
