# RemNote Bulk Importer

Independent RemNote SDK plugin and loopback MCP service for source-neutral bulk imports. Preserve its isolation from the existing Automation Bridge and its ports.

- Source: this repository. Artifacts: `D:/Artifacts/RemNoteBulkImporter`; state: `D:/AppData/RemNoteBulkImporter`; caches: `D:/Caches/RemNoteBulkImporter`.
- Node ESM + TypeScript SDK adapter; built-in Node tests. MA conversion is a separate Python consumer with Pillow; math audit uses KaTeX and SVG fallback uses resvg.
- Run `npm test`, `npm run typecheck`, `npm run build`; official validation: `node node_modules/@remnote/plugin-sdk/scripts/index.js validate`.
- `npm start` serves localhost plugin assets and MCP on 43106. `node src/cli.mjs status|prepare|start|job|pause` is a normal MCP client.
- Plugin is installed and real canaries passed. Use live job receipts to determine production course state; never infer completion from a build or a prepared package.
- Before writes confirm the live knowledge-base identity. Imported package hash, parent and library identity must match the saved checkpoint on resume.
- Import only into a new owned subtree. Never delete existing Rems, alter old plugin/config files, fabricate answers or silently recreate edited/deleted imported material.
- On pipeline failures revise the generic workflow and regenerate from original inputs. Preserve input snapshots and all valid render/readback receipts; do not patch candidate course content by hand.
- Keep learner records, source archives, generated packages, images, imported Rem IDs, checkpoint stores and private source data out of Git. Human-facing course text must not carry operational IDs/hashes/paths.
- The user has authorized all course Topics, full available lesson content and prerequisites; missing original question/image content stays explicitly marked. This does not authorize RemNote writes outside this course/test scope or global memory updates.
- Keep cloud-sync and managed-media claims separate from local RichText byte readback. Existing bridge get_media cannot retrieve embedded data-URL images.
