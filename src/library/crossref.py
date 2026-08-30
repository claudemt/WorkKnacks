from __future__ import annotations

import difflib
import json
import re
from typing import Callable

from .entry import Creator, LibraryEntry

# 注册源客户端：Crossref + OpenAlex。网络层由调用方注入（fetch.MetadataFetcher 复用其
# urllib + 缓存 + 重试），避免与本包其它模块循环导入。所有失败一律返回 None，绝不抛出。

_CJK_RE = re.compile(r'[一-鿿]')
_SIM_THRESHOLD = 0.85  # 标题模糊搜采纳阈值


def _has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(str(text or '')))


def _norm(value: str) -> str:
    return re.sub(r'[\s\W_]+', '', str(value or '')).lower()


def _first(items) -> str:
    for item in items or []:
        if isinstance(item, str) and item.strip():
            return item.strip()
    return ''


def _crossref_year(message: dict) -> int | None:
    for key in ('published-print', 'published-online', 'published', 'issued', 'created'):
        date = message.get(key) or {}
        parts = (date.get('date-parts') or [[]])[0]
        year = parts[0] if parts else None
        if isinstance(year, int):
            return year
        if isinstance(year, str) and year.isdigit():
            return int(year)
    return None


def _crossref_creators(message: dict) -> list[Creator]:
    creators: list[Creator] = []
    for author in message.get('author') or []:
        family = str(author.get('family') or '').strip()
        given = str(author.get('given') or '').strip()
        if family or given:
            creators.append(Creator(family=family, given=given))
    return creators


def entry_from_crossref(message: dict) -> LibraryEntry | None:
    title = _first(message.get('title'))
    if not title:
        return None
    journal = _first(message.get('container-title'))
    creators = _crossref_creators(message)
    language = 'zh' if _has_cjk(title) else 'en'
    entry = LibraryEntry(
        item_type='journalArticle',
        title=title.rstrip('.'),
        creators=creators,
        year=_crossref_year(message),
        language=language,
        publication_title=journal,
        doi=str(message.get('DOI') or '').strip(),
        volume=str(message.get('volume') or '').strip(),
        issue=str(message.get('issue') or '').strip(),
    )
    if message.get('ISBN'):
        isbn = str(message['ISBN'][0]) if isinstance(message.get('ISBN'), list) else str(message.get('ISBN'))
        entry.isbn = re.sub(r'[^0-9Xx]', '', isbn).upper()
    entry.extra['publisher'] = str(message.get('publisher') or '').strip()
    entry.extra['source'] = 'crossref'
    return entry


def _openalex_abstract(item: dict) -> str:
    """OpenAlex 摘要以 abstract_inverted_index（词→位置列表）存储，按位置重组原文。"""
    aii = item.get('abstract_inverted_index') or {}
    if not isinstance(aii, dict) or not aii:
        return ''
    pos: dict[int, str] = {}
    for word, idxs in aii.items():
        for i in idxs:
            pos[int(i)] = str(word)
    if not pos:
        return ''
    return ' '.join(pos[i] for i in sorted(pos)).strip()


def _openalex_pages(biblio: dict) -> tuple[str, str, str]:
    """从 biblio 提取 (pages 串, pageStart, pageEnd)。"""
    first = str(biblio.get('first_page') or '').strip()
    last = str(biblio.get('last_page') or '').strip()
    pages = ''
    if first and last:
        pages = f'{first}-{last}'
    elif first:
        pages = first
    return pages, first, last


def entry_from_openalex(item: dict) -> LibraryEntry | None:
    title = str(item.get('title') or '').strip()
    if not title:
        return None
    creators: list[Creator] = []
    for authorship in item.get('authorships') or []:
        name = (authorship.get('author') or {}).get('display_name')
        if name:
            creators.append(Creator.from_any(str(name).strip()))
    source = (item.get('primary_location') or {}).get('source') or {}
    journal = str(source.get('display_name') or '').strip()
    biblio = item.get('biblio') or {}
    doi = ''
    if item.get('doi'):
        doi = str(item['doi']).replace('https://doi.org/', '').replace('http://doi.org/', '')
    language = 'zh' if _has_cjk(title) else 'en'
    pages, page_start, page_end = _openalex_pages(biblio)
    entry = LibraryEntry(
        item_type='journalArticle',
        title=title.rstrip('.'),
        creators=creators,
        year=item.get('publication_year') or None,
        language=language,
        publication_title=journal,
        doi=doi,
        volume=str(biblio.get('volume') or '').strip(),
        issue=str(biblio.get('issue') or '').strip(),
        pages=pages,
        abstract=_openalex_abstract(item),
    )
    if page_start:
        entry.extra['pageStart'] = page_start
    if page_end:
        entry.extra['pageEnd'] = page_end
    entry.extra['source'] = 'openalex'
    return entry


def _accepted(query: str, title: str) -> float | None:
    """标题匹配分；同时满足相似度阈值或子串包含（中文标题常带副标题稀释比值）。"""
    a, b = _norm(query), _norm(title)
    if not a or not b:
        return None
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    if ratio >= _SIM_THRESHOLD or a in b or b in a:
        return ratio
    return None


def resolve_crossref_doi(doi: str, request_text: Callable[[str], str]) -> LibraryEntry | None:
    """精确 DOI 解析 Crossref。"""
    if not doi:
        return None
    url = f'https://api.crossref.org/works/{doi}?mailto=workknacks@localhost'
    try:
        payload = json.loads(request_text(url))
    except Exception:
        return None
    message = payload.get('message') or {}
    entry = entry_from_crossref(message)
    return entry if entry else None


def search_crossref(title: str, authors: list[str], request_text: Callable[[str], str]) -> LibraryEntry | None:
    """标题+作者模糊搜 Crossref；相似度≥0.85 且标题含中文才采纳。"""
    query_title = _norm(title)
    if not query_title:
        return None
    import urllib.parse
    params = {'query.title': title, 'query.bibliographic': ' '.join(authors), 'rows': '8'}
    url = 'https://api.crossref.org/works?' + urllib.parse.urlencode(params) + '&mailto=workknacks@localhost'
    try:
        payload = json.loads(request_text(url))
    except Exception:
        return None
    items = (payload.get('message') or {}).get('items') or []
    best: tuple[float, LibraryEntry] | None = None
    for item in items:
        cand = entry_from_crossref(item)
        if not cand or not _has_cjk(cand.title):
            continue
        score = _accepted(query_title, cand.title)
        if score is not None and (best is None or score > best[0]):
            best = (score, cand)
    return best[1] if best else None


def resolve_openalex_doi(doi: str, request_text: Callable[[str], str]) -> LibraryEntry | None:
    if not doi:
        return None
    url = 'https://api.openalex.org/works/doi:' + doi.replace('doi:', '')
    try:
        payload = json.loads(request_text(url))
    except Exception:
        return None
    if 'error' in payload or 'title' not in payload:
        return None
    return entry_from_openalex(payload)


def search_openalex(title: str, authors: list[str], request_text: Callable[[str], str]) -> LibraryEntry | None:
    """标题模糊搜 OpenAlex。中文标题优先用 filter=title.search（更精确），空结果回退 search=<title>。"""
    import urllib.parse
    query = _norm(title)
    if not query:
        return None
    # 优先精确标题过滤；对中文标题召回与排序更准
    filter_url = ('https://api.openalex.org/works?' + urllib.parse.urlencode(
        {'filter': 'title.search:' + title, 'per-page': '8', 'mailto': 'workknacks@localhost'}))
    best = _best_openalex_hit(request_text, filter_url, query)
    if best is None:
        fallback_url = ('https://api.openalex.org/works?' + urllib.parse.urlencode(
            {'search': title, 'per-page': '8', 'mailto': 'workknacks@localhost'}))
        best = _best_openalex_hit(request_text, fallback_url, query)
    return best


def _best_openalex_hit(request_text: Callable[[str], str], url: str, query: str) -> LibraryEntry | None:
    try:
        payload = json.loads(request_text(url))
    except Exception:
        return None
    results = payload.get('results') or []
    best: tuple[float, LibraryEntry] | None = None
    for item in results:
        cand = entry_from_openalex(item)
        if not cand or not _has_cjk(cand.title):
            continue
        score = _accepted(query, cand.title)
        if score is not None and (best is None or score > best[0]):
            best = (score, cand)
    return best[1] if best else None


def merge_network_metadata(entry: LibraryEntry, net: LibraryEntry) -> list[str]:
    """把 net（OpenAlex/Crossref）的元数据填进 entry 的空位；只填空、不覆盖。

    返回本次补全的字段名列表，供 GUI/探针展示「OpenAlex 补全了哪些字段」。
    entry 的 title/creators 不动（文件名解析通常更准），保持精度。
    """
    filled: list[str] = []

    def _fill(key: str) -> None:
        if not getattr(entry, key) and getattr(net, key):
            setattr(entry, key, getattr(net, key))
            filled.append(key)

    for key in ('publication_title', 'volume', 'issue', 'pages', 'abstract', 'year', 'doi', 'publisher'):
        _fill(key)
    # extra 层：net 有而 entry 空才写（pageStart/pageEnd/journal/affiliation）
    for key in ('pageStart', 'pageEnd', 'journal', 'affiliation'):
        if net.extra.get(key) and not entry.extra.get(key):
            entry.extra[key] = net.extra[key]
            filled.append(key)
    if filled:
        # 标出网络回填来源（OpenAlex/Crossref），供上层展示
        entry.extra['networkEnriched'] = net.extra.get('source') or 'network'
    return filled
