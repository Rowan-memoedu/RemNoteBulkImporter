# RemNote Bulk Importer

Independent personal RemNote plugin and loopback MCP service for importing a prepared, source-neutral document tree in one resumable job. It does not depend on or modify RemNote MCP Automation Bridge.

Source: `D:/Projects/RemNoteBulkImporter`. Build artifacts: `D:/Artifacts/RemNoteBulkImporter`. Runtime state: `D:/AppData/RemNoteBulkImporter`. Imported course data and private knowledge-base contents stay outside Git.

## Intended contract

- Validate the entire package before writing; use package-local stable node IDs and references.
- Create real documents and RichText references using the official RemNote plugin SDK.
- Limit concurrency, checkpoint small transactions, resume the same immutable package, and reject changed inputs or knowledge-base identity.
- Create only a new import subtree. Never overwrite pre-existing user material or generate practice cards.
- Report completion only after readback checks document flags, hierarchy, order, text, images, and reference targets.
- One external import submission runs internal SDK operations incrementally; it does not bypass RemNote rate limits or promise a single global transaction.

Initial consumer: a local Math Academy course export. Conversion remains separate from the generic importer.
