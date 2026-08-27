from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from src.core.project_paths import ProjectPaths

from .archive import ArchiveResult, archive_pdf
from .entry import LibraryEntry
from .fetch import FetchResult, MetadataFetcher
from .index import LibraryIndex


@dataclass(slots=True)
class ScanResult:
    raw: list[Path] = field(default_factory=list)
    organized: list[Path] = field(default_factory=list)
    failed: list[Path] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


@dataclass(slots=True)
class OrganizeResult:
    source: Path
    fetch: FetchResult | None = None
    archive: ArchiveResult | None = None
    duplicate_entry: LibraryEntry | None = None
    error: str = ''

    @property
    def ok(self) -> bool:
        return self.archive is not None and not self.error


def scan_project(root: str | Path, index: LibraryIndex | None = None) -> ScanResult:
    root_path = Path(root).expanduser().resolve()
    library_index = index or LibraryIndex(root_path)
    result = ScanResult()
    mapped = library_index.data.get('mappings', {})

    for path in root_path.rglob('*.pdf'):
        relative_parts = path.relative_to(root_path).parts
        if '.workknacks' in relative_parts or any(part in {'parsed', 'notes', 'translations'} for part in relative_parts):
            continue
        rel = path.relative_to(root_path).as_posix()
        mapping = mapped.get(rel) or library_index.mapping_for(path)
        if mapping and mapping.get('status') == 'organized':
            result.organized.append(path)
        elif mapping and mapping.get('status') in {'failed', 'missing'}:
            result.failed.append(path)
        elif path.parent == root_path:
            result.raw.append(path)
        else:
            
            
            result.raw.append(path)

    for rel, mapping in mapped.items():
        if mapping.get('status') == 'organized' and not (root_path / rel).exists():
            result.missing.append(rel)
    result.raw.sort(key=lambda p: p.name.casefold())
    result.organized.sort(key=lambda p: p.name.casefold())
    result.failed.sort(key=lambda p: p.name.casefold())
    return result


def organize_pdf(
    root: str | Path,
    pdf_path: str | Path,
    *,
    entry: LibraryEntry | None = None,
    fetcher: MetadataFetcher | None = None,
    index: LibraryIndex | None = None,
    allow_local_parse: bool = False,
    allow_duplicate: bool = False,
) -> OrganizeResult:
    source = Path(pdf_path).expanduser().resolve()
    library_index = index or LibraryIndex(root)
    result = OrganizeResult(source=source)
    try:
        if entry is None:
            metadata_fetcher = fetcher or MetadataFetcher(
                cache_dir=ProjectPaths.for_root(library_index.root).metadata_cache
            )
            result.fetch = metadata_fetcher.fetch(source, allow_local_parse=allow_local_parse)
            entry = result.fetch.entry
        if entry is None or not entry.title.strip():
            library_index.mark_failed(source.relative_to(library_index.root).as_posix(), '未检索到有效元数据')
            result.error = '未检索到有效元数据，请手工录入后重试。'
            return result
        duplicate, reason, _score = library_index.find_duplicate(entry)
        if duplicate and duplicate.id != entry.id and not allow_duplicate:
            result.duplicate_entry = duplicate
            result.error = f'检测到重复条目（{reason}）: {duplicate.title}'
            return result
        result.archive = archive_pdf(library_index.root, source, entry, index=library_index)
        return result
    except Exception as exc:
        result.error = str(exc)
        try:
            rel = source.relative_to(library_index.root).as_posix()
            library_index.mark_failed(rel, result.error)
        except Exception:
            pass
        return result


def batch_organize(root: str | Path, paths: Iterable[str | Path] | None = None, **kwargs) -> list[OrganizeResult]:
    library_index = kwargs.pop('index', None) or LibraryIndex(root)
    targets = list(paths) if paths is not None else scan_project(root, library_index).raw
    fetcher = kwargs.pop('fetcher', None) or MetadataFetcher(
        cache_dir=ProjectPaths.for_root(library_index.root).metadata_cache
    )
    return [organize_pdf(root, path, index=library_index, fetcher=fetcher, **kwargs) for path in targets]
