import path from 'node:path';
import {homedir} from 'node:os';
import {readdir,realpath,stat,readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';

export async function managedMediaRoots(){
  const base=path.join(homedir(),'remnote');
  try{return (await readdir(base,{withFileTypes:true})).filter(x=>x.isDirectory()&&x.name.startsWith('remnote-')).map(x=>path.join(base,x.name,'files'));}
  catch(e){if(e.code==='ENOENT')return [];throw e;}
}
export async function verifyManagedImage(locator,asset,roots){
  if(typeof locator!=='string'||!locator.startsWith('%LOCAL_FILE%'))throw new Error('Managed image locator required');
  const name=decodeURIComponent(locator.slice('%LOCAL_FILE%'.length));
  if(!name||name==='.'||name==='..'||name.includes('\0')||/[\\/]/.test(name)||path.basename(name)!==name)throw new Error('Managed image path traversal rejected');
  let match=null;
  for(const root of roots){
    try{
      const resolvedRoot=await realpath(root),file=await realpath(path.join(root,name));
      if(path.dirname(file)!==resolvedRoot)throw new Error('Managed image escaped allowed directory');
      const metadata=await stat(file);if(!metadata.isFile()||metadata.size>32*1024*1024)throw new Error('Managed image is not a bounded file');
      const bytes=await readFile(file),hash=createHash('sha256').update(bytes).digest('hex');
      if(hash!==asset.sha256)throw new Error('Managed image bytes differ from package');
      const result={sha256:hash,sizeBytes:bytes.length,mime:asset.mime};
      if(match&&match.sha256!==result.sha256)throw new Error('Ambiguous managed image');match=result;
    }catch(e){if(e.code==='ENOENT'||e.code==='ENOTDIR')continue;throw e;}
  }
  if(!match)throw new Error('Managed image file is not yet available');return match;
}
