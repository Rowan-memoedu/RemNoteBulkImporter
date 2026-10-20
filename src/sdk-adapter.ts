import type { ReactRNPlugin, RichTextInterface } from '@remnote/plugin-sdk';
import { stableJSON, sha256 } from './package.mjs';
import { checkpointStore } from './checkpoint.mjs';
import { sdkTransaction } from './sdk-transaction.mjs';
import { nativeImage } from './native-image.mjs';
import { describeRich } from './rich-diagnostic.mjs';
import { imageReadbackCompatibility } from './rich-compat.mjs';
import { imageTransportHashMatches } from './rich-hash.mjs';
import { expectedReferenceTargets } from './expected-refs.mjs';

export function sdkAdapter(plugin: ReactRNPlugin, kbId: string, monitor: any, verifyMedia: any, packageAssets: any={}) {
  const call=monitor.call;
  const compatibility=imageReadbackCompatibility(packageAssets,{
    loadCached:(hash:string)=>call('storage.getLocal',()=>plugin.storage.getLocal(`rbi-image:${kbId}:${hash}`)),
    verify:(id:string,url:string)=>call('media.verify',()=>verifyMedia(id,url)),
  });
  const checkpoints=checkpointStore({
    getLocal:(key:string)=>call('storage.getLocal',()=>plugin.storage.getLocal(key)),
    setLocal:(key:string,value:any)=>call('storage.setLocal',()=>plugin.storage.setLocal(key,value)),
  },kbId);
  const adapter = {
    preserveExternalChildren:true,
    context: monitor.setContext,
    kbId: async () => (await call('kb.getCurrentKnowledgeBaseData',()=>plugin.kb.getCurrentKnowledgeBaseData()))._id,
    load: checkpoints.load,
    save: checkpoints.save,
    find: (id: string) => call('rem.findOne',()=>plugin.rem.findOne(id)),
    findMany: (ids: string[]) => call('rem.findMany',()=>plugin.rem.findMany(ids)),
    findSentinel: (title: string,parent: string|null) => call('rem.findByName',()=>plugin.rem.findByName([title],parent)),
    createSentinel: async (title: string,parent: string|null,document: boolean) => {
      const rem = await call('rem.createRem',()=>plugin.rem.createRem());
      if(!rem) throw new Error('SDK createRem returned no Rem');
      const position = parent ? (await call('rem.findOne',()=>plugin.rem.findOne(parent)))?.children?.length ?? 0 : undefined;
      await call('rem.setText',()=>rem.setText([title]));
      await call('rem.setParent',()=>rem.setParent(parent,position));
      await call('rem.setIsDocument',()=>rem.setIsDocument(document));
      await call('rem.setEnablePractice',()=>rem.setEnablePractice(false));
      return rem;
    },
    transaction: <T>(fn:()=>Promise<T>) => call('app.transaction',()=>sdkTransaction((wrapped:any)=>plugin.app.transaction(wrapped),fn),180000),
    compile: async (segments: any[], mapping: Record<string,string>, assets: Record<string,any>, legacyImages=false) => {
      const result: RichTextInterface = [];
      for(const s of segments) {
        let part: RichTextInterface;
        switch(s.kind) {
          case 'text': part=[s.value];break;
          case 'markdown': part=await call('richText.parseFromMarkdown',()=>plugin.richText.parseFromMarkdown(s.value));break;
          case 'code': part=await call('richText.code',()=>plugin.richText.code(s.value,'text').value());break;
          case 'latex': part=await call('richText.latex',()=>plugin.richText.latex(s.value,s.block).value());break;
          case 'ref': {
            if(!mapping[s.targetId]) throw new Error(`Unmapped reference ${s.targetId}`);
            part=await call('richText.rem',()=>plugin.richText.rem(mapping[s.targetId]).value());break;
          }
          case 'image': {
            const a=assets[s.assetId];
            if(legacyImages){part=await call('richText.legacyImage',()=>plugin.richText.image(`data:${a.mime};base64,${a.base64}`).value());break;}
            const image=await nativeImage(s.assetId,a,{
              get:(hash:string)=>call('storage.getLocal',()=>plugin.storage.getLocal(`rbi-image:${kbId}:${hash}`)),
              set:(hash:string,value:any)=>call('storage.setLocal',()=>plugin.storage.setLocal(`rbi-image:${kbId}:${hash}`,value)),
              parse:(markdown:string)=>call('richText.uploadImage',()=>plugin.richText.parseFromMarkdown(markdown)),
              verify:(assetId:string,url:string)=>call('media.verify',()=>verifyMedia(assetId,url)),
            });
            compatibility.register(s.assetId,image);part=[image];break;
          }
          default: throw new Error('Unsupported RichText segment');
        }
        result.push(...part);
      }
      return result;
    },
    canonical: async (rich: RichTextInterface) => {
      try{const input=await compatibility.input(rich);return stableJSON(await call('richText.normalize',()=>plugin.richText.normalize(input)));}
      catch(error){
        const failures=[];
        if(Array.isArray(rich))for(let index=0;index<Math.min(rich.length,200);index++){
          try{await call('richText.diagnoseElement',()=>plugin.richText.normalize([rich[index]]));}
          catch(e){failures.push({index,error:String(e)});}
        }
        monitor.setContext({...monitor.snapshot().context,richDiagnostic:describeRich(rich),elementFailures:failures});
        throw error;
      }
    },
    setText: (rem:any,rich:RichTextInterface) => call('rem.setText',()=>rem.setText(rich)),
    matchesExpected: async (rich:RichTextInterface,expected:string) => {const input=await compatibility.input(rich);return imageTransportHashMatches(await call('richText.normalize',()=>plugin.richText.normalize(input)),expected);},
    move: (rem:any,parent:string,index:number) => call('rem.setParent',()=>rem.setParent(parent,index)),
    disablePractice: (rem:any) => call('rem.setEnablePractice',()=>rem.setEnablePractice(false)),
    practiceEnabled: (rem:any) => call('rem.getEnablePractice',()=>rem.getEnablePractice()),
    isDocument: (rem:any) => call('rem.isDocument',()=>rem.isDocument()),
    refs: async (rem:any) => {const rich=await compatibility.input(rem.text??[]);return call('richText.getRemIdsFromRichText',()=>plugin.richText.getRemIdsFromRichText(rich));},
    expectedRefs: async (node:any,mapping:Record<string,string>) => expectedReferenceTargets(node,mapping,{
      parse:(markdown:string)=>call('richText.parseExpectedMailto',()=>plugin.richText.parseFromMarkdown(markdown)),
      refs:(rich:RichTextInterface)=>call('richText.expectedMailtoTargets',()=>plugin.richText.getRemIdsFromRichText(rich)),
    }),
    // Snapshot children can lag after app reloads. Use the authoritative ordered
    // SDK read for an audit, matching the application's actual tree.
    children: async (rem:any) => (await call('rem.getChildrenRem',()=>rem.getChildrenRem())).map((child:any)=>child._id),
    diagnoseMismatch: async (node:any,mapping:any,assets:any,rich:any,expected:string) => {
      const original=await adapter.compile(node.text,mapping,assets,true),actual=await compatibility.input(rich);
      const canonicalOriginal=await adapter.canonical(original),canonicalActual=await adapter.canonical(actual);
      monitor.setContext({...monitor.snapshot().context,comparison:{expected,originalHash:await sha256(canonicalOriginal),actualHash:await sha256(canonicalActual),original:describeRich(original),actual:describeRich(actual)}});
    },
  };
  return adapter;
}
