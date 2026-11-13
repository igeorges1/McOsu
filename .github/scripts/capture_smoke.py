"""CI synthetic producer -> supported consumer, plus declared truncated reject."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
from windows_process import execute

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--toolchain', type=Path, required=True)
args = parser.parse_args()
tc = args.toolchain.resolve()
out = ROOT / '.ci-runs' / ('capture-consumer-' + uuid.uuid4().hex[:8])
out.mkdir(parents=True)
source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True, timeout=15).strip()
env = dict(os.environ, PATH=str(tc / 'bin') + os.pathsep + os.environ['PATH'])
records = []

def run(label, argv, seconds, expected, required):
    r = execute(argv, ROOT, env, seconds, out / (label + '.stdout.log'), out / (label + '.stderr.log'))
    output = (out / (label + '.stdout.log')).read_text(errors='replace') + (out / (label + '.stderr.log')).read_text(errors='replace')
    ok = r['exit'] == expected and not r['timeout'] and not r['error'] and all(s in output for s in required)
    records.append(dict(label=label, expected_exit=expected, intentional_negative=expected != 0, required=required, passed=ok, **r))
    (out / 'processes.json').write_text(json.dumps(records, indent=2))
    if not ok:
        print('TEST-FAULT capture consumer ' + label + ' receipt=' + str(out / 'processes.json'), flush=True)
        sys.exit(1)

relative = out.relative_to(ROOT).as_posix()
run('compile', [str(tc / 'bin/g++.exe'), '-std=c++11', '-O2', '-Wall', '-Wextra', '-Werror', '-pedantic', '-UNDEBUG',
                '-I', 'src/App/Osu', '.github/scripts/capture_smoke.cpp', '-o', relative + '/producer.exe'], 60, 0, [])
capture = out / 'synthetic.mct'
run('produce', [str(out / 'producer.exe'), source, str(capture)], 15, 0, ['COMPLETE synthetic capture producer failures=0 accepted_hits=3 marks=1'])
run('consume', [sys.executable, '-B', 'tools/verify.py', '--toolchain', str(tc), '--capture', str(capture)], 90, 0, ['COMPLETE failures=0 checks=5'])
truncated = out / 'truncated.mct'
truncated.write_bytes(capture.read_bytes()[:-20])
run('reject-truncated', [sys.executable, '-B', 'tools/verify.py', '--toolchain', str(tc), '--capture', str(truncated)], 30, 1,
    ['Missing capture checksum; report may be truncated'])
print('COMPLETE capture consumer smoke failures=0 checks=4 synthetic_helpers_only=1', flush=True)
