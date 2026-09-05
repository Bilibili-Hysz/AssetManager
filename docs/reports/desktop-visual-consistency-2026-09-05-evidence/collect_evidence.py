"""Read-only source audit; writes evidence only beside this script."""
from pathlib import Path
import ast
import csv
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
folders = ['AssetsManager/panels', 'AssetsManager/widgets', 'AssetsManager/dialogs',
           'AssetsManager/background', 'AssetsManager/plugin_api', 'Plugins/Addons']
singles = ['AssetsManager/app.py', 'AssetsManager/window.py', 'AssetsManager/window_coordinator.py',
           'AssetsManager/dock_factory.py', 'AssetsManager/core/themes.py',
           'AssetsManager/core/theme_loader.py', 'AssetsManager/core/icons.py',
           'AssetsManager/core/ui_scale.py', 'AssetsManager/core/color_utils.py',
           'AssetsManager/core/signal_bus.py']
paths = sorted(set([p for d in folders for p in (ROOT/d).rglob('*.py')] +
                   [ROOT/p for p in singles if (ROOT/p).exists()]))
rows=[]
occurrences=[]
for path in paths:
    raw=path.read_bytes()
    source=raw.decode('utf-8-sig')
    tree=ast.parse(source)
    rel=path.relative_to(ROOT).as_posix()
    counts={k:0 for k in ['qss','paint','fixed_geometry','duration','a11y_name','font_point','font_pixel']}
    classes=[]
    for node in ast.walk(tree):
        if isinstance(node,ast.ClassDef):
            classes.append(f'{node.name}({",".join(ast.unparse(b) for b in node.bases)})@{node.lineno}')
        if isinstance(node,ast.FunctionDef) and node.name=='paintEvent': counts['paint']+=1
        if not isinstance(node,ast.Call): continue
        name=node.func.attr if isinstance(node.func,ast.Attribute) else ''
        category={'setStyleSheet':'qss','setFixedSize':'fixed_geometry','setFixedWidth':'fixed_geometry',
                  'setFixedHeight':'fixed_geometry','setDuration':'duration','setAccessibleName':'a11y_name',
                  'setPointSize':'font_point','setPointSizeF':'font_point','setPixelSize':'font_pixel'}.get(name)
        if category:
            counts[category]+=1
            segment=ast.get_source_segment(source,node) or ''
            occurrences.append({'path':rel,'line':node.lineno,'kind':category,'source':segment})
    rows.append({'path':rel,'lines':len(source.splitlines()),'sha256':hashlib.sha256(raw).hexdigest(),
                 'classes':'; '.join(classes),**counts,
                 'theme_signal':'theme_changed' in source,'scale_signal':'ui_scale_changed' in source,
                 'language_signal':'language_changed' in source,'reduce_motion':'reduce_motion' in source})

with (OUT/'source-inventory.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
(OUT/'occurrences.json').write_text(json.dumps(occurrences,ensure_ascii=False,indent=2),encoding='utf-8')
manifest={'time_utc':datetime.now(timezone.utc).isoformat(),
          'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
          'scope':folders+singles,'file_count':len(rows),
          'totals':{k:sum(r[k] for r in rows) for k in ['lines','qss','paint','fixed_geometry','duration','a11y_name','font_point','font_pixel']},
          'warning':'Lexical signal/reduce_motion counts do not account for inheritance. Occurrence counts are not defect counts.',
          'files':[{'path':r['path'],'sha256':r['sha256']} for r in rows]}
(OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'working-tree-status.txt').write_text(subprocess.check_output(['git','status','--short'],cwd=ROOT,text=True,encoding='utf-8'),encoding='utf-8')
print(json.dumps({k:v for k,v in manifest.items() if k!='files'},ensure_ascii=False,indent=2))
print('TOP QSS FILES')
for r in sorted(rows,key=lambda r:r['qss'],reverse=True)[:12]: print(r['path'],r['qss'])
print('LITERAL MOTION')
for o in occurrences:
    if o['kind']=='duration' and re.search(r'setDuration\(\d',o['source']):print(o['path'],o['line'],o['source'])

def luminance(color):
    channels=[int(color[i:i+2],16)/255 for i in (1,3,5)]
    values=[c/12.92 if c<=0.04045 else ((c+0.055)/1.055)**2.4 for c in channels]
    return sum(v*w for v,w in zip(values,(0.2126,0.7152,0.0722)))

theme_rows=[]
contrasts=[]
for p in sorted((ROOT/'assets/themes').glob('*.json')):
    raw=p.read_bytes(); data=json.loads(raw); colors=data.get('colors',{})
    theme_rows.append({'path':p.relative_to(ROOT).as_posix(),'name':data.get('name'),
                       'dark':data.get('dark'),'properties':data.get('properties',{}),
                       'sha256':hashlib.sha256(raw).hexdigest()})
    for fg,bg in [('body','panel'),('muted','panel'),('on_accent','accent'),('input_text','input_bg')]:
        a,b=colors.get(fg,''),colors.get(bg,'')
        if re.fullmatch(r'#[\da-fA-F]{6}',a) and re.fullmatch(r'#[\da-fA-F]{6}',b):
            la,lb=sorted([luminance(a),luminance(b)])
            contrasts.append({'theme':data['name'],'foreground':fg,'background':bg,
                              'ratio':round((lb+.05)/(la+.05),3),
                              'scope':'raw opaque JSON pair; not rendered UI or composed wallpaper'})
(OUT/'theme-inventory.json').write_text(json.dumps(theme_rows,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'theme-contrast.json').write_text(json.dumps(contrasts,ensure_ascii=False,indent=2),encoding='utf-8')
print('THEMES',len(theme_rows),'DARK',sum(bool(r['dark']) for r in theme_rows))
print('RAW PAIRS BELOW 4.5',len([r for r in contrasts if r['ratio']<4.5]),'OF',len(contrasts))
for r in sorted(contrasts,key=lambda x:x['ratio'])[:12]:print(r)
