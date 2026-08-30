from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


@dataclass(slots=True)
class Creator:
    family: str = ''
    given: str = ''
    creator_type: str = 'author'

    @classmethod
    def from_any(cls, value: Any, creator_type: str = 'author') -> 'Creator':
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return cls(creator_type=creator_type)
            if ',' in text:
                family, given = (piece.strip() for piece in text.split(',', 1))
                return cls(family=family, given=given, creator_type=creator_type)
            parts = text.split()
            if len(parts) == 1:
                return cls(family=parts[0], creator_type=creator_type)
            return cls(family=parts[-1], given=' '.join(parts[:-1]), creator_type=creator_type)
        if isinstance(value, dict):
            return cls(
                family=str(value.get('family') or value.get('lastName') or value.get('name') or '').strip(),
                given=str(value.get('given') or value.get('firstName') or '').strip(),
                creator_type=str(value.get('creator_type') or value.get('creatorType') or creator_type or 'author'),
            )
        return cls(creator_type=creator_type)

    def display(self, family_first: bool = False) -> str:
        if self.family and self.given:
            return f'{self.family}, {self.given}' if family_first else f'{self.given} {self.family}'
        return self.family or self.given


@dataclass(slots=True)
class Attachment:
    path: str = ''
    role: str = 'other'
    title: str = ''
    content_type: str = 'application/pdf'
    doi: str = ''
    relation: str = ''
    relation_target: str = ''
    artifacts: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_any(cls, value: Any) -> 'Attachment':
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            return cls(path=value)
        if isinstance(value, dict):
            return cls(
                path=str(value.get('path') or value.get('file') or ''),
                role=str(value.get('role') or 'other'),
                title=str(value.get('title') or ''),
                content_type=str(value.get('content_type') or value.get('contentType') or 'application/pdf'),
                doi=normalize_doi(value.get('doi') or ''),
                relation=str(value.get('relation') or ''),
                relation_target=normalize_doi(value.get('relation_target') or value.get('relationTarget') or ''),
                artifacts=dict(value.get('artifacts') or {}),
            )
        return cls()


@dataclass(slots=True)
class LibraryEntry:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    item_type: str = 'journalArticle'
    title: str = ''
    creators: list[Creator] = field(default_factory=list)
    year: int | str | None = None
    date: str = ''
    publication_title: str = ''
    publisher: str = ''
    place: str = ''
    edition: str = ''
    isbn: str = ''
    volume: str = ''
    issue: str = ''
    pages: str = ''
    doi: str = ''
    arxiv_id: str = ''
    abstract: str = ''
    language: str = ''
    keywords: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    reading_status: str = 'unread'
    url: str = ''
    folder: str = ''
    files: dict[str, Any] = field(default_factory=dict)
    attachments: list[Attachment] = field(default_factory=list)
    ai_note: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec='seconds'))
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec='seconds'))

    def __post_init__(self) -> None:
        self.creators = [Creator.from_any(item) for item in self.creators]
        self.keywords = _clean_list(self.keywords)
        self.tags = _clean_list(self.tags)
        self.doi = normalize_doi(self.doi)
        self.attachments = [Attachment.from_any(item) for item in self.attachments]
        self.arxiv_id = normalize_arxiv(self.arxiv_id)
        if self.year not in (None, ''):
            match = re.search(r'\d{4}', str(self.year))
            self.year = int(match.group()) if match else str(self.year)

    @property
    def authors(self) -> list[Creator]:
        return [c for c in self.creators if c.creator_type in {'author', 'creator'}]

    @property
    def editors(self) -> list[Creator]:
        return [c for c in self.creators if c.creator_type == 'editor']

    @property
    def first_creator(self) -> str:
        creators = self.authors or self.creators
        if not creators:
            return ''
        families = [c.family or c.given for c in creators if c.family or c.given]
        if not families:
            return ''
        chinese = str(self.language).lower().startswith('zh')
        if len(families) == 1:
            return families[0]
        if len(families) == 2:
            return f'{families[0]}和{families[1]}' if chinese else f'{families[0]} and {families[1]}'
        return f'{families[0]}等' if chinese else f'{families[0]} et al.'

    def add_attachment(self, attachment: Attachment | dict[str, Any] | str) -> Attachment:
        item = Attachment.from_any(attachment)
        normalized = Path(item.path).as_posix() if item.path else ''
        for existing in self.attachments:
            if existing.path and Path(existing.path).as_posix() == normalized:
                existing.role = item.role or existing.role
                existing.title = item.title or existing.title
                existing.content_type = item.content_type or existing.content_type
                existing.doi = item.doi or existing.doi
                existing.relation = item.relation or existing.relation
                existing.relation_target = item.relation_target or existing.relation_target
                if item.artifacts:
                    existing.artifacts.update(item.artifacts)
                return existing
        self.attachments.append(item)
        return item

    @property
    def primary_attachment(self) -> Attachment | None:
        return next((item for item in self.attachments if item.role == 'primary'), None)

    @property
    def supplementary_attachments(self) -> list[Attachment]:
        return [item for item in self.attachments if item.role == 'supplement']

    def touch(self) -> None:
        self.updated_at = datetime.now().isoformat(timespec='seconds')

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)

        data['itemType'] = data.pop('item_type')
        data['publicationTitle'] = data.pop('publication_title')
        data['arxivId'] = data.pop('arxiv_id')
        data['readingStatus'] = data.pop('reading_status')
        data['aiNote'] = data.pop('ai_note')
        data['createdAt'] = data.pop('created_at')
        data['updatedAt'] = data.pop('updated_at')
        data['authors'] = [asdict(c) for c in self.authors]
        data.pop('creators', None)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'LibraryEntry':
        payload = dict(data or {})
        creators = payload.pop('creators', None)
        authors = payload.pop('authors', None)
        editors = payload.pop('editors', None)
        combined: list[Creator] = []
        for item in creators or authors or []:
            combined.append(Creator.from_any(item, 'author'))
        for item in editors or []:
            combined.append(Creator.from_any(item, 'editor'))
        aliases = {
            'itemType': 'item_type',
            'publicationTitle': 'publication_title',
            'arxivId': 'arxiv_id',
            'readingStatus': 'reading_status',
            'aiNote': 'ai_note',
            'createdAt': 'created_at',
            'updatedAt': 'updated_at',
        }
        for old, new in aliases.items():
            if old in payload and new not in payload:
                payload[new] = payload.pop(old)
        known = set(cls.__dataclass_fields__)
        extra_unknown = {k: v for k, v in payload.items() if k not in known}
        payload = {k: v for k, v in payload.items() if k in known}
        payload['creators'] = combined
        payload.setdefault('extra', {}).update(extra_unknown)
        return cls(**payload)

    def get_field(self, name: str, default: Any = '') -> Any:
        aliases = {
            'itemType': self.item_type,
            'publicationTitle': self.publication_title,
            'publisher': self.publisher,
            'place': self.place,
            'edition': self.edition,
            'ISBN': self.isbn,
            'isbn': self.isbn,
            'arxivId': self.arxiv_id,
            'DOI': self.doi,
            'doi': self.doi,
            'language': self.language,
            'title': self.title,
            'year': self.year or '',
            'date': self.date,
            'volume': self.volume,
            'issue': self.issue,
            'pages': self.pages,
            'url': self.url,
            'abstract': self.abstract,
        }
        if name in aliases:
            return aliases[name]
        snake = _camel_to_snake(name)
        if hasattr(self, snake):
            return getattr(self, snake)
        return self.extra.get(name, self.extra.get(snake, default))


def normalize_doi(value: str | None) -> str:
    text = str(value or '').strip()
    text = re.sub(r'^https?://(?:dx\.)?doi\.org/', '', text, flags=re.I)
    text = re.sub(r'^doi\s*:\s*', '', text, flags=re.I)
    return text.rstrip('.,;)').lower()


def normalize_arxiv(value: str | None) -> str:
    text = str(value or '').strip()
    text = re.sub(r'^arxiv\s*:\s*', '', text, flags=re.I)
    text = re.sub(r'v\d+$', '', text, flags=re.I)
    return text




def _clean_list(values: Iterable[Any] | None) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values or []:
        text = str(value).strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _camel_to_snake(value: str) -> str:
    return re.sub(r'(?<!^)(?=[A-Z])', '_', value).lower()
