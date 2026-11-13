# Verification layer: provenance and limits

Original accepted range is combined24da..2c9: commits
`a43fa82407e1755972674f1f786ba816f9595a68` and
`2c9dce42c4f9af0e9da7f470c4cb6473ee04f230`. The publication branch applies
those helper/test/fixture bytes to the owner-based configurable-timing stack.
README/runtime links and this source-history explanation are publication docs;
CI is explicitly additive and separately checked. No database/runtime foundation
product files are imported.

The eight-suite profile originally completed26 checks, with exact historical
pre-roll RED/fixed/current GREEN. The independent fresh/shallow-checkout run and
bounded workflow review passed at original2c9. Earlier path-limit/compiler and
runner-invocation failures were preserved separately from their corrected runs.
This proves the documented helper workflow and failure contracts, not a game.

Use the commands in [verification](../verification.md) and [CI](../ci.md).
Historical headers remain exact Git bytes with blob/hash provenance and license;
no local historical commit objects or private recipe is needed. New publication
SHAs need new receipts; original captures are never relabelled.

Publication preparation also exercised the additive CI commands locally with
the hash-locked archive: fresh extraction/compiler identity, full26 and the
six-negative runner-contract profile passed. A deliberately corrupt archive was
rejected before extraction/compiler execution. An initial CI-only expectation
looked for the nested contract marker in outer stdout; it failed truthfully,
was retained, and was corrected to require the existing outer success line and
four-check completion. Product/runner/test code was not changed for that correction.
These are local preparation results, not independent acceptance or hosted success.

## Publication YAML ingestion correction

The original publication head `11c3d0687514d55fdeccd095a74a942a8f12b8a4`
passed local commands and a PowerShell command-syntax check. That check did not
parse the surrounding YAML. Its plain `run:` scalar contained colon-space in
`"PASS runner-contract: exit=..."`; shell quotes do not quote a YAML scalar.
The timing workflow was not registered by GitHub, so there was no hosted timing
run or successful check at that head.

The correction uses a folded block scalar for that one command. PyYAML6.0.2
rejects the exact original at line28/column122 with the declared mapping-value
diagnostic and accepts the correction, preserving the complete shell command.
The original failure and corrected parser receipts remain separate. Earlier
full26/28, failure-contract and consumer results retain their original source
identities; no product, test, runner or guard changes require repeating them.
YAML parsing alone does not prove GitHub ingestion or job execution: the publisher
must inspect actual hosted runs after the correction is pushed.
