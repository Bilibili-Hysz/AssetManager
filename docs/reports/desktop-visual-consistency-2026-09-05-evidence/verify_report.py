"""Validate this report's local links and source snapshot; rerun static gates."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
import platform
import re
import subprocess
import sys

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
REPORT = OUT.parent / 'desktop-visual-consistency-2026-09-05.md'
problems = []
links = re.findall(r'\[[^\]]+\]\(([^)]+)\)', REPORT.read_text(encoding='utf-8'))
local_count = 0
for link in links:
    if '://' in link or link.startswith('#'):
        continue
    local_count += 1
    target = (REPORT.parent / link.split('#')[0]).resolve()
    if not target.exists():
        problems.append(f'Missing local link: {link}')

manifest = json.loads((OUT/'manifest.json').read_text(encoding='utf-8'))
themes = json.loads((OUT/'theme-inventory.json').read_text(encoding='utf-8'))
for item in manifest['files'] + themes:
    actual = hashlib.sha256((ROOT/item['path']).read_bytes()).hexdigest()
    if actual != item['sha256']:
        problems.append(f'Source changed: {item["path"]}')

env = dict(os.environ, PYTHONIOENCODING='utf-8')
checks = []
for name in ['check_style_sources.py','check_style_dialects.py','check_inline_styles.py','check_i18n_catalogs.py']:
    command = [sys.executable, f'scripts/{name}']
    result = subprocess.run(command, cwd=ROOT, env=env, text=True, encoding='utf-8',
                            capture_output=True, timeout=60)
    output = result.stdout + result.stderr
    (OUT/f'{name}.txt').write_text(output, encoding='utf-8')
    checks.append({'command':command, 'exit_code':result.returncode,
                   'script_sha256':hashlib.sha256((ROOT/'scripts'/name).read_bytes()).hexdigest(),
                   'output_sha256':hashlib.sha256(output.encode('utf-8')).hexdigest(),
                   'output':output})
    if result.returncode:
        problems.append(f'Static check failed: {name}')

record={'time_utc':datetime.now(timezone.utc).isoformat(), 'platform':platform.platform(),
        'python':sys.version, 'local_links_checked':local_count,
        'source_hashes_checked':len(manifest['files'])+len(themes),
        'report_sha256':hashlib.sha256(REPORT.read_bytes()).hexdigest(),
        'checks':checks, 'problems':problems}
(OUT/'verification.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in record.items() if k!='checks'},ensure_ascii=False,indent=2))
for check in checks:
    print(check['output'].strip())
raise SystemExit(bool(problems))
