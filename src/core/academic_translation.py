from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterable


_PLACEHOLDER_RE = re.compile(r'\[\[WK_KEEP_\d{6}\]\]')
_WORD_RE = re.compile(r'[A-Za-z\u00C0-\u024F\u0370-\u03FF\u0400-\u04FF\u4e00-\u9fff]')
_MATH_ENV_RE = re.compile(
    r'\\begin\{(equation\*?|align\*?|aligned|gather\*?|multline\*?|split|cases|eqnarray\*?|displaymath)\}'
    r'.*?\\end\{\1\}',
    re.S,
)
_ABBREVIATIONS = {
    'eq.', 'eqs.', 'fig.', 'figs.', 'ref.', 'refs.', 'sec.', 'secs.', 'app.',
    'al.', 'et al.', 'i.e.', 'e.g.', 'cf.', 'vs.', 'approx.', 'dr.', 'prof.',
    'no.', 'nos.', 'vol.', 'resp.',
}


@dataclass(frozen=True, slots=True)
class ProtectedSpan:
    token: str
    text: str
    kind: str


@dataclass(frozen=True, slots=True)
class TranslationSegment:
    text: str
    translatable: bool

    @property
    def chars(self) -> int:
        return len(_PLACEHOLDER_RE.sub('', self.text))


@dataclass(slots=True)
class AcademicMarkdownPlan:
    source: str
    protected_text: str
    spans: dict[str, ProtectedSpan]
    segments: list[TranslationSegment]

    @classmethod
    def build(cls, source: str, max_chars: int = 1350) -> 'AcademicMarkdownPlan':
        protected, spans = protect_scientific_markdown(source)
        segments = _build_segments(protected, max(160, int(max_chars or 1350)))
        return cls(source=source, protected_text=protected, spans=spans, segments=segments)

    @property
    def translatable_segments(self) -> list[TranslationSegment]:
        return [segment for segment in self.segments if segment.translatable]

    def restore(self, text: str) -> str:
        result = text


        for token, span in self.spans.items():
            result = result.replace(token, span.text)
        return result

    def render(self, translated: Iterable[str]) -> str:
        iterator = iter(translated)
        parts: list[str] = []
        for segment in self.segments:
            parts.append(next(iterator) if segment.translatable else segment.text)
        return self.restore(''.join(parts))


@dataclass(slots=True)
class AcademicLatexPlan:


    source: str
    protected_text: str
    spans: dict[str, ProtectedSpan]
    segments: list[TranslationSegment]

    @classmethod
    def build(cls, source: str, max_chars: int = 1350) -> 'AcademicLatexPlan':


        from .tokenizer import tokenize

        spans: dict[str, ProtectedSpan] = {}
        parts: list[str] = []
        counter = 0
        display_tokens: list[str] = []
        for kind, raw in tokenize(str(source or '')):
            if kind == 'text' or raw in {'\n', '\r'}:
                parts.append(raw)
                continue
            token = f'[[WK_KEEP_{counter:06d}]]'
            counter += 1
            span_kind = 'latex'
            stripped = raw.lstrip()
            if (
                stripped.startswith('\\begin{equation')
                or stripped.startswith('\\begin{align')
                or stripped.startswith('\\begin{gather')
                or stripped.startswith('\\begin{multline')
                or stripped.startswith('\\[')
                or stripped.startswith('$$')
            ):
                span_kind = 'display-math'
                display_tokens.append(token)
            spans[token] = ProtectedSpan(token, raw, span_kind)
            parts.append(token)

        protected = ''.join(parts)


        for token in display_tokens:
            pattern = re.compile(
                r'(?P<left>\n[ \t]*\n+)(?P<indent>[ \t]*)'
                + re.escape(token)
                + r'(?P<trail>[ \t]*)(?P<right>\n[ \t]*\n+)'
            )
            def bridge(match: re.Match[str], formula_token: str = token) -> str:
                nonlocal counter
                left_token = f'[[WK_KEEP_{counter:06d}]]'; counter += 1
                right_token = f'[[WK_KEEP_{counter:06d}]]'; counter += 1
                spans[left_token] = ProtectedSpan(left_token, match.group('left'), 'equation-gap')
                spans[right_token] = ProtectedSpan(right_token, match.group('right'), 'equation-gap')
                return left_token + match.group('indent') + formula_token + match.group('trail') + right_token
            protected = pattern.sub(bridge, protected)

        segments = _build_segments(protected, max(160, int(max_chars or 1350)))
        return cls(source=str(source or ''), protected_text=protected, spans=spans, segments=segments)

    @property
    def translatable_segments(self) -> list[TranslationSegment]:
        return [segment for segment in self.segments if segment.translatable]

    def restore(self, text: str) -> str:
        result = str(text or '')
        for token, span in self.spans.items():
            result = result.replace(token, span.text)
        return result

    def render(self, translated: Iterable[str]) -> str:
        iterator = iter(translated)
        parts: list[str] = []
        for segment in self.segments:
            parts.append(next(iterator) if segment.translatable else segment.text)
        return self.restore(''.join(parts))


def protect_scientific_markdown(source: str) -> tuple[str, dict[str, ProtectedSpan]]:


    text = str(source or '')
    spans: dict[str, ProtectedSpan] = {}
    counter = 0

    def stash(raw: str, kind: str) -> str:
        nonlocal counter
        token = f'[[WK_KEEP_{counter:06d}]]'
        counter += 1
        spans[token] = ProtectedSpan(token, raw, kind)
        return token


    text = _protect_fenced_code(text, stash)


    text = _protect_reference_sections(text, stash)

    replacements: list[tuple[re.Pattern[str], str]] = [
        (_MATH_ENV_RE, 'display-math'),
        (re.compile(r'\$\$.*?\$\$', re.S), 'display-math'),
        (re.compile(r'\\\[.*?\\\]', re.S), 'display-math'),
        (re.compile(r'\\\(.*?\\\)', re.S), 'inline-math'),
        (re.compile(r'(?<!\\)\$(?!\$)(?:\\.|[^$\n])+?(?<!\\)\$'), 'inline-math'),
        (re.compile(r'`[^`\n]+`'), 'inline-code'),
        (re.compile(r'!\[[^\]\n]*\]\([^\n)]+\)'), 'image'),
        (re.compile(r'\\(?:cite\w*|ref|eqref|label|autoref|cref|Cref)\s*\{[^{}]*\}'), 'citation'),
        (re.compile(r'\[@[^\]\n]+\]'), 'citation'),
        (re.compile(r'\b10\.\d{4,9}/[-._;()/:A-Z0-9]+', re.I), 'doi'),
        (re.compile(r'\b(?:arXiv\s*:\s*)?(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?\b', re.I), 'arxiv'),
        (re.compile(r'<[^>\n]+>'), 'html-tag'),
    ]
    for pattern, kind in replacements:
        text = pattern.sub(lambda m, k=kind: stash(m.group(0), k), text)


    display_tokens = [token for token, span in list(spans.items()) if span.kind == 'display-math']
    for token in display_tokens:
        pattern = re.compile(
            r'(?P<left>\n[ \t]*\n+)(?P<indent>[ \t]*)'
            + re.escape(token)
            + r'(?P<trail>[ \t]*)(?P<right>\n[ \t]*\n+)'
        )
        def bridge(match, formula_token=token):
            left = stash(match.group('left'), 'equation-gap')
            right = stash(match.group('right'), 'equation-gap')
            return left + match.group('indent') + formula_token + match.group('trail') + right
        text = pattern.sub(bridge, text)


    link_url = re.compile(r'(\[[^\]\n]+\]\()([^\s)]+)(\))')
    text = link_url.sub(lambda m: m.group(1) + stash(m.group(2), 'url') + m.group(3), text)


    text = _protect_table_pipes(text, stash)


    prefix = re.compile(r'(?m)^([ \t]*(?:#{1,6}[ \t]+|>[ \t]*|[-+*][ \t]+|\d+[.)][ \t]+))')
    text = prefix.sub(lambda m: stash(m.group(1), 'markdown-prefix'), text)
    return text, spans


def translate_segment_preserving_tokens(
    segment: TranslationSegment,
    translate: Callable[[str], str],
) -> str:


    if not segment.translatable:
        return segment.text
    source = segment.text
    expected = _PLACEHOLDER_RE.findall(source)
    output = translate(source)
    if _tokens_intact(output, expected):
        return output

    parts = re.split(f'({_PLACEHOLDER_RE.pattern})', source)
    rendered: list[str] = []
    for part in parts:
        if not part:
            continue
        if _PLACEHOLDER_RE.fullmatch(part):
            rendered.append(part)
        elif _has_prose(part):
            rendered.append(translate(part))
        else:
            rendered.append(part)
    return ''.join(rendered)


def _tokens_intact(output: str, expected: list[str]) -> bool:
    found = _PLACEHOLDER_RE.findall(str(output or ''))
    return len(found) == len(expected) and sorted(found) == sorted(expected)


def _protect_fenced_code(text: str, stash: Callable[[str, str], str]) -> str:
    lines = text.splitlines(keepends=True)
    output: list[str] = []
    i = 0
    while i < len(lines):
        match = re.match(r'^[ \t]*(`{3,}|~{3,})', lines[i])
        if not match:
            output.append(lines[i])
            i += 1
            continue
        marker = match.group(1)
        block = [lines[i]]
        i += 1
        while i < len(lines):
            block.append(lines[i])
            if re.match(r'^[ \t]*' + re.escape(marker[0]) + r'{' + str(len(marker)) + r',}[ \t]*(?:\r?\n)?$', lines[i]):
                i += 1
                break
            i += 1
        output.append(stash(''.join(block), 'code-fence'))
    return ''.join(output)


def _protect_reference_sections(text: str, stash: Callable[[str, str], str]) -> str:
    pattern = re.compile(
        r'(?ims)^(?P<head>#{1,6}[ \t]+(?:references|bibliography|参考文献)[ \t]*\n)'
        r'(?P<body>.*?)(?=^#{1,6}[ \t]+|\Z)'
    )

    def replace(match: re.Match[str]) -> str:
        body = match.group('body')
        return match.group('head') + (stash(body, 'bibliography') if body else '')

    return pattern.sub(replace, text)


def _protect_table_pipes(text: str, stash: Callable[[str, str], str]) -> str:
    lines = text.splitlines(keepends=True)
    rendered: list[str] = []
    for line in lines:
        body = line.rstrip('\r\n')
        newline = line[len(body):]
        stripped = body.strip()


        if stripped.startswith('|') and stripped.endswith('|') and stripped.count('|') >= 3:
            pieces = body.split('|')
            rebuilt: list[str] = []
            for idx, piece in enumerate(pieces):
                if idx:
                    rebuilt.append(stash('|', 'table-pipe'))
                rebuilt.append(piece)
            body = ''.join(rebuilt)
        rendered.append(body + newline)
    return ''.join(rendered)


def _build_segments(text: str, max_chars: int) -> list[TranslationSegment]:


    pieces = re.split(r'(\n[ \t]*\n+)', text)
    segments: list[TranslationSegment] = []
    for piece in pieces:
        if not piece:
            continue
        if re.fullmatch(r'\n[ \t]*\n+', piece):
            segments.append(TranslationSegment(piece, False))
            continue
        if not _has_prose(piece):
            segments.append(TranslationSegment(piece, False))
            continue
        for sub in _split_long_block(piece, max_chars):
            segments.append(TranslationSegment(sub, _has_prose(sub)))
    return segments


def _has_prose(text: str) -> bool:
    stripped = _PLACEHOLDER_RE.sub('', str(text or ''))
    stripped = re.sub(r'[|:#>*_~\-+=`\[\](){}\\/\d.,;!?%\s]+', '', stripped)
    return bool(_WORD_RE.search(stripped))


def _split_long_block(block: str, max_chars: int) -> list[str]:
    if len(block) <= max_chars:
        return [block]
    out: list[str] = []
    rest = block
    while len(rest) > max_chars:
        window = rest[:max_chars]
        cutoff = _best_scientific_cutoff(window)
        cutoff = _avoid_placeholder_cut(rest, cutoff)
        if cutoff <= 0:
            cutoff = _avoid_placeholder_cut(rest, max_chars)
        out.append(rest[:cutoff])
        rest = rest[cutoff:]
    if rest:
        out.append(rest)
    return out


def _best_scientific_cutoff(window: str) -> int:
    floor = max(1, int(len(window) * 0.52))


    line = window.rfind('\n', floor)
    if line >= floor:
        return line + 1

    best = 0
    for match in re.finditer(r'[.!?](?:["\'”’)]*)\s+', window):
        end = match.end()
        if end < floor:
            continue
        punct = match.start()
        if _looks_like_nonterminal_period(window, punct):
            continue
        best = end
    if best:
        return best

    for sep in ('; ', ': ', ', '):
        pos = window.rfind(sep, floor)
        if pos >= floor:
            return pos + len(sep)
    space = window.rfind(' ', floor)
    return space + 1 if space >= floor else len(window)


def _looks_like_nonterminal_period(text: str, punct_index: int) -> bool:
    if text[punct_index] != '.':
        return False
    if punct_index > 0 and punct_index + 1 < len(text):
        if text[punct_index - 1].isdigit() and text[punct_index + 1].isdigit():
            return True
    prefix = text[max(0, punct_index - 14):punct_index + 1].casefold()
    if any(prefix.endswith(item) for item in _ABBREVIATIONS):
        return True


    match = re.search(r'([A-Za-z])\.$', prefix)
    if match:
        tail = text[punct_index + 1:].lstrip()
        if tail[:1] and (tail[0].islower() or tail[0] in '(),;:='):
            return True
    return False


def _avoid_placeholder_cut(text: str, cutoff: int) -> int:
    cutoff = min(max(1, cutoff), len(text))
    left = text.rfind('[[WK_KEEP_', 0, cutoff)
    if left < 0:
        return cutoff
    close = text.find(']]', left)
    if close >= cutoff:
        return left if left > 0 else min(len(text), close + 2)
    return cutoff
