from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from src.core.project_paths import ProjectPaths
from src.library.operations import ensure_pdf_latex

from .claude_cli import ClaudeCLI
from .config import AgentConfig
from .mentions import Mention, ParsedMentions, is_sensitive_project_path, parse_mentions, resolve_project_file
from .session import SessionStore
from .skills import get_skill, native_root_skills


TEXT_EXTENSIONS = {
    '.md', '.markdown', '.txt', '.tex', '.csv', '.json', '.yaml', '.yml',
    '.toml', '.ini', '.cfg', '.py', '.js', '.ts', '.tsx', '.jsx', '.html',
    '.css', '.xml', '.rst', '.srt', '.vtt', '.bib', '.sql', '.sh',
    '.ps1', '.bat', '.cmd', '.java', '.c', '.h', '.cpp', '.hpp', '.go', '.rs',
}
IGNORE_PARTS = {'.workknacks', '.git', '.claude', '.ssh', '.aws', '__pycache__', '.pytest_cache', 'node_modules'}
MAX_SHADOW_TEXT_BYTES = 8 * 1024 * 1024
MAX_CONTEXT_CHARS_PER_FILE = 12_000
TITLE_RE = re.compile(r'\[WORKKNACKS_TITLE\](.*?)\[/WORKKNACKS_TITLE\]', re.I | re.S)
_RUN_LOCK_GUARD = threading.Lock()
_RUN_LOCKS: dict[str, threading.RLock] = {}


def _project_run_lock(root: Path) -> threading.RLock:
    key = str(root.resolve())
    with _RUN_LOCK_GUARD:
        lock = _RUN_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _RUN_LOCKS[key] = lock
        return lock


@dataclass(slots=True)
class PendingChange:
    relative_path: str
    kind: str  
    before: bytes | None
    after: bytes | None

    def text_diff(self, max_lines: int = 600) -> str:
        if self.kind == 'delete':
            before = _decode(self.before)
            return '\n'.join(f'- {line}' for line in before.splitlines()[:max_lines])
        if self.kind == 'create':
            after = _decode(self.after)
            return '\n'.join(f'+ {line}' for line in after.splitlines()[:max_lines])
        before_lines = _decode(self.before).splitlines()
        after_lines = _decode(self.after).splitlines()
        diff = list(difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile='a/' + self.relative_path,
            tofile='b/' + self.relative_path,
            lineterm='',
        ))
        if len(diff) > max_lines:
            return '\n'.join(diff[:max_lines] + [f'... diff 过长，已省略 {len(diff) - max_lines} 行'])
        return '\n'.join(diff)


@dataclass(slots=True)
class AgentRunResult:
    session_id: str
    output: str
    parsed: ParsedMentions
    pending_changes: list[PendingChange] = field(default_factory=list)
    context_files: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.pending_changes)


class ProjectAgent:
    

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.paths = ProjectPaths.for_root(self.root).ensure()
        self.config = AgentConfig(self.root)
        cache = self.config.data.get('cache') or {}
        try:
            self.paths.cleanup_cache(
                max_age_days=int(cache.get('maxAgeDays') or 30),
                max_bytes=int(cache.get('maxBytes') or 536870912),
            )
        except (OSError, ValueError, TypeError):
            
            pass
        self.sessions = SessionStore(self.root)
        self.cli = ClaudeCLI()
        self._run_lock = _project_run_lock(self.root)

    def run(
        self,
        message: str,
        *,
        session_id: str | None = None,
        extra_skills: Iterable[str] = (),
        on_event: Callable[[dict], None] | None = None,
        on_text: Callable[[str], None] | None = None,
        automatic: bool = False,
        task_kind: str = '',
    ) -> AgentRunResult:
        
        
        
        with self._run_lock:
            return self._run_unlocked(
                message, session_id=session_id,
                extra_skills=extra_skills, on_event=on_event, on_text=on_text,
                automatic=automatic, task_kind=task_kind,
            )

    def _run_unlocked(
        self,
        message: str,
        *,
        session_id: str | None = None,
        extra_skills: Iterable[str] = (),
        on_event: Callable[[dict], None] | None = None,
        on_text: Callable[[str], None] | None = None,
        automatic: bool = False,
        task_kind: str = '',
    ) -> AgentRunResult:
        ok, status = self.cli.available()
        if not ok:
            raise RuntimeError(status)
        parsed = parse_mentions(message)
        created_new = session_id is None
        if session_id is None:
            session_id = self.sessions.create().id
        info = self.sessions.info(session_id)
        if info is None:
            raise KeyError(f'未知会话：{session_id}')

        
        
        requested_skills = [*extra_skills, *parsed.values('skill')]
        skills = self._resolve_skills(requested_skills)
        context_notes, context_files = self._prepare_file_context(parsed.values('file'))
        self.sessions.append(session_id, 'user', message, automatic=bool(automatic), task_kind=str(task_kind or ''))

        shadow = self.paths.agent_worktree
        if shadow.exists():
            shutil.rmtree(shadow, ignore_errors=True)
        shadow.mkdir(parents=True, exist_ok=True)
        manifest = _build_shadow(self.root, shadow)
        _overlay_effective_skills(self.root, shadow)

        prompt = self._build_prompt(
            parsed=parsed, skills=skills, context_notes=context_notes,
            request_title=created_new,
        )
        mcp_config = self.paths.temp / 'empty-mcp.json'
        mcp_config.parent.mkdir(parents=True, exist_ok=True)
        mcp_config.write_text('{"mcpServers": {}}', encoding='utf-8')
        try:
            run = self.cli.run(
                prompt,
                cwd=shadow,
                session_id=session_id,
                resume=bool(info.native_started),
                options=self.config.cli_options,
                mcp_config=mcp_config,
                session_name=info.title,
                additional_dirs=(),
                on_event=on_event,
                on_text=on_text,
            )
            if run.session_id != session_id:
                
                
                raise RuntimeError(f'Claude 会话 ID 不一致：{run.session_id}')
            self.sessions.mark_native_started(session_id)
            changes = _collect_changes(self.root, shadow, manifest)
        finally:
            shutil.rmtree(shadow, ignore_errors=True)
            try:
                mcp_config.unlink()
            except OSError:
                pass
        clean_output, ai_title = _extract_ai_title(run.output)
        if created_new:
            fallback = _fallback_ai_title(clean_output, task_kind or parsed.clean_text or message)
            self.sessions.rename(session_id, ai_title or fallback)
        self.sessions.append(
            session_id, 'assistant', clean_output,
            pending_changes=[change.relative_path for change in changes],
            automatic=bool(automatic), task_kind=str(task_kind or ''),
        )
        return AgentRunResult(
            session_id=session_id, output=clean_output, parsed=parsed,
            pending_changes=changes, context_files=context_files,
        )

    def run_automatic(
        self,
        message: str,
        *,
        task_kind: str,
        extra_skills: Iterable[str] = (),
    ) -> AgentRunResult:
        
        return self.run(
            message,
            session_id=None,
            extra_skills=extra_skills,
            automatic=True,
            task_kind=task_kind,
        )

    def cancel(self) -> bool:
        return self.cli.cancel()

    def recompile_changed_latex(self, changes: Iterable[PendingChange]) -> list[str]:
        
        from src.providers.parse.mineru import compile_latex

        compiled: list[str] = []
        seen: set[str] = set()
        for change in changes:
            rel = str(change.relative_path).replace('\\', '/')
            if Path(rel).name != 'main.tex' or rel.casefold() in seen:
                continue
            seen.add(rel.casefold())
            tex = _safe_target(self.root, rel)
            if tex.is_file():
                try:
                    pdf = compile_latex(tex)
                except Exception:
                    pdf = None
                if pdf is not None:
                    compiled.append(rel)
        return compiled

    def apply_changes(self, changes: Iterable[PendingChange]) -> Path | None:
        changes = list(changes)
        if not changes:
            return None
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        backup_root = self.paths.backups / stamp
        backup_root.mkdir(parents=True, exist_ok=True)
        manifest = []
        for change in changes:
            target = _safe_target(self.root, change.relative_path)
            if change.kind == 'create' and target.exists():
                raise RuntimeError(f'文件在 AI 生成 diff 后已出现，拒绝覆盖：{change.relative_path}')
            if change.kind in {'modify', 'delete'}:
                if not target.exists():
                    raise RuntimeError(f'文件在 AI 生成 diff 后已不存在：{change.relative_path}')
                current = target.read_bytes()
                if current != (change.before or b''):
                    raise RuntimeError(f'文件在 AI 生成 diff 后被外部修改，拒绝覆盖：{change.relative_path}')
            if target.exists() and change.kind in {'modify', 'delete'}:
                backup = backup_root / change.relative_path
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
            manifest.append({'path': change.relative_path, 'kind': change.kind})
            if change.kind == 'delete':
                if target.exists() and target.is_file():
                    target.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(target.name + '.workknacks.tmp')
            temp.write_bytes(change.after or b'')
            temp.replace(target)
        (backup_root / 'manifest.json').write_text(
            json.dumps({'createdAt': datetime.now().isoformat(timespec='seconds'), 'changes': manifest}, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
        return backup_root

    def latest_backup(self) -> Path | None:
        root = self.paths.backups
        if not root.exists():
            return None
        candidates = [p for p in root.iterdir() if p.is_dir() and (p / 'manifest.json').exists()]
        return max(candidates, key=lambda p: p.name) if candidates else None

    def undo_backup(self, backup_root: str | Path | None = None) -> list[str]:
        backup = Path(backup_root).resolve() if backup_root else self.latest_backup()
        if not backup or not backup.exists():
            raise RuntimeError('没有可撤销的 AI 写回备份。')
        manifest_path = backup / 'manifest.json'
        if not manifest_path.exists():
            raise RuntimeError('备份缺少 manifest.json，无法安全撤销。')
        data = json.loads(manifest_path.read_text(encoding='utf-8'))
        restored: list[str] = []
        for item in reversed(data.get('changes') or []):
            rel = str(item.get('path') or '')
            kind = str(item.get('kind') or '')
            target = _safe_target(self.root, rel)
            saved = backup / rel
            if kind == 'create':
                if target.exists() and target.is_file():
                    target.unlink()
                    restored.append(rel)
            elif kind in {'modify', 'delete'}:
                if not saved.exists():
                    raise RuntimeError(f'备份文件缺失：{rel}')
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(saved, target)
                restored.append(rel)
        done = backup / 'UNDONE'
        done.write_text(datetime.now().isoformat(timespec='seconds'), encoding='utf-8')
        return restored

    def _resolve_skills(self, names: Iterable[str]) -> list[str]:
        
        
        
        result: list[str] = []
        seen = set()
        for name in names:
            key = str(name).strip().casefold()
            if not key or key in seen:
                continue
            if not get_skill(key, self.root):
                raise ValueError(f'未知 skill：{name}')
            seen.add(key); result.append(key)
        return result

    def _prepare_file_context(self, values: Iterable[str]) -> tuple[list[str], list[str]]:
        notes: list[str] = []
        files: list[str] = []
        for value in values:
            path = resolve_project_file(self.root, value)
            rel = path.relative_to(self.root).as_posix()
            files.append(rel)
            if path.suffix.lower() == '.pdf':
                parsed = _ensure_pdf_latex(path, self.root)
                if parsed:
                    parsed_rel = parsed.relative_to(self.root).as_posix()
                    notes.append(f'{rel} → 解析稿 {parsed_rel}')
                    if parsed_rel not in files:
                        files.append(parsed_rel)
                else:
                    notes.append(f'{rel}（PDF，当前无解析稿）')
            else:
                notes.append(rel)
        return notes, files

    def _build_prompt(
        self,
        *,
        parsed: ParsedMentions,
        skills: list[str],
        context_notes: list[str],
        request_title: bool = False,
    ) -> str:
        instruction = parsed.clean_text or '完成本轮任务。'
        parts = [
            '你在项目安全工作副本中。优先直接用 Read/Glob/Grep 读取相对路径；必要时可 Edit/Write，写回前由 WorkKnacks 展示 diff。',
            '不要读取或输出密钥、cookie、.env.local、.workknacks；不要修改 PDF/图片/音视频二进制文件。',
        ]
        if skills:
            hints = '、'.join(f'{name}（skills/{name}/SKILL.md）' for name in skills)
            parts.append(
                f'本次使用 skill：{hints}。请用 Read 打开这些相对路径下的 SKILL.md 并遵循其中的规范；'
                '也可以用 Glob 查看 skills/ 目录里还有哪些可用的 skill。'
            )
        if context_notes:
            parts.append('相关文件：' + '；'.join(context_notes))
        parts.append('任务：' + instruction)
        parts.append('回答尽量简洁；若改文件，只列必要结果和相对路径。')
        if request_title:
            parts.append('回答末尾加：[WORKKNACKS_TITLE]不超过24个字的标题[/WORKKNACKS_TITLE]')
        return '\n'.join(parts)


def _extract_ai_title(output: str) -> tuple[str, str]:
    text = str(output or '')
    match = TITLE_RE.search(text)
    title = ' '.join(match.group(1).split())[:80] if match else ''
    clean = TITLE_RE.sub('', text).strip()
    return clean, title


def _fallback_ai_title(output: str, hint: str) -> str:
    for line in str(output or '').splitlines():
        value = re.sub(r'^[#>*\-\s]+', '', line).strip()
        if 4 <= len(value) <= 60:
            return value[:60]
    value = ' '.join(str(hint or '').split()).strip()
    return value[:60] or 'AI 操作'


def _overlay_effective_skills(root: Path, shadow: Path) -> int:
    """Mount the live, precedence-resolved skills into the shadow's ``skills/``.

    The agent works inside ``shadow`` and reads skills by the relative path
    ``skills/<name>/SKILL.md``. ``_build_shadow`` already copies the bundled
    ``skills/``; this overlays project-local and user-global skills on top so the
    effective set (project > global > bundled) is always what the agent sees.
    Because it re-copies from disk on every run, edits made to ``skills/`` are
    picked up on the next run — nothing is baked into the prompt.
    """
    written = 0
    for spec in native_root_skills(root):
        source = spec.directory
        target = shadow / 'skills' / spec.name
        for path in source.rglob('*'):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                rel = path.relative_to(source)
            except ValueError:
                continue
            dst = target / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(path, dst)
                written += 1
            except OSError:
                continue
    return written


def _build_shadow(root: Path, shadow: Path) -> dict[str, bytes]:
    manifest: dict[str, bytes] = {}
    shadow_resolved = shadow.resolve()
    for path in root.rglob('*'):
        if not path.is_file():
            continue
        try:
            path.resolve().relative_to(shadow_resolved)
        except ValueError:
            pass
        else:
            
            continue
        try:
            rel_path = path.relative_to(root)
        except ValueError:
            continue
        if any(part in IGNORE_PARTS for part in rel_path.parts) or is_sensitive_project_path(rel_path):
            continue
        if not _is_text_file(path):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > MAX_SHADOW_TEXT_BYTES:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        rel = rel_path.as_posix()
        manifest[rel] = data
        target = shadow / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return manifest


def _collect_changes(root: Path, shadow: Path, manifest: dict[str, bytes]) -> list[PendingChange]:
    after_map: dict[str, bytes] = {}
    for path in shadow.rglob('*'):
        if not path.is_file():
            continue
        rel_path = path.relative_to(shadow)
        if any(part in IGNORE_PARTS for part in rel_path.parts) or is_sensitive_project_path(rel_path):
            continue
        
        if not _is_text_file(path) or path.stat().st_size > MAX_SHADOW_TEXT_BYTES:
            continue
        after_map[rel_path.as_posix()] = path.read_bytes()

    changes: list[PendingChange] = []
    for rel in sorted(set(manifest) | set(after_map), key=str.casefold):
        before = manifest.get(rel)
        after = after_map.get(rel)
        if before == after:
            continue
        if before is None:
            kind = 'create'
        elif after is None:
            kind = 'delete'
        else:
            kind = 'modify'
        changes.append(PendingChange(rel, kind, before, after))
    return changes


def _ensure_pdf_latex(pdf: Path, root: Path) -> Path | None:
    
    try:
        return ensure_pdf_latex(pdf, project_root=root)
    except Exception:
        return None


def _is_text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_EXTENSIONS or path.name in {'README', 'LICENSE', 'Makefile'}


def _read_excerpt(path: Path) -> str:
    try:
        text = path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''
    if len(text) <= MAX_CONTEXT_CHARS_PER_FILE:
        return text
    return text[:MAX_CONTEXT_CHARS_PER_FILE] + '\n…（摘录到此，完整文件请用 Read）'


def _history_text(history: list[dict]) -> str:
    chunks = []
    total = 0
    for item in history[-10:]:
        role = item.get('role', 'unknown')
        content = str(item.get('content') or '')
        if len(content) > 4000:
            content = content[:4000] + '…'
        chunk = f'{role}: {content}'
        total += len(chunk)
        if total > 24_000:
            break
        chunks.append(chunk)
    return '\n\n'.join(chunks)


def _safe_target(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f'Agent 改动路径越界：{relative}') from exc
    if is_sensitive_project_path(target, root):
        raise ValueError(f'Agent 不允许写入敏感/内部路径：{relative}')
    return target


def _decode(data: bytes | None) -> str:
    return (data or b'').decode('utf-8', errors='replace')
