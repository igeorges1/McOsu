"""Generate the experiment's original 20 ms cue samples (Python standard library)."""
from pathlib import Path
import math
import struct
import wave

destination = Path(__file__).resolve().parents[1] / "build/sounds"
destination.mkdir(parents=True, exist_ok=True)
for name, frequency in (("early", 660), ("late", 1320)):
    frames = []
    for i in range(882):
        t = i / 44100
        envelope = min(1, t / 0.002) * (1 - i / 881) ** 2
        frames.append(struct.pack("<h", round(16000 * envelope * math.sin(2 * math.pi * frequency * t))))
    with wave.open(str(destination / ("timing-" + name + ".wav")), "wb") as sound:
        sound.setparams((1, 2, 44100, 0, "NONE", "not compressed"))
        sound.writeframes(b"".join(frames))
