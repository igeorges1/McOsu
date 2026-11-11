"""Keep all actual timing ConVars represented in the live editor/profile schema."""
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
source = (root / 'src/App/Osu/OsuTimingAudioFeedback.cpp').read_text()
schema = (root / 'src/App/Osu/OsuTimingAudioSettings.h').read_text()
declarations = re.findall(r'^ConVar\s+\w+\("(osu_timing_audio(?:_\w+)?)"', source, re.MULTILINE)
fields = re.findall(r'\{"(osu_timing_audio(?:_\w+)?)",', schema)
assert len(fields) == len(set(fields)), 'Duplicate editor field'
assert set(fields) == set(declarations), {'missing': set(declarations) - set(fields), 'unknown': set(fields) - set(declarations)}
print(f'PASS: all {len(fields)} actual timing-audio ConVars are covered by editor/profile schema')
