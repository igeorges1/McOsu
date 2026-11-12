"""Validate timing controls and keep the tracked reference tied to source metadata."""
import argparse
from decimal import Decimal
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
osu = root / "src/App/Osu"
parser = argparse.ArgumentParser()
parser.add_argument("--write-docs", action="store_true", help="Regenerate the tracked control reference")
args = parser.parse_args()

def read(name):
    return (osu / name).read_text(encoding="utf-8")

def declarations(source, names):
    pattern = r'^ConVar\s+(\w+)\("(\w+)",\s*("[^"]*"|[^,]+),\s*FCVAR_NONE(?:,\s*"([^"]*)")?\);'
    result = {}
    for symbol, name, default, help_text in re.findall(pattern, source, re.MULTILINE):
        if not re.fullmatch(names, name):
            continue
        assert symbol == name and name not in result, name
        value = default.strip()
        if value.startswith('"'):
            value = value[1:-1]
        elif value not in ("false", "true"):
            value = format(Decimal(value.rstrip("fL")).normalize(), "f")
        result[name] = value, help_text
    return result

def number(text):
    return Decimal({"false": "0", "true": "1"}.get(text, text).rstrip("fL"))

def limits(kind, low, high, default):
    if kind == "FILENAME":
        return "Relative file under `sounds/`"
    lo, hi = number(low), number(high)
    assert lo <= number(default) <= hi, (default, low, high)
    if kind in ("BOOLEAN", "Toggle"):
        return "On / Off"
    return f"`{low.rstrip('fL')}`–`{high.rstrip('fL')}`"

audio = declarations(read("OsuTimingAudioFeedback.cpp"), r"osu_timing_audio(?:_\w+)?")
hud = declarations(read("OsuHUD.cpp") + read("OsuBeatmap.cpp"),
                   r"osu_(?:hud_hiterrorbar_\w+|draw_hiterrorbar(?:_\w+)?|hiterrorbar_misaims)")
capture = declarations(read("OsuTimingAudioFeedback.cpp"), r"osu_timing_capture_\w+")
audio_pattern = r'\{"(osu_timing_audio\w*)", "([^"]+)", (\w+), ([^,]+), ([^,]+), (true|false)(?:, "([^"]+)")?\}'
hud_pattern = r'\{"(osu_\w+)", "([^"]+)", (\w+), (\w+), ([^,]+), ([^,]+), "([^"]+)"\}'
audio_fields = re.findall(audio_pattern, read("OsuTimingAudioSettings.h"))
hud_fields = re.findall(hud_pattern, read("OsuTimingAudioHudControls.h"))
for registry, fields in ((audio, audio_fields), (dict(hud, **capture), hud_fields)):
    names = [field[0] for field in fields]
    assert len(names) == len(set(names)), "Duplicate timing control"
    assert set(names) == set(registry), {"missing": set(registry) - set(names), "unknown": set(names) - set(registry)}

editor = read("OsuTimingAudioOptions.cpp")
assert "OsuTimingAudioSettings::specs()" in editor and "const Control &control : controls()" in editor
assert "const auto &control : OsuTimingAudioHudControls::controls()" in editor
menu = read("OsuOptionsMenu.cpp").split("void OsuOptionsMenu::updateTimingAudioViewButton", 1)[0]
assert not any(f'"{name}"' in menu for name in hud), "Duplicate HUD widget binding"

lines = [
    "# Timing audio control reference",
    "",
    "Generated from the registered defaults, audio schema and HUD control metadata by",
    "`python tests/check-timing-audio-settings.py --write-docs`. See the [system map](timing-audio.md) for lifecycle and dependencies.",
    "",
    "## Audio editor",
    "",
    "Options → Timing Audio Experiment. Apply commits the draft as a batch. Mute acts immediately.",
    "All rows below save to ordinary config and named audio profiles.",
    "",
    "| Control | Key | Default | Accepted range | Applying | Effect |",
    "| --- | --- | --- | --- | --- | --- |",
]
for name, label, kind, lo, hi, restart, migration in audio_fields:
    default, help_text = audio[name]
    assert help_text, f"Missing effect description for {name}"
    if migration:
        assert number(default) == number(migration), f"Old-profile default disagrees with registered default for {name}"
    effect = "Resets learner" if restart == "true" else "Keeps learner"
    if name == "osu_timing_audio":
        effect = "Off resets timing"
    lines.append(f"| {label} | `{name}` | `{default}` | {limits(kind, lo, hi, default)} | {effect} | {help_text} |")

headings = {"CAPTURE": "Live Timing Debug Capture", "TIMING": "Timing Audio HUD",
            "APPEARANCE": "Timing Overlay Appearance", "BAR": "Hit Error Bar Appearance and Layout"}
group = None
for name, label, section, kind, lo, hi, help_text in hud_fields:
    if section != group:
        group = section
        lines += ["", f"## {headings[group]}", "",
                  "Applies immediately and saves to ordinary Options config.", "",
                  "| Control | Key | Default | Options range | Effect |",
                  "| --- | --- | --- | --- | --- |"]
    default, _ = (capture if section == "CAPTURE" else hud)[name]
    if kind == "View":
        accepted = "0 Audio, 1 Recent, 2 Projected average, 3 Projected reference"
    elif kind == "CaptureKey":
        accepted = "Key binding or 0 (unbound)"
    else:
        accepted = limits(kind, lo, hi, default)
    lines.append(f"| {label} | `{name}` | `{default}` | {accepted} | {help_text} |")

reference = root / "docs/timing-audio-controls.md"
generated = "\n".join(lines) + "\n"
if args.write_docs:
    reference.write_text(generated, encoding="utf-8")
else:
    assert reference.read_text(encoding="utf-8") == generated, "Stale timing reference. Regenerate it with --write-docs."
print(f"PASS: {len(audio_fields)} audio settings, {len(hud)} HUD settings and {len(capture)} capture settings match registration and tracked reference")
