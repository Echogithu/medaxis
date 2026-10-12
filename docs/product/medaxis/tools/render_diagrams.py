"""从产品图源生成真实 SVG/PNG；仅写文档派生物，不调用业务服务。"""
from pathlib import Path
import json
import math
import re
from html import escape
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'visuals'
FONT = Path('C:/Windows/Fonts/msyh.ttc')
if not FONT.exists():
    raise SystemExit('缺少中文字体；请在脚本中指定已安装字体后重试，不生成缺字图片。')
font = ImageFont.truetype(str(FONT), 25)
small = ImageFont.truetype(str(FONT), 19)
titlefont = ImageFont.truetype(str(FONT), 34)
colors = {'bg': '#f4f7f6', 'ink': '#173a38', 'line': '#9bb4b0', 'teal': '#0f766e', 'fill': '#ffffff', 'muted': '#536d6a'}

# 仅布局坐标，语义来自 .mmd；每图节点必须与图源完全相符。
layouts = {
 'product-map': (1500, 1100, {'core':(750,200),'patient':(270,400),'doctor':(750,400),'admin':(1230,400),
    'p1':(270,590),'p2':(270,770),'p3':(270,950),'d1':(750,590),'d2':(750,770),'d3':(750,950),
    'a1':(1230,590),'a2':(1230,770),'a3':(1230,950)}),
 'domain-model': (1480,1120, {'user':(740,150),'session':(270,350),'case':(740,530),'report':(1210,350),
    'prep':(260,760),'feedback':(740,760),'consultation':(1210,760),'plan':(740,960),'event':(1210,960)}),
 'patient-flow': (1400,1670, {'enter':(550,155),'collect':(550,285),'retrieve':(550,415),'gate':(550,550),
    'fail':(1090,550),'report':(550,705),'save':(550,845),'retry':(1090,845),'prep':(550,1000),
    'revision':(550,1140),'conflict':(1090,1140),'ready':(550,1295),'feedback':(550,1430),'restore':(550,1560)}),
 'report-consent': (1500,1980, {'upload':(560,160),'archive':(560,305),'parse':(560,450),'preview':(560,600),
    'consent':(560,760),'manual':(1140,930),'version':(560,940),'ai':(560,1120),'candidate':(560,1285),
    'draft':(560,1450),'confirm':(560,1615),'link':(560,1770),'changed':(1140,1770)}),
 'doctor-consultation': (1500,1660, {'case':(580,150),'choose':(580,305),'grant':(580,455),'active':(580,610),
    'existing':(1140,610),'pending':(580,780),'decision':(580,935),'declined':(1140,935),
    'accepted':(580,1110),'waiting':(1140,1110),'completed':(580,1450),'stop':(1140,1450)})
}

def parse(source):
    nodes = {m[0]: (m[2], m[1] == '{') for m in re.findall(r'(\w+)([\[{])"([^"]+)"[\]}]', source)}
    edges = []
    for line in source.splitlines():
        stripped = re.sub(r'(\w+)[\[{]"[^"]+"[\]}]', r'\1', line.strip())
        m = re.search(r'^(\w+)\s+-->\s*(?:\|([^|]+)\|\s*)?(\w+)', stripped)
        if m:
            edges.append((m[1],m[3],m[2] or ''))
    return nodes, edges

def lines(text, width=350):
    result=[]
    for part in text.split('／'):
        cur=''
        for char in part:
            if font.getlength(cur+char)>width:
                result.append(cur); cur=char
            else: cur+=char
        if cur: result.append(cur)
    return result

def render(name, title, source):
    width,height,positions=layouts[name]
    nodes,edges=parse(source)
    if set(nodes)!=set(positions):
        raise ValueError(f'{name} 节点/布局不一致: {set(nodes)^set(positions)}')
    image=Image.new('RGB',(width,height),colors['bg']); draw=ImageDraw.Draw(image)
    svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img"><title>{escape(title)}</title>',f'<rect width="100%" height="100%" fill="{colors["bg"]}"/>', '<g font-family="Microsoft YaHei, sans-serif">']
    def text(x,y,value,size=25,color=None,align='middle'):
        color=color or colors['ink']
        used=titlefont if size==34 else small if size==19 else font
        draw.text((x,y),value,font=used,fill=color,anchor='mm' if align=='middle' else 'lm')
        svg.append(f'<text x="{x}" y="{y}" fill="{color}" font-size="{size}" text-anchor="{align}" dominant-baseline="central">{escape(value)}</text>')
    text(44,42,title,34,align='start')
    text(44,83,'产品流程示意 · REVIEW · 静态梳理，运行与专业验收未由本图证明',19,colors['muted'],align='start')
    dims={key:(390,130 if value[1] else max(96,30*len(lines(value[0]))+25)) for key,value in nodes.items()}
    for index,(a,b,label) in enumerate(edges):
        x1,y1=positions[a];x2,y2=positions[b];w1,h1=dims[a];w2,h2=dims[b]
        if name=='product-map' and a in ('patient','doctor','admin'):
            rail=x1-225
            points=[(x1-w1/2,y1),(rail,y1),(rail,y2),(x2-w2/2,y2)]
        elif name=='report-consent' and (a,b)==('manual','draft'):
            points=[(x1,y1+h1/2),(x1,y2),(x2+w2/2,y2)]
        elif name=='domain-model' and (a,b)==('user','plan'):
            points=[(x1-w1/2,y1),(40,y1),(40,y2),(x2-w2/2,y2)]
        elif name=='doctor-consultation' and (a,b)==('pending','stop'):
            points=[(x1+w1/2,y1),(1430,y1),(1430,y2),(x2+w2/2,y2)]
        elif name=='doctor-consultation' and (a,b)==('waiting','accepted'):
            points=[(x1-w1/2,y1),(900,y1),(900,1200),(x2,1200),(x2,y2+h2/2)]
        elif name=='patient-flow' and (a,b)==('retry','save'):
            points=[(x1,y1-h1/2),(x1,755),(x2,755),(x2,y2-h2/2)]
        elif x1==x2:
            direction=1 if y2>y1 else -1
            points=[(x1,y1+direction*h1/2),(x2,y2-direction*h2/2)]
        elif y1==y2:
            direction=1 if x2>x1 else -1
            points=[(x1+direction*w1/2,y1),(x2-direction*w2/2,y2)]
        elif y2>y1:
            points=[(x1,y1+h1/2),(x1,(y1+y2)/2),(x2,(y1+y2)/2),(x2,y2-h2/2)]
        else:
            # 返回边从侧面绕行，不穿过中间主线节点。
            side= min(width-25,max(x1,x2)+240)
            points=[(x1+w1/2,y1),(side,y1),(side,y2),(x2+w2/2,y2)]
        draw.line(points,fill=colors['line'],width=3)
        svg.append('<polyline points="'+ ' '.join(f'{x},{y}' for x,y in points)+f'" fill="none" stroke="{colors["line"]}" stroke-width="3"/>')
        px,py=points[-2]; ex,ey=points[-1]; angle=math.atan2(ey-py,ex-px)
        arrow=[(ex,ey),(ex-12*math.cos(angle-.4),ey-12*math.sin(angle-.4)),(ex-12*math.cos(angle+.4),ey-12*math.sin(angle+.4))]
        draw.polygon(arrow,fill=colors['line']); svg.append('<polygon points="'+' '.join(f'{x},{y}' for x,y in arrow)+f'" fill="{colors["line"]}"/>')
        if label:
            mx=(points[0][0]+points[1][0])/2;my=(points[0][1]+points[1][1])/2-18
            if name=='report-consent' and (a,b)==('consent','manual'): mx,my=850,830
            if name=='report-consent' and (a,b)==('version','preview'): mx,my=822,930
            if name=='domain-model' and (a,b)==('session','case'): mx,my=495,422
            if name=='domain-model' and (a,b)==('report','case'): mx,my=985,422
            text(mx,my,label,19,colors['teal'])
    for key,(label,diamond) in nodes.items():
        x,y=positions[key];w,h=dims[key]
        fill='#e3f2ed' if diamond or key=='core' else colors['fill']
        if diamond:
            polygon=[(x,y-h/2),(x+w/2,y),(x,y+h/2),(x-w/2,y)]
            draw.polygon(polygon,fill=fill,outline=colors['teal'],width=2)
            svg.append('<polygon points="'+' '.join(f'{px},{py}' for px,py in polygon)+f'" fill="{fill}" stroke="{colors["teal"]}" stroke-width="2"/>')
        else:
            draw.rounded_rectangle((x-w/2,y-h/2,x+w/2,y+h/2),radius=18,fill=fill,outline='#cadbd7',width=2)
            svg.append(f'<rect x="{x-w/2}" y="{y-h/2}" width="{w}" height="{h}" rx="18" fill="{fill}" stroke="#cadbd7" stroke-width="2"/>')
        parts=lines(label,350)
        for i,part in enumerate(parts): text(x,y+(i-(len(parts)-1)/2)*30,part)
    svg.append('</g></svg>')
    (OUT/f'{name}.svg').write_text('\n'.join(svg),encoding='utf-8')
    image.save(OUT/f'{name}.png',optimize=True)
    return {'name':name,'nodes':len(nodes),'edges':len(edges),'width':width,'height':height}

flow_sources=re.findall(r'```mermaid\n(.*?)\n```',(ROOT/'USER_FLOWS.md').read_text(encoding='utf-8'),re.S)
if len(flow_sources)!=3: raise ValueError('USER_FLOWS 应包含3份流程图源')
records=[]
for name,title in [('product-map','MedAxis · 产品全景'),('domain-model','MedAxis · 资料与对象关系')]:
    records.append(render(name,title,(OUT/f'{name}.mmd').read_text(encoding='utf-8')))
for name,title,source in zip(['patient-flow','report-consent','doctor-consultation'],['患者 · 整理、保存与再次找回','报告 · 逐次同意与本人核对','医生 · 定向咨询与停止共享'],flow_sources):
    (OUT/f'{name}.mmd').write_text(source+'\n',encoding='utf-8')
    records.append(render(name,title,source))
(OUT/'diagram-manifest.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'generated':len(records),'diagrams':records},ensure_ascii=False))
