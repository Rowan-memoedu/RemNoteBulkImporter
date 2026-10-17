"""Independent source coverage checks; never modifies source ZIPs or packages.

This audit reads the original exports rather than conversion coverage receipts.
It checks semantic question data that can live outside the first rendered body.
It does not judge mathematics or infer answers absent from the source.
"""
from __future__ import annotations

import argparse
import collections
import html
import json
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path


class Plain(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def visible(value):
    text = re.sub(r'<!--.*?-->', '', str(value or ''), flags=re.S)
    if re.search(r'</?[a-zA-Z][^>]*>', text):
        parser = Plain()
        parser.feed(text)
        text = ''.join(parser.parts)
    return html.unescape(text).strip()


def canonical(value):
    text = visible(value).replace('[math]', '').replace('[/math]', '')
    return re.sub(r'[\W_]+', '', text, flags=re.UNICODE)


def read_sources(graph_path, topic_path, progress_path, course_id, external_course_id=None):
    with zipfile.ZipFile(graph_path) as archive:
        main = json.loads(archive.read(f'course-knowledge-graph/course-{course_id}.json'))['topics']
        outside = (json.loads(archive.read(f'course-knowledge-graph/course-{external_course_id}.json'))['topics']
                   if external_course_id is not None else {})
    selected = dict(main)
    pending = list(main)
    while pending:
        tid = pending.pop()
        for prerequisite in selected[tid]['prerequisites']:
            key = str(prerequisite)
            if key in selected:
                continue
            if key not in outside:
                raise ValueError(f'Prerequisite {key} missing from explicitly selected source course')
            selected[key] = outside[key]
            pending.append(key)
    with zipfile.ZipFile(topic_path) as archive:
        lessons = {tid: json.loads(archive.read(f'topic-json/topic-{tid}.json'))['lesson'] for tid in selected}
    answers = {}
    if progress_path:
        with zipfile.ZipFile(progress_path) as archive:
            for name in archive.namelist():
                if '/answers/' not in name or not name.endswith('.json') or name.startswith('__MACOSX/'):
                    continue
                for answer in (json.loads(archive.read(name)).get('task') or {}).get('answers') or []:
                    question = answer.get('question') or {}
                    if question.get('id') is not None:
                        answers[str(question['id'])] = question
    return selected, lessons, answers


def audit_sources(graph, lessons, package, answer_questions=None):
    errors = []
    counts = collections.Counter()
    nodes = {node['id']: node for node in package['nodes']}
    if len(nodes) != len(package['nodes']):
        errors.append('Duplicate package node IDs')
    children = collections.defaultdict(list)
    for node in nodes.values():
        children[node.get('parentId')].append(node)
    annotation = set()
    for node in nodes.values():
        if node.get('text') == [{'kind': 'text', 'value': '批注'}]:
            stack = [node]
            while stack:
                current = stack.pop()
                annotation.add(current['id'])
                stack.extend(children[current['id']])

    def content(prefix, label=None):
        result = []
        for key, node in nodes.items():
            if key in annotation or not (key == prefix or key.startswith(prefix + '.')):
                continue
            segments = node.get('text', [])
            if key == prefix and label and segments and segments[0].get('value') == label:
                segments = segments[1:]
            for segment in segments:
                if segment['kind'] == 'image':
                    result.append('[IMAGE]')
                elif segment['kind'] in ('text', 'markdown', 'latex', 'code'):
                    result.append(segment.get('value', ''))
        return '\n'.join(result).strip()

    def require_field(source, target, label=None, preserve=False):
        output = content(target, label)
        source_present = bool(visible(source) or re.search(r'<img\b', str(source or ''), re.I))
        counts['sourceFields'] += 1
        if source_present:
            if not output or '源资料未提供' in output:
                errors.append(f'Nonempty source field missing output: {target}')
            elif preserve and not re.search(r'\\documentclass|<img\b', str(source), re.I):
                expected = canonical(source)
                if expected and expected not in canonical(output):
                    errors.append(f'Source answer/option payload absent: {target}')
        else:
            counts['emptySourceFields'] += 1
            if '源资料未提供' not in output:
                errors.append(f'Empty source field lacks visible missing marker: {target}')

    expected_edges = {(f't{tid}', f't{p}') for tid, topic in graph.items() for p in topic['prerequisites']}
    actual_edges = []
    for node in nodes.values():
        for segment in node.get('text', []):
            if segment.get('kind') != 'ref':
                continue
            match = re.match(r'^(t\d+)\.pre\d+$', node['id'])
            if not match:
                errors.append(f'Unexpected source reference outside prerequisite location: {node["id"]}')
                continue
            edge = (match.group(1), segment.get('targetId'))
            actual_edges.append(edge)
            if edge[1] not in nodes:
                errors.append(f'Dangling prerequisite reference: {edge}')
    if set(actual_edges) != expected_edges or len(actual_edges) != len(expected_edges):
        errors.append('Package references differ from explicitly selected source graph')
    if {key for key in nodes if re.fullmatch(r't\d+', key)} != {f't{k}' for k in graph}:
        errors.append('Package Topic set differs from selected prerequisite closure')

    for tid, lesson in lessons.items():
        topic_id = f't{tid}'
        if str(lesson.get('topic', {}).get('id')) != str(tid):
            errors.append(f'Source lesson identity mismatch: {tid}')
        steps = lesson.get('steps') or []
        if not steps and '源资料未提供' not in content(topic_id + '.missing-lesson'):
            errors.append(f'Empty lesson lacks visible missing marker: {tid}')
        for step in steps:
            sid = f'{topic_id}.s{step["id"]}'
            counts['steps'] += 1
            kind = step['type']
            counts[kind] += 1
            if sid not in nodes or nodes[sid].get('parentId') != topic_id:
                errors.append(f'Original lesson step absent or misplaced: {sid}')
            obj = step.get(kind) or {}
            if kind == 'tutorial':
                require_field(obj.get('content'), sid + '.content')
            elif kind == 'example':
                require_field(obj.get('question'), sid + '.question', '题目')
                require_field(obj.get('explanation'), sid + '.explanation', '解答')
            elif kind == 'question':
                q = dict(obj)
                if not visible(q.get('text')):
                    extra = (answer_questions or {}).get(str(q.get('id')), {})
                    if visible(extra.get('text')):
                        q = {**extra, **{k: v for k, v in q.items() if v is not None}}
                if visible(q.get('text')):
                    require_field(q['text'], sid + '.text')
                elif '源资料未提供' not in content(sid + '.missing'):
                    errors.append(f'Empty question lacks visible missing marker: {sid}')
                for key, source in q.items():
                    if re.fullmatch(r'choice\d+', key) and visible(source):
                        require_field(source, sid + '.' + key, '选项 ' + key[6:], preserve=True)
                if visible(q.get('explanation')):
                    require_field(q['explanation'], sid + '.explanation')
                # Some exports retain an obsolete raw DSL in body alongside
                # the current structured freeResponse. It is not a segment map.
                body = q.get('body') if isinstance(q.get('body'), dict) else {}
                body_segments = body.get('segments') or []
                if any(visible(s.get('text') or s.get('mathJax')) for s in body_segments):
                    require_field('source body', sid + '.body')
                # The top-level selects inventory includes PR/DS choices whose
                # later section body was never included in the export.
                selections = {}
                for select in [s['select'] for s in body_segments if 'select' in s] + (q.get('selects') or []):
                    if not select.get('options'):
                        continue
                    index = select.get('index')
                    if index is None:
                        errors.append(f'Select without source index: {sid}')
                        continue
                    if index in selections and selections[index].get('options') != select['options']:
                        errors.append(f'Conflicting source select options: {sid} index {index}')
                    selections[index] = select
                for index, select in selections.items():
                    counts['selectGroups'] += 1
                    heading = f'选择 {index + 1} 的选项'
                    roots = [n for n in nodes.values() if re.fullmatch(re.escape(sid) + r'\.select\d+', n['id'])
                             and n.get('text') == [{'kind': 'text', 'value': heading}]]
                    if len(roots) != 1:
                        errors.append(f'Source select group absent/duplicated: {sid} index {index}')
                        continue
                    for option_index, option in enumerate(select['options']):
                        counts['selectOptions'] += 1
                        require_field(option, f'{roots[0]["id"]}.o{option_index}.text', preserve=True)
                free = q.get('freeResponse') or {}
                free_segments = free.get('segments') or [] if isinstance(free, dict) else []
                if isinstance(q.get('body'), str) and q['body'].strip() and not free_segments:
                    # Retain an unrecognized DSL as inert source, without
                    # interpreting its answer/type-looking keys as mathematics.
                    roots = [node for node in nodes.values() if node.get('parentId') == sid
                             and node.get('text') == [{'kind': 'text', 'value': '来源中的原始作答字段'}]]
                    raw_values = [segment.get('value') for root in roots for node in nodes.values()
                                  if node['id'] == root['id'] or node['id'].startswith(root['id'] + '.')
                                  for segment in node.get('text', []) if segment.get('kind') == 'code']
                    counts['rawAnswerFields'] += 1
                    if q['body'] not in raw_values:
                        errors.append(f'Unstructured source body lacks exact inert code fallback: {sid}')
                boxes = [s.get('textbox', s.get('input')) for s in body_segments + free_segments
                         if isinstance(s.get('textbox', s.get('input')), dict)]
                if isinstance(free, dict):
                    if free_segments:
                        require_field('source free-response layout', sid + '.fr.body')
                if not free and visible(q.get('freeAnswerChoice')):
                    require_field(q['freeAnswerChoice'], sid + '.free-answer', '来源作答区域', preserve=True)
                for index, box in enumerate(boxes):
                    counts['freeResponseTextboxes'] += 1
                    if box.get('answer') is not None and str(box['answer']).strip():
                        counts['sourceTextboxAnswers'] += 1
                        require_field(str(box['answer']), f'{sid}.fr.answer{index}.text', preserve=True)
                represented = {0} if body_segments else set()
                represented.update(s['select']['sectionIndex'] for s in body_segments
                                   if 'select' in s and s['select'].get('sectionIndex') is not None)
                for section_index, section in enumerate(q.get('sections') or []):
                    if section_index not in represented:
                        counts['unprovidedSectionBodies'] += 1
                        if '源资料未提供' not in content(f'{sid}.section{section_index}.missing'):
                            errors.append(f'Unprovided later section lacks missing marker: {sid} section {section_index}')
            else:
                errors.append(f'Unsupported source lesson step kind: {kind}')
    counts['topics'] = len(graph)
    counts['edges'] = len(expected_edges)
    return {'status': 'PASSED' if not errors else 'FAILED', 'counts': dict(counts), 'errors': errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('graph', 'topics', 'package'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--progress')
    parser.add_argument('--course-id', type=int, required=True)
    parser.add_argument('--external-course-id', type=int)
    parser.add_argument('--report')
    args = parser.parse_args()
    graph, lessons, answers = read_sources(args.graph, args.topics, args.progress, args.course_id, args.external_course_id)
    report = audit_sources(graph, lessons, json.loads(Path(args.package).read_text(encoding='utf-8')), answers)
    if args.report:
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report['status'] == 'PASSED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
