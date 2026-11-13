# Recorded configuration limitation

Saving Options can discard unrelated commands from a manually authored compound
configuration line that begins with ASCII spaces. The normal timing settings
writer emits standalone, unindented assignments; this concerns retained manual
compounds. It is inherited from the audio persistence work, separate from the
already-closed persistence corrections.

Previously reproduced with a disposable configuration: keep an indented compound
with an unrelated command before a later managed widget/timing setting, then
save through Options and reload. A representative input is:

```text
  osu_end_delay_time 2000; osu_volume_master 0.25; osu_timing_audio 0
```

Expected: unrelated commands survive, while authoritative managed values may be
written later. Previously observed: the retained line can be removed, losing its
earlier unrelated command. The first-command filter still derives token length
from the first space in the untrimmed line. Publication inspected the current
source; it did **not** execute a new save/reload reproduction or fix the product.

A future fix needs the actual parser's command boundaries, preservation of
unrelated text/values and dispatch semantics, and an indented-compound regression
without weakening unindented, echo, filename-collision or widget-ordering cases.
