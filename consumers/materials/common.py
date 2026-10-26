from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path

VERSION = 'material-workflow/1'
REPO = Path(__file__).resolve().parents[2]
ARTIFACTS = Path(os.getenv('RBI_MATERIAL_ARTIFACTS', 'D:/Artifacts/RemNoteBulkImporter/materials'))
CACHE = Path(os.getenv('RBI_MATERIAL_CACHE', 'D:/Caches/RemNoteBulkImporter/materials'))
STATE = Path(os.getenv('RBI_MATERIAL_STATE', 'D:/AppData/RemNoteBulkImporter/materials'))
BOOK = Path(os.getenv('RBI_BOOK_SIMPLIFIER', 'D:/Projects/BookSimplifier'))
READING = Path(os.getenv('RBI_READING_PROJECT', 'D:/Projects/渐进阅读工作流'))
HYPER = Path(os.getenv('RBI_HYPERSKILL_PROJECT', 'D:/Projects/HyperskillRemNoteWorkflow'))


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode('utf-8')).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for data in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            h.update(data)
    return h.hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    temporary = path.with_name(path.name + '.part')
    temporary.write_text(data, encoding='utf-8')
    temporary.replace(path)


def key(text):
    return ''.join(c.lower() for c in text if c.isalnum())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def source_run(source, output=None):
    source = Path(source).resolve(strict=True)
    digest = file_sha(source)
    folder = Path(output) if output else ARTIFACTS / digest[:24]
    folder.mkdir(parents=True, exist_ok=True)
    identity = {'source': str(source), 'source_sha256': digest, 'bytes': source.stat().st_size}
    if (folder / 'source.json').exists():
        previous = load(folder / 'source.json')
        require(previous['source_sha256'] == digest, 'Output directory belongs to another source')
    else:
        save(folder / 'source.json', identity)
    return source, folder, identity


@contextmanager
def run_lock(folder):
    """OS-released lock: a killed producer does not leave a permanent busy flag."""
    path=Path(folder)/'.material.lock'
    with path.open('a+b') as stream:
        if not path.stat().st_size:stream.write(b'0');stream.flush()
        stream.seek(0)
        if os.name=='nt':
            import msvcrt
            try:msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            except OSError:raise ValueError('This material run is already active') from None
        else:
            import fcntl
            try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError:raise ValueError('This material run is already active') from None
        try:yield
        finally:
            stream.seek(0)
            if os.name=='nt':msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(stream,fcntl.LOCK_UN)
