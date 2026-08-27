from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from .entry import Attachment, LibraryEntry


CITATION_BIB = 'citation.bib'


def export_bibtex(entries: Iterable[LibraryEntry], output_path: str | Path | None = None) -> str:
    chunks = []
    used: set[str] = set()
    for entry in entries:
        key = _cite_key(entry, used)
        used.add(key)
        fields = {
            'title': entry.title,
            'author': ' and '.join(_bib_name(c.family, c.given) for c in entry.authors),
            'year': str(entry.year or ''),
            'journal': entry.publication_title,
            'publisher': entry.publisher,
            'address': entry.place,
            'edition': entry.edition,
            'isbn': entry.isbn,
            'volume': entry.volume,
            'number': entry.issue,
            'pages': entry.pages,
            'doi': entry.doi,
            'url': entry.url,
            
            
            'file': _jabref_file_field(entry.attachments),
        }
        item_type = {
            'journalArticle': 'article',
            'book': 'book',
            'bookSection': 'incollection',
            'conferencePaper': 'inproceedings',
            'preprint': 'misc',
        }.get(entry.item_type, 'misc')
        lines = [f'@{item_type}{{{key},']
        for name, value in fields.items():
            if value:
                rendered = str(value) if name == 'file' else _bib_escape(str(value))
                lines.append(f'  {name} = {{{rendered}}},')
        lines.append('}')
        chunks.append('\n'.join(lines))
    text = '\n\n'.join(chunks) + ('\n' if chunks else '')
    if output_path:
        Path(output_path).write_text(text, encoding='utf-8')
    return text


def write_citation_bundle(folder: str | Path, entry: LibraryEntry) -> dict[str, Path]:
    
    target = Path(folder)
    target.mkdir(parents=True, exist_ok=True)
    bib = target / CITATION_BIB
    export_bibtex([entry], bib)
    return {'bibtex': bib}


def _jabref_file_field(attachments: Iterable[Attachment]) -> str:
    items = []
    seen = set()
    for attachment in attachments:
        raw = Path(str(attachment.path or '')).as_posix()
        if not raw or raw in seen:
            continue
        seen.add(raw)
        label = 'Supplement' if attachment.role == 'supplement' else ('Main article' if attachment.role == 'primary' else attachment.title)
        safe_label = str(label or '').replace(':', '-').replace(';', ',')
        safe_path = raw.replace(';', '%3B')
        ext = Path(raw).suffix.lower().lstrip('.')
        file_type = 'PDF' if ext == 'pdf' else ext.upper()
        items.append(f'{safe_label}:{safe_path}:{file_type}')
    return ';'.join(items)


def _cite_key(entry: LibraryEntry, used: set[str]) -> str:
    family = entry.authors[0].family if entry.authors else 'anon'
    base = re.sub(r'[^A-Za-z0-9]+', '', family) or 'anon'
    title_word = next((w for w in re.findall(r'[A-Za-z0-9]+', entry.title) if len(w) > 2), 'work')
    base = f'{base}{entry.year or "nd"}{title_word}'.lower()
    key = base
    counter = 2
    while key in used:
        key = f'{base}{counter}'
        counter += 1
    return key


def _bib_name(family: str, given: str) -> str:
    return f'{family}, {given}'.strip(', ') if family else given


def _bib_escape(value: str) -> str:
    return value.replace('\\', '\\\\').replace('{', '\\{').replace('}', '\\}')
