from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


BUNDLED_SKILLS_DIR = Path(__file__).resolve().parents[2] / 'skills'
BUILTIN_SKILL_NAMES = ('summarize', 'polish')
_SKILL_DIR_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')


@dataclass(frozen=True, slots=True)
class SkillSpec:
    name: str
    label: str
    description: str
    path: Path
    scope: str = 'global'
    allowed_tools: tuple[str, ...] = ()

    @property
    def directory(self) -> Path:
        return self.path.parent

    def prompt(self) -> str:
        return self.path.read_text(encoding='utf-8', errors='replace')


def workknacks_global_skills_dir() -> Path:
    
    return Path.home() / '.workknacks' / 'skills'


def ensure_global_skills() -> Path:
    
    target_root = workknacks_global_skills_dir()
    target_root.mkdir(parents=True, exist_ok=True)
    for name in BUILTIN_SKILL_NAMES:
        target = target_root / name / 'SKILL.md'
        if target.exists():
            continue
        source = BUNDLED_SKILLS_DIR / name / 'SKILL.md'
        if not source.is_file():
            raise RuntimeError(f'发布包缺少内置 Skill：{name}')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text(encoding='utf-8'), encoding='utf-8')
    return target_root


def project_skills_dir(root: str | Path | None) -> Path:
    
    if not root:
        return Path()
    return Path(root).expanduser().resolve() / '.workknacks' / 'skills'


def _project_skill_dirs(root: str | Path | None) -> list[Path]:
    if not root:
        return []
    skill_root = project_skills_dir(root)
    if not skill_root.is_dir():
        return []
    try:
        return sorted(
            (
                path for path in skill_root.iterdir()
                if path.is_dir()
                and not path.is_symlink()
                and _valid_skill_name(path.name)
            ),
            key=lambda path: path.name.casefold(),
        )
    except OSError:
        return []


def list_skills(root=None) -> list[SkillSpec]:
    
    result: list[SkillSpec] = []
    seen: set[str] = set()

    for directory in _project_skill_dirs(root):
        spec = _load_skill(directory / 'SKILL.md')
        if spec and spec.name.casefold() not in seen:
            seen.add(spec.name.casefold())
            result.append(spec)

    skill_root = ensure_global_skills()
    ordered_dirs: list[Path] = []
    for name in BUILTIN_SKILL_NAMES:
        ordered_dirs.append(skill_root / name)
    try:
        extras = sorted(
            (
                path for path in skill_root.iterdir()
                if path.is_dir()
                and not path.is_symlink()
                and path.name not in BUILTIN_SKILL_NAMES
                and _valid_skill_name(path.name)
            ),
            key=lambda path: path.name.casefold(),
        )
        ordered_dirs.extend(extras)
    except OSError:
        pass

    for directory in ordered_dirs:
        spec = _load_skill(directory / 'SKILL.md')
        if not spec or spec.name.casefold() in seen:
            continue
        seen.add(spec.name.casefold())
        result.append(spec)
    return result


def native_root_skills(root=None) -> list[SkillSpec]:
    return list_skills(root)


def get_skill(name: str, root=None) -> SkillSpec | None:
    key = str(name or '').strip().casefold().lstrip('/')
    if not key:
        return None
    return next((spec for spec in list_skills(root) if spec.name.casefold() == key), None)


def skill_names(root=None) -> list[str]:
    return [spec.name for spec in list_skills(root)]


def _valid_skill_name(name: str) -> bool:
    return bool(_SKILL_DIR_RE.fullmatch(str(name or ''))) and not str(name).startswith('.')


def _load_skill(path: Path) -> SkillSpec | None:
    if path.is_symlink() or not path.is_file() or not _valid_skill_name(path.parent.name):
        return None
    try:
        text = path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return None
    name = path.parent.name
    meta, body = _frontmatter(text)
    label = str(meta.get('name') or name).strip() or name
    description = str(meta.get('description') or _first_paragraph(body) or name).strip()
    allowed_raw = str(meta.get('allowed-tools') or '').strip()
    allowed = tuple(piece for piece in re.split(r'[\s,]+', allowed_raw) if piece)
    return SkillSpec(name=name, label=label, description=description, path=path, allowed_tools=allowed)


def _frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith('---'):
        return {}, text
    lines = text.splitlines()
    try:
        end = lines.index('---', 1)
    except ValueError:
        return {}, text
    meta: dict[str, str] = {}
    for line in lines[1:end]:
        if ':' not in line:
            continue
        key, value = line.split(':', 1)
        meta[key.strip()] = value.strip().strip('"\'')
    return meta, '\n'.join(lines[end + 1:])


def _first_paragraph(text: str) -> str:
    for chunk in re.split(r'\n\s*\n', str(text or '').strip()):
        cleaned = ' '.join(line.strip('# ').strip() for line in chunk.splitlines() if line.strip())
        if cleaned:
            return cleaned[:300]
    return ''
