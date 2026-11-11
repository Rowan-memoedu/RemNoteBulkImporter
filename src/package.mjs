/** Source-neutral package validation. No source text is interpreted as instructions. */
export function stableJSON(value) {
  if (Array.isArray(value)) return `[${value.map(stableJSON).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.keys(value).sort().map(k => `${JSON.stringify(k)}:${stableJSON(value[k])}`).join(',')}}`;
  return JSON.stringify(value);
}

function check(ok, message) { if (!ok) throw new Error(message); }
function exactKeys(obj, allowed, path) {
  check(obj && typeof obj === 'object' && !Array.isArray(obj), `${path}: expected object`);
  for (const k of Object.keys(obj)) check(allowed.includes(k), `${path}: unknown field ${k}`);
}
function identifier(s) { return typeof s === 'string' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,149}$/.test(s); }

export function validatePackage(plan) {
  exactKeys(plan, ['schemaVersion','packageId','title','nodes','assets','provenance'], 'package');
  check(plan.schemaVersion === 1, 'Unsupported schemaVersion');
  check(identifier(plan.packageId), 'Invalid packageId');
  check(typeof plan.title === 'string' && plan.title.trim() && plan.title.length <= 1000, 'Invalid package title');
  check(Array.isArray(plan.nodes) && plan.nodes.length > 0 && plan.nodes.length <= 100000, 'Expected 1..100000 nodes');
  const ids = new Set(), ordered = [], byId = new Map(), assets = plan.assets ?? {};
  exactKeys(assets, Object.keys(assets), 'assets');
  let assetBytes = 0, textChars = 0, refs = 0, documents = 0, mermaid = 0;
  for (const [id, asset] of Object.entries(assets)) {
    check(identifier(id), 'Invalid asset ID');
    exactKeys(asset, ['mime','base64','sha256'], `asset ${id}`);
    check(['image/png','image/jpeg','image/webp','image/gif'].includes(asset.mime), `asset ${id}: unsupported MIME`);
    check(typeof asset.base64 === 'string' && asset.base64.length > 0 && asset.base64.length % 4 === 0 && /^[A-Za-z0-9+/]*={0,2}$/.test(asset.base64), `asset ${id}: invalid base64`);
    check(typeof asset.sha256 === 'string' && /^[a-f0-9]{64}$/.test(asset.sha256), `asset ${id}: missing sha256`);
    assetBytes += asset.base64.length * 3 / 4;
  }
  check(assetBytes <= 256 * 1024 * 1024, 'Assets exceed 256 MiB');
  for (const node of plan.nodes) {
    exactKeys(node, ['id','parentId','document','text'], 'node');
    check(identifier(node.id) && !ids.has(node.id), `Duplicate/invalid node ID: ${node.id}`);
    check(node.parentId === null || ids.has(node.parentId), `${node.id}: parent must appear earlier in package`);
    check(typeof node.document === 'boolean', `${node.id}: document must be boolean`);
    check(Array.isArray(node.text) && node.text.length > 0 && node.text.length <= 20000, `${node.id}: invalid text segments`);
    for (const s of node.text) {
      check(s && typeof s === 'object', `${node.id}: invalid segment`);
      switch(s.kind) {
        case 'text': case 'markdown': case 'code':
          exactKeys(s, ['kind','value'], node.id);
          check(typeof s.value === 'string', `${node.id}: segment value must be string`);
          // Inline references and media have dedicated typed segments; markdown must not bypass them.
          if (s.kind === 'markdown') check(!/!\[|\[\[|<img|data:|file:\/\//i.test(s.value), `${node.id}: use typed image/reference segments`);
          textChars += s.value.length; break;
        case 'latex':
          exactKeys(s, ['kind','value','block'], node.id);
          check(typeof s.value === 'string' && typeof s.block === 'boolean', `${node.id}: invalid latex`);
          textChars += s.value.length; break;
        case 'mermaid':
          exactKeys(s, ['kind','value'], node.id);
          check(!node.document && node.text.length === 1, `${node.id}: Mermaid requires its own outline node`);
          check(typeof s.value === 'string' && s.value.trim(), `${node.id}: Mermaid source is empty`);
          textChars += s.value.length; mermaid++; break;
        case 'ref':
          exactKeys(s, ['kind','targetId'], node.id);
          check(identifier(s.targetId), `${node.id}: invalid reference`); refs++; break;
        case 'image':
          exactKeys(s, ['kind','assetId'], node.id);
          check(Object.hasOwn(assets,s.assetId), `${node.id}: missing asset ${s.assetId}`); break;
        default: throw new Error(`${node.id}: unsupported segment kind ${s.kind}`);
      }
    }
    ids.add(node.id); ordered.push(node); byId.set(node.id,node); documents += Number(node.document);
  }
  check(textChars <= 64 * 1024 * 1024, 'Text exceeds 64 MiB');
  for (const node of ordered) for (const s of node.text) if(s.kind==='ref') check(ids.has(s.targetId), `${node.id}: unresolved reference ${s.targetId}`);
  return {nodes:ordered.length,documents,references:refs,assets:Object.keys(assets).length,assetBytes,textChars,...(mermaid?{mermaid}:{})};
}

export async function sha256(text) {
  const bytes = typeof text === 'string' ? new TextEncoder().encode(text) : text;
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)), b=>b.toString(16).padStart(2,'0')).join('');
}

export async function inspectPackage(plan) {
  const counts = validatePackage(plan);
  for (const [id,asset] of Object.entries(plan.assets ?? {})) {
    const bytes = Uint8Array.from(atob(asset.base64), c=>c.charCodeAt(0));
    check(await sha256(bytes) === asset.sha256, `asset ${id}: hash mismatch`);
    const magic = Array.from(bytes.slice(0,12));
    const valid = asset.mime==='image/png' ? magic.slice(0,8).join(',')==='137,80,78,71,13,10,26,10'
      : asset.mime==='image/jpeg' ? magic[0]===255 && magic[1]===216
      : asset.mime==='image/gif' ? String.fromCharCode(...magic.slice(0,6)).match(/^GIF8[79]a$/)
      : String.fromCharCode(...magic.slice(0,4))==='RIFF' && String.fromCharCode(...magic.slice(8,12))==='WEBP';
    check(valid, `asset ${id}: MIME/signature mismatch`);
  }
  return {hash:await sha256(stableJSON(plan)),...counts};
}
