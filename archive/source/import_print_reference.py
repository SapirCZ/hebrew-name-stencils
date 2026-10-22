"""Read the user-supplied stroke-card PDF into a reference JSON and overview JPG.

Run with the bundled Python runtime (pypdf and Pillow). This imports instructional
vectors, not font outlines. It never changes production approvals or exports meshes.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader
from pypdf.generic import ContentStream

ROOT=Path(__file__).resolve().parents[1]
PDF_ORDER='אבגדהוזחטיכלמנסעפצקרשתךםןףץ'
DISPLAY_ORDER='אבגדהוזחטיכךלמםנןסעפףצץקרשת'
EXPECTED_COUNTS=[3,2,2,2,2,1,2,2,1,1,1,1,2,1,1,2,2,2,2,1,2,2,1,1,1,2,2]


def points_for_path(commands):
    points=[];start=None
    for item in commands:
        op,v=item['op'],item['values']
        if op=='m':
            start=tuple(v);points=[start]
        elif op=='l':points.append(tuple(v))
        elif op=='c':
            a=points[-1];b,c,d=[v[i:i+2] for i in [0,2,4]]
            for k in range(1,31):
                t=k/30;u=1-t
                points.append(tuple(u**3*a[j]+3*u*u*t*b[j]+3*u*t*t*c[j]+t**3*d[j] for j in [0,1]))
        elif op=='h':points.append(start)
        else:raise ValueError(f'Unsupported diagram operator: {op}')
    return points


def read_cards(source):
    raw=source.read_bytes();reader=PdfReader(source)
    if len(reader.pages)!=27:raise ValueError('Expected one card for each of 27 print letters')
    cards=[]
    for index,(page,char,expected) in enumerate(zip(reader.pages,PDF_ORDER,EXPECTED_COUNTS),1):
        lines=[line.strip() for line in page.extract_text().splitlines() if line.strip()]
        width=0;path=[];color=None;strokes=[];labels=[];font_size=0;text_matrix=None;diagram_matrix=None
        for operands,op in ContentStream(page.get_contents(),reader).operations:
            if op==b'w':width=float(operands[0])
            elif op==b'RG':color=[float(x) for x in operands]
            elif op==b'cm' and len(operands)==6 and float(operands[3])==-1:
                diagram_matrix=[float(v) for v in operands]
            elif op==b'Tf':font_size=float(operands[1])
            elif op==b'Tm':text_matrix=[float(x) for x in operands]
            elif op==b'Tj' and font_size==14:
                if diagram_matrix is None or text_matrix is None:raise ValueError('Missing number transform')
                labels.append({'number':int(str(operands[0])),
                               'x':text_matrix[4]-diagram_matrix[4],
                               'y':diagram_matrix[5]-text_matrix[5],
                               'source_font_size':font_size})
            elif op==b'n':path=[]
            elif op in [b'm',b'l',b'c',b'h']:
                path.append({'op':op.decode(),'values':[float(x) for x in operands]})
            elif op in [b'S',b's']:
                if abs(width-3.7)<1e-4:
                    strokes.append({'number':len(strokes)+1,'rgb':color.copy(),'path':path.copy()})
                path=[]
            elif op in [b'f',b'f*']:
                # The three-segment colored filled triangle following a stroke.
                if strokes and len(path)==5 and [p['op'] for p in path]==['m','l','l','l','h']:
                    strokes[-1]['arrow_head']=path.copy()
                elif strokes and len(path)==4 and [p['op'] for p in path]==['m','l','l','h']:
                    strokes[-1]['arrow_head']=path.copy()
                path=[]
        if len(strokes)!=expected or sorted(label['number'] for label in labels)!=list(range(1,expected+1)):
            raise ValueError(f'Card {index}: count/numbering mismatch')
        for stroke in strokes:
            n=stroke['number'];where=max(i for i,line in enumerate(lines) if line==str(n))
            stroke['description_he']=lines[where+1]
            points=points_for_path(stroke['path'])
            stroke['start']=points[0];stroke['end']=points[-1]
            if 'arrow_head' not in stroke:raise ValueError(f'Missing arrow head: {char} {n}')
            if points[0]!=points[-1] and any(abs(a-b)>.01 for a,b in zip(points[-1],stroke['arrow_head'][0]['values'])):
                raise ValueError(f'Arrow tip does not match stroke end: {char} {n}')
        cards.append({'char':char,'name_he':lines[1],'source_page':index,'stroke_count':expected,
                      'status':'user_supplied_reference; not production approval',
                      'coordinate_space':'source diagram units, x right, y down; not millimeters',
                      'outline_source':'explicit diagram paths in PDF, not a glyph from its text font',
                      'strokes':strokes,'number_positions':labels,'source_text_he':'\n'.join(lines)})
    previous=json.loads((ROOT/'data/review/print_arrow_layout_v4.json').read_text())
    old={row['char']:row for row in previous['tiles']}
    differences=[{'char':r['char'],'source_page':r['source_page'],'old_visual_paths':len(old[r['char']]['candidate_paths_mm']),
                  'pdf_strokes':r['stroke_count']} for r in cards if len(old[r['char']]['candidate_paths_mm'])!=r['stroke_count']]
    result={'source_pdf':str(source.resolve()),'source_sha256':hashlib.sha256(raw).hexdigest(),
            'source_role':'user-supplied writing diagram reference',
            'pdf_metadata':{str(k):str(v) for k,v in (reader.metadata or {}).items()},
            'pages':27,'date_imported':'2026-10-18','production_metadata_changed':False,
            'count_differences_from_v4':differences,
            'direction_review_notes':[
                {'char':'ז','source_page':7,'note':'Short roof descends diagonally to the right; leg is vertical and begins in the middle of the roof.'},
                {'char':'ד','source_page':4,'note':'Separate roof and leg; leg begins before the right end of the roof.'},
                {'char':'מ','source_page':13,'note':'First stroke begins at lower left and rises; previous visual draft began at the roof.'},
                {'char':'צ','source_page':18,'note':'Long left diagonal and baseline come first; upper right branch comes second.'},
                {'char':'ץ','source_page':27,'note':'Long left diagonal comes first; upper right branch comes second.'},
            ],'cards':cards}
    return result


def draw_overview(data):
    ss=2;cw=360;ch=430;header=145;footer=100
    width,height=cw*7,header+ch*4+footer
    im=Image.new('RGB',(width*ss,height*ss),'#f7f5ef');d=ImageDraw.Draw(im)
    font_path=str(ROOT/'fonts/print/heebo/Heebo[wght].ttf')
    title=ImageFont.truetype(font_path,40*ss);sub=ImageFont.truetype(font_path,24*ss)
    label_font=ImageFont.truetype(font_path,24*ss)
    d.text(((width-35)*ss,22*ss),'מפת משיכות לפי הכרטיסיות שצירפת',font=title,anchor='rt',direction='rtl',fill='#19354b')
    d.text(((width-35)*ss,83*ss),'27 אותיות דפוס • נקודה = התחלה • חץ אחד = משיכה רצופה אחת',font=sub,anchor='rt',direction='rtl',fill='#547082')
    bychar={r['char']:r for r in data['cards']}
    for i,char in enumerate(DISPLAY_ORDER):
        card=bychar[char];col,row=6-i%7,i//7
        left,top=col*cw+7,header+row*ch+6
        d.rounded_rectangle((left*ss,top*ss,(left+cw-14)*ss,(top+ch-14)*ss),radius=14*ss,fill='white')
        scale=1.02*ss;ox=(col*cw+cw/2)*ss-150*scale;oy=(header+row*ch+22)*ss
        tf=lambda p:(ox+p[0]*scale,oy+p[1]*scale)
        for stroke in card['strokes']:
            points=[tf(p) for p in points_for_path(stroke['path'])]
            d.line(points,fill='#e1eaf0',width=round(20*scale),joint='curve')
            for point in [points[0],points[-1]]:
                rad=10*scale;d.ellipse((point[0]-rad,point[1]-rad,point[0]+rad,point[1]+rad),fill='#e1eaf0')
        for stroke in card['strokes']:
            rgb=tuple(round(v*255) for v in stroke['rgb'])
            points=[tf(p) for p in points_for_path(stroke['path'])]
            d.line(points,fill=rgb,width=round(3.7*scale),joint='curve')
            head=[tf(item['values']) for item in stroke['arrow_head'] if item['op'] in ['m','l']]
            d.polygon(head,fill=rgb)
        for stroke in card['strokes']:
            x,y=tf(stroke['start']);rad=4*scale
            d.ellipse((x-rad,y-rad,x+rad,y+rad),fill='#19354b')
        for number in card['number_positions']:
            rgb=tuple(round(v*255) for v in card['strokes'][number['number']-1]['rgb'])
            x,y=tf((number['x'],number['y']))
            font=ImageFont.truetype(font_path,round(16*scale))
            d.text((x,y-16*scale),str(number['number']),font=font,fill=rgb)
        label=f"{char}  ·  עמוד {card['source_page']}"
        d.text(((col*cw+cw/2)*ss,(header+row*ch+371)*ss),label,font=label_font,anchor='mt',direction='rtl',fill='#19354b')
    d.text(((width-35)*ss,(height-75)*ss),'מפת ייחוס לסדר התנועה • התאמה לפונט ולמיקום הסימונים על האריח בשלב הבא',font=sub,anchor='rt',direction='rtl',fill='#547082')
    result=ROOT/'outputs/previews/print_stroke_cards_reference_v6.jpg'
    im.resize((width,height),Image.Resampling.LANCZOS).save(result,quality=96,subsampling=0,dpi=(220,220))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf',type=Path)
    args=parser.parse_args()
    result=read_cards(args.pdf)
    directory=ROOT/'data/review';directory.mkdir(exist_ok=True)
    destination=directory/'user_print_stroke_cards_v6.json'
    destination.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    image=draw_overview(result)
    print(json.dumps({'reference_json':str(destination),'overview_jpg':str(image),
                      'letters':len(result['cards']),'strokes':sum(c['stroke_count'] for c in result['cards']),
                      'count_changes':result['count_differences_from_v4']},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
