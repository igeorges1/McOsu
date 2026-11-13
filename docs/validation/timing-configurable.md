# Configurable timing: validation and source boundary

This layer follows the timing HUD at `5f2289edce8c4060d0e9f314c945fd5701d09d46`.
Accepted original owner source is `492194dcc2b7f24aedc19a4afb1549bff947b113`
(commits `f826024`, `8f2018b`, `492194d`). Publication adds documentation and
output-ignore rules; it does not change the original game, test or settings bytes.
The [system map](../timing-audio.md) and [generated controls](../timing-audio-controls.md)
describe the implemented dependencies, lifecycle, defaults and persistence scope.

Local software suites and the metadata inventory passed on the accepted source.
The bounded implementation review and affected rechecks closed the Options
slider writeback/precision defect and the help/map coverage issues. Numeric/file
help and callback-free slider initialization are in this layer. Earlier PR4's
three fixes belong to its own `5f2289e` boundary and are not new findings here.

From this checkout, Python 3.13+ can check registration and the generated reference:

```powershell
python tests/check-timing-audio-settings.py
```

The supported guarded C++ runner is introduced by the next verification layer;
this head does not contain `tools/verify.py`. The original combined validation
base `24da0eec695b581a00d57a25043b3d447783c27b` also included separately merged
database/runtime work. That foundation history is deliberately absent from this
PR's diff. Use the independently [merged tooling documentation](https://github.com/igeorges1/McOsu/blob/c977662847c422b2f435774897a18a702bc0a690/tools/runtime/README.md)
for builds rather than treating the dependent ancestry as the fork default.

Local review is not a GitHub approval or hosted check. Publication is not a game
release or deployment. Native tooltip placement, physical controls, real-game
save/restart behavior, acoustic output and player usefulness require their own
evidence; helper results do not establish those claims. Historical unexpected
private fixture failures remain separate from product fixes and later passes.
The inherited [indented compound save limitation](known-limitations.md) is still open.
