from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

from .entry import LibraryEntry


RULES: dict[str, tuple[str, ...]] = {
    'AI': ('artificial intelligence', 'machine learning', 'deep learning', 'neural network', 'transformer', 'llm', 'large language model', '人工智能', '机器学习', '深度学习'),
    'NLP': ('natural language processing', 'language model', 'nlp', '自然语言处理'),
    'CV': ('computer vision', 'image recognition', 'vision transformer', '计算机视觉', '图像识别'),
    'Robotics': ('robot', 'robotics', '机器人'),
    'Biology': ('biology', 'protein', 'genome', 'cell', '生物', '蛋白', '基因'),
    'Medicine': ('clinical', 'patient', 'medical', 'disease', '医学', '临床', '疾病'),
    'Methods': ('method', 'methodology', 'algorithm', 'framework', '方法', '算法', '框架'),
    'Review': ('review', 'survey', 'meta-analysis', '综述', '元分析'),
}


def suggest_rule_tags(entry: LibraryEntry, limit: int = 8) -> list[str]:
    text = f'{entry.title}\n{entry.abstract}\n{" ".join(entry.keywords)}'.casefold()
    hits = []
    for tag, needles in RULES.items():
        score = sum(text.count(needle.casefold()) for needle in needles)
        if score:
            hits.append((score, tag))
    return [tag for _, tag in sorted(hits, key=lambda pair: (-pair[0], pair[1]))[:limit]]


def parse_keywords_from_note(markdown: str, limit: int = 8) -> list[str]:
    lines = str(markdown or '').splitlines()
    for i, line in enumerate(lines):
        if re.match(r'^#{1,6}\s*(关键词|keywords)\b', line.strip(), flags=re.I):
            tail = re.sub(r'^#{1,6}\s*(关键词|keywords)\s*[:：-]?\s*', '', line.strip(), flags=re.I)
            if not tail and i + 1 < len(lines):
                tail = lines[i + 1].strip()
            values = re.split(r'[,，;；、|/]+', tail)
            return _dedupe(values)[:limit]
    
    match = re.search(r'(?:关键词|keywords)\s*[:：]\s*([^\n]+)', str(markdown or ''), flags=re.I)
    return _dedupe(re.split(r'[,，;；、|/]+', match.group(1)))[:limit] if match else []


def merge_tags(entry: LibraryEntry, tags: Iterable[str]) -> LibraryEntry:
    entry.tags = _dedupe([*entry.tags, *tags])
    entry.touch()
    return entry


def set_reading_status(entry: LibraryEntry, status: str) -> LibraryEntry:
    aliases = {'未读': 'unread', '已读': 'read', '精读': 'deep-read'}
    normalized = aliases.get(status, status)
    if normalized not in {'unread', 'read', 'deep-read'}:
        raise ValueError('阅读状态必须是 unread/read/deep-read（未读/已读/精读）')
    entry.reading_status = normalized
    entry.touch()
    return entry


def _dedupe(values: Iterable[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        text = str(value).strip().strip('#*- ')
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result
