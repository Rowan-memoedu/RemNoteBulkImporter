"""Independent fixtures: audits must reject plausible, nonempty data loss."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location('source_audit', Path(__file__).parents[1] / 'consumers/audit-course-source.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class SourceAuditTests(unittest.TestCase):
    def setUp(self):
        self.graph = {'81': {'prerequisites': [12]}, '12': {'prerequisites': []}}
        self.lessons = {
            '81': {'topic': {'id': 81}, 'steps': [
                {'id': 101, 'type': 'tutorial', 'tutorial': {'content': 'Independent lecture'}},
                {'id': 103, 'type': 'example', 'example': {'question': 'A prompt', 'explanation': ''}},
                {'id': 107, 'type': 'question', 'question': {
                    'text': 'A multi-stage source question',
                    'body': {'segments': [{'text': 'First stage'}, {'select': {'index': 0, 'options': ['red', 'blue']}}]},
                    'selects': [{'index': 0, 'options': ['red', 'blue']}, {'index': 1, 'options': ['31', '47']}],
                    'sections': [{}, {'complete': False}],
                    'freeResponse': {'segments': [{'textbox': {'answer': '59', 'type': 'number'}}, {'text': ' units'}]},
                }},
            ]},
            '12': {'topic': {'id': 12}, 'steps': []},
        }
        self.package = {'nodes': []}
        def add(key, text, parent=None, kind='text'):
            self.package['nodes'].append({'id': key, 'parentId': parent, 'text': [{'kind': kind, 'value': text}]})
        add('t81', 'Independent topic')
        add('t12', 'Prerequisite')
        self.package['nodes'].append({'id': 't81.pre12', 'parentId': 't81.prereqs', 'text': [{'kind': 'ref', 'targetId': 't12'}]})
        add('t12.missing-lesson', '【源资料未提供该 Topic 的课文内容】')
        add('t81.s101', '讲解', 't81')
        add('t81.s101.content.p0', 'Independent lecture')
        add('t81.s103', '例题', 't81')
        add('t81.s103.question.p0', 'A prompt')
        add('t81.s103.explanation.missing', '【源资料未提供此处内容】')
        add('t81.s107', '练习', 't81')
        add('t81.s107.text.p0', 'A multi-stage source question')
        add('t81.s107.body.p0', 'First stage [选择 1]')
        add('t81.s107.fr.body.p0', '[填空 1] units')
        add('t81.s107.fr.answer0.text.p0', '59', kind='latex')
        add('t81.s107.section1.missing', '【源资料未提供此步骤的正文；保留下方可用选项】')
        for index, options in enumerate([['red', 'blue'], ['31', '47']]):
            add(f't81.s107.select{index}', f'选择 {index+1} 的选项')
            for option_index, option in enumerate(options):
                add(f't81.s107.select{index}.o{option_index}.text.p0', option)

    def check(self):
        return audit.audit_sources(self.graph, self.lessons, self.package)

    def remove(self, prefix):
        self.package['nodes'] = [node for node in self.package['nodes'] if not node['id'].startswith(prefix)]

    def test_independent_source_fixture_passes(self):
        report = self.check()
        self.assertEqual(report['errors'], [])
        self.assertEqual(report['counts']['sourceTextboxAnswers'], 1)
        self.assertEqual(report['counts']['selectOptions'], 4)

    def test_nonempty_question_does_not_hide_missing_source_textbox_answer(self):
        self.remove('t81.s107.fr.answer0')
        self.assertTrue(any('fr.answer0' in error for error in self.check()['errors']))

    def test_typed_code_is_nonempty_lesson_content(self):
        self.lessons['81']['steps'][0]['tutorial']['content'] = '```python\n    return 73\n```'
        next(node for node in self.package['nodes'] if node['id'] == 't81.s101.content.p0')['text'] = [
            {'kind': 'code', 'value': '    return 73', 'language': 'python'}]
        self.assertEqual(self.check()['errors'], [])

    def test_legacy_body_string_uses_structured_free_response_inventory(self):
        question = self.lessons['81']['steps'][2]['question']
        question['body'] = '[ answer: 999; type: number; ].'
        question.pop('sections')
        question['freeResponse']['segments'].insert(0, {'textbox': {'answer': '61', 'type': 'number'}})
        self.package['nodes'].append({'id': 't81.s107.fr.answer1.text.p0', 'text': [{'kind': 'latex', 'value': '59'}]})
        next(node for node in self.package['nodes'] if node['id'] == 't81.s107.fr.answer0.text.p0')['text'][0]['value'] = '61'
        report = self.check()
        self.assertEqual(report['errors'], [])
        self.assertEqual(report['counts']['sourceTextboxAnswers'], 2)

    def test_raw_dsl_without_structured_layout_requires_exact_inert_code(self):
        question = self.lessons['81']['steps'][2]['question']
        question['body'] = '[\n answer: 999;\n type: number;\n].'
        question.pop('freeResponse')
        question.pop('sections')
        self.assertTrue(any('inert code fallback' in error for error in self.check()['errors']))
        self.package['nodes'].extend([
            {'id': 't81.s107.raw-body', 'parentId': 't81.s107', 'text': [{'kind': 'text', 'value': '来源中的原始作答字段'}]},
            {'id': 't81.s107.raw-body.content', 'parentId': 't81.s107.raw-body', 'text': [{'kind': 'code', 'value': question['body']}]},
        ])
        self.assertEqual(self.check()['errors'], [])
        self.package['nodes'][-1]['text'][0]['value'] = '[ answer: 888; ].'
        self.assertTrue(any('inert code fallback' in error for error in self.check()['errors']))

    def test_first_section_does_not_hide_missing_later_options(self):
        self.remove('t81.s107.select1')
        self.assertTrue(any('select group' in error for error in self.check()['errors']))

    def test_wrong_nonempty_option_is_rejected(self):
        next(node for node in self.package['nodes'] if node['id'] == 't81.s107.select1.o1.text.p0')['text'][0]['value'] = '99'
        self.assertTrue(any('payload absent' in error for error in self.check()['errors']))

    def test_empty_source_and_unprovided_lesson_need_visible_markers(self):
        self.remove('t12.missing-lesson')
        self.remove('t81.s103.explanation')
        errors = self.check()['errors']
        self.assertTrue(any('Empty lesson' in error for error in errors))
        self.assertTrue(any('Empty source field' in error for error in errors))

    def test_dangling_or_changed_prerequisite_cannot_pass(self):
        next(node for node in self.package['nodes'] if node['id'] == 't81.pre12')['text'][0]['targetId'] = 't999'
        errors = self.check()['errors']
        self.assertTrue(any('Dangling' in error for error in errors))
        self.assertTrue(any('selected source graph' in error for error in errors))

    def test_removed_original_step_and_empty_later_section_are_detected(self):
        self.remove('t81.s101')
        self.remove('t81.s107.section1.missing')
        errors = self.check()['errors']
        self.assertTrue(any('Original lesson step absent' in error for error in errors))
        self.assertTrue(any('later section' in error for error in errors))

    def test_explicit_external_course_ignores_other_course_dependency_variant(self):
        with tempfile.TemporaryDirectory(dir='D:/Artifacts/RemNoteBulkImporter') as temporary:
            root = Path(temporary)
            with zipfile.ZipFile(root / 'graphs.zip', 'w') as archive:
                for cid, topics in [(80, {'81': {'prerequisites': [12]}}),
                                    (91, {'12': {'prerequisites': [7]}, '7': {'prerequisites': []}}),
                                    (92, {'12': {'prerequisites': []}})]:
                    archive.writestr(f'course-knowledge-graph/course-{cid}.json', json.dumps({'topics': topics}))
            with zipfile.ZipFile(root / 'topics.zip', 'w') as archive:
                for tid in [81, 12, 7]:
                    archive.writestr(f'topic-json/topic-{tid}.json', json.dumps({'lesson': {'topic': {'id': tid}, 'steps': []}}))
            graph, lessons, answers = audit.read_sources(root / 'graphs.zip', root / 'topics.zip', None, 80, 91)
            self.assertEqual(set(graph), {'81', '12', '7'})
            self.assertEqual(graph['12']['prerequisites'], [7])
            self.assertEqual(set(lessons), set(graph))
            self.assertEqual(answers, {})


if __name__ == '__main__':
    unittest.main()
