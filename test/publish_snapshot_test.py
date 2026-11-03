"""Source-neutral regression fixtures for Publish collection representation."""
import sys
import json
import tempfile
import io
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'consumers'))
from materials.publish_snapshot import normalize, page_anchor, resolve_link, source_outline, prepare, svg_dimension
from materials.common import sha
from materials.validate import markdown_visible_with_math
from markdown_it import MarkdownIt
from materials.structure import validate_groups


class PublishSnapshotTests(unittest.TestCase):
    def test_svg_viewport_units(self):
        self.assertEqual(svg_dimension('576pt',0),768)
        self.assertEqual(svg_dimension('2in',0),192)
        self.assertEqual(svg_dimension('100%',800),800)

    def test_coverage_does_not_treat_split_style_markers_as_source_text(self):
        parser=MarkdownIt('commonmark',{'html':True})
        self.assertEqual(markdown_visible_with_math('**Rate $v$ and $a$** changes.',parser),'Rate v and a changes.')
        self.assertEqual(markdown_visible_with_math('`$literal$` and $x_1$',parser),'$literal$ and x_1')

    def test_scope_and_media_resolution(self):
        paths = {'book/a.md', 'book/b.md', 'other/b.md', 'assets/drawing.png'}
        self.assertEqual(resolve_link('b', 'book/a.md', paths), 'book/b.md')
        self.assertEqual(resolve_link('drawing.webp|400', 'book/a.md', paths), 'assets/drawing.png')
        self.assertIsNone(resolve_link('missing.webp', 'book/a.md', paths))

    def test_links_embeds_and_literal_code(self):
        paths = {'book/a.md', 'book/b.md', 'assets/chart.svg'}
        aliases = {'book/a.md':'book/a.md', 'book/b.md':'book/b.md'}
        media = {'assets/chart.svg':{'absolute':'D:/example/chart.svg'}}
        notes = []
        source = '[[b|乙]] ![[chart.svg|300]]\n\n`[[b]]`\n\n<iframe src="https://example.org/demo"></iframe>'
        result = normalize(source, 'book/a.md', 'https://example.org', paths, aliases, media, {}, notes)
        self.assertIn('[乙](#'+page_anchor('book/b.md')+')', result)
        self.assertIn('![](<D:/example/chart.svg>)', result)
        self.assertIn('`[[b]]`', result)
        self.assertIn('[交互演示](<https://example.org/demo>)', result)
        self.assertEqual([n['kind'] for n in notes], ['image','embedded_link'])

    def test_nested_heading_list_and_formula(self):
        source = '# Experiment\n\nA $x^2$ paragraph.\n\n- Step one\n  - Child\n- Step two\n\n## Result\n\n$$E=mc^2$$\n\n# Other\n\nEnd.'
        atoms, groups = source_outline(source, Path('.'))
        for atom in atoms:
            atom['doc'] = 'fixture'
        validate_groups(groups, atoms, set(range(len(atoms))))
        texts = [a['text'] for a in atoms]
        self.assertIn('$$E=mc^2$$', texts)
        step = texts.index('Step one')
        child = texts.index('Child')
        self.assertIn({'parent':step,'through':child}, groups)
        first = next(g for g in groups if g['parent']==0)
        self.assertLess(first['through'], texts.index('Other'))

    def test_display_math_blank_lines_are_not_paragraph_boundaries(self):
        equation = '$$\n\\begin{aligned}\nx &= 1 \\\\\n\ny &= 2\n\\end{aligned}\n$$'
        atoms, _ = source_outline('# Heading\n\n'+equation+'\n\nAfter.', Path('.'))
        self.assertEqual([a['text'] for a in atoms], ['Heading',equation,'After.'])

    def test_table_images_remain_html_images(self):
        atoms,_=source_outline('| Illustration | Formula |\n|---|---|\n| ![](assets/chart.png) | $\\alpha_1$ |',Path('.'))
        self.assertEqual(atoms[0]['kind'],'table')
        self.assertIn('<img src="assets/chart.png"',atoms[0]['text'])
        self.assertIn('$\\alpha_1$',atoms[0]['text'])

    def test_independent_collection_full_validation(self):
        root = Path('D:/Artifacts/RemNoteBulkImporter/test-fixtures')
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as temporary:
            folder = Path(temporary)
            source = folder/'source'
            source.mkdir()
            pages = []
            inputs = {'history/Chronology.md':'# Evidence\n\nA dated letter.\n\n- First\n  - Detail\n\n[[Archive]]',
                      'history/Archive.md':'## Table\n\n| Year | Count |\n|---|---|\n| 1800 | $n+1$ |\n\n![[chart.png]]\n\n<iframe src="https://example.org/map"></iframe>',
                      'old/Archive.md':'## Table\n\n| Year | Count |\n|---|---|\n| 1800 | $n+1$ |\n\n![[chart.png]]\n\n<iframe src="https://example.org/map"></iframe>',
                      'history/Empty.md':''}
            for number,(path,text) in enumerate(inputs.items()):
                name=str(number)+'.md'
                (source/name).write_bytes(text.encode('utf8'))
                pages.append({'path':path,'file':name,'sha256':sha(text),'notFound':False})
            from PIL import Image
            buffer=io.BytesIO();Image.new('RGB',(16,12),'green').save(buffer,format='PNG')
            image=buffer.getvalue();(source/'chart.webp').write_bytes(image)
            for name,data in {'snapshot.json':{'site':'https://example.org','pages':pages,'failures':[]},
                              'cache.json':dict.fromkeys([*inputs,'assets/chart.png'],{}),
                              'assets.json':{'records':[{'path':'assets/chart.png','file':'chart.webp','sha256':sha(image)}],'failures':[]}}.items():
                (source/name).write_text(json.dumps(data),encoding='utf8')
            package=prepare(source/'snapshot.json',folder/'output','Archive collection')
            report=json.loads((folder/'output/validation.json').read_text(encoding='utf8'))
            self.assertEqual(report['status'],'VALIDATED')
            self.assertGreater(report['info']['references'],0)
            self.assertEqual(report['info']['assets'],1)
            self.assertEqual(sum(s['kind']=='image' for n in package['nodes'] for s in n['text']),1)
            self.assertEqual(sum(n['id'].startswith('page-') for n in package['nodes']),3)


if __name__ == '__main__':
    unittest.main()
