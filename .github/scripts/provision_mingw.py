"""Hash-locked official MinGW archive, extracted without installing anything."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
import urllib.request
import uuid

from windows_process import execute, nonmodal

ROOT = Path(__file__).resolve().parents[2]
URL = ('https://downloads.sourceforge.net/project/mingw-w64/Toolchains%20targetting%20Win32/'
       'Personal%20Builds/mingw-builds/8.1.0/threads-win32/dwarf/'
       'i686-8.1.0-release-win32-dwarf-rt_v6-rev0.7z')
SHA256 = '28d0a0608d9524868f7feaf9f9ec5daf69669076eafc9e776af02d60ebfba93c'
SIZE = 45077278
COMPILERS = {'g++.exe': '333229b220efe27d059993c8ffdbd07623759b6d99f59fa21f2b42757ca5ac09',
             'gcc.exe': 'c4cc9a5d11fee13e184697755ac7368668249c0bbe7f25dd993da16a82ed7335'}
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--out', type=Path, required=True)
parser.add_argument('--archive', type=Path, help='Explicit offline copy; identical hash is required')
args = parser.parse_args()
nonmodal()
logs = ROOT / '.ci-runs' / ('provision-' + uuid.uuid4().hex[:8])
logs.mkdir(parents=True)
record = {'complete': False, 'result': 'INCOMPLETE', 'url': URL, 'archive_sha256': SHA256,
          'archive_size': SIZE, 'out': str(args.out.resolve()), 'processes': [], 'python': sys.version}
save = lambda: (logs / 'result.json').write_text(json.dumps(record, indent=2))
save()
try:
    if sys.platform != 'win32' or sys.version_info < (3, 13):
        raise ValueError('Windows and Python3.13+ are required')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    archive = args.archive.resolve() if args.archive else out / 'compiler.7z'
    if not args.archive:
        start = time.monotonic()
        request = urllib.request.Request(URL, headers={'User-Agent': 'McOsu-verification-CI'})
        with urllib.request.urlopen(request, timeout=30) as response, archive.open('xb') as dest:
            count = 0
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                count += len(block)
                if count > SIZE or time.monotonic() - start > 180:
                    raise ValueError('Download exceeds locked size or 180s budget')
                dest.write(block)
        record['download_seconds'] = round(time.monotonic() - start, 3)
    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    record['observed_archive_sha256'] = actual
    if archive.stat().st_size != SIZE or actual != SHA256:
        raise ValueError('Compiler archive size/SHA256 mismatch; no extraction or compiler execution')
    sevenzip = shutil.which('7z') or str(Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / '7-Zip/7z.exe')
    if not Path(sevenzip).is_file():
        raise ValueError('7-Zip is required (included in windows-2022 image)')
    def run(label, argv, seconds):
        r = execute(argv, ROOT, os.environ.copy(), seconds, logs / (label + '.stdout.log'), logs / (label + '.stderr.log'))
        record['processes'].append(dict(label=label, **r)); save()
        if r['exit'] != 0 or r['timeout'] or r['error'] or r['owned_process_remaining']:
            raise ValueError('Owned provisioning process failed: ' + label)
        return (logs / (label + '.stdout.log')).read_text() + (logs / (label + '.stderr.log')).read_text()
    run('extract', [sevenzip, 'x', str(archive), '-o' + str(out), '-y', '-bb0'], 120)
    toolchain = out / 'mingw32'
    for name, expected in COMPILERS.items():
        if hashlib.sha256((toolchain / 'bin' / name).read_bytes()).hexdigest() != expected:
            raise ValueError('Extracted compiler hash mismatch: ' + name)
    gxx = str(toolchain / 'bin/g++.exe')
    if run('version', [gxx, '-dumpversion'], 15).strip() != '8.1.0':
        raise ValueError('GCC8.1 required')
    if run('target', [gxx, '-dumpmachine'], 15).strip() != 'i686-w64-mingw32':
        raise ValueError('i686 target required')
    verbose = run('configuration', [gxx, '-v'], 15)
    if 'Thread model: win32' not in verbose or '--with-dwarf2' not in verbose:
        raise ValueError('Win32 threads/DWARF2 required')
    record['toolchain'] = str(toolchain)
    if os.environ.get('GITHUB_ENV'):
        with open(os.environ['GITHUB_ENV'], 'a', encoding='utf-8') as stream:
            stream.write('MCOSU_TOOLCHAIN=' + str(toolchain) + '\nMCOSU_TEST_CC=' + str(toolchain / 'bin/gcc.exe') + '\n')
    record.update(complete=True, result='PASS'); save()
    print('COMPLETE provision failures=0 toolchain=' + str(toolchain), flush=True)
except Exception as error:
    record.update(complete=True, result='FAIL', error=str(error)); save()
    print('TEST-FAULT provisioning ' + str(error) + ' receipt=' + str(logs / 'result.json'), flush=True)
    sys.exit(1)
