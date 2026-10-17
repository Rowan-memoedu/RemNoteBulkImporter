"""Mechanical MA export conversion. Source preservation and import are separate stages.

No network login, external AI, or source-provided command is used. TeX is rendered
with Tectonic --untrusted in hash-addressed artifact directories. Source files are
retained separately from deterministic compatibility transformations.
"""
from __future__ import annotations
import argparse, base64, collections, concurrent.futures, hashlib, html, json, os, re
import subprocess, time, zipfile
from pathlib import Path
from html.parser import HTMLParser
from PIL import Image, ImageChops

TEX = re.compile(r'\\documentclass(?:\[[^\]]*\])?\s*\{[^}]+\}.*?\\end\{document\}',re.S)
IMG = re.compile(r'<img\b[^>]*?\bsrc=[\"\']([^\"\']+)[\"\'][^>]*>',re.I)
CODE_HTML = re.compile(r'<pre\b[^>]*>.*?</pre>|<code\b[^>]*>.*?</code>',re.S|re.I)
MATH = re.compile(r'\[math\](.*?)\[/math\]|\\\[(.*?)\\\]|\\\((.*?)\\\)|\$\$(.*?)\$\$|(?<!\\)\$(?!\$)(.*?)(?<!\\)\$|\\begin\{(align\*?|equation\*?|gather\*?|multline\*?)\}(.*?)\\end\{\6\}',re.S)

def digest(b): return hashlib.sha256(b if isinstance(b,bytes) else b.encode('utf-8')).hexdigest()
def dump(file,obj):
    file.parent.mkdir(parents=True,exist_ok=True)
    file.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')

class ToMarkdown(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.out=[];self.unknown=set()
        self.pre=None;self.inline_code=None;self.code_language='';self.code_blocks=[]
    @staticmethod
    def code_fence(value,minimum):
        return '`'*max(minimum,max((len(m.group())+1 for m in re.finditer(r'`+',value)),default=minimum))
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if self.pre is not None:
            if tag=='br':self.pre.append('\n')
            if tag=='code':
                language=re.search(r'(?:^|\s)language-([\w+-]+)(?:\s|$)',attrs.get('class',''))
                if language:self.code_language=language.group(1)
            return
        if self.inline_code is not None:
            if tag=='br':self.inline_code.append('\n')
            return
        if tag=='pre':self.pre=[];self.code_language=''
        elif tag=='code':self.inline_code=[]
        elif tag=='hr':self.out.append('\n\n')
        elif tag in ['p','div','section','tr','blockquote']: self.out.append('\n\n')
        elif tag in ['h1','h2','h3','h4','h5','h6']:self.out.append('\n\n**')
        elif tag in ['br']: self.out.append('\n')
        elif tag=='li': self.out.append('\n* ')
        elif tag in ['strong','b']: self.out.append('**')
        elif tag in ['em','i']: self.out.append('*')
        elif tag in ['td','th']: self.out.append(' | ')
        elif tag in ['sup','sub']: self.out.append('^(' if tag=='sup' else '_(')
        elif tag=='img': self.out.append(f"MISSING_IMAGE:{attrs.get('src','')}")
        elif tag not in ['span','ul','ol','table','tbody','thead','a','u']:self.unknown.add(tag)
    def handle_endtag(self,tag):
        if self.pre is not None:
            if tag=='pre':
                value=''.join(self.pre);token=f'RBICODEBLOCK{len(self.code_blocks)+1:08d}END'
                self.code_blocks.append({'token':token,'value':value,'language':self.code_language})
                self.out.append('\n\n'+token+'\n\n');self.pre=None
            return
        if self.inline_code is not None:
            if tag=='code':
                value=''.join(self.inline_code);fence=self.code_fence(value,1)
                pad=' ' if value.startswith(('`',' ')) or value.endswith(('`',' ')) else ''
                self.out.append(fence+pad+value+pad+fence);self.inline_code=None
            return
        if tag in ['p','div','section','tr','blockquote']:self.out.append('\n\n')
        elif tag in ['h1','h2','h3','h4','h5','h6']:self.out.append('**\n\n')
        elif tag in ['strong','b']:self.out.append('**')
        elif tag in ['em','i']:self.out.append('*')
        elif tag in ['sup','sub']:self.out.append(')')
    def handle_data(self,data):
        if self.pre is not None:self.pre.append(data)
        elif self.inline_code is not None:self.inline_code.append(data)
        else:self.out.append(data)

def tex_compatible(source):
    # Source-neutral old-MA syntax normalization; originals remain untouched.
    source=source.replace('[math]','$').replace('[/math]','$')
    source=re.sub(r'\\usetkzobj\s*\{all\}','',source)
    if r'\tkzDrawVector' in source:
        # tkz-euclide 4 removed this legacy shorthand; an arrowed segment has
        # the same endpoints and draw options. No coordinates are changed.
        source=source.replace(r'\begin{document}',r'\providecommand{\tkzDrawVector}[1][]{\tkzDrawSegment[->,#1]}'+'\n'+r'\begin{document}',1)
    # Prevent source file IO/shell extensions; only mathematical drawing source is expected.
    if re.search(r'\\(?:input|include|openin|openout|write18|read|immediate|special)\b',source):
        raise ValueError('TeX source contains unsupported file/shell operation')
    return source

def normalize_math_markers(source):
    """Repair repeated opening [math] used as closing marker; preserve payload."""
    opened=False
    def replace(m):
        nonlocal opened
        if m.group()=='[math]':
            if opened:opened=False;return '[/math]'
            opened=True;return '[math]'
        opened=False;return m.group()
    return re.sub(r'\[/?math\]',replace,source)

def split_standalone(source):
    """Ship independent TikZ panels separately to release TeX page memory.
    Panel expressions, coordinates, labels and sampling are left unchanged.
    """
    if source.count(r'\begin{tikzpicture}')<2:return None
    pattern=r'\\documentclass(?:\[([^\]]*)\])?\s*\{standalone\}'
    if not re.search(pattern,source):return None
    return re.sub(pattern,lambda m:r'\documentclass[multi=tikzpicture,'+(m.group(1) or '')+']{standalone}',source,count=1)

def group_end(value,start):
    depth=0;i=start
    while i<len(value):
        if value[i]=='\\':i+=2;continue
        if value[i]=='{':depth+=1
        elif value[i]=='}':
            depth-=1
            if depth==0:return i
        i+=1
    raise ValueError('Unbalanced LaTeX macro group')

def group_macro(value,name,transform):
    pattern=re.compile(r'\\'+name+r'\b\s*(?:\[([^\]]*)\])?\s*\{')
    pos=0
    while True:
        m=pattern.search(value,pos)
        if not m:break
        end=group_end(value,m.end()-1);body=value[m.end():end]
        replacement=transform(body,m.group(1));value=value[:m.start()]+replacement+value[end+1:];pos=m.start()+len(replacement)
    return value

def extract_source_macros(source):
    """Retain field-local zero-argument TeX declarations as explicit context.
    They are formatting instructions, not displayed mathematics. Do not parse
    drawing documents here; callers protect those first. Other definitions stay
    unchanged so the strict native-math audit can reject unsupported syntax.
    """
    pattern=re.compile(r'\\(?:newcommand|renewcommand|providecommand)\s*\{\s*(\\[A-Za-z]+)\s*\}\s*\{')
    macros={};out=[];pos=0
    for m in pattern.finditer(source):
        if m.start()<pos:continue
        end=group_end(source,m.end()-1)
        macros[m.group(1)]=source[m.end():end]
        out.append(source[pos:m.start()]);pos=end+1
    out.append(source[pos:]);return ''.join(out),macros

def expand_source_macros(value,macros):
    for _ in range(32):
        expanded=re.sub(r'\\[A-Za-z]+',lambda m:macros.get(m.group(),m.group()),value)
        if expanded==value:return value
        value=expanded
    raise ValueError('Recursive or excessively nested source math macro')

def latex_compatible(value):
    # Equivalent MathJax/old plain-TeX notation, with all mathematical payloads
    # retained. Raw input and rendered original titles stay in source exports.
    value=value.replace('[math]','$').replace('[/math]','$')
    value=re.sub(r'\\require\s*\{[^}]+\}','',value)
    value=group_macro(value,'eqalign',lambda b,o:r'\begin{aligned}'+b+r'\end{aligned}')
    value=group_macro(value,'matrix',lambda b,o:r'\begin{matrix}'+b+r'\end{matrix}')
    def bbox(body,options):
        options=[s.strip() for s in (options or '').split(',')]
        colors=[s for s in options if re.fullmatch(r'[a-zA-Z]+',s)]
        return (r'\colorbox{'+colors[-1]+'}{$'+body+'$}') if colors else r'\boxed{'+body+'}'
    value=group_macro(value,'bbox',bbox)
    value=re.sub(r'\\bbox\[([^\]]+)\]\s*([^\s{}\\&])',lambda m:bbox(m.group(2),m.group(1)),value)
    value=group_macro(value,'enclose',lambda b,o:r'\boxed{'+b+'}') if r'\enclose[' in value else value
    value=re.sub(r'\\artanh\b',lambda m:r'\operatorname{artanh}',value)
    value=value.replace(r'\begin{eqnarray*}',r'\begin{aligned}').replace(r'\end{eqnarray*}',r'\end{aligned}')
    value=re.sub(r'(?<!\\)_{2,}',lambda m:r'\_'*len(m.group()),value)
    pos=0
    while True:
        m=re.search(r'\^\\sqrt\s*\{',value[pos:])
        if not m:break
        start=pos+m.start();arg=pos+m.end()-1;end=group_end(value,arg)
        replacement='^{'+value[start+1:end+1]+'}';value=value[:start]+replacement+value[end+1:];pos=start+len(replacement)
    value=re.sub(r'\\unicode\{x([a-fA-F0-9]+)\}',lambda m:r'\$' if int(m.group(1),16)==36 else chr(int(m.group(1),16)),value)
    return value

def substitute_math(source,transform):
    """Scan delimiters with brace depth; nested dollars in text macros are
    part of their parent expression, never separate/truncated formulas."""
    starts=re.compile(r'\[math\]|(?<!\\)\\\[|(?<!\\)\\\(|\\begin\{(align\*?|equation\*?|gather\*?|multline\*?)\}|(?<!\\)\${1,2}')
    out=[];pos=0
    while True:
        m=starts.search(source,pos)
        if not m:out.append(source[pos:]);break
        opening=m.group();end=-1;value='';block=False
        if opening=='[math]':
            closing='[/math]';end=source.find(closing,m.end())
        elif opening in [r'\[',r'\(']:
            closing=r'\]' if opening==r'\[' else r'\)';block=opening==r'\[';end=source.find(closing,m.end())
        elif m.group(1):
            closing=r'\end{'+m.group(1)+'}';block=True;end=source.find(closing,m.end())
        else:
            closing=opening;block=opening=='$$';depth=0;i=m.end()
            while i<len(source):
                if source[i]=='\\':i+=2;continue
                if source[i]=='{':depth+=1
                elif source[i]=='}':depth=max(0,depth-1)
                elif source.startswith(closing,i) and depth==0:end=i;break
                i+=1
        if end<0:out.append(source[pos:m.end()]);pos=m.end();continue
        value=source[m.end():end]
        if m.group(1):value=opening+value+closing
        out.append(source[pos:m.start()]);out.append(transform(value,block));pos=end+len(closing)
    return ''.join(out)

def course_graph(path,course_id,include_external=False,external_course_id=None):
    with zipfile.ZipFile(path) as z:
        main=json.loads(z.read(f'course-knowledge-graph/course-{course_id}.json'))['topics']
        assert main,'Course graph is empty'
        graph=dict(main);pending={str(p) for t in graph.values() for p in t['prerequisites']} - set(graph)
        if pending and not include_external:raise ValueError('Course has external prerequisites; explicit --include-external-prerequisites is required: '+','.join(sorted(pending,key=int)))
        catalog=None
        while pending:
            if catalog is None:
                catalog=collections.defaultdict(list)
                for name in z.namelist():
                    if re.fullmatch(r'course-knowledge-graph/course-\d+\.json',name):
                        for tid,t in json.loads(z.read(name)).get('topics',{}).items():catalog[tid].append(t)
            tid=min(pending,key=int);pending.remove(tid)
            if tid in graph:continue
            candidates=catalog.get(tid,[])
            if external_course_id is not None:candidates=[t for t in candidates if int(t['course']['id'])==int(external_course_id)]
            if not candidates:raise ValueError(f'External prerequisite absent from supplied graphs: {tid}')
            signatures={(t['name'],tuple(sorted(t['prerequisites']))) for t in candidates}
            if len(signatures)!=1:raise ValueError(f'Conflicting supplied prerequisite Topic: {tid}')
            graph[tid]=min(candidates,key=lambda t:int(t['course']['id']))
            pending.update(str(p) for p in graph[tid]['prerequisites'] if str(p) not in graph)
    return graph,set(main)

def dependency_order(graph):
    remaining=set(graph);result=[]
    while remaining:
        ready=sorted((tid for tid in remaining if not any(str(p) in remaining for p in graph[tid]['prerequisites'])),key=int)
        if not ready:raise ValueError('Supplied prerequisite graph contains a cycle')
        result.extend(ready);remaining.difference_update(ready)
    return {tid:i for i,tid in enumerate(result)}

def hierarchy_ids(topic,course_id):
    cid=topic.get('course',{}).get('id',course_id)
    prefix='' if int(cid)==int(course_id) else f'external.c{cid}.'
    unit=f'{prefix}u{topic["unit"]["number"]}'
    return unit,f'{unit}.m{topic["module"]["number"]}'

def unit_label(topic,args):
    base=f'单元 {topic["unit"]["number"]}'
    numeric=getattr(args,'unit_labels','source')=='numeric' and int(topic.get('course',{}).get('id',args.course_id))==args.course_id
    return base if numeric else base+'：'+topic['unit']['name']

class Converter:
    def __init__(self,args):
        self.args=args;self.root=Path(args.output);self.root.mkdir(parents=True,exist_ok=True)
        self.drawings={};self.graphic_index={};self.gaps=[];self.records=[];self.stats=collections.Counter();self.nodes=[];self.assets={}
        self.coverage=[];self.tokens={};self.token_number=0
        audit=getattr(args,'math_audit',None)
        self.invalid_math={d['value'] for d in json.loads(Path(audit).read_text(encoding='utf-8'))['details']} if audit else set()

    def load(self):
        self.graph,self.main_ids=course_graph(self.args.graph,self.args.course_id,getattr(self.args,'include_external_prerequisites',False),getattr(self.args,'external_course_id',None))
        dump(self.root/'source'/'resolved-graph.json',{'topics':self.graph,'courseTopicIds':sorted(self.main_ids,key=int)})
        self.course=next(self.graph[tid]['course'] for tid in self.graph if tid in self.main_ids)
        rank=dependency_order(self.graph)
        with zipfile.ZipFile(self.args.progress) as z:
            names=sorted(n for n in z.namelist() if re.fullmatch(rf'ma-[^/]+/progress/course_{self.args.course_id}_\d{{4}}-\d{{2}}-\d{{2}}\.json',n))
            if not names and not getattr(self.args,'allow_missing_progress',False):raise ValueError('Course progress snapshot missing; explicit --allow-missing-progress is required')
            self.progress_name=names[-1] if names else None;self.progress=json.loads(z.read(names[-1]))['topics'] if names else None
            if self.progress is not None:
                assert set(self.progress)==self.main_ids,'Topic identity conflict'
                for tid in self.main_ids:
                    t=self.graph[tid];assert t['name']==self.progress[tid]['name'] and t['prerequisites']==self.progress[tid]['prerequisites'],f'Graph/progress conflict {tid}'
            # Only supplied answer source objects are used; learner/session metadata is discarded.
            self.answer_questions={}
            for n in z.namelist():
                if '/answers/' not in n or not n.endswith('.json') or n.startswith('__MACOSX/'):continue
                data=json.loads(z.read(n));task=data.get('task') or {}
                for a in task.get('answers') or []:
                    q=a.get('question') or {}
                    if q.get('id') is not None:self.answer_questions[str(q['id'])]=q
        self.lessons={}
        with zipfile.ZipFile(self.args.topics) as z:
            for tid in self.graph:
                data=z.read(f'topic-json/topic-{tid}.json');lesson=json.loads(data)['lesson'];assert str(lesson['topic']['id'])==tid
                self.lessons[tid]=lesson
                file=self.root/'source'/f'topic-{tid}.json';file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(data)
        # Source fileId, not graphic array position, is the only valid mapping key.
        def collect(obj):
            if isinstance(obj,dict):
                if isinstance(obj.get('fileId'),str) and isinstance(obj.get('tex'),str):
                    key=obj['fileId'];value=obj['tex']
                    if key in self.graphic_index and self.graphic_index[key]!=value:
                        raise ValueError(f'Conflicting graphics source for {key}')
                    self.graphic_index[key]=value
                for v in obj.values():collect(v)
            elif isinstance(obj,list):
                for v in obj:collect(v)
        collect(self.lessons);collect(self.answer_questions)
        # Exact source recovery for empty lesson questions, without importing learner state.
        for tid,lesson in self.lessons.items():
            for step in lesson.get('steps',[]):
                if step['type']=='question':
                    q=step.get('question') or {};extra=self.answer_questions.get(str(q.get('id')))
                    if not q.get('text') and extra and extra.get('text'):
                        step['question']={**extra,**{k:v for k,v in q.items() if v is not None}};self.stats['questions_recovered']+=1
        def position(tid):
            t=self.graph[tid];outside=tid not in self.main_ids
            number=self.progress[tid]['number'] if self.progress is not None and not outside else rank[tid]
            return (outside,int(t['course']['id']) if outside else 0,t['unit']['number'],t['module']['number'],number,int(tid))
        self.order=sorted(self.graph,key=position)
        self.source_hashes={k:digest(Path(getattr(self.args,k)).read_bytes()) for k in ['graph','progress','topics']}

    def image(self,source,where):
        key=digest(source)
        self.drawings.setdefault(key,{'source':source,'uses':[]})['uses'].append(where)
        return {'kind':'image','assetId':key}

    def svg_image(self,source,where):
        key=digest(source);self.drawings.setdefault(key,{'source':source,'format':'svg','uses':[]})['uses'].append(where)
        self.stats['native_math_svg_fallbacks']+=1
        return {'kind':'image','assetId':key}

    def token(self,segments):
        self.token_number+=1;key=f'RBITOKEN{self.token_number:08d}END';self.tokens[key]=segments;return key

    def field(self,source,where,rendered=None):
        if source is None or not str(source).strip():return []
        source=str(source);raw=source;token_start=self.token_number
        # HTML comments/style/script are unpublished markup, preserved in the
        # raw export but excluded from the readable lesson representation.
        source=re.sub(r'<!--.*?-->','',source,flags=re.S)
        if rendered:
            rendered=re.sub(r'<!--.*?-->','',rendered,flags=re.S)
            rendered=re.sub(r'<(?:style|script)\b[^>]*>.*?</(?:style|script)>','',rendered,flags=re.S|re.I)
        def protect_code(value):
            def code(m):
                fragment=m.group();parser=ToMarkdown()
                parser.feed(fragment if re.match(r'<pre\b',fragment,re.I) else '<pre>'+fragment+'</pre>')
                if len(parser.code_blocks)!=1:raise ValueError(f'Cannot preserve source code block at {where}')
                return self.token([{'kind':'code','value':parser.code_blocks[0]['value']}])
            return CODE_HTML.sub(code,value)
        document_source=CODE_HTML.sub('',source)
        documents=list(TEX.finditer(document_source));imgs=IMG.findall(CODE_HTML.sub('',rendered or ''))
        _,macros=extract_source_macros(TEX.sub('',document_source))
        if rendered is not None and len(documents)!=len(imgs):raise ValueError(f'Graphic/source mismatch {where}')
        local_graphics={url.split('/')[-1]:doc.group() for url,doc in zip(imgs,documents)}
        rendered_svgs=re.findall(r'<svg\b.*?</svg>',rendered or '',re.S|re.I)
        use_rendered=bool(rendered_svgs) and all(re.search(r'<title\b[^>]*>.*?</title>',s,re.S|re.I) for s in rendered_svgs)
        if use_rendered:
            # The exported rendered HTML carries original LaTeX in every SVG
            # <title>. Prefer that exact representation to the occasionally
            # corrupted [math] serialization of the same field.
            body=re.search(r'<body\b[^>]*>(.*?)</body>',rendered,re.S|re.I)
            source=protect_code(body.group(1) if body else rendered)
            def svg(m):
                title=re.search(r'<title\b[^>]*>(.*?)</title>',m.group(),re.S|re.I)
                if not title:raise ValueError(f'SVG lacks source math title at {where}')
                title_source,local=extract_source_macros(html.unescape(title.group(1)))
                value=latex_compatible(expand_source_macros(title_source,{**macros,**local}));context=source[max(0,m.start()-160):m.start()]
                if not value.strip():return ''
                if value in self.invalid_math:return self.token([self.svg_image(m.group(),where)])
                span=re.findall(r'<span\b[^>]*>',context)
                block=bool(span and 'mjpage__block' in span[-1]) or bool(re.search(r'\\begin\{(?:align|equation|gather|multline)',value))
                self.stats['formulas']+=1
                return self.token([{'kind':'latex','value':value,'block':block}])
            source=re.sub(r'<svg\b.*?</svg>',svg,source,flags=re.S|re.I)
        else:source=TEX.sub(lambda m:self.token([self.image(m.group(),where)]),protect_code(source))
        source,_=extract_source_macros(source)
        # Remaining HTML images in source fields are matched only through explicit file IDs.
        def img(m):
            file_id=m.group(1).split('/')[-1]
            graphic=local_graphics.get(file_id) or self.graphic_index.get(file_id)
            if graphic:return self.token([self.image(graphic,where)])
            self.gaps.append({'kind':'missing_graphic','where':where,'source':m.group(1)})
            return self.token([{'kind':'text','value':'【原题配图缺失】'}])
        source=IMG.sub(img,source)
        # Protect formulas before stripping source HTML or splitting paragraphs.
        def math(value,block):
            value=latex_compatible(expand_source_macros(html.unescape(value).strip(),macros))
            if not value.strip():return ''
            self.stats['formulas']+=1
            block=block or bool(re.search(r'\\begin\{(?:align|equation|gather|multline)',value))
            return self.token([{'kind':'latex','value':value,'block':block}])
        source=substitute_math(normalize_math_markers(source),math)
        if re.search(r'</?(?:p|div|span|strong|em|br|table|ul|ol|li|sup|sub)\b',source,re.I):
            parser=ToMarkdown();parser.feed(source);source=''.join(parser.out)
            for block in parser.code_blocks:source=source.replace(block['token'],self.token([{'kind':'code','value':block['value']}]))
            if parser.unknown:self.gaps.append({'kind':'unknown_html','where':where,'tags':sorted(parser.unknown)})
        if 'MISSING_IMAGE:' in source:raise ValueError(f'Unhandled image at {where}')
        tokenized_source=source
        # Source indentation is kept for lists; paragraph nodes hold their own line breaks.
        blocks=[]
        for paragraph in re.split(r'\n\s*\n',source):
            if not paragraph.strip():continue
            for line in re.split(r'\n(?=\s*(?:[-*+]\s|\d+\.\s))',paragraph):
                line=line.strip()
                bullet=re.match(r'^(?:[-*+]\s+|\d+\.\s+)',line)
                if bullet:line=line[bullet.end():]
                if not line:continue
                segments=[]
                for part in re.split(r'(RBITOKEN\d{8}END)',line):
                    if part in self.tokens:segments.extend(self.tokens[part])
                    elif part:
                        # Plain source that contains literal [[ syntax is not an instruction/reference.
                        kind='text' if re.search(r'\[\[|!\[|data:|file://',part,re.I) else 'markdown'
                        segments.append({'kind':kind,'value':html.unescape(part)})
                if segments:blocks.append(segments)
        emitted={id(s) for b in blocks for s in b}
        field_tokens=[f'RBITOKEN{i:08d}END' for i in range(token_start+1,self.token_number+1)]
        lost=[k for k in field_tokens if any(id(s) not in emitted for s in self.tokens[k])]
        if lost:self.gaps.append({'kind':'token_loss','where':where,'lost':lost,'context':[tokenized_source[max(0,tokenized_source.find(k)-120):tokenized_source.find(k)+180] for k in lost[:2]]})
        self.coverage.append({'where':where,'representation':'rendered-html-math-titles' if use_rendered else 'raw-source','rawSha256':digest(raw),'rawChars':len(raw),'paragraphs':len(blocks),'formulaTokens':sum(s['kind']=='latex' for b in blocks for s in b),'imageTokens':sum(s['kind']=='image' for b in blocks for s in b)})
        return blocks

    def add(self,id,parent,text,document=False):
        if isinstance(text,str):text=[{'kind':'text','value':text}]
        self.nodes.append({'id':id,'parentId':parent,'document':document,'text':text});return id
    def add_field(self,id,parent,source,where,rendered=None):
        blocks=self.field(source,where,rendered)
        if blocks:
            rich=[]
            for i,b in enumerate(blocks):
                if i:rich.append({'kind':'text','value':'\n\n'})
                rich.extend(b)
            self.add(f'{id}.p0',parent,rich)
        else:
            self.gaps.append({'kind':'missing_content','where':where})
            self.add(f'{id}.missing',parent,'【源资料未提供此处内容】')
    def labeled_field(self,id,parent,label,source,where,rendered=None):
        rich=[{'kind':'text','value':label}]
        blocks=self.field(source,where,rendered)
        if not blocks:
            self.gaps.append({'kind':'missing_content','where':where})
            rich.append({'kind':'text','value':'\n\n【源资料未提供此处内容】'})
        for block in blocks:
            rich.append({'kind':'text','value':'\n\n'});rich.extend(block)
        return self.add(id,parent,rich)

    def question(self,tid,step,parent):
        q=step.get('question') or {};sid=f't{tid}.s{step["id"]}'
        root=self.add(sid,parent,f'练习 {q.get("number",step["number"])}')
        if not q.get('text'):
            self.gaps.append({'kind':'missing_question','where':sid,'questionId':q.get('id')});self.add(sid+'.missing',root,'【源资料未提供该练习的题干】')
        else:self.add_field(sid+'.text',root,q['text'],sid+'.text')
        selects=[];seen_selects={};textboxes=[];represented_sections=set()
        def selection_key(sel):
            if sel.get('index') is not None:return ('index',sel.get('sectionIndex'),sel['index'])
            if sel.get('id') is not None:return ('id',sel['id'])
            return ('content',json.dumps(sel,sort_keys=True,ensure_ascii=False))
        def remember_selection(sel):
            key=selection_key(sel)
            if key not in seen_selects:seen_selects[key]=len(selects);selects.append(sel)
            return seen_selects[key]
        def placeholder(label,text):
            closing=None
            for token in re.findall(r'(?<!\\)\${1,2}|\[/?math\]|(?<!\\)\\[\[\]()]',text):
                if token==closing or (closing=='[/math]' and token=='[math]'):closing=None
                elif closing is None:closing={'$':'$','$$':'$$','[math]':'[/math]',r'\[':r'\]',r'\(':r'\)'}.get(token)
            return (r'\boxed{\text{'+label+'}}') if closing else '['+label+']'
        def segment_text(segments,where):
            text=''
            for segment in segments:
                if 'text' in segment:text+=segment['text']
                elif 'mathJax' in segment:text+=segment['mathJax']
                elif segment.get('newParagraph') or segment.get('newline'):text+='\n\n'
                elif 'select' in segment:
                    sel=segment['select'];i=remember_selection(sel)
                    if sel.get('sectionIndex') is not None:represented_sections.add(sel['sectionIndex'])
                    label='选择 '+str(sel.get('index',i)+1)
                    text+=placeholder(label,text)
                elif 'textbox' in segment or 'input' in segment:
                    box=segment.get('textbox',segment.get('input'));textboxes.append(box if isinstance(box,dict) else {})
                    label='填空 '+str(len(textboxes))
                    text+=placeholder(label,text)
                else:self.gaps.append({'kind':'unknown_body_segment','where':where,'keys':list(segment)})
            return text
        raw_body=q.get('body');free=q.get('freeResponse') or {}
        body=raw_body if isinstance(raw_body,dict) else {}
        if isinstance(raw_body,str) and raw_body.strip() and not (isinstance(free,dict) and free.get('segments')):
            rawroot=self.add(sid+'.body-source',root,'来源中的原始作答字段')
            self.add(sid+'.body-source.raw',rawroot,[{'kind':'code','value':raw_body}])
        if body.get('segments'):
            bodytext=segment_text(body['segments'],sid+'.body')
            self.add_field(sid+'.body',root,bodytext,sid+'.body')
            # The source body is the displayed first section; completion flags
            # on later sections are learner state and never become course text.
            represented_sections.add(0)
        if isinstance(free,dict) and free.get('segments'):
            frroot=self.add(sid+'.fr',root,'作答区域：自由作答')
            self.add_field(sid+'.fr.body',frroot,segment_text(free['segments'],sid+'.fr.body'),sid+'.fr.body')
        elif q.get('freeResponse'):self.add(sid+'.fr',root,'作答形式：自由作答')
        elif str(q.get('freeAnswerChoice') or '').strip():
            self.labeled_field(sid+'.free-answer',root,'来源作答区域',q['freeAnswerChoice'],sid+'.free-answer')
        # PR/DS exports include all later selectors but only the first section's
        # prose. Keep every supplied option without inventing the missing prose.
        for sel in q.get('selects') or []:
            if isinstance(sel,dict) and sel.get('options'):remember_selection(sel)
        section_roots={}
        for i,section in enumerate(q.get('sections') or []):
            if i not in represented_sections:
                secroot=self.add(f'{sid}.section{i}',root,f'步骤 {i+1}')
                section_roots[i]=secroot
                self.add(f'{sid}.section{i}.missing',secroot,'【源资料未提供此步骤的正文；保留下方可用选项】')
                self.gaps.append({'kind':'missing_question_section','where':f'{sid}.section{i}.missing'})
        for i,sel in enumerate(selects):
            selroot=self.add(f'{sid}.select{i}',section_roots.get(sel.get('sectionIndex'),root),f'选择 {sel.get("index",i)+1} 的选项')
            for j,option in enumerate(sel.get('options') or []):
                opt=self.add(f'{sid}.select{i}.o{j}',selroot,f'{j+1}.')
                value=f'[math]{option}[/math]' if sel.get('context')=='mathJax' else option
                self.add_field(f'{sid}.select{i}.o{j}.text',opt,value,f'{sid}.select{i}.o{j}')
        for i,box in enumerate(textboxes):
            answer=box.get('answer')
            if answer is not None and str(answer).strip():
                answerroot=self.add(f'{sid}.fr.answer{i}',root,f'来源中附带的解答：填空 {i+1}')
                value=str(answer)
                if box.get('type') in ['number','math','mathJax']:value=f'[math]{value}[/math]'
                self.add_field(f'{sid}.fr.answer{i}.text',answerroot,value,f'{sid}.fr.answer{i}')
        for i in range(1,6):
            v=q.get(f'choice{i}')
            if v and v.strip():
                self.labeled_field(f'{sid}.choice{i}',root,f'选项 {i}',v,f'{sid}.choice{i}')
        # Practice answer=null in exports; never fabricate answers from ordering.
        if q.get('explanation'):self.add_field(sid+'.explanation',self.add(sid+'.answer',root,'来源中附带的解答'),q['explanation'],sid+'.explanation')

    def convert(self):
        self.add('course.source',None,self.course['name'])
        self.add('course.note',None,'前置知识列出所提供图谱中的直接依赖。')
        self.add('course.question-note',None,'源资料缺失的内容已在对应位置标注；练习解答仅按来源提供。')
        units=set();modules=set();external_courses=set()
        for tid in self.order:
            t=self.graph[tid];unit,module=hierarchy_ids(t,self.args.course_id);outside=int(t.get('course',self.course).get('id',self.args.course_id))!=self.args.course_id
            parent=None
            if outside:
                if not external_courses:self.add('external-prerequisites',None,'课程外前置知识',True)
                cid=str(t['course']['id']);parent=f'external.c{cid}'
                if cid not in external_courses:self.add(parent,'external-prerequisites',t['course']['name']+'（前置知识）',True);external_courses.add(cid)
            if unit not in units:
                self.add(unit,parent,unit_label(t,self.args),True);units.add(unit)
            if module not in modules:
                self.add(module,unit,f'模块 {t["module"]["number"]}：{t["module"]["name"]}',True);modules.add(module)
            topic=self.add(f't{tid}',module,t['name'],True)
            pre=self.add(f't{tid}.prereqs',topic,'前置知识')
            for p in t['prerequisites']:self.add(f't{tid}.pre{p}',pre,[{'kind':'ref','targetId':f't{p}'}])
            if not t['prerequisites']:self.add(f't{tid}.pre-none',pre,'所提供图谱未列出直接前置 Topic。')
            if not self.lessons[tid].get('steps'):
                self.gaps.append({'kind':'missing_lesson','where':f't{tid}'})
                self.add(f't{tid}.missing-lesson',topic,'【源资料未提供该 Topic 的课文内容】')
            for step in self.lessons[tid].get('steps',[]):
                kind=step['type'];self.stats[kind]+=1
                obj=step.get(kind) or {};sid=f't{tid}.s{step["id"]}'
                if kind=='tutorial':
                    section=self.add(sid,topic,f'讲解 {step["number"]}：{obj.get("title") or "Untitled"}')
                    self.add_field(sid+'.content',section,obj.get('content'),sid+'.content',obj.get('html'))
                elif kind=='example':
                    section=self.add(sid,topic,f'例题 {step["number"]}：{obj.get("title") or "Untitled"}')
                    for key,rendered,label in [('question','questionHtml','题目'),('explanation','explanationHtml','解答')]:
                        self.labeled_field(sid+'.'+key,section,label,obj.get(key),sid+'.'+key,obj.get(rendered))
                elif kind=='question':self.question(tid,step,topic)
                else:raise ValueError(f'Unknown lesson step: {kind}')
        self.stats['topics']=len(self.graph);self.stats['prerequisites']=sum(len(t['prerequisites']) for t in self.graph.values())
        for key,d in self.drawings.items():
            folder=self.root/'drawings'/key;folder.mkdir(parents=True,exist_ok=True)
            if d.get('format')=='svg':
                (folder/'original.svg').write_text(d['source'],encoding='utf-8');(folder/'drawing.svg').write_text(d['source'],encoding='utf-8');continue
            if not getattr(self.args,'plan_only',False):(folder/'original.tex').write_text(d['source'],encoding='utf-8')
            try:
                compatible=tex_compatible(d['source'])
                if not getattr(self.args,'plan_only',False):(folder/'drawing.tex').write_text(compatible,encoding='utf-8')
                d['compatibleSha256']=digest(compatible)
            except ValueError as e:d['sourceError']=str(e)
        self.plan={'schemaVersion':1,'packageId':f'ma.course{self.args.course_id}.source-export','title':self.args.title,'nodes':self.nodes,'assets':{},'provenance':{'sourceHashes':self.source_hashes,'progressFile':self.progress_name,'courseId':self.args.course_id,'courseTopicIds':sorted(getattr(self,'main_ids',set(self.graph)),key=int),'externalPrerequisiteTopicIds':sorted(set(self.graph)-getattr(self,'main_ids',set(self.graph)),key=int),'externalCourseId':getattr(self.args,'external_course_id',None),'unitLabels':getattr(self.args,'unit_labels','source'),'topicOrderSource':'progress' if getattr(self,'progress',None) is not None else 'source-groups-and-prerequisite-DAG'}}
        dump(self.root/'draft-package.json',self.plan);dump(self.root/'source-coverage.json',self.coverage)
        dump(self.root/'drawings-index.json',{k:{a:b for a,b in d.items() if a!='source'} for k,d in self.drawings.items()})
        dump(self.root/'source-gaps.json',self.gaps);dump(self.root/'conversion-summary.json',{'counts':dict(self.stats),'nodes':len(self.nodes),'uniqueDrawings':len(self.drawings),'gaps':dict(collections.Counter(g['kind'] for g in self.gaps)),'sourceHashes':self.source_hashes})
        print(json.dumps({'phase':'converted','counts':dict(self.stats),'nodes':len(self.nodes),'drawings':len(self.drawings),'gaps':dict(collections.Counter(g['kind'] for g in self.gaps))}),flush=True)

def render_one(key,root,tectonic,pdftoppm):
    folder=root/'drawings'/key;src=folder/'drawing.tex';output=folder/'drawing.png'
    if (folder/'drawing.svg').exists():
        if output.exists() and (folder/'success.json').exists():return key,True,'cached SVG'
        result=subprocess.run(['node',str(Path(__file__).with_name('render-svg.mjs')),str(folder/'drawing.svg'),str(output)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=60)
        if result.returncode:return key,False,result.stdout.decode(errors='replace')[-1000:]
        im=Image.open(output);dump(folder/'success.json',{'width':im.width,'height':im.height,'pngSha256':digest(output.read_bytes()),'sourceSha256':key,'transformations':['rasterize-original-mathjax-svg-without-rewriting-notation']});return key,True,''
    try:
        normalized=tex_compatible((folder/'original.tex').read_text(encoding='utf-8'))
        changed=not src.exists() or src.read_text(encoding='utf-8')!=normalized
        if changed:src.write_text(normalized,encoding='utf-8')
    except ValueError as e:return key,False,str(e)
    if not changed and output.exists() and (folder/'success.json').exists():
        receipt=json.loads((folder/'success.json').read_text())
        if receipt.get('pngSha256')==digest(output.read_bytes()) and receipt.get('compatibleSha256',digest(src.read_bytes()))==digest(src.read_bytes()):return key,True,'cached'
    if not src.exists():return key,False,'source compatibility failure'
    env={**os.environ,'TECTONIC_CACHE_DIR':'D:/Caches/RemNoteBulkImporter/tectonic','TEMP':'D:/Caches/RemNoteBulkImporter/temp','TMP':'D:/Caches/RemNoteBulkImporter/temp'}
    for k in ['TECTONIC_CACHE_DIR','TEMP']:Path(env[k]).mkdir(parents=True,exist_ok=True)
    try:
        with (folder/'compile.log').open('wb') as log:
            result=subprocess.run([tectonic,'-X','compile','--outdir',str(folder),'--outfmt','pdf','--untrusted','--keep-logs','drawing.tex'],cwd=folder,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=180)
        transformations=[];pdf=folder/'drawing.pdf'
        if result.returncode and 'TeX capacity exceeded' in (folder/'compile.log').read_text(errors='replace'):
            split=split_standalone(src.read_text(encoding='utf-8'))
            if split:
                (folder/'drawing-split.tex').write_text(split,encoding='utf-8')
                with (folder/'compile-split.log').open('wb') as log:
                    result=subprocess.run([tectonic,'-X','compile','--outdir',str(folder),'--outfmt','pdf','--untrusted','--keep-logs','drawing-split.tex'],cwd=folder,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=180)
                pdf=folder/'drawing-split.pdf';transformations.append('ship-independent-tikz-panels-separately')
            elif re.search(r'shader\s*=\s*faceted interp',src.read_text(encoding='utf-8')):
                # Same sampled coordinates, mesh, equations and labels; use
                # constant facet coloring where the engine cannot hold the
                # interpolated PDF shading program in memory.
                compatible=re.sub(r'shader\s*=\s*faceted interp','shader=faceted',src.read_text(encoding='utf-8'))
                (folder/'drawing-facets.tex').write_text(compatible,encoding='utf-8')
                with (folder/'compile-facets.log').open('wb') as log:
                    result=subprocess.run([tectonic,'-X','compile','--outdir',str(folder),'--outfmt','pdf','--untrusted','--keep-logs','drawing-facets.tex'],cwd=folder,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=180)
                pdf=folder/'drawing-facets.pdf';transformations.append('same-mesh-faceted-coloring-for-engine-memory-limit')
        if result.returncode or not pdf.exists():
            name='compile-facets.log' if transformations and transformations[-1].startswith('same-mesh') else 'compile-split.log' if transformations else 'compile.log'
            return key,False,(folder/name).read_text(errors='replace')[-2000:]
        result=subprocess.run([pdftoppm,'-png','-r','144',str(pdf),str(folder/'page')],cwd=folder,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=60)
        if result.returncode:return key,False,result.stdout.decode(errors='replace')[-1000:]
        pages=[]
        for file in sorted(folder.glob('page-*.png')):
            im=Image.open(file).convert('RGB');bg=Image.new('RGB',im.size,'white');box=ImageChops.difference(im,bg).getbbox()
            if box:
                box=(max(0,box[0]-12),max(0,box[1]-12),min(im.width,box[2]+12),min(im.height,box[3]+12));pages.append(im.crop(box))
        if not pages:return key,False,'Blank PDF output'
        horizontal=bool(transformations and r'\hspace' in src.read_text(encoding='utf-8'))
        width=sum(p.width for p in pages)+16*(len(pages)-1) if horizontal else max(p.width for p in pages)
        height=max(p.height for p in pages) if horizontal else sum(p.height for p in pages)+16*(len(pages)-1)
        canvas=Image.new('RGB',(width,height),'white');pos=0
        for p in pages:
            canvas.paste(p,(pos,(height-p.height)//2) if horizontal else ((width-p.width)//2,pos));pos+=(p.width if horizontal else p.height)+16
        canvas.save(output,optimize=True);dump(folder/'success.json',{'width':width,'height':height,'pages':len(pages),'pngSha256':digest(output.read_bytes()),'sourceSha256':key,'compatibleSha256':digest(src.read_bytes()),'transformations':transformations})
        return key,True,''
    except Exception as e:return key,False,str(e)

def render(args):
    root=Path(args.output);index=json.loads((root/'drawings-index.json').read_text(encoding='utf-8'));keys=list(index)
    if args.retry_failed:
        keys=[k for k in keys if (root/'drawings'/k/'compile.log').exists() and not (root/'drawings'/k/'success.json').exists() and 'error:' in (root/'drawings'/k/'compile.log').read_text(errors='replace')]
    if args.limit:keys=keys[:args.limit]
    results=[];start=time.time()
    # Render one first to initialize shared package cache without concurrent download races.
    if keys:
        r=render_one(keys[0],root,args.tectonic,args.pdftoppm);results.append(r);print(json.dumps({'rendered':1,'total':len(keys),'ok':r[1],'key':r[0],'detail':r[2][-300:]}),flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures=[pool.submit(render_one,k,root,args.tectonic,args.pdftoppm) for k in keys[1:]]
        for f in concurrent.futures.as_completed(futures):
            r=f.result();results.append(r)
            if len(results)%10==0 or not r[1] or len(results)==len(keys):print(json.dumps({'rendered':len(results),'total':len(keys),'ok':sum(x[1] for x in results),'last':r[0],'error':r[2][-300:] if not r[1] else '', 'elapsedSeconds':round(time.time()-start)}),flush=True)
    dump(root/('retry-results.json' if args.retry_failed else 'render-results.json'),{'total':len(results),'passed':sum(r[1] for r in results),'failed':[{'key':r[0],'error':r[2]} for r in results if not r[1]]})

def pack(args):
    root=Path(args.output);plan=json.loads((root/'draft-package.json').read_text(encoding='utf-8'));index=json.loads((root/'drawings-index.json').read_text(encoding='utf-8'));missing=[]
    gaps=json.loads((root/'source-gaps.json').read_text(encoding='utf-8'))
    assert all(g['kind'] in ['missing_question','missing_graphic','missing_content','missing_lesson','missing_question_section'] for g in gaps),'Unresolved conversion loss/format errors'
    math=json.loads((root/'math-final-audit.json').read_text())
    assert math['errors']==0,'Native math audit has unresolved failures'
    for key in index:
        f=root/'drawings'/key/'drawing.png'
        if not f.exists():missing.append(key);continue
        data=f.read_bytes();receipt=json.loads((f.parent/'success.json').read_text())
        assert receipt['pngSha256']==digest(data),f'Image receipt mismatch {key}'
        plan['assets'][key]={'mime':'image/png','base64':base64.b64encode(data).decode(),'sha256':digest(data)}
    if missing:raise ValueError(f'{len(missing)} diagrams not rendered; refuse final package')
    out=Path(args.package);dump(out,plan)
    print(json.dumps({'phase':'packed','path':str(out),'bytes':out.stat().st_size,'nodes':len(plan['nodes']),'assets':len(plan['assets'])}),flush=True)

def audit(args):
    root=Path(args.output);plan=json.loads(Path(args.package).read_text(encoding='utf-8'));nodes={n['id']:n for n in plan['nodes']}
    assert len(nodes)==len(plan['nodes']),'Duplicate package IDs'
    graph,main_ids=course_graph(args.graph,args.course_id,getattr(args,'include_external_prerequisites',False),getattr(args,'external_course_id',None))
    unit_ids={hierarchy_ids(t,args.course_id)[0] for t in graph.values()}
    module_ids={hierarchy_ids(t,args.course_id)[1] for t in graph.values()}
    outside={str(t['course']['id']) for tid,t in graph.items() if tid not in main_ids}
    external_docs=({'external-prerequisites'}|{f'external.c{cid}' for cid in outside}) if outside else set()
    assert {n['id'] for n in nodes.values() if n['document']}=={'t'+tid for tid in graph}|unit_ids|module_ids|external_docs,'Course document hierarchy differs from source'
    if outside:
        assert nodes['external-prerequisites']['parentId'] is None
        for cid in outside:assert nodes[f'external.c{cid}']['parentId']=='external-prerequisites'
    children=collections.defaultdict(list)
    for n in plan['nodes']:children[n['parentId']].append(n)
    actual=set();steps=collections.Counter()
    for tid,t in graph.items():
        n=nodes['t'+tid]
        unit,module=hierarchy_ids(t,args.course_id)
        assert n['parentId']==module and n['text']==[{'kind':'text','value':t['name']}],f'Topic identity/placement mismatch {tid}'
        assert nodes[unit]['parentId']==(None if tid in main_ids else f'external.c{t["course"]["id"]}') and nodes[unit]['text']==[{'kind':'text','value':unit_label(t,args)}],'Unit mismatch'
        assert nodes[module]['parentId']==unit and nodes[module]['text']==[{'kind':'text','value':f'模块 {t["module"]["number"]}：{t["module"]["name"]}'}],'Module mismatch'
        assert f't{tid}.meta' not in nodes,'Redundant unit/module metadata remains under Topic'
        for child in children['t'+tid+'.prereqs']:
            for s in child['text']:
                if s['kind']=='ref':actual.add((int(tid),int(s['targetId'][1:])))
        lesson=json.loads((root/'source'/f'topic-{tid}.json').read_text(encoding='utf-8'))['lesson']
        if not lesson.get('steps'):assert nodes[f't{tid}.missing-lesson']['text']==[{'kind':'text','value':'【源资料未提供该 Topic 的课文内容】'}]
        for step in lesson['steps']:
            assert f't{tid}.s{step["id"]}' in nodes,'Source lesson step missing'
            steps[step['type']]+=1
    expected={(t['id'],p) for t in graph.values() for p in t['prerequisites']}
    assert actual==expected,'Prerequisite edges differ from source'
    math=json.loads((root/'math-final-audit.json').read_text());assert math['errors']==0
    assert sum(s['kind']=='latex' for n in nodes.values() for s in n['text'])==math['count'],'Math audit is stale'
    images=collections.Counter(s['assetId'] for n in nodes.values() for s in n['text'] if s['kind']=='image')
    assert set(images)==set(plan['assets']),'Image set differs from package assets'
    for key,a in plan['assets'].items():assert digest(base64.b64decode(a['base64']))==a['sha256'],'Asset digest mismatch'
    gaps=json.loads((root/'source-gaps.json').read_text(encoding='utf-8'))
    assert all(g['kind'] in ['missing_question','missing_graphic','missing_content','missing_lesson','missing_question_section'] for g in gaps),'Unresolved conversion errors'
    for gap in gaps:
        if gap['kind']=='missing_content':
            loc=gap['where'];n=nodes.get(loc) or nodes.get(loc+'.missing')
            assert n and any('【源资料未提供此处内容】' in s.get('value','') for s in n['text']),'Missing content placeholder absent'
        elif gap['kind']=='missing_question_section':
            marker=nodes.get(gap['where'])
            assert marker and any('【源资料未提供此步骤的正文' in s.get('value','') for s in marker['text']),'Missing section-body placeholder absent'
    report={'status':'PASSED','topics':len(graph),'courseTopics':len(main_ids),'externalPrerequisiteTopics':len(graph)-len(main_ids),'units':len(unit_ids),'modules':len(module_ids),'edges':len(actual),'steps':dict(steps),'nodes':len(nodes),'nativeFormulas':math['count'],'formulaErrors':0,'uniqueImages':len(images),'imageOccurrences':sum(images.values()),'sourceGaps':dict(collections.Counter(g['kind'] for g in gaps))}
    dump(root/'package-audit.json',report);print(json.dumps(report),flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['convert','render','pack','audit']);p.add_argument('--graph');p.add_argument('--progress');p.add_argument('--topics');p.add_argument('--course-id',type=int,default=154);p.add_argument('--title',default='数学物理方法一（MA）');p.add_argument('--output',required=True);p.add_argument('--tectonic');p.add_argument('--pdftoppm');p.add_argument('--workers',type=int,default=2);p.add_argument('--limit',type=int);p.add_argument('--retry-failed',action='store_true');p.add_argument('--plan-only',action='store_true');p.add_argument('--math-audit');p.add_argument('--package')
    p.add_argument('--allow-missing-progress',action='store_true');p.add_argument('--include-external-prerequisites',action='store_true');p.add_argument('--external-course-id',type=int);p.add_argument('--unit-labels',choices=['source','numeric'],default='source')
    a=p.parse_args()
    if a.stage=='convert':c=Converter(a);c.load();c.convert()
    elif a.stage=='render':render(a)
    elif a.stage=='audit':audit(a)
    else:pack(a)
if __name__=='__main__':main()
