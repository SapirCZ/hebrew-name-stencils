"""v8 review: continuous Mem stroke 1 and a single top-insert puzzle connector."""
import copy
import hashlib
import json
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

import generate as g
from card_shapes import shapes
from review_card_tiles import render
from review_print_arrows import number_shape


def mem_guide(c,source,original_start,body):
    # A smaller inward offset keeps the continuation readable in Mem's narrow
    # interior. Raise the final horizontal section to leave room for its head.
    guide=list(source.offset_curve(-3.0,quad_segs=24,join_style=1).coords)
    if len(guide)!=4:raise ValueError('Source Mem geometry changed; review its continuation')
    guide[0]=tuple(original_start)
    guide[-2]=(guide[-2][0],guide[-2][1]+1)
    guide[-1]=(guide[-1][0],guide[-1][1]+1)
    mark=g.arrow_geometry(c,guide).union(Point(guide[0]).buffer(.78,quad_segs=20))
    if not body.buffer(-c['marker_clearance']).contains(mark):
        raise ValueError('Mem continuation reaches the aperture')
    return guide


def marks(c,row):
    parts=[]
    for arrow in row['arrows']:
        guide=arrow['guide_path_mm']
        parts.extend([g.arrow_geometry(c,guide),Point(guide[0]).buffer(.78,quad_segs=20)])
    parts.extend(number_shape(c,v['number'],v['x'],v['y']) for v in row['number_labels'])
    return unary_union(parts)


def font(c,size):return ImageFont.truetype(str(g.ROOT/c['fonts']['print']),size)


def mem_preview(c,body,mark,path):
    ss=2;w,h=780,1000
    im=Image.new('RGB',(w*ss,h*ss),'#f7f5ef');d=ImageDraw.Draw(im)
    d.text(((w-30)*ss,22*ss),'מ׳ — תנועה רציפה בשלב 1',font=font(c,35*ss),anchor='rt',direction='rtl',fill='#283d42')
    d.text(((w-30)*ss,78*ss),'עולים באלכסון, יורדים מימין ופונים שמאלה',font=font(c,24*ss),anchor='rt',direction='rtl',fill='#687470')
    tf=lambda x,y:((120+x*10.5)*ss,(154+(c['height']-y)*10.5)*ss)
    g.paint(d,body,tf,'#e7aeaa');g.paint(d,mark,tf,'#294a43')
    d.text(((w/2)*ss,852*ss),'חיבור פאזל יחיד בכל צד',font=font(c,28*ss),anchor='mt',direction='rtl',fill='#283d42')
    d.text(((w-30)*ss,939*ss),'הפתח בלבן; הסימונים על החומר המלא',font=font(c,24*ss),anchor='rt',direction='rtl',fill='#687470')
    im.resize((w,h),Image.Resampling.LANCZOS).save(path,quality=96,subsampling=0,dpi=(220,220))


def puzzle_preview(c,shape,path):
    ss=2;w,h=1560,900
    im=Image.new('RGB',(w*ss,h*ss),'#f7f5ef');d=ImageDraw.Draw(im)
    def rtl(x,y,text,size=25,color='#283d42'):
        d.text((x*ss,y*ss),text,font=font(c,size*ss),anchor='rt',direction='rtl',fill=color)
    rtl(w-30,25,'חיבור פאזל יחיד — הרכבה מלמעלה',37)
    rtl(w-30,82,'ראש רחב וצוואר צר, עם שקע תואם • התאמת ההידוק תיבדק בהדפסת ניסיון',24,'#687470')
    rtl(735,160,'מצב מחובר — מבט מלמעלה',28)
    rtl(1520,160,'הנחת הלשונית לתוך השקע',28)
    left=shape;right=affinity.translate(shape,xoff=20)
    tf=lambda x,y:((180+x*11.5)*ss,(260+(24-y)*11.5)*ss)
    g.paint(d,left,tf,'#a4c3b7');g.paint(d,right,tf,'#e7aeaa')
    rtl(735,603,'ראש: 8.4 מ״מ • צוואר: 4.2 מ״מ',24)
    rtl(735,650,'הראש הרחב חוסם משיכה ישרה לצדדים',24)
    # Actual extruded coupon meshes show the raised half before it is lowered.
    a=g.extrude(shape,c['thickness'])
    b=a.copy();b.apply_translation([20,0,14])
    tris=[]
    for mesh,base in [(a,np.array([164,195,183])),(b,np.array([231,174,170]))]:
        for face,normal in zip(mesh.triangles,mesh.face_normals):
            p=np.array([[(x-y)*.8660254,(x+y)*.5-z] for x,y,z in face])
            brightness=1 if normal[2]>.5 else .77 if normal[2]<-.5 else .83+.08*normal[0]-.04*normal[1]
            color=tuple(np.clip(base*brightness,0,255).astype(int))
            tris.append((float(face.sum(axis=1).mean()),p,color))
    allpoints=np.concatenate([p for _,p,_ in tris]);lo=allpoints.min(axis=0);hi=allpoints.max(axis=0)
    scale=min(650/(hi[0]-lo[0]),340/(hi[1]-lo[1]))
    origin=np.array([845,240])-lo*scale
    project=lambda p:tuple((origin+np.asarray(p)*scale)*ss)
    for _,triangle,color in sorted(tris,key=lambda row:row[0]):d.polygon([project(v) for v in triangle],fill=color)
    # The arrow lies in the free vertical gap directly above the socket.
    point=lambda z:project([(15.9-12)*.8660254,(15.9+12)*.5-z])
    start,end=np.array(point(12.2)),np.array(point(4.7))
    d.line([tuple(start),tuple(end)],fill='#294a43',width=5*ss)
    v=(end-start)/np.linalg.norm(end-start);n=np.array([-v[1],v[0]])
    d.polygon([tuple(end),tuple(end-v*17*ss+n*8*ss),tuple(end-v*17*ss-n*8*ss)],fill='#294a43')
    rtl(1520,603,'החיבור נעשה בהורדה מלמעלה',24)
    rtl(1520,650,'טולרנס התחלתי לניסוי: 0.20 מ״מ',24)
    rtl(w-30,811,'סקיצת מנגנון • החוזק ונוחות החיבור ממתינים לבדיקה פיזית',24,'#687470')
    im.resize((w,h),Image.Resampling.LANCZOS).save(path,quality=96,subsampling=0,dpi=(220,220))


def connector_trial(c):
    out=g.ROOT/'outputs/connector_v8';out.mkdir(exist_ok=True)
    # Compact printable pieces use exactly the full-size tile's connector.
    coupon=copy.deepcopy(c);coupon.update(width=20.0,height=24.0,corner_radius=2.0)
    shape=g.tile(coupon);mesh=g.extrude(shape,c['thickness'])
    mesh.export(out/'puzzle_test_piece.stl')
    objects=[]
    for i,x in enumerate([10,48]):
        piece=mesh.copy();piece.apply_translation([x,5,0])
        objects.append((f'test_piece_{i+1}',piece,'#E7AEAA' if i==0 else '#A4C3B7'))
    g.write_3mf(out/'puzzle_test_pair.3mf',objects)
    mate=affinity.translate(shape,xoff=20)
    overlap=shape.intersection(mate).area
    separation={str(dx):shape.intersection(affinity.translate(mate,xoff=dx)).area for dx in [0,.1,.5,1,2]}
    if overlap>1e-8 or separation['1']<.1:raise ValueError('Puzzle profile lacks a collision-free seat or sideways retention')
    details={'connector_count_per_side':1,'head_diameter_mm':2*c['connector_radius'],
             'neck_width_mm':c['connector_neck'],'projection_mm':c['connector_projection'],
             'clearance_mm':c['connector_clearance'],'tile_thickness_mm':c['thickness'],
             'assembly':'align XY and lower the part from above; no Z snap latch',
             'aligned_material_overlap_mm2':overlap,'side_pull_collision_area_mm2_by_displacement_mm':separation,
             'watertight':bool(mesh.is_watertight),'print_arrangement_bounds_mm':[
                 np.concatenate([part.vertices for _,part,_ in objects]).min(axis=0).tolist(),
                 np.concatenate([part.vertices for _,part,_ in objects]).max(axis=0).tolist()],
             'physical_fit':'pending','printer_profile':'generic 3MF; no G-code'}
    (out/'validation.json').write_text(json.dumps(details,ensure_ascii=False,indent=2)+'\n')
    puzzle_preview(c,shape,g.ROOT/'outputs/previews/puzzle_connector_v8.jpg')
    return details


def main():
    baseline=json.loads((g.ROOT/'data/review/card_stencil_layout_v7.json').read_text())
    c=copy.deepcopy(baseline['print_config'])
    c.update(connector_y_fractions=[.5],connector_radius=4.2,connector_neck=4.2,
             connector_projection=8.3,connector_clearance=.2)
    g.validate_config(c)
    (g.ROOT/'config.card_tiles.json').write_text(json.dumps(c,ensure_ascii=False,indent=2)+'\n')
    reference=json.loads((g.ROOT/'data/review/user_print_stroke_cards_v6.json').read_text())
    glyphs,source_paths,_=shapes(c,reference)
    review=copy.deepcopy(baseline);review.update(revision='v8',print_config=c,
       design_changes=['Mem stroke 1 is a continuous rising/downward/left-turn guide.',
                       'One central jigsaw connector per side, assembled from above.'])
    visuals=[];qa=[]
    for row in review['tiles']:
        char=row['char'];body=unary_union([g.tile(c).difference(glyphs[char]),*[Polygon(p) for p in row['bridges_mm']]])
        if char=='מ':
            arrow=row['arrows'][0]
            arrow['guide_path_mm']=mem_guide(c,source_paths[char][0],arrow['guide_path_mm'][0],body)
            arrow.update(guide_scope='continuous rise, right downstroke and left baseline',
                         guide_offset_mm=None,guide_variable_offset_mm=[3.0,4.0],
                         guide_length_fraction=LineString(arrow['guide_path_mm']).length/source_paths[char][0].length)
        mark=marks(c,row);safe=body.buffer(-c['marker_clearance'])
        if not safe.contains(mark):raise ValueError(f'Marks reach the new connector or aperture: {char}')
        solid=g.extrude(body,c['thickness']);inlay=g.extrude(mark,c['marker_depth'],c['thickness']-c['marker_depth'])
        if len(solid.split())!=1 or not inlay.is_watertight:raise ValueError(f'Invalid solid: {char}')
        visuals.append((char,body,mark))
        qa.append({'char':char,'body_watertight':True,'marker_watertight':True,
                   'minimum_marker_clearance_mm':mark.distance(body.boundary),
                   'marker_aperture_overlap_mm2':mark.intersection(g.tile(c).difference(body)).area})
        if char=='מ':mem_preview(c,body,mark,g.ROOT/'outputs/previews/print_mem_continuous_v8.jpg')
    # The only change in the instructional layout is the requested Mem line.
    for old,new in zip(baseline['tiles'],review['tiles']):
        if old['char']!='מ' and old!=new:raise ValueError('Unrequested marker revision')
    (g.ROOT/'data/review/card_stencil_layout_v8.json').write_text(json.dumps(review,ensure_ascii=False,indent=2)+'\n')
    render(c,visuals,g.ROOT/'outputs/previews/print_card_stencil_review_v8.jpg')
    profile=connector_trial(c)
    (g.ROOT/'outputs/card_review_v8_qa.json').write_text(json.dumps({'status':'visual and geometric review; unprinted',
             'letters':27,'arrows':44,'instructional_layout_changes':['מ stroke 1 continuation'],
             'other_26_marker_layouts_unchanged':True,'all_marks_on_solid_material':True,
             'connector':profile,'tiles':qa},ensure_ascii=False,indent=2)+'\n')
    active_path=g.ROOT/'data/active_design.json';active=json.loads(active_path.read_text())
    active['print'].update(marker_positions_status='visual review v8',review_generator='src/refine_card_design.py',
          review_metadata='data/review/card_stencil_layout_v8.json',config_path='config.card_tiles.json',
          connectors='one central puzzle knob/socket per side; top-insert assembly')
    active['print']['current_print_files']='Full letter STL/3MF still refer to the earlier font-based pilot. New v8 connector coupons are available for physical fit trials.'
    active_path.write_text(json.dumps(active,ensure_ascii=False,indent=2)+'\n')
    print('Saved v8: 27 card-derived tiles, continuous Mem guide, central puzzle connectors, fit coupons.')
    print('Side pull collision areas:',profile['side_pull_collision_area_mm2_by_displacement_mm'])


if __name__=='__main__':main()
