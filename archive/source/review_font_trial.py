"""Focused JPG trial: Alef Zayin/Gimel and Dalet's leg marker. No mesh export."""
import copy
import hashlib
import json

from PIL import Image, ImageDraw, ImageFont
from shapely.ops import unary_union

import generate as g
from review_print_arrows import number_shape


def main():
    c=json.loads((g.ROOT/'config.json').read_text())
    alternate=copy.deepcopy(c)
    alternate['fonts']['print']='fonts/print/alef/Alef-Regular.ttf'
    alternate['font_axes']['print']={}
    glyphs={'Heebo':g.style_glyphs(c,'print'),'Alef':g.style_glyphs(alternate,'print')}
    specs=[
        {'char':'ז','font':'Alef','paths':[[[18,48],[34,48]],[[20.6,37.5],[23.2,23]]],
         'labels':[(16,51),(15,36)],'caption':'שני קווים; החץ השני מקביל לרגל'},
        {'char':'ג','font':'Alef','paths':[[[21,48],[34.5,48],[34.5,30],[38,21]],[[22,32],[14.5,22]]],
         'labels':[(16,51),(15,33)],'caption':'ניסיון בצורת האות של פונט Alef'},
        {'char':'ד','font':'Heebo','paths':[[[17,47],[35,47]],[[24.9,37.5],[24.9,23.5]]],
         'labels':[(11,49),(19,35)],'caption':'חץ 2 לצד הרגל, בתוך חלל האות'},
    ]
    visuals=[];records=[]
    for spec in specs:
        char,font=spec['char'],spec['font']
        config=c if font=='Heebo' else alternate
        body,_=g.outline_body(config,glyphs[font][char])
        safe=body.buffer(-c['marker_clearance'])
        arrows=[g.arrow_geometry(c,path) for path in spec['paths']]
        digits=[number_shape(c,i,x,y) for i,(x,y) in enumerate(spec['labels'],1)]
        for marker in [*arrows,*digits]:
            if not safe.contains(marker):
                raise ValueError(f'Insufficient marker clearance: {char}')
        occupied=[]
        for marker in [*arrows,*digits]:
            if any(marker.distance(other)<.35 for other in occupied):
                raise ValueError(f'Markers too close: {char}')
            occupied.append(marker)
        marks=unary_union([*arrows,*digits])
        font_path=g.ROOT/config['fonts']['print']
        records.append({**spec,'font_path':config['fonts']['print'],
                        'font_sha256':hashlib.sha256(font_path.read_bytes()).hexdigest(),
                        'visual_only':True,'minimum_material_clearance_mm':c['marker_clearance'],
                        'actual_material_clearance_mm':min(m.distance(body.boundary) for m in [*arrows,*digits])})
        visuals.append((spec,body,marks))
    # Human feedback only; no global font decision or stroke approval is changed.
    review=g.ROOT/'data/review';review.mkdir(exist_ok=True)
    (review/'font_trial_v5.json').write_text(json.dumps({
        'status':'visual_proposal_only','date':'2026-10-18',
        'user_feedback':'Try another font for Zayin and Gimel. Place Dalet leg marker relative to the actual descending stroke.',
        'zayin_correction':'The old marker leaned left as it descended, opposing the glyph. The trial marker leans right with the glyph.',
        'production_metadata_changed':False,'font_trial_only':['ז','ג'],'tiles':records,
    },ensure_ascii=False,indent=2)+'\n')
    ss=2;cw=520;header=135;rowheight=650;footer=90
    width,height=cw*3,header+rowheight+footer
    im=Image.new('RGB',(width*ss,height*ss),'#f7f5ef');d=ImageDraw.Draw(im)
    fp=str(g.ROOT/c['fonts']['print'])
    title=ImageFont.truetype(fp,36*ss);subtitle=ImageFont.truetype(fp,24*ss);letterfont=ImageFont.truetype(fp,32*ss)
    d.text(((width-34)*ss,22*ss),'ניסיון חדש — ז׳, ג׳ וד׳',font=title,anchor='rt',direction='rtl',fill='#283d42')
    d.text(((width-34)*ss,76*ss),'ז׳ וג׳ בפונט Alef; בד׳ החץ הועבר לצד הפנימי של הרגל',font=subtitle,anchor='rt',direction='rtl',fill='#687470')
    for i,(spec,body,marks) in enumerate(visuals):
        col=2-i;ox=col*cw+65;oy=header+8
        tf=lambda x,y:((ox+x*7.35)*ss,(oy+(c['height']-y)*7.35)*ss)
        g.paint(d,body,tf,'#e7aeaa');g.paint(d,marks,tf,'#294a43')
        center=(col*cw+cw/2)*ss
        d.text((center,(oy+482)*ss),spec['char']+'׳',font=letterfont,anchor='mt',direction='rtl',fill='#283d42')
        d.text((center,(oy+530)*ss),spec['font'],font=subtitle,anchor='mt',fill='#687470')
        d.text((center,(oy+577)*ss),spec['caption'],font=subtitle,anchor='mt',direction='rtl',fill='#283d42')
    d.text(((width-34)*ss,(height-56)*ss),'סקיצה חזותית למשוב',font=subtitle,anchor='rt',direction='rtl',fill='#687470')
    output=g.ROOT/'outputs/previews/print_font_trial_v5.jpg'
    im.resize((width,height),Image.Resampling.LANCZOS).save(output,quality=96,subsampling=0,dpi=(220,220))
    print('Created',output)
    print('All three tiles retain marker clearance and separate arrow labels.')


if __name__=='__main__':main()
