"""CI supervisor around existing commands, not a replacement test runner."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

from windows_process import execute

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--label', required=True)
parser.add_argument('--timeout', required=True, type=int)
parser.add_argument('--contains', action='append', default=[])
parser.add_argument('--expected-exit', type=int, default=0)
parser.add_argument('--negative-reason')
parser.add_argument('command', nargs=argparse.REMAINDER)
args = parser.parse_args()
if not re.fullmatch('[a-z0-9-]+', args.label) or not 1 <= args.timeout <= 300:
    parser.error('safe label and timeout 1..300 seconds required')
if args.expected_exit and (not args.negative_reason or not args.contains):
    parser.error('a negative needs an explicit reason and diagnostic')
command = args.command[1:] if args.command[:1] == ['--'] else args.command
if not command:
    parser.error('an existing command is required')
command[0] = shutil.which(command[0]) or command[0]
out = ROOT / '.ci-runs' / (args.label + '-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-' + uuid.uuid4().hex[:8])
out.mkdir(parents=True)
record = {'label': args.label, 'complete': False, 'expected_exit': args.expected_exit,
          'required_output': args.contains, 'intentional_negative': args.negative_reason,
          'python': sys.version, 'platform': sys.platform}
for key, revision in [('source', 'HEAD'), ('tree', 'HEAD^{tree}')]:
    record[key] = subprocess.check_output(['git', 'rev-parse', revision], cwd=ROOT, text=True, timeout=15).strip()
(out / 'result.json').write_text(json.dumps(record, indent=2))
result = execute(command, ROOT, os.environ.copy(), args.timeout, out / 'stdout.log', out / 'stderr.log')
record['process'] = result
stdout = (out / 'stdout.log').read_text(errors='replace')
stderr = (out / 'stderr.log').read_text(errors='replace')
ok = (result['exit'] == args.expected_exit and not result['timeout'] and not result['error']
      and not result['owned_process_remaining'] and all(s in stdout + stderr for s in args.contains))
record.update(complete=True, result='PASS' if ok else 'FAIL')
(out / 'result.json').write_text(json.dumps(record, indent=2))
print(stdout, end='', flush=True)
print(stderr, end='', file=sys.stderr, flush=True)
print(('COMPLETE' if ok else 'TEST-FAULT') + ' CI ' + args.label + ' result=' + record['result'] + ' receipt=' + str(out / 'result.json'), flush=True)
sys.exit(0 if ok else 1)
