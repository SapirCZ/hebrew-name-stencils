"""JPG layout proposals only. Never approves strokes or exports printable meshes."""
import json
import math
import argparse
import copy
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import LineString, Point
from shapely.ops import substring, unary_union
from shapely import affinity

import generate as g

ORDER='אבגדהוזחטיכךלמםנןסעפףצץקרשת'


def contour_guide(shape, start, end, clockwise=True, offset=2.9):
    ring=max(g.polygons(shape.buffer(offset,quad_segs=32)),key=lambda p:p.area).exterior
    coords=list(ring.coords)
    if bool(ring.is_ccw)==clockwise:
        coords.reverse()
    line=LineString(coords)
    a,b=line.project(Point(start)),line.project(Point(end))
    if b>a:
        arc=substring(line,a,b)
    else:
        arc=LineString([*substring(line,a,line.length).coords,*list(substring(line,0,b).coords)[1:]])
    count=max(2,math.ceil(arc.length/.55)+1)
    return [list(arc.interpolate(i/(count-1),normalized=True).coords[0]) for i in range(count)]


def number_shape(c, number, x, y):
    shape=g.glyph(g.ROOT/c['fonts']['print'],str(number),c['font_axes']['print'])
    x0,y0,x1,y1=shape.bounds
    scale=c['marker_number_height']/(y1-y0)
    return affinity.translate(affinity.scale(shape,scale,scale,origin=(0,0)),x-x0*scale,y-y0*scale)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision',choices=['v3','v4'],default='v4')
    args=parser.parse_args()
    c=json.loads((g.ROOT/'config.json').read_text())
    rows={(r['style'],r['char']):r for r in json.loads((g.ROOT/'data/letters_metadata.json').read_text())}
    gs=g.style_glyphs(c,'print')
    def follow(ch,start,end,cw=True):return contour_guide(gs[ch],start,end,cw)
    paths={
      'א':[[[14,53],[18.7,47.5]],rows['print','א']['direction_arrows'][1]['path'],rows['print','א']['direction_arrows'][2]['path']],
      'ב':[a['path'] for a in rows['print','ב']['direction_arrows']],
      'ג':[[[22,47],[36,47],[36,38],[35,24]],[[22,32],[15,23]]],
      'ד':[[[17,47],[38.5,47],[38.5,23]]],
      'ה':[follow('ה',(17,47),(38,23)),[[13.5,32],[13.5,23]]],
      'ו':[[[32.5,42],[32.5,23]]],
      'ז':[[[21,47],[35,47],[31,23]]],
      'ח':[follow('ח',(18,47),(38,23)),[[13.5,39],[13.5,23]]],
      'ט':[follow('ט',(13.5,41),(38.5,41),False)],
      'י':[follow('י',(33,42),(33,33))],
      'כ':[follow('כ',(18,47),(18,16.3))],
      'ך':[follow('ך',(18,47),(37,14))],
      'ל':[follow('ל',(14,50),(20,17),False)],
      'מ':[follow('מ',(25,47),(39,23)),[[14.7,39],[12,23]]],
      'ם':[follow('ם',(18,47),(13.5,30))],
      'נ':[follow('נ',(23,47),(20,16.2))],
      'ן':[[[32.5,42],[32.5,14]]],
      'ס':[a['path'] for a in rows['print','ס']['direction_arrows']],
      'ע':[follow('ע',(38.5,41),(17,16)),follow('ע',(13.4,41),(22,27),False)],
      'פ':[follow('פ',(19,47),(17,16))],
      'ף':[follow('ף',(19,47),(38,14))],
      'צ':[follow('צ',(39,44),(31,30)),[[12.5,41.5],[24,27]]],
      'ץ':[follow('ץ',(39,44),(31,30)),[[10.5,41.5],[23.5,25],[23.5,15]]],
      'ק':[follow('ק',(18,47),(38,29)),[[13.5,31],[13.5,14]]],
      'ר':[follow('ר',(19,47),(37,23))],
      'ש':[follow('ש',(10,41),(20,16),False),[[26,51],[26,47]],follow('ש',(42,41),(36,19))],
      'ת':[follow('ת',(18,47),(40.3,23)),[[13.5,38],[13.5,25],[10.5,21]]]
    }
    if args.revision=='v4':
        # Human feedback from the chat and IMG_8530.HEIC. This is still a
        # visual proposal; production stroke metadata is deliberately untouched.
        paths.update({
            'א':[[[18.5,48.5],[26.5,38.5]],*paths['א'][1:]],
            'ד':[[[17,47],[35,47]],[[38.5,41],[38.5,23]]],
            'ו':[[[22.7,47],[32.5,47],[32.5,23]]],
            'ז':[[[21,47],[33,47]],[[35,40],[31,23]]],
        })
    visuals=[];reports=[]
    for ch in ORDER:
        row=rows['print',ch]
        body,bridges=g.outline_body(c,gs[ch],row.get('bridge_paths_mm'))
        safe=body.buffer(-c['marker_clearance'])
        arrows=[g.arrow_geometry(c,path) for path in paths[ch]]
        for i,arrow in enumerate(arrows,1):
            if not safe.contains(arrow):
                raise ValueError(f'Arrow intersects opening or leaves insufficient clearance: {ch} {i}')
        labels=[];placements=[]
        occupied=unary_union(arrows).buffer(.9)
        for i,path in enumerate(paths[ch],1):
            tail=np.array(path[0])
            candidates=[]
            for dx in [-6,-4,-2,0,2,4,6]:
                for dy in [-6,-4,-2,0,2,4,6]:
                    if abs(dx)+abs(dy)<4:continue
                    candidates.append((dx,dy))
            candidates.sort(key=lambda v:math.hypot(v[0]+2,v[1]-3))
            if ch=='א' and i==1:candidates=[(-4,3),*candidates]
            for dx,dy in candidates:
                x,y=tail+np.array([dx,dy])
                shape=number_shape(c,i,x,y)
                if safe.contains(shape) and not occupied.intersects(shape):
                    labels.append(shape);placements.append({'number':i,'x':float(x),'y':float(y)})
                    occupied=occupied.union(shape.buffer(.7))
                    break
            else:raise ValueError(f'No label room: {ch} {i}')
        visuals.append((ch,body,unary_union([*arrows,*labels])))
        reports.append({'char':ch,'style':'print','font':'Heebo Regular 400','visual_review_only':True,
                        'existing_pilot_definition':row.get('stroke_order_status')=='approved',
                        'candidate_paths_mm':paths[ch],'number_label_positions_mm':placements,
                        'minimum_material_clearance_mm':c['marker_clearance'],
                        'geometry_fits_tile':all(safe.contains(a) for a in arrows),
                        'note':'Candidate arrow placement only. Numbers identify visual paths; they do not approve stroke count or teaching order.'})
    # Draw large, antialiased tiles in Hebrew reading order, final forms adjacent.
    ss=2;cellw=390;cellh=475;header=160;footer=90;width=cellw*7;height=header+cellh*4+footer
    im=Image.new('RGB',(width*ss,height*ss),'#f7f5ef');draw=ImageDraw.Draw(im)
    fontpath=str(g.ROOT/c['fonts']['print'])
    title=ImageFont.truetype(fontpath,43*ss);sub=ImageFont.truetype(fontpath,26*ss);label=ImageFont.truetype(fontpath,28*ss)
    def text_right(x,y,text,font,fill='#283d42'):
        draw.text((x*ss,y*ss),text,font=font,anchor='rt',direction='rtl',fill=fill)
    text_right(width-45,25,'אותיות דפוס — סקיצת חצים למשוב',title)
    subtitle='מימין לשמאל, כולל סופיות • א׳, ד׳, ו׳ וז׳ עודכנו לפי המשוב' if args.revision=='v4' else 'מימין לשמאל, כולל סופיות • בא׳: חץ 1 הועבר מעל האות'
    text_right(width-45,85,subtitle,sub)
    for index,(ch,body,marks) in enumerate(visuals):
        col,row=6-index%7,index//7
        ox,oy=col*cellw+51,header+row*cellh+9
        tf=lambda x,y:((ox+x*5.6)*ss,(oy+(c['height']-y)*5.6)*ss)
        g.paint(draw,body,tf,'#e7aeaa');g.paint(draw,marks,tf,'#294a43')
        cx=(col*cellw+cellw/2)*ss
        draw.text((cx,(oy+369)*ss),f'{ch}  ·  {index+1:02d}',font=label,anchor='mt',direction='rtl',fill='#283d42')
        # This is a visual layout, not an educational approval of the proposed paths.
        draw.text((cx,(oy+412)*ss),'סקיצת מיקום',font=sub,anchor='mt',direction='rtl',fill='#687470')
    text_right(width-45,height-66,'טיוטה חזותית בלבד • מספרי החצים הם לצורך משוב ואינם אישור לסדר המשיכות',sub)
    im=im.resize((width,height),Image.Resampling.LANCZOS)
    out=g.ROOT/'outputs/previews';out.mkdir(exist_ok=True,parents=True)
    jpg=out/f'print_alphabet_arrow_review_{args.revision}.jpg'
    im.save(jpg,quality=95,subsampling=0,dpi=(220,220))
    # Save a separate readable close-up of Alef from the exact same layout.
    im.crop((6*cellw,header,7*cellw,header+cellh)).resize((780,950),Image.Resampling.LANCZOS).save(out/f'print_alef_arrow_review_{args.revision}.jpg',quality=96,subsampling=0)
    review=g.ROOT/'data/review';review.mkdir(exist_ok=True)
    (review/f'print_arrow_layout_{args.revision}.json').write_text(json.dumps({'status':'visual_proposal_only','order':ORDER,'font':c['fonts']['print'],
          'revision':args.revision,
          'user_reference':'IMG_8530.HEIC' if args.revision=='v4' else None,
          'user_feedback':{'א':'Arrow 1 follows the upper side of the diagonal, per the supplied drawing.',
                           'ד':'Two separate strokes: roof, then leg.',
                           'ו':'One continuous stroke, starting with the small top hook.',
                           'ז':'Two separate strokes: top, then lower leg.',
                           'ג':'Font shape questioned; provide comparison without changing the selected font.'} if args.revision=='v4' else {},
          'purpose':'User requested all PRINT letters for visual feedback. Do not manufacture or promote stroke approvals from this sheet.',
          'tiles':reports},ensure_ascii=False,indent=2)+'\n')
    if args.revision=='v4':
        focus_preview(c,visuals,gs,out)
    print('Created',jpg,'letters',len(visuals),'fits',sum(r['geometry_fits_tile'] for r in reports))


def focus_preview(c,visuals,gs,out):
    """Four requested corrections plus the same Gimel in two existing fonts."""
    bychar={ch:(body,marks) for ch,body,marks in visuals}
    alternative=copy.deepcopy(c)
    alternative['fonts']['print']='fonts/print/alef/Alef-Regular.ttf'
    alternative['font_axes']['print']={}
    alt_gimel=g.style_glyphs(alternative,'print')['ג']
    main_body,_=g.outline_body(c,gs['ג'])
    alt_body,_=g.outline_body(c,alt_gimel)
    panels=[
        ('א׳',*bychar['א'],'1 מלווה את האלכסון מעליו'),
        ('ד׳',*bychar['ד'],'1 — גג; 2 — רגל נפרדת'),
        ('ו׳',*bychar['ו'],'משיכה אחת, החל מהצ׳ופצ׳יק'),
        ('ז׳',*bychar['ז'],'1 — קו עליון; 2 — קו תחתון'),
        ('ג׳ — Heebo',main_body,None,'הפונט הנוכחי — ללא חצים'),
        ('ג׳ — Alef',alt_body,None,'פונט נוסף להשוואת הצורה'),
    ]
    ss=2;cw=510;ch=640;header=130;footer=90
    width,height=cw*3,header+ch*2+footer
    im=Image.new('RGB',(width*ss,height*ss),'#f7f5ef');d=ImageDraw.Draw(im)
    fontpath=str(g.ROOT/c['fonts']['print'])
    title=ImageFont.truetype(fontpath,37*ss)
    note=ImageFont.truetype(fontpath,24*ss)
    label=ImageFont.truetype(fontpath,31*ss)
    d.text(((width-35)*ss,22*ss),'תיקוני החצים לפי הסקיצה שלך',font=title,anchor='rt',direction='rtl',fill='#283d42')
    d.text(((width-35)*ss,76*ss),'א׳, ד׳, ו׳ וז׳ • ובתחתית: השוואת צורת ג׳ בשני פונטים',font=note,anchor='rt',direction='rtl',fill='#687470')
    for i,(name,body,marks,description) in enumerate(panels):
        col,row=2-i%3,i//3
        ox,oy=col*cw+65,header+row*ch+8
        tf=lambda x,y:((ox+x*7.2)*ss,(oy+(c['height']-y)*7.2)*ss)
        g.paint(d,body,tf,'#e7aeaa')
        if marks is not None:g.paint(d,marks,tf,'#294a43')
        center=(col*cw+cw/2)*ss
        d.text((center,(oy+475)*ss),name,font=label,anchor='mt',direction='rtl',fill='#283d42')
        d.text((center,(oy+528)*ss),description,font=note,anchor='mt',direction='rtl',fill='#283d42')
    d.text(((width-35)*ss,(height-55)*ss),'סקיצה חזותית למשוב',font=note,anchor='rt',direction='rtl',fill='#687470')
    im.resize((width,height),Image.Resampling.LANCZOS).save(out/'print_arrow_corrections_v4.jpg',quality=96,subsampling=0,dpi=(220,220))


if __name__=='__main__':main()
