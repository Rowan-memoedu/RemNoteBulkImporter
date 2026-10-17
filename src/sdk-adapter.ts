import type { ReactRNPlugin, RichTextInterface } from '@remnote/plugin-sdk';
import { stableJSON } from './package.mjs';
import { checkpointStore } from './checkpoint.mjs';
import { sdkTransaction } from './sdk-transaction.mjs';
import { nativeImage } from './native-image.mjs';

export function sdkAdapter(plugin: ReactRNPlugin, kbId: string, monitor: any, verifyMedia: any) {
  const call=monitor.call;
  const checkpoints=checkpointStore({
    getLocal:(key:string)=>call('storage.getLocal',()=>plugin.storage.getLocal(key)),
    setLocal:(key:string,value:any)=>call('storage.setLocal',()=>plugin.storage.setLocal(key,value)),
  },kbId);
  return {
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
    compile: async (segments: any[], mapping: Record<string,string>, assets: Record<string,any>) => {
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
            part=[await nativeImage(s.assetId,a,{
              get:(hash:string)=>call('storage.getLocal',()=>plugin.storage.getLocal(`rbi-image:${kbId}:${hash}`)),
              set:(hash:string,value:any)=>call('storage.setLocal',()=>plugin.storage.setLocal(`rbi-image:${kbId}:${hash}`,value)),
              parse:(markdown:string)=>call('richText.uploadImage',()=>plugin.richText.parseFromMarkdown(markdown)),
              verify:(assetId:string,url:string)=>call('media.verify',()=>verifyMedia(assetId,url)),
            })];break;
          }
          default: throw new Error('Unsupported RichText segment');
        }
        result.push(...part);
      }
      return result;
    },
    canonical: async (rich: RichTextInterface) => stableJSON(await call('richText.normalize',()=>plugin.richText.normalize(rich))),
    setText: (rem:any,rich:RichTextInterface) => call('rem.setText',()=>rem.setText(rich)),
    move: (rem:any,parent:string,index:number) => call('rem.setParent',()=>rem.setParent(parent,index)),
    disablePractice: (rem:any) => call('rem.setEnablePractice',()=>rem.setEnablePractice(false)),
    practiceEnabled: (rem:any) => call('rem.getEnablePractice',()=>rem.getEnablePractice()),
    isDocument: (rem:any) => call('rem.isDocument',()=>rem.isDocument()),
    refs: (rem:any) => call('richText.getRemIdsFromRichText',()=>plugin.richText.getRemIdsFromRichText(rem.text ?? [])),
    // findOne/findMany already returns fresh, ordered child IDs.
    children: async (rem:any) => rem.children ?? [],
  };
}
