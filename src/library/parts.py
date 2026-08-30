from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

_CJK = r'一-鿿'
_CJK_NUM = '一二三四五六七八九十'
_TRAIL_QUOTE = r'[》」』]*'

# 分卷标记统一取「标题尾部」的成对/明确后缀，避免误伤正文里的单字“上下”。
# 每个模式捕获两组：base（去标记正题）、marker（原始标记）。
_MARKER_PATTERNS = [
    re.compile(rf'^(?P<base>.+?)\s*(?P<marker>[（(](?:上|中|下|续|续一|续二|续三|[{_CJK_NUM}])[)）]){_TRAIL_QUOTE}$'),
    re.compile(rf'^(?P<base>.+?)\s*(?P<marker>上册|中册|下册|上篇|中篇|下篇){_TRAIL_QUOTE}$'),
    re.compile(rf'^(?P<base>.+?)\s*(?P<marker>之[{_CJK_NUM}]){_TRAIL_QUOTE}$'),
    re.compile(rf'^(?P<base>.+?)\s*(?P<marker>第[{_CJK_NUM}百]+[卷辑]){_TRAIL_QUOTE}$'),
    re.compile(r'^(?P<base>.+?)\s*Part\s*(?P<marker>I{1,3}|IV|V|[1-9])\s*$', re.I),
    re.compile(r'^(?P<base>.+?)\s*(?P<marker>[（(](?:[1-9]|I{1,3}|IV|V)[)）])\s*$'),
]

_CJK_ORDER = {
    '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
    '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
    '上': 1, '中': 2, '下': 3,
    '续': 98, '续一': 99, '续二': 100, '续三': 101,
}
_ROMAN_ORDER = {'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5}


@dataclass(slots=True)
class Part:
    base: str = ''
    marker: str = ''
    order: int | None = None


def _clean_text(value: Any) -> str:
    return re.sub(r'\s+', ' ', str(value or '').replace('　', ' ')).strip()


def _order_for(marker: str) -> int | None:
    m = str(marker).strip()
    m = m.strip('（()）')  # 括号标记去掉分隔符再判序
    if not m:
        return None
    if m.startswith('第') and len(m) >= 3 and m[-1] in '卷辑':
        return _CJK_ORDER.get(m[1:-1])
    if m.startswith('之') and len(m) >= 2:
        return _CJK_ORDER.get(m[1:])
    if len(m) > 1 and m[0] in '上下中':
        return _CJK_ORDER.get(m[0])
    if m in _CJK_ORDER:
        return _CJK_ORDER[m]
    if m.isdigit():
        return int(m)
    return _ROMAN_ORDER.get(m.upper())


def parse_part(text: Any) -> Part | None:
    s = _clean_text(text)
    if not s:
        return None
    for pattern in _MARKER_PATTERNS:
        match = pattern.match(s)
        if not match:
            continue
        base = _clean_text(match.group('base'))
        marker = _clean_text(match.group('marker'))
        if len(base) < 2:
            continue
        return Part(base=base, marker=marker, order=_order_for(marker))
    return None


def strip_part_markers(text: Any) -> str:
    part = parse_part(text)
    return part.base if part else _clean_text(text)


def _norm(value: str) -> str:
    return ' '.join(''.join(ch.lower() if ch.isalnum() else ' ' for ch in str(value)).split())


def is_part_of(candidate_text: Any, parent_title: Any) -> bool:
    """candidate 是否与 parent 属于同一部作品的分卷（两者去分卷标记后的正题一致/高相似）。"""
    candidate_base = strip_part_markers(candidate_text)
    parent_base = strip_part_markers(parent_title)
    if not candidate_base or not parent_base:
        return False
    if candidate_base == parent_base:
        return True
    return SequenceMatcher(None, _norm(candidate_base), _norm(parent_base)).ratio() >= 0.85
