from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable


@dataclass(slots=True)
class ClaudeCLIOptions:
    model: str = ''
    effort: str = 'medium'
    max_turns: int = 24
    max_budget_usd: float = 0.0
    permission_mode: str = 'acceptEdits'
    tools: tuple[str, ...] | None = ('Read', 'Edit', 'Write', 'Glob', 'Grep')
    bare_mode: bool = True
    strict_mcp: bool = True
    include_partial_messages: bool = True


@dataclass(slots=True)
class ClaudeRun:
    output: str
    session_id: str
    exit_code: int
    events: list[dict[str, Any]] = field(default_factory=list)
    stderr: str = ''


class ClaudeCLI:


    def __init__(self, executable: str | None = None):
        self.executable = executable or os.environ.get('CLAUDE_BIN') or shutil.which('claude') or 'claude'
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.RLock()

    def available(self) -> tuple[bool, str]:
        exe = shutil.which(self.executable) if not Path(self.executable).exists() else self.executable
        if not exe:
            return False, '未找到 Claude Code CLI。请先安装并完成 claude auth login。'
        try:
            proc = subprocess.run([str(exe), '--version'], capture_output=True, text=True, timeout=8)
            version = (proc.stdout or proc.stderr).strip()
            return proc.returncode == 0, version or 'Claude Code CLI 可用'
        except Exception as exc:
            return False, str(exc)

    def auth_status(self) -> dict[str, Any]:
        try:
            proc = subprocess.run([self.executable, 'auth', 'status'], capture_output=True, text=True, timeout=10)
            payload = json.loads(proc.stdout or '{}') if (proc.stdout or '').strip().startswith('{') else {}
            payload.setdefault('ok', proc.returncode == 0)
            if proc.stderr.strip():
                payload.setdefault('message', proc.stderr.strip())
            return payload
        except Exception as exc:
            return {'ok': False, 'message': str(exc)}

    def build_command(
        self,
        *,
        session_id: str,
        resume: bool,
        options: ClaudeCLIOptions,
        mcp_config: str | Path | None = None,
        session_name: str = '',
        additional_dirs: Iterable[str | Path] = (),
    ) -> list[str]:
        cmd = [self.executable, '-p', '--output-format', 'stream-json', '--verbose']
        if options.include_partial_messages:
            cmd.append('--include-partial-messages')
        if resume:
            cmd.extend(['--resume', session_id])
        else:
            cmd.extend(['--session-id', session_id])
            if session_name:
                cmd.extend(['--name', session_name[:80]])
        if options.model:
            cmd.extend(['--model', options.model])
        if options.effort:
            cmd.extend(['--effort', options.effort])
        if options.max_turns > 0:
            cmd.extend(['--max-turns', str(options.max_turns)])
        if options.max_budget_usd > 0:
            cmd.extend(['--max-budget-usd', f'{options.max_budget_usd:.4f}'])
        if options.permission_mode:
            cmd.extend(['--permission-mode', options.permission_mode])
        if options.tools is not None:

            cmd.extend(['--tools', ','.join(options.tools)])


        if options.bare_mode:
            cmd.append('--bare')
        safe_dirs: list[str] = []
        for value in additional_dirs:
            path = Path(value).expanduser().resolve()
            if path.is_dir():
                safe_dirs.append(str(path))
        if safe_dirs:
            cmd.append('--add-dir')
            cmd.extend(safe_dirs)
        if options.strict_mcp and mcp_config:


            cmd.extend([
                '--strict-mcp-config', '--mcp-config', str(mcp_config),
                '--disallowedTools', 'mcp__*',
            ])
        return cmd

    def run(
        self,
        prompt: str,
        *,
        cwd: str | Path,
        session_id: str,
        resume: bool,
        options: ClaudeCLIOptions | None = None,
        mcp_config: str | Path | None = None,
        session_name: str = '',
        additional_dirs: Iterable[str | Path] = (),
        on_event: Callable[[dict[str, Any]], None] | None = None,
        on_text: Callable[[str], None] | None = None,
    ) -> ClaudeRun:
        options = options or ClaudeCLIOptions()
        command = self.build_command(
            session_id=session_id,
            resume=resume,
            options=options,
            mcp_config=mcp_config,
            session_name=session_name,
            additional_dirs=additional_dirs,
        )
        with self._lock:
            if self._process is not None:
                raise RuntimeError('Claude Agent 已在运行')
            try:
                self._process = subprocess.Popen(
                    command,
                    cwd=str(Path(cwd).resolve()),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    bufsize=1,
                )
            except FileNotFoundError as exc:
                raise RuntimeError('未找到 Claude Code CLI。请先安装 Claude Code。') from exc
            process = self._process

        events: list[dict[str, Any]] = []
        streamed: list[str] = []
        final_result = ''
        try:
            assert process.stdin is not None
            process.stdin.write(str(prompt))
            process.stdin.close()
            assert process.stdout is not None
            for raw in process.stdout:
                line = raw.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    event = {'type': 'raw', 'text': raw.rstrip('\n')}
                if isinstance(event, dict):
                    events.append(event)
                    if on_event:
                        on_event(event)
                    delta = _text_delta(event)
                    if delta:
                        streamed.append(delta)
                        if on_text:
                            on_text(delta)
                    if event.get('type') == 'result' and isinstance(event.get('result'), str):
                        final_result = event['result']
                    event_session = str(event.get('session_id') or event.get('sessionId') or '')
                    if event_session:
                        session_id = event_session
            assert process.stderr is not None
            stderr = process.stderr.read()
            exit_code = process.wait()
        finally:
            with self._lock:
                self._process = None
        output = ''.join(streamed).strip() or final_result.strip()
        if exit_code != 0:
            detail = _strip_telemetry(stderr) or final_result.strip() or f'Claude Code exited with {exit_code}'
            raise RuntimeError(detail)
        return ClaudeRun(output=output, session_id=session_id, exit_code=exit_code, events=events, stderr=stderr)

    def cancel(self) -> bool:
        with self._lock:
            process = self._process
            if process is None or process.poll() is not None:
                return False
            process.terminate()
            return True


def _strip_telemetry(text: str) -> str:


    if not text:
        return text.strip()
    lines = [line for line in text.splitlines() if not line.lstrip().startswith('[claude-code:')]
    return '\n'.join(lines).strip()


def _text_delta(event: dict[str, Any]) -> str:

    if event.get('type') == 'stream_event':
        inner = event.get('event') or {}
        if isinstance(inner, dict):
            delta = inner.get('delta') or {}
            if isinstance(delta, dict) and isinstance(delta.get('text'), str):
                return delta['text']
    if event.get('type') == 'content_block_delta':
        delta = event.get('delta') or {}
        if isinstance(delta, dict) and isinstance(delta.get('text'), str):
            return delta['text']


    if event.get('type') in {'assistant_delta', 'text'} and isinstance(event.get('text'), str):
        return event['text']
    return ''
