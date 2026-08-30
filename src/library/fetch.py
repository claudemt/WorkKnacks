from __future__ import annotations

import hashlib
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .artifacts import ArtifactLayout
from .cn_meta import _has_cjk, extract_cn_metadata
from .crossref import (
    merge_network_metadata,
    resolve_crossref_doi,
    resolve_openalex_doi,
    search_crossref,
    search_openalex,
)
from .entry import Creator, LibraryEntry, normalize_arxiv, normalize_doi
from .supplement import SupplementDetection, detect_supplement


DOI_RE = re.compile(r'\b10\.\d{4,9}/[-._;()/:A-Z0-9]+', re.I)
ARXIV_RE = re.compile(r'\b(?:arXiv\s*:\s*)?((?:\d{4}\.\d{4,5})|(?:[a-z-]+(?:\.[A-Z]{2})?/\d{7}))(?:v\d+)?\b', re.I)
ISBN_RE = re.compile(r'(?i)\b(?:ISBN(?:-1[03])?\s*[:：]?\s*)?((?:97[89][ -]?)?[0-9][0-9Xx -]{8,16}[0-9Xx])\b')


@dataclass(slots=True)
class FetchAttempt:
    source: str
    ok: bool
    message: str = ''


@dataclass(slots=True)
class FetchResult:
    entry: LibraryEntry | None
    source: str = ''
    doi: str = ''
    arxiv_id: str = ''
    attempts: list[FetchAttempt] = field(default_factory=list)
    supplement: SupplementDetection = field(default_factory=SupplementDetection)

    @property
    def found(self) -> bool:
        return self.entry is not None and bool(self.entry.title)

    @property
    def document_kind(self) -> str:
        return 'supplement' if self.supplement.is_supplement else 'primary'


class MetadataFetcher:


    def __init__(
        self,
        timeout: float = 10.0,
        retries: int = 2,
        user_agent: str = 'WorkKnacks/3.0',
        *,
        cache_dir: str | Path | None = None,
        cache_max_age_days: int = 14,
    ):
        self.timeout = timeout
        self.retries = retries
        self.user_agent = user_agent
        self.cache_dir = Path(cache_dir).expanduser().resolve() if cache_dir else None
        self.cache_max_age_seconds = max(1, int(cache_max_age_days)) * 86400
        # 网络失败短路：任一请求连接失败即视为离线，跳过后续注册源检索，避免断网时每篇卡顿。
        self._net_failed = False

    def fetch(self, pdf_path: str | Path, allow_local_parse: bool = True) -> FetchResult:
        self._net_failed = False
        path = Path(pdf_path).expanduser().resolve()
        body_text = extract_pdf_text(path, max_pages=3)
        frontmatter = extract_pdf_frontmatter(path)
        identifiers_text = (frontmatter + '\n' + body_text).strip() if frontmatter else body_text
        doi = extract_doi(identifiers_text) or extract_doi(path.name)
        arxiv_id = extract_arxiv_id(identifiers_text) or extract_arxiv_id(path.name)
        initial_supplement = detect_supplement(
            identifiers_text, filename=path.name, extracted_doi=doi
        )
        result = FetchResult(entry=None, doi=doi, arxiv_id=arxiv_id, supplement=initial_supplement)

        if arxiv_id:
            entry = self._attempt(result, 'arXiv', lambda: self.arxiv_by_id(arxiv_id))
            if entry:
                entry.arxiv_id = entry.arxiv_id or arxiv_id
                return self._finalize_result(result, entry, 'arXiv', identifiers_text, path)

        # 注册源解析：有 DOI 先精确查 Crossref/OpenAlex，取权威作者/期刊/年卷期。
        # 断网（_net_failed）时跳过所有注册源，直接走本地，避免每篇卡顿。
        if doi and not self._net_failed:
            reg_entry = self.crossref_by_doi(doi)
            reg_source = 'Crossref'
            if not reg_entry:
                reg_entry = self.openalex_by_doi(doi)
                reg_source = 'OpenAlex'
            if reg_entry:
                result.attempts.append(FetchAttempt(reg_source, True, reg_entry.title))
                reg_entry.doi = reg_entry.doi or doi
                return self._finalize_result(result, reg_entry, reg_source, identifiers_text, path)

        if _has_cjk(identifiers_text) or _has_cjk(path.stem):
            cn_entry, cn_source = extract_cn_metadata(
                text=identifiers_text, filename=path.stem, path=path
            )
            if cn_entry is not None and cn_entry.title:
                if not self._net_failed:
                    # 网络回填：中文优先 OpenAlex（更可能命中）；命中后合并填空而非替换，
                    # 保留文件名解析出的准确标题/作者。断网（_net_failed）时静默跳过。
                    authors = [c.family or c.given for c in cn_entry.creators]
                    fuzzy = self.openalex_search(cn_entry.title, authors)
                    fuzzy_source = 'OpenAlex'
                    if not fuzzy:
                        fuzzy = self.crossref_search(cn_entry.title, authors)
                        fuzzy_source = 'Crossref'
                    if fuzzy:
                        filled = merge_network_metadata(cn_entry, fuzzy)
                        cn_entry.extra['networkFields'] = filled
                        result.attempts.append(FetchAttempt(fuzzy_source, True, fuzzy.title))
                        return self._finalize_result(result, cn_entry, fuzzy_source, identifiers_text, path)
                result.attempts.append(FetchAttempt(cn_source, True, cn_entry.title))
                return self._finalize_result(result, cn_entry, cn_source, identifiers_text, path)

        local = metadata_from_text(identifiers_text, filename=path.stem)

        if allow_local_parse:
            parsed = self._local_parse_metadata(path, result)
            if parsed and parsed.title:
                return self._finalize_result(result, parsed, 'local', identifiers_text, path)

        if local.title and local.title.casefold() != path.stem.casefold():
            source = 'pdf-frontmatter' if frontmatter else 'local-text'
            return self._finalize_result(result, local, source, identifiers_text, path)
        return result

    def _finalize_result(
        self, result: FetchResult, entry: LibraryEntry, source: str, text: str, path: Path
    ) -> FetchResult:
        detection = detect_supplement(
            text,
            filename=path.name,
            metadata=entry.extra,
            extracted_doi=result.doi or entry.doi,
        )

        if result.supplement.confidence > detection.confidence and result.supplement.is_supplement:
            detection = result.supplement
        entry.extra['source'] = source
        entry.extra['documentRole'] = 'parent-of-supplement' if detection.is_supplement else 'primary'
        if detection.is_supplement:
            entry.extra['supplementDetection'] = {
                'confidence': detection.confidence,
                'reasons': list(detection.reasons),
                'parentDoi': detection.parent_doi,
                'parentTitle': detection.parent_title,
            }
        result.entry = entry
        result.source = source
        result.supplement = detection
        return result

    def _attempt(self, result: FetchResult, source: str, call: Callable[[], LibraryEntry | None]) -> LibraryEntry | None:
        try:
            entry = call()
            if entry and entry.title:
                result.attempts.append(FetchAttempt(source, True, entry.title))
                return entry
            result.attempts.append(FetchAttempt(source, False, '未命中'))
        except Exception as exc:
            result.attempts.append(FetchAttempt(source, False, str(exc)))
        return None

    def _cache_path(self, url: str, suffix: str) -> Path | None:
        if self.cache_dir is None:
            return None
        digest = hashlib.sha256(url.encode('utf-8', errors='replace')).hexdigest()
        return self.cache_dir / f'{digest}{suffix}'

    def _read_cache(self, url: str, suffix: str, *, fresh_only: bool) -> bytes | None:
        path = self._cache_path(url, suffix)
        if path is None or not path.is_file():
            return None
        try:
            if fresh_only and time.time() - path.stat().st_mtime > self.cache_max_age_seconds:
                return None
            return path.read_bytes()
        except OSError:
            return None

    def _write_cache(self, url: str, suffix: str, payload: bytes) -> None:
        path = self._cache_path(url, suffix)
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + f'.tmp-{os.getpid()}-{time.time_ns()}')
            tmp.write_bytes(payload)
            os.replace(tmp, path)
        except OSError:
            try:
                if 'tmp' in locals() and tmp.exists():
                    tmp.unlink()
            except OSError:
                pass

    def _request_text(self, url: str, *, timeout: float | None = None, retries: int | None = None) -> str:
        cached = self._read_cache(url, '.xml', fresh_only=True)
        if cached is not None:
            return cached.decode('utf-8', errors='replace')

        stale = self._read_cache(url, '.xml', fresh_only=False)
        timeout = self.timeout if timeout is None else timeout
        retries = self.retries if retries is None else retries
        request = urllib.request.Request(url, headers={'User-Agent': self.user_agent})
        last: Exception | None = None
        for attempt in range(retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    payload = response.read()
                self._write_cache(url, '.xml', payload)
                return payload.decode('utf-8', errors='replace')
            except Exception as exc:
                self._net_failed = True
                last = exc
                if attempt < retries:
                    time.sleep(0.35 * (attempt + 1))
        if stale is not None:
            return stale.decode('utf-8', errors='replace')
        raise RuntimeError(f'请求失败: {last}')

    def arxiv_by_id(self, arxiv_id: str) -> LibraryEntry | None:
        url = 'https://export.arxiv.org/api/query?' + urllib.parse.urlencode({'id_list': arxiv_id})
        return _adapt_arxiv(self._request_text(url))

    def crossref_by_doi(self, doi: str) -> LibraryEntry | None:
        return resolve_crossref_doi(doi, lambda url: self._request_text(url, timeout=6.0, retries=1))

    def crossref_search(self, title: str, authors: list[str]) -> LibraryEntry | None:
        return search_crossref(title, authors, lambda url: self._request_text(url, timeout=6.0, retries=0))

    def openalex_by_doi(self, doi: str) -> LibraryEntry | None:
        return resolve_openalex_doi(doi, lambda url: self._request_text(url, timeout=6.0, retries=1))

    def openalex_search(self, title: str, authors: list[str]) -> LibraryEntry | None:
        return search_openalex(title, authors, lambda url: self._request_text(url, timeout=6.0, retries=0))

    def _local_parse_metadata(self, path: Path, result: FetchResult) -> LibraryEntry | None:

        parse_dir = ArtifactLayout.for_source(path).parse_dir
        candidates = list(parse_dir.rglob('*')) if parse_dir.exists() else []
        candidates = [c for c in candidates if c.suffix.lower() in ('.md', '.tex', '.mmd')]
        for candidate in candidates:
            try:
                entry = _parse_ocr_output(candidate.read_text(encoding='utf-8', errors='replace'), filename=path.stem)
                if entry.title:
                    result.attempts.append(FetchAttempt('local MinerU cache', True, candidate.name))
                    return entry
            except OSError:
                continue
        try:
            from src.providers import registry
            provider = registry.get('mineru')
            if not provider:
                return None
            ok, message = provider.validate_auth()
            if not ok:
                result.attempts.append(FetchAttempt('local MinerU', False, message))
                return None
            output_dir = ArtifactLayout.for_source(path).ensure_parse_dir()
            raw_result = provider.process_file(str(path), str(output_dir))
            md_path = Path(str(raw_result).split(' + ', 1)[0])
            if md_path.exists():
                entry = _parse_ocr_output(md_path.read_text(encoding='utf-8', errors='replace'), filename=path.stem)
                result.attempts.append(FetchAttempt('local MinerU', bool(entry.title), md_path.name))
                return entry
        except Exception as exc:
            result.attempts.append(FetchAttempt('local MinerU', False, str(exc)))
        return None


def extract_doi(text: str) -> str:
    source = _normalize_identifier_text(str(text or ''))
    match = DOI_RE.search(source)
    return normalize_doi(match.group(0)) if match else ''


def _normalize_identifier_text(text: str) -> str:


    value = str(text or '').replace('\u200b', '').replace('\ufeff', '').replace('\u00ad', '')
    value = re.sub(r'(?i)(10\.\d{4,9}/)\s+(?=[A-Z0-9])', r'\1', value)
    value = re.sub(r'(?i)(doi\.org/10\.\d{4,9}/)\s+(?=[A-Z0-9])', r'\1', value)
    return value


def extract_arxiv_id(text: str) -> str:
    match = ARXIV_RE.search(str(text or ''))
    return normalize_arxiv(match.group(1)) if match else ''


def _plausible_year(value) -> int | None:
    match = re.search(r'(?:19|20)\d{2}', str(value or ''))
    if not match:
        return None
    year = int(match.group())
    now = time.localtime().tm_year
    return year if 1900 <= year <= now + 1 else None


def extract_isbn(text: str) -> str:
    for match in ISBN_RE.finditer(str(text or '')):
        raw = re.sub(r'[^0-9Xx]', '', match.group(1))
        if len(raw) in {10, 13}:
            return raw.upper()
    return ''


def extract_pdf_text(path: str | Path, max_pages: int = 3) -> str:
    path = Path(path)
    if not path.exists():
        return ''

    try:
        import fitz
        doc = fitz.open(str(path))
        try:
            return '\n'.join(doc[i].get_text('text') for i in range(min(max_pages, doc.page_count)))
        finally:
            doc.close()
    except Exception:
        pass
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        return '\n'.join((page.extract_text() or '') for page in reader.pages[:max_pages])
    except Exception:
        pass
    try:
        raw = path.read_bytes()[:2_000_000]

        return raw.decode('latin-1', errors='ignore')
    except OSError:
        return ''


def _is_letter_spaced_header(text: str) -> bool:
    """短的全大写、高空格比文本，通常是期刊页眉/卷标（如 'P LAN ETARY SCI EN C E'）。"""
    if not text.isupper() or len(text) < 8:
        return False
    return text.count(' ') / max(1, len(text)) > 0.25


def extract_pdf_frontmatter(path: str | Path) -> str:

    pdf = Path(path)
    if not pdf.is_file():
        return ''
    try:
        import fitz
        doc = fitz.open(str(pdf))
        try:
            if doc.page_count < 1:
                return ''
            page = doc[0]
            flines = []
            blocks = []
            for block in page.get_text('dict').get('blocks', []):
                if 'lines' not in block:
                    continue
                spans = [span for line in block.get('lines', []) for span in line.get('spans', [])]
                text = ' '.join(' '.join(str(span.get('text') or '') for span in spans).split())
                if not text:
                    continue
                max_size = max((float(span.get('size') or 0) for span in spans), default=0.0)
                x0, y0, x1, y1 = block.get('bbox', (0, 0, 0, 0))
                blocks.append({'text': _normalize_pdf_unicode(text), 'size': max_size, 'y0': float(y0), 'y1': float(y1)})
                for line in block.get('lines', []):
                    lspans = line.get('spans', [])
                    ltext = ' '.join(' '.join(str(span.get('text') or '') for span in lspans).split())
                    if not ltext:
                        continue
                    lsize = max((float(span.get('size') or 0) for span in lspans), default=0.0)
                    lbbox = line.get('bbox', (0, 0, 0, 0))
                    flines.append({'text': _normalize_pdf_unicode(ltext), 'size': lsize, 'y0': float(lbbox[1]), 'y1': float(lbbox[3])})
        finally:
            doc.close()
    except Exception:
        return ''

    abstract_y = min((l['y0'] for l in flines if re.search(r'(?i)^abstract\s*(?:[|:—-]|$)', l['text'])), default=10_000.0)

    # 标题：按行 + 同字号连续行构成标题块，取顶部区域字号最大者。
    # 页眉（如期刊名 'P LAN ETARY SCI EN C E'）字号通常较小、全大写，被 size/全大写/字母间距规则剔除。
    runs: list[dict] = []
    for l in flines:
        text = l['text'].strip()
        if not (8 <= len(text) <= 350 and 1 <= len(text.split()) <= 40):
            continue
        if l['y0'] >= abstract_y:
            continue
        if l['size'] < 12 or l['size'] > 36:
            continue
        if text.isupper() and len(text.split()) <= 4:
            continue
        if _is_letter_spaced_header(text):
            continue
        if re.fullmatch(r'(?i)(reviews?|articles?|letters?|perspectives?|editorials?|research)', text):
            continue
        if runs and runs[-1]['size'] == l['size'] and l['y0'] - runs[-1]['y1'] < 8:
            runs[-1]['y1'] = max(runs[-1]['y1'], l['y1'])
            runs[-1]['text'] = (runs[-1]['text'] + ' ' + text).strip()
        else:
            runs.append({'size': l['size'], 'y0': l['y0'], 'y1': l['y1'], 'text': text})
    if not runs:
        return ''
    title_run = max(runs, key=lambda r: (r['size'], -r['y0']))
    title = ' '.join(title_run['text'].split())
    title_y1 = title_run['y1']
    author_candidates = [
        b for b in blocks
        if title_y1 <= b['y0'] < abstract_y
        and 4 <= len(b['text']) <= 600
        and not re.search(r'(?i)^abstract\b|department|university|institute|laboratory|doi\.org|\bet\s+al\b|Sci\.?\s+Adv', b['text'])
    ]
    authors = min(author_candidates, key=lambda b: b['y0'], default=None)
    author_text = _clean_pdf_author_line(authors['text']) if authors else ''

    all_text = '\n'.join(b['text'] for b in blocks)
    doi = extract_doi(all_text)
    _months = 'January|February|March|April|May|June|July|August|September|October|November|December'
    month_years = re.findall(r'(?i)\b(?:([0-9]{1,2})\s+)?(?:' + _months + r')\s+((?:19|20)\d{2})\b', all_text)
    year = ''
    if month_years:
        # 优先带日期的完整日期（如 28 April 2023 = 出版日）；否则取最大年份。
        dated = [int(y) for d, y in month_years if d]
        if dated:
            year = str(max(dated))
        else:
            year = str(max(int(y) for _, y in month_years))
    lines = [title]
    if author_text:
        lines.append(author_text)
    if doi:
        lines.append('DOI: ' + doi)
    if year:
        lines.append('Published: ' + year)
    return '\n'.join(lines)


def _clean_pdf_author_line(value: str) -> str:
    text = _normalize_pdf_unicode(value)
    text = re.sub(r'[✉†‡§*]+', ' ', text)
    text = re.sub(r'(?<=\D)\s+\d+(?=\s|$)', ' ', text)
    text = re.sub(r'(?<=[A-Za-z])\d+', '', text)  # 姓名后紧跟的上下标/单位序号：Qin1 → Qin
    text = re.sub(r',\s*\d+', ' ', text)           # 序号与逗号粘连：Wu1,3 → Wu
    text = re.sub(r'\b\d+\b', ' ', text)           # 兜底：任何残留的孤立数字
    text = re.sub(r'\s+', ' ', text).strip(' ,;')
    return text

def metadata_from_markdown(markdown: str, filename: str = '') -> LibraryEntry:
    return metadata_from_text(markdown, filename=filename)


def _strip_latex_cmds(text: str) -> str:
    """去掉 LaTeX 命令/花括号/注释并折叠空白，保留正文文本。不裁剪前言。"""
    text = re.sub(r'(?m)%.*$', '', text)                       # LaTeX 注释
    text = re.sub(r'\\(?:[a-zA-Z]+)\*?(?:\[[^\]]*\])?', ' ', text)  # \cmd / \cmd[opt]
    text = text.replace('{', ' ').replace('}', ' ')
    text = text.replace('\\', ' ')
    return re.sub(r'\s+', ' ', text).strip()


def _latex_body(tex: str) -> str:
    """裁剪掉 LaTeX 前言（\begin{document} 之前），便于行扫描标题。"""
    i = str(tex or '').find(r'\begin{document}')
    body = str(tex or '')[i:] if i != -1 else str(tex or '')
    return _strip_latex_cmds(body)


def metadata_from_latex(latex: str, filename: str = '') -> LibraryEntry:
    r"""从 MinerU 的 LaTeX OCR 输出提取元信息。

    之前直接把 .tex 当 markdown 喂给 metadata_from_markdown，导致前言第一行
    「% This LaTeX document needs to be compiled with XeLaTeX.」被当标题。这里
    优先读 title / author / date 宏；缺省时裁掉前言交给行扫描。
    """
    tex = str(latex or '')
    entry = metadata_from_text(_latex_body(tex), filename=filename)

    tm = re.search(r'\\title\s*\{([^{}]*)\}', tex)
    if tm:
        t = _strip_latex_cmds(tm.group(1)).strip(' \n')
        if _has_cjk(t) and 2 <= len(t) <= 200:
            entry.title = t
            entry.language = 'zh'
    am = re.search(r'\\author\s*\{([^{}]*)\}', tex)
    if am:
        raw = _strip_latex_cmds(am.group(1))
        names = [n.strip(' ,，、\n') for n in re.split(r'\\and|\band\b|[;；]', raw) if n.strip()]
        if names:
            entry.creators = [Creator.from_any(n) for n in names if n]
    dm = re.search(r'\\date\s*\{([^{}]*)\}', tex)
    if dm:
        y = _plausible_year(_strip_latex_cmds(dm.group(1)))
        if y:
            entry.year = y
    return entry


def _parse_ocr_output(text: str, filename: str = '') -> LibraryEntry:
    """按内容自动分发：LaTeX 源（MinerU 默认输出）→ metadata_from_latex，否则按 markdown。"""
    t = (str(text or '') or '').lstrip()
    if (t.startswith('%') or t.startswith('\\')
            or '\\documentclass' in t or '\\begin{document}' in t):
        return metadata_from_latex(text, filename=filename)
    return metadata_from_markdown(text, filename=filename)


def metadata_from_text(text: str, filename: str = '') -> LibraryEntry:
    lines = [line.strip() for line in str(text or '').splitlines() if line.strip()]
    title = ''
    title_index = -1
    for idx, line in enumerate(lines[:80]):
        cleaned = re.sub(r'^#{1,6}\s*', '', line).strip()
        if not cleaned or cleaned.lower().startswith(('doi:', 'arxiv:', 'abstract', '摘要')):
            continue
        if re.search(r'^\d{4}\s*Vol|\bVol[.．]?\s*\d+\s*,\s*No[.．]?\s*\d+\b', cleaned, re.I):
            continue
        if re.fullmatch(r'\d{1,4}[\s.,;:]*', cleaned):
            continue
        if _is_letter_spaced_header(cleaned):
            continue
        if 8 <= len(cleaned) <= 350 and not re.fullmatch(r'[\d\W_]+', cleaned):
            title = _normalize_pdf_unicode(cleaned)
            title_index = idx
            break
    if not title:
        title = filename.replace('_', ' ').strip()
    doi = extract_doi(text)
    arxiv_id = extract_arxiv_id(text)
    isbn = extract_isbn(text)
    head_text = '\n'.join(lines[:180])
    year_match = (
        re.search(r'(?im)^\s*Published\s*:[^\n]*(\b(?:19|20)\d{2}\b)', head_text)
        or re.search(r'(?i)\b(?:J\.|Journal|Phys\.|Chem\.|Nature|Science)\b[^\n]{0,100}?(\b(?:19|20)\d{2}\b)', head_text)
        or re.search(r'\b(?:19|20)\d{2}\b', head_text)
    )
    language = 'zh' if re.search(r'[\u4e00-\u9fff]', title) else 'en'
    creators: list[Creator] = []
    if 0 <= title_index < len(lines) - 1:


        for candidate in lines[title_index + 1:title_index + 5]:
            clean = re.sub(r'[\*†‡§]+', '', _normalize_pdf_unicode(candidate)).strip()
            if re.search(r'(?i)\b(abstract|department|university|institute|laboratory|center|school|college|address)\b', clean):
                break
            if len(clean) > 600 or any(ch.isdigit() for ch in clean):
                continue
            names = re.split(r'\s*,\s*|\s+(?:and|&)\s+|\s*;\s*', clean)
            names = [name.strip(' ,') for name in names if name.strip(' ,')]
            # \u9632 "Family, Given" \u5355\u4f5c\u8005\u88ab\u8bef\u62c6\u6210\u4e24\u4eba
            if len(names) == 2 and all(' ' not in n for n in names):
                names = [clean]
            names = [name for name in names if 2 <= len(name) <= 80]
            if names and all(re.search(r'[A-Za-z\u4e00-\u9fff]', name) for name in names):
                creators = [Creator.from_any(name) for name in names]
                break
    publication = ''
    for line in lines[:180]:
        clean = _normalize_pdf_unicode(line).strip()
        match = re.search(r'(?i)^((?:The\s+)?Journal of .{3,80}|Physical Review [A-Z](?: .*)?|Nature(?: Physics| Photonics| Chemistry| Materials| Communications)?|Science(?: Advances| Translational Medicine| Robotics)?)$', clean)
        if match:
            publication = match.group(1).strip()
            break
    if not publication:
        normalized_head = _normalize_pdf_unicode(head_text)
        if re.search(r'(?i)\bnatrevphys\b|Nature\s+Rev\w*\s*\|?\s*Phys\w*', normalized_head):
            publication = 'Nature Reviews Physics'
        else:
            for line in lines[:240]:
                match = re.search(r'\|\s*([A-Z][A-Za-z. ]{3,60})\s+(?:19|20)\d{2}\s*,', _normalize_pdf_unicode(line))
                if match:
                    publication = ' '.join(match.group(1).split()).strip()
                    break


    is_book = bool(isbn) or bool(re.search(
        r'(?i)\b(?:\d+(?:st|nd|rd|th)\s+edition|revised\s+edition|publisher|published\s+by|isbn|library\s+of\s+congress|university\s+press|\w+\s+press)\b',
        head_text,
    ))
    edition = ''
    publisher = ''
    if is_book:
        edition_match = re.search(
            r'(?i)\b((?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|\d+(?:st|nd|rd|th))\s+(?:revised\s+)?edition)\b',
            head_text,
        )
        if edition_match:
            edition = ' '.join(edition_match.group(1).split())
        publisher_pattern = re.compile(
            r'(?i)\b(?:Cambridge University Press|Oxford University Press|Princeton University Press|MIT Press|Springer(?:-Verlag)?|Elsevier|Wiley(?:-VCH)?|CRC Press|Taylor\s*&\s*Francis|McGraw[- ]Hill|World Scientific|(?:[A-Z][A-Za-z&. -]{2,50}\s+Press))\b'
        )
        for candidate in lines[:100]:
            match = publisher_pattern.search(_normalize_pdf_unicode(candidate))
            if match:
                publisher = ' '.join(match.group(0).split())
                break
    return LibraryEntry(
        item_type='book' if is_book and not doi and not arxiv_id else 'journalArticle',
        title=title, creators=creators, doi=doi, arxiv_id=arxiv_id, isbn=isbn,
        year=_plausible_year(year_match.group(1) if year_match.lastindex else year_match.group()) if year_match else None, language=language,
        publication_title=publication, publisher=publisher, edition=edition,
    )


def _normalize_pdf_unicode(value: str) -> str:
    return str(value).translate(str.maketrans({
        'ﬀ': 'ff', 'ﬁ': 'fi', 'ﬂ': 'fl', 'ﬃ': 'ffi', 'ﬄ': 'ffl',
        '\u00ad': '',
    }))


def _adapt_arxiv(xml_text: str) -> LibraryEntry | None:
    if not xml_text:
        return None
    root = ET.fromstring(xml_text)
    ns = {'atom': 'http://www.w3.org/2005/Atom', 'arxiv': 'http://arxiv.org/schemas/atom'}
    entry_node = root.find('atom:entry', ns)
    if entry_node is None:
        return None
    title = ' '.join((entry_node.findtext('atom:title', default='', namespaces=ns) or '').split())
    summary = ' '.join((entry_node.findtext('atom:summary', default='', namespaces=ns) or '').split())
    published = entry_node.findtext('atom:published', default='', namespaces=ns) or ''
    creators = [Creator.from_any(node.findtext('atom:name', default='', namespaces=ns) or '') for node in entry_node.findall('atom:author', ns)]
    url = entry_node.findtext('atom:id', default='', namespaces=ns) or ''
    arxiv_id = url.rsplit('/', 1)[-1]
    doi = entry_node.findtext('arxiv:doi', default='', namespaces=ns) or ''
    return LibraryEntry(
        item_type='preprint',
        title=title,
        creators=creators,
        year=int(published[:4]) if published[:4].isdigit() else None,
        date=published,
        doi=doi,
        arxiv_id=arxiv_id,
        abstract=summary,
        language='en',
        url=url,
    )


