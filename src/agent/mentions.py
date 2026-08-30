from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path


MENTION_RE = re.compile(r'@(file|skill)\b', re.I)
SENSITIVE_PARTS = {'.git', '.workknacks', '.claude', '.ssh', '.aws', '__pycache__', '.pytest_cache', 'node_modules'}
SENSITIVE_NAME_TOKENS = {'cookie', 'cookies', 'credential', 'credentials', 'secret', 'secrets', 'token', 'tokens', 'password', 'passwd', 'apikey', 'api_key', 'private_key', 'records_list'}


@dataclass(frozen=True, slots=True)
class Mention:
    kind: str
    value: str
    start: int
    end: int


@dataclass(slots=True)
class ParsedMentions:
    text: str
    clean_text: str
    mentions: list[Mention]

    def values(self, kind: str) -> list[str]:
        return [m.value for m in self.mentions if m.kind == kind]


def parse_mentions(text: str) -> ParsedMentions:

    source = str(text or '')
    matches = list(MENTION_RE.finditer(source))
    mentions: list[Mention] = []
    remove_spans: list[tuple[int, int]] = []
    for idx, match in enumerate(matches):
        kind = match.group(1).casefold()
        segment_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(source)
        raw_segment = source[match.end():segment_end]
        leading = len(raw_segment) - len(raw_segment.lstrip())
        value_start = match.end() + leading
        segment = raw_segment.lstrip()
        value, consumed = _first_token(segment)
        end = value_start + consumed
        value = value.rstrip('，,;；')
        if value:
            mentions.append(Mention(kind, value, match.start(), end))
            remove_spans.append((match.start(), end))
    clean = source
    for start, end in reversed(remove_spans):
        clean = clean[:start] + ' ' + clean[end:]
    clean = re.sub(r'[ \t]{2,}', ' ', clean)
    clean = re.sub(r' *\n *', '\n', clean).strip()
    return ParsedMentions(source, clean, mentions)


def is_sensitive_project_path(path: str | Path, root: str | Path | None = None) -> bool:
    candidate = Path(path)
    if root is not None:
        try:
            candidate = candidate.resolve().relative_to(Path(root).expanduser().resolve())
        except Exception:
            return True
    parts = {part.casefold() for part in candidate.parts}
    if parts & {part.casefold() for part in SENSITIVE_PARTS}:
        return True
    name = candidate.name.casefold()
    if name.startswith('.env') or name in {'id_rsa', 'id_ed25519'}:
        return True
    stem = candidate.stem.casefold()
    if stem in SENSITIVE_NAME_TOKENS:
        return True
    words = set(re.findall(r'[a-z0-9]+', stem))
    sensitive_words = {'cookie', 'cookies', 'credential', 'credentials', 'secret', 'secrets', 'token', 'tokens', 'password', 'passwd', 'apikey'}
    return bool(words & sensitive_words) or {'private', 'key'} <= words or stem == 'records_list'


def resolve_project_file(root: str | Path, value: str) -> Path:
    root_path = Path(root).expanduser().resolve()
    raw = str(value).strip().strip('"\'')
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = root_path / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root_path)
    except ValueError as exc:
        raise ValueError(f'@file 路径越界：{value}') from exc
    if not resolved.exists():
        raise FileNotFoundError(str(resolved))
    if is_sensitive_project_path(resolved, root_path):
        raise ValueError(f'@file 不允许读取敏感/内部路径：{value}')
    return resolved


def completion_data(root: str | Path) -> dict[str, list[str]]:
    root_path = Path(root).expanduser().resolve()
    files = []
    if root_path.exists():
        for path in root_path.rglob('*'):
            if not path.is_file() or is_sensitive_project_path(path, root_path):
                continue
            try:
                files.append(path.relative_to(root_path).as_posix())
            except ValueError:
                continue
    return {'file': sorted(files, key=str.casefold)}


def _first_token(segment: str) -> tuple[str, int]:
    if not segment:
        return '', 0
    quote = segment[0] if segment[0] in {'"', "'"} else ''
    if quote:
        escaped = False
        for i in range(1, len(segment)):
            ch = segment[i]
            if escaped:
                escaped = False
                continue
            if ch == '\\':
                escaped = True
                continue
            if ch == quote:
                token_text = segment[:i + 1]
                try:
                    token = shlex.split(token_text, posix=True)[0]
                except Exception:
                    token = token_text[1:-1]
                return token, i + 1
        return segment[1:], len(segment)
    match = re.match(r'[^\s]+', segment)
    return (match.group(0), match.end()) if match else ('', 0)
