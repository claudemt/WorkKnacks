from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .entry import normalize_doi


SUPPLEMENT_NAME_RE = re.compile(
    r'(?i)(?:^|[._\-\s])(supp(?:lement(?:ary)?)?|supporting[._\-\s]*info(?:rmation)?|si|esm|mmc|suppmat)(?:$|[._\-\s\d])'
)
STRONG_HEADER_RE = re.compile(
    r'(?im)^\s*(?:supporting|supplementary|supplemental)\s+(?:information|material(?:s)?)(?:\s+(?:for|to)\b|\s*$)'
)
FOR_PARENT_RE = re.compile(
    r'(?is)(?:supporting|supplementary|supplemental)\s+(?:information|material(?:s)?)\s+(?:for|to)\s*[:\-]?\s*([^\n]{8,300})'
)
MAIN_ARTICLE_MARKERS = (
    'abstract:', '\nabstract\n', '\n■ introduction', '\nintroduction\n',
    'received:', 'revised:', 'published:', 'article\npubs.', 'journal of ',
)
ASSOCIATED_CONTENT_RE = re.compile(r'(?is)associated\s+content.{0,220}(?:supporting|supplementary)\s+information')


@dataclass(slots=True)
class SupplementDetection:
    is_supplement: bool = False
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)
    parent_doi: str = ''
    parent_title: str = ''
    relation_source: str = ''

    @property
    def label(self) -> str:
        if not self.is_supplement:
            return 'primary'
        if self.confidence >= 0.85:
            return 'supplement-high'
        if self.confidence >= 0.65:
            return 'supplement-medium'
        return 'supplement-low'


def detect_supplement(
    text: str,
    *,
    filename: str = '',
    metadata: dict[str, Any] | None = None,
    extracted_doi: str = '',
) -> SupplementDetection:
    
    source = str(text or '')
    lower = source.casefold()
    first = '\n'.join(source.splitlines()[:80])
    score = 0.0
    reasons: list[str] = []
    parent_doi = ''
    parent_title = ''
    relation_source = ''

    relation = _supplement_relation(metadata or {})
    if relation:
        parent_doi = relation
        score += 0.9
        relation_source = 'metadata-relation'
        reasons.append('元数据包含 isSupplementTo / is-supplement-to 关系')

    if filename and SUPPLEMENT_NAME_RE.search(Path(filename).stem):
        score += 0.45
        reasons.append('文件名符合常见 supplementary/SI 命名')

    strong_header = STRONG_HEADER_RE.search(first)
    if strong_header:
        score += 0.65
        reasons.append('文档首页标题明确标注 Supporting/Supplementary Material')

    parent_match = FOR_PARENT_RE.search(first)
    if parent_match:
        candidate = ' '.join(parent_match.group(1).split()).strip(' :-')
        
        candidate = re.split(r'\s{2,}|\bAuthors?\s*:', candidate, maxsplit=1, flags=re.I)[0].strip()
        if candidate and len(candidate) >= 8:
            parent_title = candidate[:300]
            score += 0.15
            reasons.append('首页包含“Supplementary … for <母文章>”结构')

    
    
    
    
    
    
    if strong_header and not parent_title:
        lines = [line.strip() for line in first.splitlines()]
        try:
            header_line = source[: strong_header.end()].count('\n')
        except Exception:
            header_line = -1
        for candidate in lines[header_line + 1 : header_line + 6] if header_line >= 0 else []:
            candidate = ' '.join(candidate.split()).strip(' :-')
            low = candidate.casefold()
            if not (8 <= len(candidate) <= 300):
                continue
            if any(token in low for token in ('doi:', 'http://', 'https://', 'authors:', 'author:', 'affiliation', 'abstract', 'contents')):
                continue
            if re.search(r'(?i)\b(university|institute|department|laboratory|college|school)\b', candidate):
                continue
            if candidate.count(',') >= 3 and len(candidate.split()) < 18:
                continue
            parent_title = candidate
            score += 0.10
            reasons.append('Supporting Information 标题后的首个有效文本行作为母文章标题候选')
            break

    
    
    marker_count = sum(1 for marker in MAIN_ARTICLE_MARKERS if marker in lower)
    if marker_count >= 2:
        score -= 0.55
        reasons.append('检测到摘要/引言/收稿信息等主文章结构')
    elif marker_count == 1:
        score -= 0.20

    
    
    if ASSOCIATED_CONTENT_RE.search(source):
        score -= 0.35
        reasons.append('仅在 Associated Content 中引用 Supporting Information，倾向主文章')

    
    
    if re.search(r'(?im)^\s*\*?s\s+supporting\s+information\s*$', first) and 'abstract:' in first.casefold() and not strong_header:
        score -= 0.25
        reasons.append('首页“S Supporting Information”与主文摘要共存，不单独视为补充材料')

    score = max(0.0, min(1.0, score))
    is_supplement = bool(relation) or score >= 0.65

    if is_supplement and not parent_doi:
        
        
        parent_doi = normalize_doi(extracted_doi)
        if parent_doi:
            reasons.append('将文档内 DOI 作为母文章 DOI 候选')

    return SupplementDetection(
        is_supplement=is_supplement,
        confidence=score,
        reasons=reasons,
        parent_doi=parent_doi,
        parent_title=parent_title,
        relation_source=relation_source,
    )


def _supplement_relation(metadata: dict[str, Any]) -> str:
    relations = metadata.get('relation') or metadata.get('relations') or {}
    if not isinstance(relations, dict):
        return ''
    for key, values in relations.items():
        normalized = str(key).replace('_', '-').casefold()
        if normalized not in {'is-supplement-to', 'issupplementto'}:
            continue
        if not isinstance(values, list):
            values = [values]
        for value in values:
            if isinstance(value, dict):
                ident = value.get('id') or value.get('identifier') or value.get('DOI') or value.get('doi')
            else:
                ident = value
            doi = normalize_doi(str(ident or ''))
            if doi.startswith('10.'):
                return doi
    return ''
