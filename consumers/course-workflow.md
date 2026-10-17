# Course workflow

`course-workflow.mjs` composes the existing MA consumer, math auditor, image renderer, annotation layout and package inspector. Its default mode only prepares local artifacts. It never uses source text as a command, invokes children with argv arrays and `shell: false`, and does not implement a second RemNote import engine.

```powershell
node consumers/course-workflow.mjs --graph D:/Downloads/course-knowledge-graph.zip --progress D:/Downloads/ma-43105.zip --topics D:/Downloads/topic-json.zip --course-id 82 --title '复分析（MA）' --output D:/Artifacts/RemNoteBulkImporter/course-82 --package D:/Artifacts/RemNoteBulkImporter/packages/course-82.json --allow-missing-progress --workers 1
```

Stages are convert, initial math audit, source regeneration with the audit report if needed, final native math audit, render, pack, top annotation layout, final package math audit, consumer source audit, independent original-ZIP source audit and package inspection. Failed diagrams or remaining formula errors stop the workflow. Missing source material stays in the consumer's explicit gap markers. Source ZIPs are retained; candidate content is never repaired by hand.

`workflow-stages.json` records input and output fingerprints. Rerunning reuses intact stages and valid renderer receipts; source or implementation changes invalidate dependent work. Each output directory is locked against concurrent runs. A crash can leave `workflow.lock`; inspect its PID and confirm the process has ended before removing that lock. Complete output packages remain under the chosen `--package` path; internal drafts and reports remain in `--output`.

Registered course packages are immutable evidence. Even prepare mode checks the registry before writing the final candidate and refuses a changed hash. An identical package preserves existing bytes. Changing registered course content requires an explicit revision/migration workflow; this entrypoint does not implement an update engine. Unregistered local candidates may be regenerated normally.

Runtime selection is `--python` / `RBI_PYTHON` / known bundled Python, `--tectonic` / `RBI_TECTONIC` / `CODEX_TECTONIC_PATH` / PATH, and `--pdftoppm` / `RBI_PDFTOPPM` / known bundled Poppler / PATH. `--workers` defaults to 1. The external prerequisite closure forwards `--include-external-prerequisites --external-course-id 109`; absent progress forwards `--allow-missing-progress`; unreliable source unit labels can use `--unit-labels numeric`.

Explicit `import` mode runs preparation first, then uses `src/cli.mjs status/prepare/start/job`. It requires `--expected-kb-id`, validates the live KB, registers the course/package/destination before starting, and polls the same job. Add `--parent-rem-id` only for a specific destination. The default registry is `D:/AppData/RemNoteBulkImporter/course-workflow-registry.json`. The service's own known jobs are checked to prevent a different package hash from silently creating a second course root. A timeout or interruption preserves the job; inspect service diagnostics and fence any timed-out mutation before rerunning. `--poll-ms` and `--max-polls` bound polling without stopping an active native job.

Adopt an existing fully verified import without conversion or RemNote writes:

```powershell
node consumers/course-workflow.mjs adopt --course-id 154 --adopt-job-id c537b74d26cc69b3fccea2119fd44ab417138233e3f8834b71ac0d9b2e0ca34b --expected-kb-id 6890492bda670f6536424bb2
```

Adoption reads the existing job through the CLI, requires complete exact readback and matching course/KB/destination, and records its original root. It never prepares, starts, edits or rebuilds that course. Existing completed courses should be adopted before new import activity.

Run the independent workflow tests with `node --test test/course-workflow.test.mjs`. Tests use isolated fixtures, exercise stage invalidation and fallback regeneration, and mock the CLI to verify adoption and duplicate prevention without RemNote writes.
