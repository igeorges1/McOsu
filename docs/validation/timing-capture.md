# Timing capture: accepted boundary and publication builds

Accepted source range is original2c9..ce3 (`3dfc48e`, `ce3ecd9`). Game/model,
consumer, tests and quota-fix bytes are preserved on this publication dependency.
The local bounded review closed the Windows capture-folder quota error; exact
production enumeration/caller cases and affected checks passed on originalce3.
An accepted private synthetic-driver native capture and a later human capture
were replayed at their original source identities. They are not new runs of
this publication SHA, physical-input acceptance, full scoring replay or acoustics.

The [capture guide](../timing-capture.md) defines full-prefix/source requirements,
partial and overflow reports, screenshot association and its original synchronous
mark cost. CI adds a small explicitly synthetic production-helper capture producer,
then calls the supported consumer and requires a specific truncated-file rejection.
It supplies no game, beatmap, Engine, BASS device or private capture.

## Build-driver foundation dependency

The original capture commit also adds three source-ID stamping lines to
`tools/runtime/build.py`, a file from the already-merged tooling foundation.
That complete runtime product is deliberately not duplicated into this owner-based
game PR. The old fork-master builder alone does not stamp replayable captures.

Use the exact accepted builder from the preserved original combined source
`3c69a2a4e374a24bda8a3c9574e772ab85241b30`, with `--source` pointing to this clean
publication checkout. Use the matching complete tooling directory/checkout:
`build.py` imports its adjacent `runtime.py`, so a lone downloaded script is not
sufficient. Its existing code derives the define from **that source's HEAD**,
not from the builder's own checkout. Keep both checkouts separate:

```powershell
python C:/accepted-original/tools/runtime/build.py build --source C:/publication --engine C:/dependencies/McEngine --toolchain C:/dependencies/mingw32 --assets C:/dependencies/normal-assets --out C:/temporary/fresh-normal-build
```

The [accepted build/runtime guide](https://github.com/igeorges1/McOsu/blob/3c69a2a4e374a24bda8a3c9574e772ab85241b30/tools/runtime/README.md)
provides pinned dependencies and package commands. The publisher preserves the
original source archive so both these instructions and historical exact-source
reports stay reproducible. Publication mapping records the omitted foundational
builder patch and its accepted blob separately; no game or test change is hidden.
This preparation performs no new game build or deployment.

The same exact three accepted builder additions also have a separate proposed
`publish/capture-build-identity` integration branch targeting fork master. It is
independent of the game stack and runtime-CI branch; the archived complete tooling
checkout above remains the usable fallback until that proposal is integrated.
