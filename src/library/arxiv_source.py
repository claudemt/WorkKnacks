from __future__ import annotations

import gzip
import io
import re
import shutil
import tarfile
import tempfile
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable

EPRINT_URL = 'https://export.arxiv.org/e-print/{id}'
API_QUERY_URL = 'https://export.arxiv.org/api/query'
USER_AGENT = 'WorkKnacks/3.0'
_MAIN_TEX = 'main.tex'


def _safe_extract(archive: tarfile.TarFile, destination: Path) -> None:
    try:
        archive.extractall(destination, filter='data')
    except TypeError:
        archive.extractall(destination)


def _extract_archive(data: bytes, extract_dir: Path) -> None:
    extract_dir.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:*') as archive:
            _safe_extract(archive, extract_dir)
            return
    except tarfile.TarError:
        pass

    if data[:2] == b'\x1f\x8b':
        try:
            content = gzip.decompress(data)
        except (OSError, EOFError):
            return
        try:
            with tarfile.open(fileobj=io.BytesIO(content), mode='r:*') as archive:
                _safe_extract(archive, extract_dir)
                return
        except tarfile.TarError:
            pass
        (extract_dir / _MAIN_TEX).write_bytes(content)
        return

    if data:
        (extract_dir / _MAIN_TEX).write_bytes(data)


def _has_documentclass(path: Path) -> bool:
    try:
        with path.open('rb') as fh:
            head = fh.read(4096)
    except OSError:
        return False
    return b'\\documentclass' in head


def _find_main_tex(root: Path) -> Path | None:
    tex_files = [p for p in root.rglob('*.tex') if p.is_file() and not p.name.startswith('.')]
    if not tex_files:
        return None
    documents = [p for p in tex_files if _has_documentclass(p)]
    pool = documents or tex_files

    def score(path: Path) -> tuple[int, int]:
        depth = len(path.relative_to(root).parts)
        return (depth, -path.stat().st_size)

    return min(pool, key=score)


_STOPWORDS = {
    'the', 'a', 'an', 'and', 'or', 'of', 'to', 'in', 'for', 'on', 'with',
    'by', 'at', 'from', 'as', 'is', 'are', 'via', 'into', 'using', 'between',
    'its', 'their', 'his', 'her', 'this', 'that', 'these', 'those', 'we',
}


def _title_tokens(title: str) -> list[str]:
    words = re.findall(r'[A-Za-z][A-Za-z0-9]{1,}', str(title or ''))
    return [w.casefold() for w in words if len(w) >= 3 and w.casefold() not in _STOPWORDS]


def _title_similarity(left: str, right: str) -> float:
    """Jaccard similarity over normalized content-word sets.

    Punctuation/word-order differences (e.g. 'PINEM)- theoretical' vs
    'PINEM: theoretical', en-dash vs hyphen) don't hurt the score, but a
    *different* paper sharing a few words scores well below a true match.
    """
    a = set(_title_tokens(left))
    b = set(_title_tokens(right))
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _family(name: str) -> str:
    name = re.sub(r'[^A-Za-z]+', ' ', str(name)).strip()
    return name.split()[-1].casefold() if name else ''


def _author_overlap(query_names, meta_names) -> int:
    q = {_family(n) for n in (query_names or []) if _family(n)}
    m = {_family(n) for n in (meta_names or []) if _family(n)}
    return len(q & m)


def _entry_meta(entry, ns: dict) -> dict:
    ident = entry.findtext('atom:id', default='', namespaces=ns) or ''
    title = ' '.join((entry.findtext('atom:title', default='', namespaces=ns) or '').split())
    authors = []
    for author in entry.findall('atom:author', ns):
        name = ' '.join((author.findtext('atom:name', default='', namespaces=ns) or '').split())
        if name:
            authors.append(name)
    published = entry.findtext('atom:published', default='', namespaces=ns) or ''
    match = re.search(r'(\d{4})', published)
    return {
        'id': ident.rsplit('/', 1)[-1] if ident else '',
        'title': title,
        'authors': authors,
        'year': int(match.group(1)) if match else 0,
    }


def _search_arxiv(query: str, *, timeout: int, max_results: int = 5) -> list[dict]:
    params = urllib.parse.urlencode({'search_query': query, 'start': 0, 'max_results': max_results})
    url = API_QUERY_URL + '?' + params
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            xml_text = response.read().decode('utf-8', errors='replace')
    except Exception:
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    ns = {'atom': 'http://www.w3.org/2005/Atom'}
    return [_entry_meta(e, ns) for e in root.findall('atom:entry', ns)]


def _verify_candidate(meta: dict, title: str, authors=None, year=None) -> bool:
    """Return True only when the arXiv entry is (very likely) the same paper.

    Title similarity alone is not enough — a different paper sharing most of a
    title (e.g. Dahan 2018 'Anomalous Photon-induced Near-field Electron
    Microscopy' vs Barwick 2009) passes a pure-title check. So when author
    names are known we additionally require at least one matching family name.
    """
    sim = _title_similarity(meta['title'], title)
    if sim < 0.5:
        return False
    if authors:
        if _author_overlap(authors, meta['authors']) < 1:
            return False
        return sim >= 0.6
    # Without author hints only a near-identical title is trustworthy — a
    # similarly-titled *different* paper (e.g. 'Anomalous Photon-induced...')
    # sits at ~0.86 and must be rejected.
    return sim >= 0.9


def arxiv_id_for_title(
    title: str,
    *,
    authors: list[str] | None = None,
    year: int | None = None,
    timeout: int = 30,
) -> str:
    """Search arXiv and return the ID of the paper matching ``title`` (or '').

    Verifies each candidate against the known title and (when available)
    author/year hints so a similarly-titled *different* paper is never adopted.
    Returns '' when nothing can be confirmed — the caller then falls back to
    MinerU rather than risk attaching the wrong source.
    """
    query = str(title or '').strip()
    if not query:
        return ''

    for meta in _search_arxiv(f'ti:"{query}"', timeout=timeout):
        if _verify_candidate(meta, query, authors, year):
            return meta['id']

    terms = sorted(_title_tokens(query), key=len, reverse=True)[:4]
    if len(terms) >= 3:
        keyword_query = ' AND '.join(f'all:{term}' for term in terms)
        for meta in _search_arxiv(keyword_query, timeout=timeout):
            if _verify_candidate(meta, query, authors, year):
                return meta['id']

    return ''


def _download(arxiv_id: str, destination: Path, *, timeout: int) -> Path:
    url = EPRINT_URL.format(id=arxiv_id.strip())
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read()
    destination.write_bytes(payload)
    return destination


def fetch_arxiv_source(
    arxiv_id: str,
    parse_dir: str | Path,
    *,
    timeout: int = 60,
    status: Callable[[str], None] | None = None,
) -> Path | None:
    """Download a paper's real TeX source from arXiv into ``parse_dir``.

    Returns the path to ``main.tex`` (the arXiv source, normalized into the
    same ``parsed/<stem>/`` layout the rest of the app expects) on success,
    or ``None`` when the paper has no downloadable arXiv source.
    """
    target = Path(parse_dir).expanduser().resolve()
    paper_id = str(arxiv_id or '').strip().rstrip('/')
    if not paper_id:
        return None
    if status:
        status('正在从 arXiv 下载预印本 TeX 源码…')

    with tempfile.TemporaryDirectory(prefix='workknacks-arxiv-') as temp_name:
        temp_root = Path(temp_name)
        try:
            archive = _download(paper_id, temp_root / 'source', timeout=timeout)
        except Exception:
            return None

        extract_dir = temp_root / 'src'
        try:
            _extract_archive(archive.read_bytes(), extract_dir)
        except Exception:
            return None

        main_src = _find_main_tex(extract_dir)
        if main_src is None:
            return None

        for child in target.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
        target.mkdir(parents=True, exist_ok=True)
        shutil.copytree(extract_dir, target, dirs_exist_ok=True)

        main_tex = target / _MAIN_TEX
        relative = main_src.relative_to(extract_dir)
        staged = target / relative
        if staged.exists() and staged.is_file():
            shutil.copy2(staged, main_tex)
        elif main_tex.is_file():
            pass
        else:
            shutil.copy2(main_src, main_tex)

        if not main_tex.is_file():
            return None
        if status:
            status('arXiv 源码下载成功，无需 MinerU。')
        return main_tex
