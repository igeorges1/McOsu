"""Generate original, longer and brighter experiment cues (standard library)."""
from pathlib import Path
import math
import struct
import wave

destination = Path(__file__).resolve().parents[1] / "build/sounds"
destination.mkdir(parents=True, exist_ok=True)
for name, frequency in (("early", 660), ("late", 1320)):
    original = []
    for i in range(882):
        t = i / 44100
        envelope = min(1, t / 0.002) * (1 - i / 881) ** 2
        original.append(round(16000 * envelope * math.sin(2 * math.pi * frequency * t)))
    profiles = {"": original}
    for suffix, duration, harmonic in (("-longer", .045, 0), ("-brighter", .030, .35)):
        values = []
        for i in range(round(44100 * duration)):
            t = i / 44100
            envelope = min(1, t / .002) * max(0, min(1, (duration - t) / .018))
            values.append(envelope * ((1 - harmonic) * math.sin(2 * math.pi * frequency * t)
                                     + harmonic * math.sin(4 * math.pi * frequency * t)))
        scale = max(abs(x) for x in original) / max(abs(x) for x in values)
        profiles[suffix] = [round(x * scale) for x in values]
    for suffix, values in profiles.items():
        with wave.open(str(destination / ("timing-" + name + suffix + ".wav")), "wb") as sound:
            sound.setparams((1, 2, 44100, 0, "NONE", "not compressed"))
            sound.writeframes(b"".join(struct.pack("<h", value) for value in values))
