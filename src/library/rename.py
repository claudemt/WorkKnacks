from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .entry import Creator, LibraryEntry


DEFAULT_RENAME_TEMPLATE = '{{ firstCreator suffix=" - " }}{{ year suffix=" - " }}{{ title truncate="100" }}'
WINDOWS_RESERVED = {
    'con', 'prn', 'aux', 'nul',
    *(f'com{i}' for i in range(1, 10)),
    *(f'lpt{i}' for i in range(1, 10)),
}


@dataclass(slots=True)
class TemplatePart:
    kind: str
    value: str


def normalize_rename_template(template: str) -> str:
    return re.sub(r'\r?\n', '', str(template or '')).strip()


def parse_template_brackets(template: str) -> list[TemplatePart]:
    template = normalize_rename_template(template)
    parts: list[TemplatePart] = []
    text_start = 0
    i = 0
    while i < len(template):
        if template.startswith('{{', i):
            if i > text_start:
                parts.append(TemplatePart('text', template[text_start:i]))
            start = i + 2
            i += 2
            depth = 1
            quote = ''
            while i < len(template) and depth:
                ch = template[i]
                if quote:


                    if ch == quote:
                        quote = ''
                    i += 1
                    continue
                if ch in {'"', "'"}:
                    quote = ch
                    i += 1
                    continue
                if template.startswith('{{', i):
                    depth += 1
                    i += 2
                    continue
                if template.startswith('}}', i):
                    depth -= 1
                    if depth == 0:
                        parts.append(TemplatePart('expr', template[start:i].strip()))
                        i += 2
                        text_start = i
                        break
                    i += 2
                    continue
                i += 1
            if depth:
                raise ValueError('模板中的 {{ }} 未配平')
        elif template.startswith('}}', i):
            raise ValueError('模板包含没有对应 {{ 的 }}')
        else:
            i += 1
    if text_start < len(template):
        parts.append(TemplatePart('text', template[text_start:]))
    return parts


def is_template_valid(template: str) -> bool:
    try:
        parts = parse_template_brackets(template)
    except ValueError:
        return False
    stack: list[dict[str, bool]] = []
    for part in parts:
        if part.kind != 'expr':
            continue
        expr = part.value.strip()
        lower = expr.lower()
        if lower.startswith('if '):
            stack.append({'else_seen': False})
        elif lower.startswith('elseif '):
            if not stack or stack[-1]['else_seen']:
                return False
        elif lower == 'else':
            if not stack or stack[-1]['else_seen']:
                return False
            stack[-1]['else_seen'] = True
        elif lower == 'endif':
            if not stack:
                return False
            stack.pop()
        elif expr.startswith(('"', "'")):
            if _parse_string_literal(expr) is None:
                return False
    return not stack


def render_template(entry: LibraryEntry, template: str = DEFAULT_RENAME_TEMPLATE) -> str:
    template = normalize_rename_template(template)
    if not is_template_valid(template):
        template = DEFAULT_RENAME_TEMPLATE
    parts = parse_template_brackets(template)

    frames = [{'parent': True, 'active': True, 'taken': False, 'else_seen': False}]
    output = ''
    for part in parts:
        if part.kind == 'text':
            if frames[-1]['active']:
                output = _append_safely(output, part.value)
            continue

        expr = part.value.strip()
        lower = expr.lower()
        if lower.startswith('if '):
            parent = bool(frames[-1]['active'])
            condition = parent and evaluate_condition(entry, expr[3:].strip())
            frames.append({'parent': parent, 'active': condition, 'taken': condition, 'else_seen': False})
            continue
        if lower.startswith('elseif '):
            if len(frames) == 1:
                continue
            frame = frames[-1]
            condition = bool(frame['parent']) and not bool(frame['taken']) and evaluate_condition(entry, expr[7:].strip())
            frame['active'] = condition
            frame['taken'] = bool(frame['taken']) or condition
            continue
        if lower == 'else':
            if len(frames) > 1:
                frame = frames[-1]
                frame['active'] = bool(frame['parent']) and not bool(frame['taken'])
                frame['taken'] = True
                frame['else_seen'] = True
            continue
        if lower == 'endif':
            if len(frames) > 1:
                frames.pop()
            continue
        if not frames[-1]['active']:
            continue

        if expr.startswith(('"', "'")):
            literal = _parse_string_literal(expr)
            output = _append_safely(output, literal if literal is not None else '')
            continue

        name, attrs = _parse_identifier(expr)
        output = _append_safely(output, evaluate_identifier(entry, name, attrs))

    return output


def evaluate_condition(entry: LibraryEntry, expression: str) -> bool:
    op_info = _find_top_level_operator(expression)
    if not op_info:
        return bool(_evaluate_operand(entry, expression.strip()))
    left_text, operator, right_text = op_info
    left = _evaluate_operand(entry, left_text.strip())
    right = _evaluate_operand(entry, right_text.strip())
    left_num = _as_number(left)
    right_num = _as_number(right)
    if left_num is not None and right_num is not None:
        a: Any = left_num
        b: Any = right_num
    else:
        a = str(left).casefold()
        b = str(right).casefold()
    return {
        '==': lambda: a == b,
        '!=': lambda: a != b,
        '<=': lambda: a <= b,
        '>=': lambda: a >= b,
        '<': lambda: a < b,
        '>': lambda: a > b,
    }[operator]()


def evaluate_identifier(entry: LibraryEntry, name: str, attrs: dict[str, str] | None = None) -> str:
    attrs = attrs or {}
    lowered = name.casefold()
    if lowered == 'firstcreator':
        raw: Any = entry.first_creator
    elif lowered in {'authors', 'editors', 'creators'}:
        if lowered == 'authors':
            creators = entry.authors
        elif lowered == 'editors':
            creators = entry.editors
        else:
            creators = entry.creators
        raw = _format_creators(creators, attrs, entry.language)

        attrs = {k: v for k, v in attrs.items() if k not in _CREATOR_ATTRS}
    elif lowered in {'authorscount', 'editorscount', 'creatorscount'}:
        if lowered == 'authorscount':
            raw = len(entry.authors)
        elif lowered == 'editorscount':
            raw = len(entry.editors)
        else:
            raw = len(entry.creators)
    elif lowered == 'itemtype':
        raw = entry.item_type
    elif lowered == 'attachmenttitle':
        raw = entry.extra.get('attachmentTitle', '')
    elif lowered == 'accessdate':
        raw = _format_access_date(entry.extra.get('accessDate', ''), attrs.get('timeZone', ''))
        attrs = {k: v for k, v in attrs.items() if k != 'timeZone'}
    elif lowered == 'year':
        raw = entry.year or _year_from_date(entry.date)
    else:
        raw = entry.get_field(name, '')
    return _apply_common(str(raw or ''), attrs)


def build_name(entry: LibraryEntry, template: str | None = None, max_length: int = 180) -> str:
    rendered = render_template(entry, template or DEFAULT_RENAME_TEMPLATE)
    cleaned = get_valid_file_name(rendered)
    if not cleaned:
        cleaned = get_valid_file_name(entry.title or entry.doi or entry.arxiv_id or 'Untitled')
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip(' .-_')
    return cleaned or 'Untitled'


def get_valid_file_name(value: str) -> str:
    text = unicodedata.normalize('NFC', str(value or ''))
    text = ''.join(' ' if ord(ch) < 32 else ch for ch in text)
    text = re.sub(r'[<>:"/\\|?*]+', '-', text)
    text = re.sub(r'\s+', ' ', text).strip(' .')
    text = re.sub(r'\s*[-–—]\s*[-–—]+\s*', ' - ', text)
    text = re.sub(r'\s{2,}', ' ', text).strip(' .')
    if text.casefold() in WINDOWS_RESERVED:
        text += '_'
    return text


def _parse_identifier(expr: str) -> tuple[str, dict[str, str]]:


    text = str(expr or '').strip()
    if not text:
        return '', {}
    match = re.match(r'([^\s]+)', text)
    if not match:
        return '', {}
    name = match.group(1)
    rest = text[match.end():]
    attrs: dict[str, str] = {}
    attr_re = re.compile(r"([\w-]+)\s*=+\s*(?:\"([^\"]*)\"|'([^']*)')", re.DOTALL)
    for attr in attr_re.finditer(rest):
        key = re.sub(r'-(.)', lambda m: m.group(1).upper(), attr.group(1))
        attrs[key] = attr.group(2) if attr.group(2) is not None else (attr.group(3) or '')
    return name, attrs


def _parse_string_literal(statement: str) -> str | None:
    text = str(statement or '').strip()
    if len(text) < 2 or text[0] not in {'"', "'"}:
        return None
    quote = text[0]

    end = text.find(quote, 1)
    if end != len(text) - 1:
        return None
    return text[1:end]


def _regex_flags(regex_opts: str | None) -> tuple[int, bool]:

    opts = str(regex_opts if regex_opts is not None else 'i')
    flags = 0
    if 'i' in opts:
        flags |= re.IGNORECASE
    if 'm' in opts:
        flags |= re.MULTILINE
    if 's' in opts:
        flags |= re.DOTALL
    return flags, 'g' in opts


def _js_replacement_to_python(value: str) -> str:

    token = '\x00WORKKNACKS_DOLLAR\x00'
    text = str(value or '').replace('$$', token)
    text = re.sub(r'\$(\d+)', lambda m: rf'\g<{m.group(1)}>', text)
    return text.replace(token, '$')


def _apply_common(value: str, attrs: dict[str, str]) -> str:
    result = value
    flags, global_match = _regex_flags(attrs.get('regexOpts'))
    if 'match' in attrs:
        try:
            found = re.search(attrs['match'], result, flags=flags)
        except re.error:
            found = None
        return found.group(0) if found else ''

    if 'start' in attrs:
        try:
            result = result[max(0, int(attrs['start'])):]
        except (TypeError, ValueError):
            pass


    if 'truncate' in attrs:
        try:
            result = result[:max(0, int(attrs['truncate']))]
        except (TypeError, ValueError):
            pass

    if attrs.get('trim', 'true').casefold() not in {'false', '0', 'no'}:
        result = result.strip()

    if 'replaceFrom' in attrs:
        try:
            count = 0 if global_match else 1
            replacement = _js_replacement_to_python(attrs.get('replaceTo', ''))
            result = re.sub(attrs['replaceFrom'], replacement, result, count=count, flags=flags)
        except (re.error, IndexError):
            pass

    if result:
        prefix = attrs.get('prefix', '')
        suffix = attrs.get('suffix', '')
        if prefix in {'\\', '/'}:
            prefix = ''
        if suffix in {'\\', '/'}:
            suffix = ''
        if prefix and not result.startswith(prefix):
            result = prefix + result
        if suffix and not result.endswith(suffix):
            result = result + suffix

    case = attrs.get('case', '').casefold()
    if case:
        result = _change_case(result, case)
    return result

def _change_case(value: str, case: str) -> str:
    if case == 'upper':
        return value.upper()
    if case == 'lower':
        return value.lower()
    if case == 'sentence':
        return value[:1].upper() + value[1:]
    if case == 'title':
        return value.title()
    if case in {'hyphen', 'snake'}:
        separator = '-' if case == 'hyphen' else '_'
        return re.sub(r'[^\w\u0080-\uffff]+', separator, value, flags=re.UNICODE).strip(separator).lower()
    if case in {'camel', 'pascal'}:
        words = [word for word in re.split(r'[^\w\u0080-\uffff]+', value, flags=re.UNICODE) if word]
        if not words:
            return ''
        first = words[0].lower() if case == 'camel' else words[0][:1].upper() + words[0][1:]
        return first + ''.join(word[:1].upper() + word[1:] for word in words[1:])
    return value


_CREATOR_ATTRS = {
    'max', 'join', 'name', 'namePartSeparator', 'initialize', 'initializeWith',
}


def _format_creators(creators: list[Creator], attrs: dict[str, str], language: str = '') -> str:
    if not creators:
        return ''
    selected = list(creators)
    if 'max' in attrs and attrs.get('max') != '':
        try:
            limit = int(attrs['max'])
            if limit == 0:
                selected = []
            elif limit > 0:
                selected = selected[:limit]
            else:
                selected = list(reversed(selected[limit:]))
        except ValueError:
            pass
    values = [_transform_name(creator, attrs) for creator in selected]
    values = [v for v in values if v]


    return attrs.get('join', ', ').join(values)


def _initialize_name_part(value: str, initialize: bool, initialize_with: str) -> str:
    value = value.strip()
    if not value:
        return ''
    return value[:1].upper() + initialize_with if initialize else value


def _transform_name(creator: Creator, attrs: dict[str, str]) -> str:
    family = creator.family.strip()
    given = creator.given.strip()
    mode = attrs.get('name', 'family').casefold()
    initialize = attrs.get('initialize', '').casefold()
    initialize_with = attrs.get('initializeWith', '.')
    separator = attrs.get('namePartSeparator', ' ')

    given = _initialize_name_part(given, initialize in {'full', 'given', 'first'}, initialize_with)
    family = _initialize_name_part(family, initialize in {'full', 'family', 'last'}, initialize_with)

    if mode in {'full', 'given-family', 'first-last'}:
        return separator.join(piece for piece in (given, family) if piece)
    if mode in {'full-reversed', 'family-given', 'last-first'}:
        return separator.join(piece for piece in (family, given) if piece)
    if mode in {'given', 'first'}:
        return given
    return family or given

def _evaluate_operand(entry: LibraryEntry, text: str) -> Any:
    text = text.strip()
    if text.startswith('{{') and text.endswith('}}'):
        name, attrs = _parse_identifier(text[2:-2].strip())
        return evaluate_identifier(entry, name, attrs)
    literal = _parse_string_literal(text)
    if literal is not None:
        return literal
    number = _as_number(text)
    if number is not None:
        return number
    name, attrs = _parse_identifier(text)
    return evaluate_identifier(entry, name, attrs)


def _find_top_level_operator(expression: str) -> tuple[str, str, str] | None:
    quote = ''
    depth = 0
    i = 0
    while i < len(expression):
        ch = expression[i]
        if quote:
            if ch == quote:
                quote = ''
            i += 1
            continue
        if ch in {'"', "'"}:
            quote = ch
            i += 1
            continue
        if expression.startswith('{{', i):
            depth += 1
            i += 2
            continue
        if expression.startswith('}}', i) and depth:
            depth -= 1
            i += 2
            continue
        if depth == 0:
            for operator in ('==', '!=', '<=', '>=', '<', '>'):
                if expression.startswith(operator, i):
                    return expression[:i], operator, expression[i + len(operator):]
        i += 1
    return None


def _as_number(value: Any) -> float | None:
    text = str(value).strip()
    if not re.fullmatch(r'[+-]?\d+(?:\.\d+)?', text):
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _format_access_date(value: Any, time_zone: str = '') -> str:
    text = str(value or '').strip()
    if not text or not time_zone:
        return text
    try:
        normalized = text.replace('Z', '+00:00')
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(ZoneInfo(time_zone))
    except (ValueError, ZoneInfoNotFoundError):
        return text
    timespec = 'seconds' if dt.second or re.search(r':\d{2}:\d{2}', text) else 'minutes'
    return dt.isoformat(sep=' ', timespec=timespec)


def _year_from_date(value: str) -> str:
    match = re.search(r'\b(1\d{3}|2\d{3})\b', str(value or ''))
    return match.group(1) if match and match.group(1) != '0000' else ''


def _append_safely(current: str, chunk: str) -> str:
    if not current:
        return chunk
    if not chunk:
        return current
    max_overlap = min(len(current), len(chunk), 24)
    for size in range(max_overlap, 0, -1):
        overlap = current[-size:]
        if overlap == chunk[:size] and re.fullmatch(r'[\s\W_]+', overlap, flags=re.UNICODE):
            return current + chunk[size:]
    return current + chunk
