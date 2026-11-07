"""Write an original listening/test map into a separate development runtime.

Usage: python tools/generate-timing-audio-fixture.py PATH_TO_RUNTIME
No existing game installation or user beatmap is modified.
"""
import math
from pathlib import Path
import struct
import sys
import wave

folder = Path(sys.argv[1]) / "fixture/Songs/TimingAudio"
folder.mkdir(parents=True, exist_ok=True)
with wave.open(str(folder / "music.wav"), "wb") as audio:
    audio.setparams((1, 2, 44100, 0, "NONE", "not compressed"))
    for second in range(37):
        audio.writeframes(b"".join(struct.pack("<h", round(1800 * (math.sin(2 * math.pi * 220 * (second + i / 44100))
                              + 0.5 * math.sin(2 * math.pi * 330 * (second + i / 44100))))) for i in range(44100)))

objects = [f"256,192,{t},1,0,0:0:0:0:" for t in range(2000, 6000, 500)]
objects += ["256,192,6500,2,0,L|396:192,2,560,0|0|0,0:0|0:0|0:0,0:0:0:0:"]
objects += ["256,192,11500,8,0,15500,0:0:0:0:"]
objects += [f"256,192,{t},1,0,0:0:0:0:" for t in range(16000, 17500, 500)]
objects += [f"256,192,{t},1,0,0:0:0:0:" for t in range(18000, 22000, 50)]
objects += [f"256,192,{t},1,0,0:0:0:0:" for t in range(23000, 26500, 500)]
objects += [f"256,192,{t},1,0,0:0:0:0:" for t in range(31000, 35000, 500)]
if "--preroll-circle" in sys.argv[2:]:
    objects = ["256,192,0,1,0,0:0:0:0:", "256,192,500,1,0,0:0:0:0:"] + objects
if "--preroll-head" in sys.argv[2:]:
    objects = ["256,192,0,2,0,L|396:192,1,140,0|0,0:0|0:0,0:0:0:0:", "256,192,500,1,0,0:0:0:0:"] + objects
if "--early-return" in sys.argv[2:]:
    objects = [f"256,192,{t},1,0,0:0:0:0:" for t in range(2000, 2800, 100)]
    objects += [f"256,192,{t},1,0,0:0:0:0:" for t in (5700, 6200, 6700, 7200)]
if "--late-departure" in sys.argv[2:]:
    objects = [f"256,192,{t},1,0,0:0:0:0:" for t in range(2000, 2800, 100)]
    objects += [f"256,192,{t},1,0,0:0:0:0:" for t in (2800, 5800, 6300)]
metadata = """osu file format v14

[General]
AudioFilename: music.wav
AudioLeadIn: 0
PreviewTime: 18000
Mode: 0
StackLeniency: 0

[Metadata]
Title: Timing Audio Experiment
Artist: Generated test signal
Creator: Local experiment
Version: Sparse, bodies, dense, rest
BeatmapID: 0
BeatmapSetID: -1

[Difficulty]
HPDrainRate: 0
CircleSize: 4
OverallDifficulty: 5
ApproachRate: 7
SliderMultiplier: 1.4
SliderTickRate: 1

[Events]
2,27000,30000

[TimingPoints]
0,500,4,1,0,60,1,0

[HitObjects]
"""
(folder / "experiment.osu").write_text(metadata + "\n".join(objects) + "\n", encoding="utf-8")
print(folder / "experiment.osu")
