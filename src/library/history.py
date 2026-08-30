from __future__ import annotations

import json
import os
import shutil
import threading
from datetime import datetime
from pathlib import Path

from src.core.config import config
from src.core.project_paths import ProjectPaths

# `.workknacks` 下不纳入快照/还原的子目录。
# `state` 排除：index.json 单独拷贝还原，整目录还原会冲掉 agent.json/workspace.json。
# 不放在 backups/sessions 下，避免被 config_dialog「清理缓存」误删。

_GLOBAL_LOCK = threading.Lock()
# 撤回分组：模块级共享，跨 HistoryStore 实例生效（批量 worker 各自 new 一个实例，
# 但都用 _GLOBAL_LOCK + 这份全局组栈，使整批 before_mutation 落在同一个 group_id 上）。
_group_stack: list[int] = []
_group_seq: int = 0


def _rel_parts(rel: str) -> list[str]:
    return rel.split('/')


def _copy_file(snap_dir: Path, src: Path, rel: str) -> dict:
    rec = {'rel': rel, 'existed': False, 'is_dir': False}
    if src.exists():
        dst = snap_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        rec['existed'] = True
    return rec


def _copy_into(snap_dir: Path, src: Path, rel: str, records: list) -> None:
    existed = src.exists() or src.is_symlink()
    is_dir = src.is_dir() and not src.is_symlink()
    rec = {'rel': rel, 'existed': existed, 'is_dir': is_dir}
    if existed:
        dst = snap_dir / 'files' / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if is_dir:
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
    records.append(rec)


def _remove_path(p: Path) -> None:
    if p.is_symlink():
        p.unlink(missing_ok=True)
    elif p.is_dir():
        shutil.rmtree(p, ignore_errors=True)
    else:
        p.unlink(missing_ok=True)


class HistoryStore:
    """绑定项目根的撤回快照仓库，存于 `.workknacks/history/`。

    每次改动性操作前调用 `before_mutation(affected)`：历史为空时做一次全量基线，
    之后只拷贝受影响路径（内容），但始终记录完整相对路径清单用于孤儿清理。
    `undo()` 还原受影响路径内容 + 删除操作新建的孤儿路径 + 还原 index.json。
    """

    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root).expanduser().resolve()
        self.paths = ProjectPaths.for_root(self.root)
        self.dir = self.paths.history
        self.manifest_path = self.dir / 'history.json'
        # 模块级全局锁：批量 worker 各自创建实例，用同一把锁串行化捕获/清单写。
        self._lock = _GLOBAL_LOCK
        self._entries = self._load_manifest()

    @staticmethod
    def enabled() -> bool:
        return config.get_int('REALTIME_BACKUP', 1) == 1

    def _load_manifest(self) -> list:
        if not self.manifest_path.exists():
            return []
        try:
            data = json.loads(self.manifest_path.read_text(encoding='utf-8'))
            entries = data.get('entries', [])
            return entries if isinstance(entries, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _save_manifest(self, entries: list) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.manifest_path.with_suffix('.tmp')
        tmp.write_text(
            json.dumps({'entries': entries}, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
        tmp.replace(self.manifest_path)

    def can_undo(self) -> bool:
        with self._lock:
            return bool(self._entries)

    def describe_top(self) -> str:
        with self._lock:
            if not self._entries:
                return ''
            e = self._entries[-1]
            paths = e.get('paths') or []
            if not paths:
                return f'撤回一步（{e.get("time", "")}）'
            label = '，'.join(str(p.get('rel', p)) for p in paths[:4])
            return label + ('…' if len(paths) > 4 else '')

    def clear(self) -> None:
        with self._lock:
            if self.dir.exists():
                for item in self.dir.iterdir():
                    if item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                    else:
                        item.unlink(missing_ok=True)
            self._entries = []

    def begin_group(self) -> None:
        """开启一个撤回分组：组内所有 before_mutation 合成一个撤回步。线程安全、跨实例生效。"""
        with self._lock:
            global _group_seq
            _group_seq += 1
            _group_stack.append(_group_seq)

    def end_group(self) -> None:
        """结束最近的撤回分组。仅在对应的所有 before_mutation 完成后调用。"""
        with self._lock:
            if _group_stack:
                _group_stack.pop()

    @staticmethod
    def _entry_gid(entry: dict) -> object:
        # 组内条目共享 group_id；组外条目各用自己的 seq；老历史缺字段时回退 seq → 单步不粘连。
        return entry.get('group_id', entry.get('seq'))

    def _iter_project(self):
        """产出 (path, rel)；跳过 `.workknacks` 与任何隐藏路径。"""
        for path in self.root.rglob('*'):
            try:
                rel = path.relative_to(self.root).as_posix()
            except ValueError:
                continue
            if rel.startswith('.workknacks') or any(p.startswith('.') for p in _rel_parts(rel)):
                continue
            yield path, rel

    def _resolve_affected(self, affected) -> list[str]:
        rels: list[str] = []
        for a in affected or []:
            if not a:
                continue
            p = Path(a)
            if not p.is_absolute():
                p = self.root / p
            try:
                rel = p.resolve().relative_to(self.root).as_posix()
            except ValueError:
                continue
            if rel.startswith('.workknacks') or any(x.startswith('.') for x in _rel_parts(rel)):
                continue
            rels.append(rel)
        # 去重：父目录已包含时丢弃子路径（按深度升序，父先入列）。
        rels = sorted(set(rels), key=lambda r: (r.count('/'), r))
        out: list[str] = []
        for rel in rels:
            if any(rel.startswith(other + '/') for other in out):
                continue
            out.append(rel)
        return out

    def before_mutation(self, affected=None, index=None) -> dict | None:
        if not self.enabled():
            return None
        with self._lock:
            self._entries = self._load_manifest()
            is_baseline = not self._entries
            seq = len(self._entries) + 1
            snap_id = f'snap-{seq:04d}'
            snap_dir = self.dir / snap_id
            snap_dir.mkdir(parents=True, exist_ok=True)

            listing: list[str] = []
            records: list[dict] = []
            if is_baseline:
                # 全量基线：只拷贝顶层条目（copytree 递归），清单记录全部路径。
                for _path, rel in self._iter_project():
                    listing.append(rel)
                    if '/' not in rel:
                        _copy_into(snap_dir, self.root / rel, rel, records)
            else:
                for _path, rel in self._iter_project():
                    listing.append(rel)
                for rel in self._resolve_affected(affected):
                    _copy_into(snap_dir, self.root / rel, rel, records)

            (snap_dir / 'listing.json').write_text(
                json.dumps(listing, ensure_ascii=False), encoding='utf-8',
            )
            index_path = self.paths.index
            if index_path.exists():
                idx_rec = _copy_file(snap_dir, index_path, 'index.json')
                records.append(idx_rec)
            else:
                records.append({'rel': 'index.json', 'existed': False, 'is_dir': False})

            (snap_dir / 'manifest.json').write_text(
                json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8',
            )

            entry = {
                'seq': seq,
                'baseline': is_baseline,
                'time': datetime.now().isoformat(timespec='seconds'),
                'paths': records,
                'dir': snap_id,
                'group_id': (f'g{_group_stack[-1]}' if _group_stack else seq),
            }
            self._entries.append(entry)
            self._save_manifest(self._entries)
            return entry

    def _delete_orphans(self, listing: set[str]) -> None:
        orphans = []
        for _path, rel in self._iter_project():
            if rel not in listing:
                orphans.append(rel)
        for rel in sorted(orphans, key=lambda r: r.count('/'), reverse=True):
            _remove_path(self.root / rel)

    def _undo_one(self, entry: dict) -> None:
        """还原单个快照 entry：恢复受影响路径 + 孤儿清理 + 还原 index.json。"""
        snap_dir = self.dir / entry.get('dir', '')
        if not snap_dir.is_dir():
            return

        records: list[dict] = []
        man = snap_dir / 'manifest.json'
        if man.exists():
            try:
                records = json.loads(man.read_text(encoding='utf-8'))
            except (OSError, json.JSONDecodeError):
                records = []

        # 1) 还原受影响路径内容
        for rec in records:
            rel = rec.get('rel')
            if not rel or rel == 'index.json':
                continue
            target = self.root / rel
            if target.exists() or target.is_symlink():
                _remove_path(target)
            if rec.get('existed'):
                src = snap_dir / 'files' / rel
                if src.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if rec.get('is_dir'):
                        shutil.copytree(src, target)
                    else:
                        shutil.copy2(src, target)

        # 2) 孤儿清理：删除操作新建、不在捕获时清单里的路径
        listing: set[str] = set()
        lp = snap_dir / 'listing.json'
        if lp.exists():
            try:
                listing = set(json.loads(lp.read_text(encoding='utf-8')))
            except (OSError, json.JSONDecodeError):
                listing = set()
        self._delete_orphans(listing)

        # 3) 还原 index.json
        idx_snap = snap_dir / 'index.json'
        idx_target = self.paths.index
        if idx_snap.exists():
            idx_target.parent.mkdir(parents=True, exist_ok=True)
            tmp = idx_target.with_suffix('.tmp')
            tmp.write_bytes(idx_snap.read_bytes())
            tmp.replace(idx_target)
        elif any(rec.get('rel') == 'index.json' and not rec.get('existed') for rec in records):
            _remove_path(idx_target)
            _remove_path(idx_target.with_suffix('.json.bak'))

        shutil.rmtree(snap_dir, ignore_errors=True)

    def undo(self, index=None) -> str | None:
        with self._lock:
            self._entries = self._load_manifest()
            if not self._entries:
                return None
            # 弹出一个撤回步：顶部同 group_id 的连续条目（组内=整批；组外=单条）。
            gid = self._entry_gid(self._entries[-1])
            undone: list[dict] = []
            while self._entries and self._entry_gid(self._entries[-1]) == gid:
                undone.append(self._entries.pop())
            for entry in undone:
                self._undo_one(entry)
            self._save_manifest(self._entries)

        if index is not None:
            try:
                index.reload()
            except Exception:
                pass

        labels: list[str] = []
        for entry in undone:
            paths = entry.get('paths') or []
            label = '，'.join([str(p.get('rel', p)) for p in paths if isinstance(p, dict) and p.get('rel') != 'index.json'][:4])
            if label:
                labels.append(label)
        if len(undone) > 1:
            return f'已撤回批量 {len(undone)} 步（{labels[0]}{"…" if len(labels) > 1 else ""}）'
        return f'已撤回 {labels[0]}'.strip() if labels else '已撤回一步'
