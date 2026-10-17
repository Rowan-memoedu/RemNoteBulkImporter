# RemNote Bulk Importer

Independent RemNote SDK plugin and loopback MCP service for source-neutral bulk imports. Preserve its isolation from the existing Automation Bridge and its ports.

- Source: this repository. Artifacts: `D:/Artifacts/RemNoteBulkImporter`; state: `D:/AppData/RemNoteBulkImporter`; caches: `D:/Caches/RemNoteBulkImporter`.
- Node ESM + TypeScript SDK adapter; built-in Node tests. MA conversion is a separate Python consumer with Pillow; math audit uses KaTeX and SVG fallback uses resvg.
- Run `npm test`, `npm run typecheck`, `npm run build`; official validation: `node node_modules/@remnote/plugin-sdk/scripts/index.js validate`.
- `npm start` serves localhost plugin assets and MCP on 43106. `node src/cli.mjs status|prepare|start|job|pause|restructure` is a normal MCP client.
- Earlier installed versions passed real canaries, including the 0.1.5 managed-image stress canary. Production readback and final restructuring status must come from job receipts, never a build or prepared package.
- Before writes confirm the live knowledge-base identity. Imported package hash, parent and library identity must match the saved checkpoint on resume.
- Status includes current SDK call/node and timeout diagnostics. A timed-out mutation may finish late; reload the fenced plugin instance before resuming, never retry it concurrently.
- Import only into a new owned subtree. Never delete existing Rems, alter old plugin/config files, fabricate answers or silently recreate edited/deleted imported material.
- On pipeline failures revise the generic workflow and regenerate from original inputs. Preserve input snapshots and all valid render/readback receipts; do not patch candidate course content by hand.
- Keep learner records, source archives, generated packages, images, imported Rem IDs, checkpoint stores and private source data out of Git. Human-facing course text must not carry operational IDs/hashes/paths.
- The final course must use Course → 13 Unit documents → 46 Module documents → 294 Topic documents; remove duplicate unit/module metadata from Topic bodies by reversible archiving. Preserve Topic Rem IDs and references.
- Every course Document (root, Unit, Module and Topic) and every owned direct non-document content child must begin with one “批注” branch containing exactly two empty leaves. This includes lecture/example/question headings and prerequisite/source notes, excludes existing annotation branches and non-imported portals. Prepare through the generic layout stage outside RemNote; preserve existing annotation IDs and all content.
- The user has authorized all course Topics, full available lesson content and prerequisites; missing original question/image content stays explicitly marked. This does not authorize RemNote writes outside this course/test scope or global memory updates.
- Native images use the official Markdown parser upload path and byte-exact managed-file verification in this independent local MCP. Older imported data-URL images remain covered by their original RichText hashes with strict read-only compatibility for omitted undefined geometry or verified automatic natural-size metadata. Keep cloud-sync claims separate from local verification.
- Poll active jobs through CLI/MCP service memory. Do not read active receipt files with tools that briefly deny Windows delete-sharing.
