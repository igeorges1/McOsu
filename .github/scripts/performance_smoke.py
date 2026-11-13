"""Python-only public consumer on synthetic wire data; never a benchmark."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid
from windows_process import execute

ROOT = Path(__file__).resolve().parents[2]
out = ROOT / '.ci-runs' / ('performance-consumer-' + uuid.uuid4().hex[:8])
out.mkdir(parents=True)
source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True, timeout=15).strip()
data = (f'MCOSU_PERFORMANCE 1\nsource {source}\nmap unknown\nclock engine_monotonic_seconds\n'
        'mark 0.5\nevicted 0\ndiscontinuities 0\npost 0 0\nboundary 2\npost_end target\n'
        'stages_ms 0.05 -1 1 -1 -1 -1\nframes 2\n'
        'sequence,start,interval,update,draw,draws,context,fps_limit,background_limit,unlimited,vsync\n'
        '1,0,0.01,0.001,0.002,1,0,120,120,0,0\n'
        '2,0.01,1.11,1.1,0.004,1,0,120,120,0,0\nend\n')
cases = [('valid', data, 0, 'COMPLETE performance samples=2'),
         ('truncated', data[:-4], 1, 'Truncated or extra frame rows'),
         ('unsupported', data.replace('MCOSU_PERFORMANCE 1', 'MCOSU_PERFORMANCE 9'), 1, 'Unsupported performance capture schema'),
         ('false-target', data.replace('boundary 2', 'boundary 0'), 1, 'Inconsistent post-mark completion')]
records = []
for label, text, expected, diagnostic in cases:
    path = out / (label + '.csv')
    path.write_text(text, encoding='ascii')
    r = execute([sys.executable, '-B', 'tools/verify.py', '--performance', str(path)], ROOT,
                os.environ.copy(), 15, out / (label + '.stdout.log'), out / (label + '.stderr.log'))
    output = (out / (label + '.stdout.log')).read_text(errors='replace') + (out / (label + '.stderr.log')).read_text(errors='replace')
    ok = r['exit'] == expected and not r['timeout'] and not r['error'] and diagnostic in output
    if ok and label == 'valid':
        match = re.search(r'summary=(.*?) graph=([^\r\n]+)', output)
        ok = bool(match)
        if match:
            summary = json.loads(Path(match.group(1)).read_text())
            ok = (summary['boundary'] == 'complete' and summary['cadence']['crosses_mark']['count'] == 1
                  and summary['cadence']['crosses_mark']['max_ms'] > 1000
                  and summary['cadence']['after']['count'] == 0 and '<svg' in Path(match.group(2)).read_text())
    records.append(dict(label=label, expected_exit=expected, intentional_negative=expected != 0,
                        diagnostic=diagnostic, passed=ok, **r))
    (out / 'processes.json').write_text(json.dumps(records, indent=2))
    if not ok:
        print('TEST-FAULT performance consumer ' + label + ' receipt=' + str(out / 'processes.json'), flush=True)
        sys.exit(1)
print('COMPLETE performance consumer smoke failures=0 checks=4 synthetic_wire_only=1', flush=True)
