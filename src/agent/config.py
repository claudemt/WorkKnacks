from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
from typing import Any

from src.core.project_paths import ProjectPaths
from src.library.rename import DEFAULT_RENAME_TEMPLATE
from .claude_cli import ClaudeCLIOptions


CLAUDE_EFFORT_LEVELS = ('low', 'medium', 'high', 'xhigh', 'max', 'ultracode')
CLAUDE_PERMISSION_MODES = ('acceptEdits', 'default', 'plan', 'auto', 'dontAsk')
SAFE_AGENT_TOOLS = ('Read', 'Edit', 'Write', 'Glob', 'Grep')


class AgentConfig:
    

    SCHEMA_VERSION = 1

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.paths = ProjectPaths.for_root(self.root)
        self.path = self.paths.agent_config
        self._lock = RLock()
        self.data = self._load()

    def _base(self) -> dict[str, Any]:
        return {
            'version': self.SCHEMA_VERSION,
            'renameTemplate': DEFAULT_RENAME_TEMPLATE,
            'agent': {
                'model': '',
                'effort': 'medium',
                'maxTurns': 24,
                'maxBudgetUsd': 0.0,
                'permissionMode': 'acceptEdits',
                'tools': list(SAFE_AGENT_TOOLS),
                'bareMode': True,
                'strictMcp': True,
                'maxContextChars': 100_000,
                'safeWrites': True,
            },
            'cache': {'maxAgeDays': 30, 'maxBytes': 536870912},
        }

    def _load(self) -> dict[str, Any]:
        base = self._base()
        if not self.path.exists():
            return base
        try:
            loaded = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            return base
        if not isinstance(loaded, dict) or int(loaded.get('version') or 0) != self.SCHEMA_VERSION:
            return base
        agent = dict(base['agent'])
        agent.update(loaded.get('agent') or {})
        cache = dict(base['cache'])
        cache.update(loaded.get('cache') or {})
        base.update({key: value for key, value in loaded.items() if key not in {'agent', 'cache'}})
        base['agent'] = agent
        base['cache'] = cache
        return base

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.data['version'] = self.SCHEMA_VERSION
            temp = self.path.with_suffix('.json.tmp')
            temp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding='utf-8')
            temp.replace(self.path)

    @property
    def cli_options(self) -> ClaudeCLIOptions:
        raw = self.data.get('agent') or {}
        effort = str(raw.get('effort') or 'medium')
        if effort not in CLAUDE_EFFORT_LEVELS:
            effort = 'medium'
        permission_mode = str(raw.get('permissionMode') or 'acceptEdits')
        if permission_mode not in CLAUDE_PERMISSION_MODES:
            permission_mode = 'acceptEdits'
        try:
            max_turns = max(0, min(10_000, int(raw.get('maxTurns') or 0)))
        except (TypeError, ValueError):
            max_turns = 24
        try:
            max_budget = max(0.0, float(raw.get('maxBudgetUsd') or 0.0))
        except (TypeError, ValueError):
            max_budget = 0.0
        model = str(raw.get('model') or '').strip().replace('\r', '').replace('\n', '')[:200]
        return ClaudeCLIOptions(
            model=model,
            effort=effort,
            max_turns=max_turns,
            max_budget_usd=max_budget,
            permission_mode=permission_mode,
            tools=SAFE_AGENT_TOOLS,
            bare_mode=True,
            strict_mcp=True,
        )

    def update_cli_settings(
        self,
        *,
        model: str = '',
        effort: str = 'medium',
        max_turns: int = 24,
        max_budget_usd: float = 0.0,
        permission_mode: str = 'acceptEdits',
    ) -> None:
        effort = str(effort).strip()
        if effort not in CLAUDE_EFFORT_LEVELS:
            raise ValueError(f'不支持的 Claude effort：{effort}')
        permission_mode = str(permission_mode).strip()
        if permission_mode not in CLAUDE_PERMISSION_MODES:
            raise ValueError(f'不支持或不安全的 Claude permission mode：{permission_mode}')
        model = str(model).strip()
        if '\n' in model or '\r' in model:
            raise ValueError('Claude model 不能包含换行。')
        max_turns = int(max_turns)
        if not 0 <= max_turns <= 10_000:
            raise ValueError('max turns 必须在 0–10000 之间；0 表示不额外限制。')
        max_budget_usd = float(max_budget_usd)
        if max_budget_usd < 0:
            raise ValueError('预算上限不能为负数；0 表示不额外限制。')
        self.data.setdefault('agent', {}).update({
            'model': model,
            'effort': effort,
            'maxTurns': max_turns,
            'maxBudgetUsd': max_budget_usd,
            'permissionMode': permission_mode,
            'tools': list(SAFE_AGENT_TOOLS),
            'bareMode': True,
            'strictMcp': True,
            'safeWrites': True,
        })
        self.save()
