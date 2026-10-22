"""Exact user-card centerlines and round stroke silhouettes, independent of fonts."""
import json
from pathlib import Path

import numpy as np
from shapely.geometry import LineString
from shapely.ops import unary_union

import generate as g


def flatten(commands):
    points=[];start=None
    for item in commands:
        op,v=item['op'],item['values']
        if op=='m':start=tuple(v);points=[start]
        elif op=='l':points.append(tuple(v))
        elif op=='c':
            a=np.asarray(points[-1]);b,c,d=np.asarray(v).reshape(3,2)
            for t in np.linspace(0,1,41)[1:]:
                points.append(tuple((1-t)**3*a+3*(1-t)**2*t*b+3*(1-t)*t*t*c+t**3*d))
        elif op=='h':points.append(start)
        else:raise ValueError(f'Unsupported source command: {op}')
    return points


def shapes(config,reference):
    # The source PDF's light letter strokes have width 20 source units. Retain
    # their width, round caps and round joins with one common isotropic scale.
    raw={card['char']:[LineString(flatten(s['path'])) for s in card['strokes']] for card in reference['cards']}
    widths={ch:unary_union([line.buffer(10,quad_segs=24) for line in paths]) for ch,paths in raw.items()}
    lo=min(p.bounds[1] for p in widths.values());hi=max(p.bounds[3] for p in widths.values())
    scale=min(config['glyph_window_height']/(hi-lo),
              config['glyph_window_width']/max(p.bounds[2]-p.bounds[0] for p in widths.values()))
    letters={};paths={};transforms={}
    for ch,source in widths.items():
        cx=(source.bounds[0]+source.bounds[2])/2
        def tf(x,y):return config['width']/2+(x-cx)*scale,config['glyph_bottom']+(hi-y)*scale
        paths[ch]=[LineString([tf(x,y) for x,y in line.coords]) for line in raw[ch]]
        letters[ch]=unary_union([line.buffer(10*scale,quad_segs=24) for line in paths[ch]])
        transforms[ch]={'scale_mm_per_source_unit':scale,'source_center_x':cx,'source_max_y':hi,
                        'x_translation_mm':config['width']/2-cx*scale,
                        'y_translation_mm':config['glyph_bottom']+hi*scale,
                        'stroke_width_mm':20*scale}
    return letters,paths,transforms
