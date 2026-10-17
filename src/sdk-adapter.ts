import type { ReactRNPlugin, RichTextInterface } from '@remnote/plugin-sdk';
import { stableJSON } from './package.mjs';

export function sdkAdapter(plugin: ReactRNPlugin, kbId: string) {
  return {
    kbId: async () => (await plugin.kb.getCurrentKnowledgeBaseData())._id,
    load: async (hash: string) => plugin.storage.getLocal<any>(`rbi:${kbId}:${hash}`),
    save: async (hash: string, cp: any) => plugin.storage.setLocal(`rbi:${kbId}:${hash}`,cp),
    find: (id: string) => plugin.rem.findOne(id),
    findSentinel: (title: string,parent: string|null) => plugin.rem.findByName([title],parent),
    createSentinel: async (title: string,parent: string|null,document: boolean) => {
      const rem = await plugin.rem.createRem();
      if(!rem) throw new Error('SDK createRem returned no Rem');
      const position = parent ? (await plugin.rem.findOne(parent))?.children?.length ?? 0 : undefined;
      await rem.setText([title]);
      await rem.setParent(parent,position);
      await rem.setIsDocument(document);
      await rem.setEnablePractice(false);
      return rem;
    },
    transaction: <T>(fn:()=>Promise<T>) => plugin.app.transaction(fn),
    compile: async (segments: any[], mapping: Record<string,string>, assets: Record<string,any>) => {
      const result: RichTextInterface = [];
      for(const s of segments) {
        let part: RichTextInterface;
        switch(s.kind) {
          case 'text': part=[s.value];break;
          case 'markdown': part=await plugin.richText.parseFromMarkdown(s.value);break;
          case 'code': part=await plugin.richText.code(s.value,'text').value();break;
          case 'latex': part=await plugin.richText.latex(s.value,s.block).value();break;
          case 'ref': {
            if(!mapping[s.targetId]) throw new Error(`Unmapped reference ${s.targetId}`);
            part=await plugin.richText.rem(mapping[s.targetId]).value();break;
          }
          case 'image': {
            const a=assets[s.assetId];
            part=await plugin.richText.image(`data:${a.mime};base64,${a.base64}`).value();break;
          }
          default: throw new Error('Unsupported RichText segment');
        }
        result.push(...part);
      }
      return result;
    },
    canonical: async (rich: RichTextInterface) => stableJSON(await plugin.richText.normalize(rich)),
    setText: (rem:any,rich:RichTextInterface) => rem.setText(rich),
    disablePractice: (rem:any) => rem.setEnablePractice(false),
    practiceEnabled: (rem:any) => rem.getEnablePractice(),
    isDocument: (rem:any) => rem.isDocument(),
    refs: (rem:any) => plugin.richText.getRemIdsFromRichText(rem.text ?? []),
    children: async (rem:any) => (await rem.getChildrenRem()).map((r:any)=>r._id),
  };
}
