from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from .artifacts import ArtifactLayout, artifact_relpath
from .biblio import write_citation_bundle
from .entry import Attachment, LibraryEntry, normalize_doi
from .history import HistoryStore
from .index import LibraryIndex
from .parts import parse_part
from .rename import build_name


def _snap(root, affected, index=None) -> None:
    """改动性操作前快照受影响路径；REALTIME_BACKUP=0 时退化为 no-op。"""
    HistoryStore(root).before_mutation(affected, index)


@dataclass(slots=True)
class ArchiveResult:
    entry: LibraryEntry
    folder: Path
    pdf: Path
    original: Path
    conflict_index: int = 0
    document_role: str = 'primary'


def archive_pdf(
    root: str | os.PathLike[str],
    src: str | os.PathLike[str],
    entry: LibraryEntry,
    *,
    index: LibraryIndex | None = None,
    template: str | None = None,
) -> ArchiveResult:

    root_path, source = _validate_pdf(root, src)
    library_index = index or LibraryIndex(root_path)
    duplicate, reason, _score = library_index.find_duplicate(entry)
    existing = duplicate if duplicate and duplicate.id != entry.id and (reason == 'doi' or not entry.doi or not duplicate.doi) else None

    if existing and _has_primary_pdf(root_path, existing):
        raise ValueError(f'该母文章已经有主 PDF：{existing.title}')

    original_name = source.name
    old_stem = source.stem
    sidecars = _existing_sidecars(source.parent, old_stem)
    if existing:
        entry = _merge_entry(existing, entry)
        folder = root_path / entry.folder
        _snap(root_path, [source, *[p for _, p in sidecars], folder], library_index)
        folder.mkdir(parents=True, exist_ok=True)
        base = folder.name
        pdf = folder / f'{base}.pdf'
        if pdf.exists() and pdf.resolve() != source.resolve():
            raise FileExistsError(str(pdf))
        conflict_index = 0
    else:
        base = build_name(entry, template or library_index.rename_template)
        folder, pdf, conflict_index = _resolve_target(root_path, base, source)
        _snap(root_path, [source, *[p for _, p in sidecars], folder], library_index)
        folder.mkdir(parents=True, exist_ok=True)

    if source.resolve() != pdf.resolve():
        shutil.move(str(source), str(pdf))
    artifact_map = _move_sidecars(sidecars, folder, old_stem, pdf.stem)

    entry.folder = folder.relative_to(root_path).as_posix()
    entry.files['pdf'] = pdf.name
    primary_attachment = entry.add_attachment(Attachment(path=pdf.name, role='primary', title='Main article'))
    _apply_attachment_artifacts(entry, primary_attachment, artifact_map, primary=True)
    library_index.upsert(entry, save=False)
    _drop_stale_mappings(library_index, entry.id, original_name, source, root_path)
    library_index.record_mapping(
        pdf.relative_to(root_path).as_posix(),
        entry=entry,
        original_name=original_name,
        folder=entry.folder,
        status='organized',
        save=False,
    )
    library_index.save()
    write_citation_bundle(folder, entry)
    return ArchiveResult(entry=entry, folder=folder, pdf=pdf, original=source, conflict_index=conflict_index, document_role='primary')


def archive_supplement(
    root: str | os.PathLike[str],
    src: str | os.PathLike[str],
    parent_entry: LibraryEntry,
    *,
    index: LibraryIndex | None = None,
    template: str | None = None,
    parent_doi: str = '',
    supplement_doi: str = '',
) -> ArchiveResult:

    root_path, source = _validate_pdf(root, src)
    library_index = index or LibraryIndex(root_path)
    old_stem = source.stem
    sidecars = _existing_sidecars(source.parent, old_stem)
    duplicate, reason, _score = library_index.find_duplicate(parent_entry)
    if duplicate and reason == 'title' and parent_entry.doi and duplicate.doi and parent_entry.doi != duplicate.doi:
        duplicate = None
    if duplicate:
        entry = _merge_entry(duplicate, parent_entry)
        folder = root_path / entry.folder if entry.folder else root_path / build_name(entry, template or library_index.rename_template)
    else:
        entry = parent_entry
        folder = root_path / build_name(entry, template or library_index.rename_template)
    _snap(root_path, [source, *[p for _, p in sidecars], folder], library_index)
    folder.mkdir(parents=True, exist_ok=True)
    entry.folder = folder.relative_to(root_path).as_posix()

    target = _supplement_target(folder, folder.name, source)
    original_name = source.name
    if source.resolve() != target.resolve():
        shutil.move(str(source), str(target))
    artifact_map = _move_sidecars(sidecars, folder, old_stem, target.stem)

    normalized_parent_doi = normalize_doi(parent_doi or entry.doi or '')
    normalized_supplement_doi = normalize_doi(supplement_doi or '')
    if normalized_supplement_doi and normalized_supplement_doi == normalized_parent_doi:


        normalized_supplement_doi = ''
    supplement_attachment = entry.add_attachment(Attachment(
        path=target.name,
        role='supplement',
        title='Supporting Information',
        doi=normalized_supplement_doi,
        relation='isSupplementTo',
        relation_target=normalized_parent_doi,
        artifacts=artifact_map,
    ))
    supplement_attachment.artifacts.update(artifact_map)
    entry.files['supplements'] = [a.path for a in entry.supplementary_attachments if a.path]
    library_index.upsert(entry, save=False)
    _drop_stale_mappings(library_index, entry.id, original_name, source, root_path, keep_entry_mappings=True)
    library_index.record_mapping(
        target.relative_to(root_path).as_posix(),
        entry=entry,
        original_name=original_name,
        folder=entry.folder,
        status='supplement',
        save=False,
    )
    library_index.save()
    write_citation_bundle(folder, entry)
    return ArchiveResult(entry=entry, folder=folder, pdf=target, original=source, conflict_index=0, document_role='supplement')


def archive_part_merge(
    root: str | os.PathLike[str],
    src: str | os.PathLike[str],
    parent_entry: LibraryEntry,
    *,
    index: LibraryIndex | None = None,
    template: str | None = None,
    part=None,
) -> ArchiveResult:

    root_path, source = _validate_pdf(root, src)
    library_index = index or LibraryIndex(root_path)
    if not part or not part.base:
        raise ValueError('无法识别分卷标记')
    new_marker = str(part.marker or '')
    for att in parent_entry.attachments:
        if att.path:
            existing = parse_part(Path(att.path).stem)
            if existing and existing.marker == new_marker:
                raise ValueError(f'该分卷标记 {new_marker} 已存在于条目中，跳过并入')

    entry = parent_entry
    entry.title = part.base
    new_base = build_name(entry, template or library_index.rename_template)
    old_folder = (root_path / entry.folder) if entry.folder else None
    current_pdf = None
    if old_folder and entry.files.get('pdf'):
        current_pdf = old_folder / str(entry.files['pdf'])
    if old_folder and old_folder.name == new_base:
        target_folder = old_folder
    else:
        target_folder, _, _ = _resolve_target(
            root_path, new_base, current_pdf or source, allow_current=old_folder
        )
    sidecars = _existing_sidecars(source.parent, source.stem)
    affected = [source, *[p for _, p in sidecars]]
    if old_folder:
        affected.append(old_folder)
    if target_folder != old_folder:
        affected.append(target_folder)
    _snap(root_path, affected, library_index)
    if old_folder and old_folder.exists() and old_folder.resolve() != target_folder.resolve():
        target_folder.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(old_folder), str(target_folder))
        source = target_folder / source.name
    elif not target_folder.exists():
        target_folder.mkdir(parents=True, exist_ok=True)
    entry.folder = target_folder.relative_to(root_path).as_posix()


    renames: dict[str, str] = {}
    old_pdf_name = str(entry.files.get('pdf') or '')
    if old_pdf_name:
        old_pdf = target_folder / old_pdf_name
        new_pdf_name = _part_target_name(new_base, old_pdf)
        if new_pdf_name != old_pdf_name and old_pdf.exists():
            old_pdf.rename(target_folder / new_pdf_name)
        renames[old_pdf_name] = new_pdf_name
        entry.files['pdf'] = new_pdf_name
        primary = entry.primary_attachment
        if primary and primary.path == old_pdf_name:
            primary.path = new_pdf_name
    for att in entry.attachments:
        if att.role != 'part' or not att.path:
            continue
        old_path = target_folder / att.path
        new_name = _part_target_name(new_base, old_path)
        if new_name != att.path and old_path.exists():
            old_path.rename(target_folder / new_name)
        renames[att.path] = new_name
        att.path = new_name

    target = target_folder / (new_base + new_marker + source.suffix)
    if target.exists() and target.resolve() != source.resolve():
        target = _unique_file_target(target)
    original_name = source.name
    sidecars = _existing_sidecars(source.parent, source.stem)
    if source.resolve() != target.resolve():
        shutil.move(str(source), str(target))
    artifact_map = _move_sidecars(sidecars, target_folder, source.stem, target.stem)

    entry.add_attachment(Attachment(
        path=target.name,
        role='part',
        title=str(part.marker or ''),
        relation='isPartOf',
        artifacts=artifact_map,
    ))
    entry.files['parts'] = [a.path for a in entry.attachments if a.role == 'part' and a.path]
    library_index.upsert(entry, save=False)
    _rebuild_entry_mappings(library_index, entry, root_path)
    library_index.save()
    write_citation_bundle(target_folder, entry)
    return ArchiveResult(entry=entry, folder=target_folder, pdf=target, original=source, conflict_index=0, document_role='part')


def _part_target_name(new_base: str, path: Path) -> str:
    marker = ''
    parsed = parse_part(path.stem)
    if parsed:
        marker = parsed.marker
    return new_base + marker + (path.suffix or '.pdf')


def rename_archived_entry(
    root: str | os.PathLike[str],
    entry: LibraryEntry,
    index: LibraryIndex | None = None,
    template: str | None = None,
) -> ArchiveResult:
    root_path = Path(root).expanduser().resolve()
    library_index = index or LibraryIndex(root_path)
    current_pdf = root_path / entry.folder / str(entry.files.get('pdf') or '')
    if not current_pdf.exists():

        if entry.folder and entry.supplementary_attachments:
            return _rename_supplement_only_parent(root_path, entry, library_index, template)
        raise FileNotFoundError(str(current_pdf))
    old_folder = current_pdf.parent
    old_name = current_pdf.name
    old_stem = current_pdf.stem
    base = build_name(entry, template or library_index.rename_template)
    target_folder, target_pdf, conflict_index = _resolve_target(root_path, base, current_pdf, allow_current=old_folder)
    if any(att.role == 'part' for att in entry.attachments):
        primary_marker = ''
        parsed = parse_part(old_stem)
        if parsed:
            primary_marker = parsed.marker
        if primary_marker:
            target_pdf = target_folder / (target_folder.name + primary_marker + (Path(old_name).suffix or '.pdf'))

    _snap(
        root_path,
        [old_folder, *[p for _, p in _existing_sidecars(old_folder, old_stem)], *([target_folder] if target_folder != old_folder else [])],
        library_index,
    )
    if target_folder != old_folder:
        target_folder.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(old_folder), str(target_folder))
        moved_current = target_folder / old_name
    else:
        moved_current = current_pdf
    if moved_current != target_pdf:
        moved_current.rename(target_pdf)

    sidecars = _existing_sidecars(target_folder, old_stem)
    artifact_map = _move_sidecars(sidecars, target_folder, old_stem, target_pdf.stem)
    _rename_supplement_attachments(target_folder, old_folder.name, target_folder.name, entry)

    entry.folder = target_folder.relative_to(root_path).as_posix()
    entry.files['pdf'] = target_pdf.name
    primary_attachment = _replace_attachment_path(entry, old_name, target_pdf.name, role='primary')
    _apply_attachment_artifacts(entry, primary_attachment, artifact_map, primary=True)
    _rebuild_entry_mappings(library_index, entry, root_path)
    library_index.save()
    write_citation_bundle(target_folder, entry)
    return ArchiveResult(entry, target_folder, target_pdf, current_pdf, conflict_index, 'primary')


def _rename_supplement_only_parent(root: Path, entry: LibraryEntry, index: LibraryIndex, template: str | None) -> ArchiveResult:
    old_folder = root / entry.folder
    if not old_folder.exists():
        raise FileNotFoundError(str(old_folder))
    base = build_name(entry, template or index.rename_template)
    target_folder = root / base
    if target_folder.exists() and target_folder.resolve() != old_folder.resolve():
        target_folder, _, _ = _resolve_target(root, base, old_folder / '__none__.pdf', allow_current=old_folder)
    if target_folder.resolve() != old_folder.resolve():
        shutil.move(str(old_folder), str(target_folder))
    _rename_supplement_attachments(target_folder, old_folder.name, target_folder.name, entry)
    entry.folder = target_folder.relative_to(root).as_posix()
    _rebuild_entry_mappings(index, entry, root)
    index.save()
    write_citation_bundle(target_folder, entry)
    supplement = entry.supplementary_attachments[0]
    return ArchiveResult(entry, target_folder, target_folder / supplement.path, old_folder, 0, 'supplement')


def _rename_supplement_attachments(folder: Path, old_base: str, new_base: str, entry: LibraryEntry) -> None:
    supplements = entry.supplementary_attachments
    for idx, attachment in enumerate(supplements, start=1):
        old = folder / attachment.path
        if not old.exists():
            continue
        old_stem = old.stem
        sidecars = _existing_sidecars(folder, old_stem)
        suffix = ' - Supporting Information' if idx == 1 else f' - Supplement {idx}'
        target = folder / f'{new_base}{suffix}{old.suffix or ".pdf"}'
        if target.exists() and target.resolve() != old.resolve():
            target = _unique_file_target(target)
        if target.resolve() != old.resolve():
            old.rename(target)
        attachment.path = target.name
        artifact_map = _move_sidecars(sidecars, folder, old_stem, target.stem)
        if artifact_map:
            attachment.artifacts.update(artifact_map)
    entry.files['supplements'] = [a.path for a in supplements if a.path]
    for attachment in entry.attachments:
        if attachment.role != 'part' or not attachment.path:
            continue
        old = folder / attachment.path
        if not old.exists():
            continue
        old_stem = old.stem
        sidecars = _existing_sidecars(folder, old_stem)
        target = folder / _part_target_name(new_base, old)
        if target.resolve() != old.resolve():
            if target.exists():
                target = _unique_file_target(target)
            old.rename(target)
        attachment.path = target.name
        artifact_map = _move_sidecars(sidecars, folder, old_stem, target.stem)
        if artifact_map:
            attachment.artifacts.update(artifact_map)
    entry.files['parts'] = [a.path for a in entry.attachments if a.role == 'part' and a.path]


def _rebuild_entry_mappings(index: LibraryIndex, entry: LibraryEntry, root: Path) -> None:
    mappings = index.data.setdefault('mappings', {})
    old = {k: v for k, v in mappings.items() if v.get('entryId') == entry.id}
    for key in list(old):
        mappings.pop(key, None)
    index.upsert(entry, save=False)
    if entry.files.get('pdf'):
        rel = (Path(entry.folder) / str(entry.files['pdf'])).as_posix()
        index.record_mapping(rel, entry=entry, original_name=Path(str(entry.files['pdf'])).name, folder=entry.folder, status='organized', save=False)
    for attachment in entry.attachments:
        if attachment.role not in ('supplement', 'part') or not attachment.path:
            continue
        rel = (Path(entry.folder) / attachment.path).as_posix()
        index.record_mapping(rel, entry=entry, original_name=Path(attachment.path).name, folder=entry.folder, status='supplement', save=False)


def _merge_entry(existing: LibraryEntry, incoming: LibraryEntry) -> LibraryEntry:


    for field in (
        'item_type', 'title', 'year', 'date', 'publication_title', 'publisher', 'place', 'edition', 'isbn', 'volume', 'issue',
        'pages', 'doi', 'arxiv_id', 'abstract', 'language', 'url',
    ):
        value = getattr(incoming, field)
        if value not in (None, '', [], {}):
            setattr(existing, field, value)
    if incoming.creators:
        existing.creators = incoming.creators
    if incoming.keywords:
        existing.keywords = incoming.keywords
    existing.extra.update(incoming.extra)
    return existing


def _has_primary_pdf(root: Path, entry: LibraryEntry) -> bool:
    value = str(entry.files.get('pdf') or '')
    return bool(value and (root / entry.folder / value).exists())


def _drop_stale_mappings(
    index: LibraryIndex,
    entry_id: str,
    original_name: str,
    source: Path,
    root: Path,
    *,
    keep_entry_mappings: bool = False,
) -> None:
    mappings = index.data.setdefault('mappings', {})
    try:
        old_rel = source.relative_to(root).as_posix()
    except ValueError:
        old_rel = ''
    if old_rel:
        mappings.pop(old_rel, None)
    for key in list(mappings):
        value = mappings[key]
        if (not keep_entry_mappings and value.get('entryId') == entry_id) or (value.get('status') == 'failed' and Path(key).name == original_name):
            mappings.pop(key, None)


def _validate_pdf(root: str | os.PathLike[str], src: str | os.PathLike[str]) -> tuple[Path, Path]:
    root_path = Path(root).expanduser().resolve()
    source = Path(src).expanduser().resolve()
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(str(source))
    if source.suffix.lower() != '.pdf':
        raise ValueError('归档仅接受 PDF 文件')
    try:
        source.relative_to(root_path)
    except ValueError as exc:
        raise ValueError('源文件必须位于项目根目录内') from exc
    return root_path, source


def _supplement_target(folder: Path, parent_base: str, source: Path) -> Path:
    existing = [p for p in folder.glob('*.pdf') if p.exists()]
    supplement_count = sum(1 for p in existing if 'supporting information' in p.stem.casefold() or 'supplement' in p.stem.casefold())
    label = 'Supporting Information' if supplement_count == 0 else f'Supplement {supplement_count + 1}'
    target = folder / f'{parent_base} - {label}.pdf'
    if target.exists() and target.resolve() != source.resolve():
        target = _unique_file_target(target)
    return target


def _replace_attachment_path(entry: LibraryEntry, old: str, new: str, role: str = '') -> Attachment:
    for attachment in entry.attachments:
        if attachment.path == old or (role and attachment.role == role):
            attachment.path = new
            if role:
                attachment.role = role
            return attachment
    return entry.add_attachment(Attachment(path=new, role=role or 'other'))


def _existing_sidecars(parent: Path, stem: str) -> list[tuple[str, Path]]:

    pseudo = parent / f'{stem}.pdf'
    layout = ArtifactLayout.for_source(pseudo)
    candidates: list[tuple[str, Path]] = [
        ('parseDir', layout.parse_dir),
        ('note', layout.note_path('summary')),
    ]
    if layout.translations_root.exists():
        candidates.extend(('translation', path) for path in layout.translations_root.glob(f'{stem}.*') if path.is_file())
    return [(kind, path) for kind, path in candidates if path.exists()]


def _move_sidecars(
    sidecars: list[tuple[str, Path]],
    target_folder: Path,
    old_stem: str,
    new_stem: str,
) -> dict[str, object]:

    target_layout = ArtifactLayout.for_source(target_folder / f'{new_stem}.pdf')
    artifact_map: dict[str, object] = {}
    translation_paths: list[str] = []
    for kind, path in sidecars:
        if kind == 'parseDir':
            target = target_layout.parse_dir
        elif kind == 'note':
            target = target_layout.note_path('summary')
        elif kind == 'translation':
            tail = path.name[len(old_stem):] if path.name.startswith(old_stem) else path.suffix
            target = target_layout.translations_root / f'{new_stem}{tail}'
        else:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.resolve() != target.resolve():
            if target.exists():
                target = _unique_sidecar_target(target)
            shutil.move(str(path), str(target))
        rel = artifact_relpath(target_folder, target)
        if kind == 'translation':
            translation_paths.append(rel)
        else:
            artifact_map[kind] = rel
    if translation_paths:
        artifact_map['translations'] = translation_paths
    return artifact_map


def _apply_attachment_artifacts(
    entry: LibraryEntry,
    attachment: Attachment,
    artifacts: dict[str, object],
    *,
    primary: bool = False,
) -> None:
    if not artifacts:
        return
    attachment.artifacts.update(artifacts)
    if not primary:
        return
    for key in ('parseDir', 'note', 'translations'):
        if key in artifacts:
            entry.files[key] = artifacts[key]
    entry.files.pop('translation', None)
    note_path = artifacts.get('note')
    if note_path and isinstance(entry.ai_note, dict):
        entry.ai_note['path'] = str(note_path)


def _unique_sidecar_target(target: Path) -> Path:
    if target.is_dir() or not target.suffix:
        base_name = target.name
        for idx in range(2, 10_000):
            candidate = target.with_name(f'{base_name} ({idx})')
            if not candidate.exists():
                return candidate
    return _unique_file_target(target)


def _unique_file_target(target: Path) -> Path:
    stem, suffix = target.stem, target.suffix
    for idx in range(2, 10_000):
        candidate = target.with_name(f'{stem} ({idx}){suffix}')
        if not candidate.exists():
            return candidate
    raise RuntimeError(f'无法分配不冲突的名称：{target.name}')


def _resolve_target(root: Path, base: str, source: Path, allow_current: Path | None = None) -> tuple[Path, Path, int]:
    for idx in range(0, 10_000):
        suffix = '' if idx == 0 else f' ({idx + 1})'
        name = base + suffix
        folder = root / name
        pdf = folder / f'{name}.pdf'
        if allow_current is not None and folder.resolve() == allow_current.resolve():
            return folder, pdf, idx
        if not folder.exists():
            return folder, pdf, idx
        try:
            if source.resolve().parent == folder.resolve():
                return folder, pdf, idx
        except OSError:
            pass
    raise RuntimeError('无法分配不冲突的归档文件名')
