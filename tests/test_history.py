from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from src.library.history import HistoryStore


def _build(root: Path) -> Path:
    (root / 'note-a.pdf').write_bytes(b'PDF-A')
    (root / 'note-a').mkdir()
    (root / 'note-a' / 'citation.bib').write_text('@a{}')
    return root


def _enable():
    os.environ['REALTIME_BACKUP'] = '1'


def test_archive_move_undone():
    _enable()
    with tempfile.TemporaryDirectory() as d:
        root = _build(Path(d))
        hs = HistoryStore(root)
        hs.before_mutation([])  # baseline
        (root / 'note-a' / 'note-a.pdf').write_bytes(b'PDF-A')  # simulate archive move
        (root / 'note-a.pdf').unlink()
        hs.undo(None)
        assert (root / 'note-a.pdf').read_bytes() == b'PDF-A'
        assert not (root / 'note-a' / 'note-a.pdf').exists()
        assert (root / 'note-a' / 'citation.bib').exists()
        assert hs.can_undo() is False


def test_two_step_undo_each_own_op():
    _enable()
    with tempfile.TemporaryDirectory() as d:
        root = _build(Path(d))
        hs = HistoryStore(root)
        hs.before_mutation([])  # op1 baseline
        (root / 'note-a' / 'note-a.pdf').write_bytes(b'PDF-A')
        (root / 'note-a.pdf').unlink()
        hs.before_mutation([root / 'note-a'])  # op2 surgical
        (root / 'note-a' / 'note.md').write_text('note')
        hs.undo(None)  # revert op2
        assert not (root / 'note-a' / 'note.md').exists()
        assert (root / 'note-a' / 'note-a.pdf').exists()
        hs.undo(None)  # revert op1
        assert (root / 'note-a.pdf').read_bytes() == b'PDF-A'
        assert not (root / 'note-a' / 'note-a.pdf').exists()
        assert hs.can_undo() is False


def test_deleted_folder_recreated():
    _enable()
    with tempfile.TemporaryDirectory() as d:
        root = _build(Path(d))
        hs = HistoryStore(root)
        hs.before_mutation([])
        shutil.rmtree(root / 'note-a')
        hs.undo(None)
        assert (root / 'note-a' / 'citation.bib').read_text() == '@a{}'
        assert (root / 'note-a.pdf').exists()


def test_created_target_removed_on_undo():
    _enable()
    with tempfile.TemporaryDirectory() as d:
        root = _build(Path(d))
        hs = HistoryStore(root)
        hs.before_mutation([])
        hs.before_mutation([root / 'brand-new'])  # didn't exist at capture
        (root / 'brand-new').mkdir()
        (root / 'brand-new' / 'x.txt').write_text('x')
        hs.undo(None)
        assert not (root / 'brand-new').exists()


def test_disabled_noop():
    os.environ['REALTIME_BACKUP'] = '0'
    with tempfile.TemporaryDirectory() as d:
        root = _build(Path(d))
        hs = HistoryStore(root)
        assert hs.before_mutation([root / 'note-a.pdf']) is None
        assert hs.can_undo() is False


def test_persistence_across_reinstantiation():
    _enable()
    with tempfile.TemporaryDirectory() as d:
        root = _build(Path(d))
        HistoryStore(root).before_mutation([])
        hs2 = HistoryStore(root)
        assert hs2.can_undo() is True
        assert hs2._entries[-1]['baseline'] is True


def test_monotonic_seq():
    _enable()
    with tempfile.TemporaryDirectory() as d:
        root = _build(Path(d))
        seqs = []
        for _ in range(5):
            hs = HistoryStore(root)
            hs.before_mutation([root / 'note-a.pdf'])
            seqs.append(hs._entries[-1]['seq'])
        assert seqs == [1, 2, 3, 4, 5]


def _entry(title='测试', year=2020):
    from src.library.entry import LibraryEntry, Creator
    return LibraryEntry(title=title, year=year, creators=[Creator.from_any('张三')])


def test_archive_pdf_undone():
    _enable()
    from src.library.archive import archive_pdf
    from src.library.history import HistoryStore
    from src.core.project_paths import ProjectPaths
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / 'draft.pdf').write_bytes(b'PDF')
        ProjectPaths.for_root(root).ensure()
        res = archive_pdf(root, root / 'draft.pdf', _entry())
        assert (root / 'draft.pdf').exists() is False
        folder = res.folder
        hs = HistoryStore(root)
        assert hs.can_undo() is True
        hs.undo(None)
        assert (root / 'draft.pdf').read_bytes() == b'PDF'
        assert not folder.exists()
        assert hs.can_undo() is False


def test_grouped_batch_undone_in_one_step():
    _enable()
    with tempfile.TemporaryDirectory() as d:
        root = _build(Path(d))
        hs = HistoryStore(root)
        hs.before_mutation([])  # baseline
        hs.begin_group()
        hs.before_mutation([root / 'note-a'])
        (root / 'note-a' / 'g.md').write_text('g')
        hs.before_mutation([root / 'note-b'])  # 目标本不存在 → 验证孤儿清理
        (root / 'note-b').mkdir()
        (root / 'note-b' / 'b.pdf').write_bytes(b'B')
        hs.end_group()
        assert (root / 'note-a' / 'g.md').read_text() == 'g'
        assert (root / 'note-b' / 'b.pdf').read_bytes() == b'B'
        desc = hs.undo(None)  # 一次撤回 = 整批
        assert desc and '批量' in desc
        assert not (root / 'note-a' / 'g.md').exists()
        assert not (root / 'note-b').exists()
        assert (root / 'note-a' / 'citation.bib').exists()
        assert hs.can_undo() is True  # 基线仍在，还可再撤一步


def test_group_shared_across_instances():
    # 模拟批量 worker：各自 new 一个 HistoryStore，共用模块级组栈。
    _enable()
    with tempfile.TemporaryDirectory() as d:
        root = _build(Path(d))
        HistoryStore(root).before_mutation([])  # baseline
        HistoryStore(root).begin_group()
        try:
            HistoryStore(root).before_mutation([root / 'note-a'])
            (root / 'note-a' / 'x.md').write_text('x')
            HistoryStore(root).before_mutation([root / 'note-a'])
            (root / 'note-a' / 'y.md').write_text('y')
        finally:
            HistoryStore(root).end_group()
        hs = HistoryStore(root)
        assert hs.can_undo() is True
        hs.undo(None)  # 一步还原两条跨实例记录
        assert not (root / 'note-a' / 'x.md').exists()
        assert not (root / 'note-a' / 'y.md').exists()
        assert (root / 'note-a' / 'citation.bib').exists()
        assert hs.can_undo() is True


def test_rename_archived_entry_when_target_differs_does_not_crash():
    # 回归：rename_archived_entry 里 `*target_folder`（Path 不能 * 解包）曾抛
    # TypeError，导致「编辑→保存→按规范名重命名文件夹」在目标名≠当前名时失败。
    _enable()
    from src.library.archive import archive_pdf, rename_archived_entry
    from src.library.history import HistoryStore
    from src.core.project_paths import ProjectPaths
    from src.library.index import LibraryIndex
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / 'draft.pdf').write_bytes(b'PDF')
        ProjectPaths.for_root(root).ensure()
        res = archive_pdf(root, root / 'draft.pdf', _entry(title='旧标题', year=2020))
        idx = LibraryIndex(root)
        HistoryStore(root).before_mutation([])
        entry = idx.get(res.entry.id)
        entry.title = '一个完全不同的新标题'  # 强制目标文件夹名 ≠ 当前名
        new_res = rename_archived_entry(root, entry, index=idx)
        assert new_res.folder.name.startswith('张三')
        assert '新标题' in new_res.folder.name
        assert new_res.folder.exists()
        assert entry.files['pdf'] and (new_res.folder / entry.files['pdf']).exists()
        found = idx.entry_for_path(new_res.folder / entry.files['pdf'])
        assert found is not None and found.id == entry.id


def test_rename_archived_entry_undone():
    _enable()
    from src.library.archive import archive_pdf, rename_archived_entry
    from src.library.history import HistoryStore
    from src.core.project_paths import ProjectPaths
    from src.library.index import LibraryIndex
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / 'draft.pdf').write_bytes(b'PDF')
        ProjectPaths.for_root(root).ensure()
        res = archive_pdf(root, root / 'draft.pdf', _entry())
        idx = LibraryIndex(root)
        rename_archived_entry(root, idx.get(res.entry.id))
        hs = HistoryStore(root)
        hs.undo(None)  # revert rename -> back to archived state
        assert res.folder.exists()
        assert hs.can_undo() is True
        hs.undo(None)  # revert archive -> back to loose pdf
        assert (root / 'draft.pdf').read_bytes() == b'PDF'
        assert not res.folder.exists()
        assert hs.can_undo() is False
