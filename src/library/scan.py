from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .index import LibraryIndex


@dataclass(slots=True)
class ScanResult:
    raw: list[Path] = field(default_factory=list)
    organized: list[Path] = field(default_factory=list)
    failed: list[Path] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


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


