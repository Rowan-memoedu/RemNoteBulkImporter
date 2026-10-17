# RemNote Bulk Importer

Independent personal RemNote plugin and loopback MCP service for importing a prepared, source-neutral document tree in one resumable job. It does not depend on or modify RemNote MCP Automation Bridge.

Source: `D:/Projects/RemNoteBulkImporter`. Build artifacts: `D:/Artifacts/RemNoteBulkImporter`. Runtime state: `D:/AppData/RemNoteBulkImporter`. Imported course data and private knowledge-base contents stay outside Git.

## Import contract

- Validate the entire package before writing; use package-local stable node IDs and references.
- Create real documents and RichText references using the official RemNote plugin SDK.
- Limit concurrency, checkpoint small transactions, resume the same immutable package, and reject changed inputs or knowledge-base identity.
- Create only a new import subtree. Never overwrite pre-existing user material or generate practice cards.
- Report completion only after readback checks document flags, hierarchy, order, text, images, and reference targets.
- One external import submission runs internal SDK operations incrementally; it does not bypass RemNote rate limits or promise a single global transaction.

Initial consumer: a local Math Academy course export. Conversion remains separate from the generic importer.

## Install locally

Requires Node 22+ and the official RemNote plugin SDK. `npm ci` restores pinned dependencies.

1. `npm run build` writes only to `D:/Artifacts/RemNoteBulkImporter/plugin`.
2. `npm start` serves plugin assets and the independent MCP endpoint on loopback port **43106**. It never connects to the old bridge on 43101/43102/43103.
3. In RemNote's developer-plugin entry (Settings → Plugins → Build → Develop from localhost), add `http://localhost:43106`. The official installation UI wording may vary by RemNote version. Installing this plugin is a one-time manual step; the existing RemNote MCP does not expose plugin installation.
4. `node src/cli.mjs status` verifies the loaded plugin version and active knowledge base. A subsequent build does not prove that RemNote has reloaded it. The service rejects imports from an older loaded plugin; reload the developer plugin before resuming. The existing MCP does not expose plugin reload.

The plugin uses native commands/toasts instead of a custom web control panel. `rbi` in RemNote's command menu shows connection status. SDK permission is Read/Create/Modify plus knowledge-base identity; no delete permission is requested. Disable the plugin and stop this one local process to unload it; imported data remains in RemNote.

## Prepare and import

Place a source-neutral package in `D:/Artifacts/RemNoteBulkImporter/packages`, then run:

```powershell
node src/cli.mjs prepare D:/Artifacts/RemNoteBulkImporter/packages/example.json
node src/cli.mjs start <jobId> [destinationParentRemId]
node src/cli.mjs job <jobId>
node src/cli.mjs pause <jobId>
node src/cli.mjs restructure <completedBaseJobId> <structurePackagePath> <recoveryParentRemId>
```

Omit destinationParentRemId to create a new top-level document. `prepare` is read-only with respect to RemNote. `start` submits the whole immutable package once; the server returns immediately and the plugin runs bounded SDK batches. Resume a paused/interrupted/failed task with the same `start` command. Do not change knowledge base or destination during a task.

The MCP endpoint is `http://127.0.0.1:43106/mcp`. Tool names: `bulk_import_status`, `bulk_import_prepare`, `bulk_import_start`, `bulk_import_job`, `bulk_import_pause`, `bulk_import_restructure`. The CLI is a normal MCP client, not a second import implementation. Job receipts and immutable packages live in `D:/AppData/RemNoteBulkImporter`. Browser origins cannot invoke MCP; the WebSocket accepts only the local plugin and official RemNote origins. No server listens on the LAN.

## Package v1

```json
{
  "schemaVersion": 1,
  "packageId": "my-source.stable-export-id",
  "title": "Imported document",
  "nodes": [
    {"id":"topic-a","parentId":null,"document":true,"text":[{"kind":"text","value":"Topic A"}]},
    {"id":"pre-a","parentId":"topic-a","document":false,"text":[{"kind":"text","value":"Prerequisite: "},{"kind":"ref","targetId":"topic-b"}]},
    {"id":"topic-b","parentId":null,"document":true,"text":[{"kind":"text","value":"Topic B"}]}
  ]
}
```

Parents must appear before children; references may target later nodes. Array order is sibling order. All references resolve by package-local ID, never by title. Supported text segments are `text`, `markdown`, `latex` (`block`: boolean), `code`, `ref` (`targetId`), and `image` (`assetId`). Images must be embedded PNG/JPEG/WebP/GIF assets with matching MIME, base64 bytes and SHA-256. SVG is intentionally not accepted as executable input; rasterize diagrams outside RemNote. The package allows source provenance as opaque JSON; it never executes source text or interprets it as instructions.

Full readback checks every imported node's RichText hash, parent, document flag, direct child order, disabled practice state and exact reference targets. Incomplete/edited/missing nodes fail the audit instead of producing a success receipt. Current limits: 100,000 nodes, 64 MiB text and 256 MiB decoded assets. One long global transaction is intentionally avoided because the SDK warns that it can block RemNote.

The live SDK adapter preserves additional non-imported children (for example a user-added reference portal). Full readback still requires every imported ID under its exact parent, with exact content and relative sibling order. External children are recorded separately in the completion receipt. Restructuring preserves their parent, identity and sibling slots; misplaced owned Rems remain audit failures. The generic engine defaults to strict child equality unless the adapter explicitly enables this preservation policy.

## Recovery boundaries

Small creation transactions use deterministic temporary sentinel titles. A committed creation followed by checkpoint failure can be recovered by sentinel under its exact owned parent. Titles become final only after all node IDs are recorded. If a user edits or deletes an imported node, resuming stops before overwriting it. A failed task can leave its newly created partial subtree in place; it does not delete it automatically. Preserve plugin-local checkpoint data while an import is incomplete. Uninstalling a plugin or clearing local data is not a supported checkpoint recovery method.

Version 0.1.1 validates existing mapped IDs with SDK `findMany` in batches of 128. Checkpoints use append-only pages of 256 entries and commit compact metadata last. Only changed tail pages are rewritten. The original full checkpoint remains as the migration source; it is never deleted during recovery. Tests cover migration and a failed metadata commit. These changes reduce resume and checkpoint overhead; they do not establish the cause of an application restart.

Version 0.1.2 exposes current SDK call, elapsed time and import-node context through status. Individual SDK calls have a 60-second limit; a whole small transaction has a 180-second limit. A timeout fences further import calls in that plugin instance until reload, because a pending mutation might still complete. It never retries a timed-out mutation automatically. Completion still requires the unchanged full readback audit.

The earlier plugin passed real RemNote canaries for document flags, references, multiline text, math, formatting and an embedded 116,856-byte PNG. The full course then exposed RemNote's per-Rem synchronization-size limit when several embedded images shared one Rem. From 0.1.4, the official Markdown image parser uploads each asset and returns a managed `%LOCAL_FILE%` image object. The complete native object is retained and cached by knowledge base and source SHA-256. The independent local MCP service hashes the actual managed file in RemNote's existing media directories and rejects mismatched bytes or paths outside those directories. No old bridge dependency is added. Cross-device synchronization requires separate verification.

SDK transaction callback errors are captured, acknowledged by the host, and rethrown outside the callback. This prevents a callback rejection from concealing the real SDK error. Partial committed writes remain recoverable; the adapter does not assume host rollback.

`restructure` accepts a completed owned import and a new immutable package with identical retained text, reference targets and assets. It verifies the entire base, adds plain-text documents or nodes (including empty annotation leaves), reparents existing Rem IDs, and moves obsolete unreferenced plain leaf metadata beneath an explicit recovery parent outside the course. It never deletes those nodes. Checkpoints recover committed moves, and the final result requires the same full-node readback as an ordinary import. Current MA hierarchy is Course → Unit documents → Module documents → Topic documents.

Readback uses the authoritative SDK `getChildrenRem()` ordering rather than potentially stale snapshot children. It fetches snapshots in `findMany` batches of 128 and checks at most four nodes concurrently; failed reads drain outstanding work before reporting failure. Read batching is independent of the small mutation transaction limit, reducing fixed yield waits in hidden plugin frames. All original checks remain mandatory, and completion progress advances only after the whole batch passes. A fully written import proceeds directly to full readback, avoiding a redundant existence scan. Job polling reads MCP service memory; Windows atomic receipt writes retry bounded sharing conflicts without deleting the destination.

Version 0.1.8 accommodates observed image serialization states in a read-only projection. SDK image objects can contain explicit undefined geometry keys that JSON transport omits; the app may subsequently add exact natural width/height and `percent: 0`, which the current SDK validator rejects. The projection restores the original builder shape only for exact package image bytes and verified natural dimensions. For omitted undefined width/height pairs, the verifier tests only equivalent key-presence states against the original checkpoint hash; a changed text, formula, reference, URL, title or actual size cannot pass this check. Managed image bytes are independently checked against their source SHA-256, and their parser metadata is retained. Neither live RichText nor source packages are rewritten.

`node scripts/annotate-documents.mjs <immutable-package> <new-package>` supports the earlier document-only layout: a “批注” branch under every document, including the root, with exactly two empty leaves each. Preparation runs outside RemNote and retains the original package. `auditAnnotations()` verifies those branches and rejects nonempty or duplicate leaves. The earlier MA document-only stage contained 354 annotation branches and 708 empty leaves.

The current layout uses `node scripts/layout-annotations.mjs <immutable-package> <new-package>`: each Document and each owned direct non-document content child starts with “批注” and two empty leaves. Existing annotation IDs, text and all other content remain unchanged. The MA layout covers 354 Documents and 3,875 document-level content headings (including lessons, examples, exercises, prerequisites and source notes): 4,229 annotation branches and 8,458 empty leaves. Running from the original hierarchy package or the completed document-only annotation package produces the same immutable result. External user portals are outside this preparation scope.

Version 0.1.9 creates added plain-text nodes in batches of 16 with separate durable mapping and text checkpoints. Committed creation batches recover by exact sentinel and parent; committed text batches accept only identical text. Reordering compares parent child lists even when no nodes change parent, and moves only children whose current positions differ. The final whole-import audit remains mandatory.

## Validation

`npm test`, `npm run typecheck`, and `node node_modules/@remnote/plugin-sdk/scripts/index.js validate`.

The engine tests cover forward and cyclic content references, hierarchy/order, pause/resume, create-commit/checkpoint failure, write-commit/checkpoint failure, SDK rollback, duplicate rejection, knowledge-base changes, edited/missing notes and exact readback. A separate transport integration test exercises a real MCP client, HTTP transport and WebSocket; it uses a simulated plugin, not a real RemNote knowledge base. `npm run canary` prepares a seven-node test package with two Topic documents, a reference, a native formula, a multiline Rem, formatting and an embedded PNG. Import it only after installing the plugin.

The 0.1.9 suite has 54 passing tests, including batched structure creation, partial ordering transactions, failed-checkpoint recovery, order-only changes, annotation placement and exact preservation of retained IDs and content. Ordering uses small transactions and batches metadata checkpoints, re-reading committed positions after interruptions. Its independent live 44-node canary passed complete readback; the original MCP independently confirmed all 11 annotation parents begin with the annotation branch. The live course's private receipts and independent readbacks stay under the D: artifact/state roots rather than in Git.

## Math Academy consumer

`consumers/math_academy.py` converts the supplied course graph, progress snapshots and lesson JSON into the generic package. It reads the provided answer archive only to recover matching question/graphic source; learner names, history and progress values are not imported. Source exports, graphics and evidence remain under `D:/Artifacts/RemNoteBulkImporter`, never in Git.

- `convert`: validates course identities across graph and progress, creates nested Unit/Module/Topic documents in source order, creates package-local prerequisite references, and retains original lesson JSON separately. Unit/module descriptions are represented by document hierarchy rather than duplicate metadata under each Topic.
- MathJax-rendered HTML with original LaTeX in SVG titles is preferred where available, because some `[math]` strings in the source export are damaged. Unsupported/legacy syntax is mechanically converted without changing mathematical payloads. The brace-aware delimiter scanner preserves nested math inside text macros. Original notation can fall back to its supplied SVG when native KaTeX cannot represent it.
- Unpublished HTML comments, styles and scripts remain in source exports and are excluded from readable lesson text. Missing question bodies/images get explicit local placeholders; standard answers are never inferred from option order.
- Paragraph breaks are preserved inside native multiline Rems; titles, examples, question/answer fields, options and prerequisite branches keep their logical hierarchy. Human-facing course text contains no operational IDs, paths, hashes or audit receipts.
- `render`: uses existing Tectonic with `--untrusted`, hash-addressed work directories and D: caches; rasterizes PDFs with Poppler/Pillow. Independent panels can be shipped separately when TeX runs out of page memory. A faceted-coloring fallback retains sampled coordinates, mesh, labels and equations when interpolated shading exceeds engine memory. Every such transformation is recorded beside the source image, and successful renders are reused.
- `pack`: requires all referenced drawing outputs, embeds image bytes and hashes, and writes a generic package. `consumers/audit-math.mjs` validates every native expression using KaTeX; its failure report can feed original-SVG fallback with `--math-audit`.
- `audit`: independently compares the finished package against source Topic identities, prerequisite edges and every lesson step; verifies that math audit counts and image digests still match the package. Packing rejects unhandled conversion loss and missing drawing receipts.

The converter uses the bundled desktop Python runtime (Pillow), existing Tectonic and Poppler paths. No full TeX Live installation is required. Run its independent fixtures with the bundled Python:

```powershell
<bundled-python> -m unittest discover -s test -p test_ma_conversion.py -v
```

The current local course package audit is `D:/Artifacts/RemNoteBulkImporter/course-154/package-audit.json`. It verifies all source Topic identities, direct prerequisite edges and lesson steps separately from the generic SDK readback. Runtime completion is tracked by the MCP job; a prepared package or a successful conversion audit is not a completed RemNote import.

Official references: [Rem API](https://plugins.remnote.com/advanced/rem_api), [RichText](https://plugins.remnote.com/advanced/rich_text), [SDK changelog and transaction warning](https://plugins.remnote.com/CHANGELOG), [local plugin setup](https://plugins.remnote.com/getting-started/quick_start_guide).
