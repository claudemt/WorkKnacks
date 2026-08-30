import re

_SENT_END = re.compile(r'[.?!](?:\s+|$)')
_NEWLINE = re.compile(r'\n')

def _best_cutoff(segment: str) -> int:

    best = 0

    for m in _SENT_END.finditer(segment):
        best = m.end()

    if best < len(segment) * 0.5:
        for m in _NEWLINE.finditer(segment):
            if m.end() > len(segment) * 0.5:
                best = m.end()
                break

    if best < len(segment) * 0.5:
        last_space = segment.rfind(' ')
        if last_space > len(segment) * 0.5:
            best = last_space + 1

    return best

class TextChunker:

    def __init__(self, max_chars: int = 1350):
        self.max_chars = max_chars

    def chunk(self, text: str) -> list[str]:

        if not text.strip():
            return []
        if len(text) <= self.max_chars:
            return [text]

        chunks = []
        remaining = text

        while len(remaining) > self.max_chars:
            segment = remaining[:self.max_chars]
            cutoff = _best_cutoff(segment) or self.max_chars
            piece = remaining[:cutoff].strip()
            if piece:
                chunks.append(piece)
            remaining = remaining[cutoff:].lstrip()

        if remaining.strip():
            chunks.append(remaining.strip())
        return chunks


