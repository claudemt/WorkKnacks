import re

GLOSSARY = [
    ('库伦', '库仑'),
    ('洛仑兹', '洛伦兹'),
    ('勒让德尔', '勒让德'),
    ('贝赛尔', '贝塞尔'),
]

RECURSE_COMMANDS = {
    'chapter', 'part', 'section', 'subsection', 'subsubsection',
    'caption', 'text', 'textbf', 'textit', 'emph', 'textrm', 'textsf',
    'underline', 'mbox', 'makebox', 'plainunnumberedchapter', 'unnumberedchapter',
    'title', 'author', 'date',
}

PROTECTED_COMMANDS = {
    'label', 'ref', 'eqref', 'cite', 'pageref', 'includegraphics', 'input',
    'setcounter', 'addtocounter', 'index', 'indexitem', 'url', 'href',
    'hspace', 'vspace', 'rule', 'BookEnglishMetadata', 'BookMetadata',
    'begin', 'end', 'item',
}

MATH_ENVS = {
    'equation', 'equation*', 'aligned', 'array', 'primeequation',
    'gather', 'gather*', 'align', 'align*', 'multline', 'displaymath',
    'math', 'split', 'cases', 'eqnarray', 'eqnarray*', 'subequations',
}

PROTECTED_ENVS = {
    'verbatim', 'Verbatim', 'verbatim*', 'lstlisting', 'lstlisting*',
    'minted', 'alltt', 'comment', 'filecontents', 'filecontents*', 'thebibliography',
}

KEEP_CHARS = set('&#~^_')

def is_escaped(s: str, j: int) -> bool:

    bs = 0
    k = j - 1
    while k >= 0 and s[k] == '\\':
        bs += 1
        k -= 1
    return bs % 2 == 1

def parse_balanced(s: str, i: int, open_ch: str, close_ch: str):

    depth, j = 0, i
    while j < len(s):
        c = s[j]
        if c in (open_ch, close_ch) and not is_escaped(s, j):
            if c == open_ch:
                depth += 1
            elif c == close_ch:
                depth -= 1
                if depth == 0:
                    return s[i + 1:j], j + 1
        j += 1
    return s[i + 1:], len(s)

def read_math_env(s: str, i: int):

    m = re.match(r'\\(begin)\s*\{([^}]+)\}', s[i:])
    name = m.group(2).strip()
    depth, j = 0, i
    pat = re.compile(r'\\(begin|end)\s*\{' + re.escape(name) + r'\}')
    while j < len(s):
        m2 = pat.search(s, j)
        if not m2:
            return s[i:], len(s)
        if m2.group(1) == 'begin':
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return s[i:m2.end()], m2.end()
        j = m2.end()
    return s[i:], len(s)

def tokenize(s: str):

    out, buf, i, n = [], [], 0, len(s)

    def flush():
        if buf:
            out.append(('text', ''.join(buf)))
            buf.clear()

    def keep(k):
        flush()
        out.append(('keep', k))

    def scan_group(j):

        inner, end = parse_balanced(s, j, '{', '}')
        return scan(inner, 0, len(inner)), end

    def scan(t, a, b):
        toks, buf2 = [], []
        j = a

        def fl():
            if buf2:
                toks.append(('text', ''.join(buf2)))
                buf2.clear()

        while j < b:
            c = t[j]
            if c == '%' and not is_escaped(t, j):
                fl()
                e = t.find('\n', j)
                e = b if e < 0 else e
                toks.append(('keep', t[j:e]))
                j = e
            elif c in '\r\n':
                fl()
                toks.append(('keep', c))
                j += 1
            elif c == '$' and not is_escaped(t, j):
                fl()
                if j + 1 < b and t[j + 1] == '$':
                    e = t.find('$$', j + 2)
                    e = b if e < 0 else e + 2
                    toks.append(('keep', t[j:e]))
                    j = e
                else:
                    e = t.find('$', j + 1)
                    e = b if e < 0 else e + 1
                    toks.append(('keep', t[j:e]))
                    j = e
            elif c == '\\':
                fl()
                if j + 1 >= b:
                    toks.append(('keep', '\\'))
                    j += 1
                elif t[j + 1] == '\\':
                    toks.append(('keep', '\\\\'))
                    j += 2
                elif t[j + 1] in '([':

                    close = ')' if t[j + 1] == '(' else ']'
                    e = t.find('\\' + close, j + 2)
                    if e < 0:
                        e = t.find('\n', j)
                        e = b if e < 0 else e
                        toks.append(('keep', t[j:e]))
                        j = e
                    else:
                        toks.append(('keep', t[j:e + 2]))
                        j = e + 2
                elif not t[j + 1].isalpha():
                    toks.append(('keep', t[j:j + 2]))
                    j += 2
                else:
                    begin_pos = j
                    m = re.match(r'\\([a-zA-Z]+)(\*?)', t[j:])
                    name, star = m.group(1), m.group(2)
                    cmd_tok = '\\' + name + star
                    j += m.end()

                    def ws():

                        nonlocal j
                        k = j
                        while k < b and t[k] in ' \t':
                            k += 1
                        w = t[j:k]
                        j = k
                        return w

                    if name == 'begin' and not star:
                        g0 = j
                        g, j = parse_balanced(t, j, '{', '}')
                        keep_tok = ['\\begin', t[g0:j]]

                        while j < b and t[j] in '[{':
                            if t[j] == '[':
                                raw, j = parse_balanced(t, j, '[', ']')
                                keep_tok.append('[' + raw + ']')
                            else:
                                raw, j = parse_balanced(t, j, '{', '}')
                                keep_tok.append('{' + raw + '}')
                        if g.strip() in MATH_ENVS or g.strip() in PROTECTED_ENVS:
                            raw, j = read_math_env(t, begin_pos)
                            keep_tok = [raw]
                        toks.append(('keep', ''.join(keep_tok)))
                    elif name == 'addcontentsline':
                        w1 = ws()
                        g1, j = parse_balanced(t, j, '{', '}')
                        w2 = ws()
                        g2, j = parse_balanced(t, j, '{', '}')
                        toks.append(('keep', cmd_tok + w1 + '{' + g1 + '}' + w2 + '{' + g2 + '}'))
                        w3 = ws()
                        toks.append(('keep', w3 + '{'))
                        gt, j = scan_group(j)
                        toks.extend(gt)
                        toks.append(('keep', '}'))
                    elif name in RECURSE_COMMANDS:

                        opt = ''
                        if j < b and t[j] == '[':
                            raw, j = parse_balanced(t, j, '[', ']')
                            opt = '[' + raw + ']'
                        w1 = ws()
                        toks.append(('keep', cmd_tok + opt + w1))
                        w2 = ws()
                        toks.append(('keep', w2 + '{'))
                        gt, j = scan_group(j)
                        toks.extend(gt)
                        toks.append(('keep', '}'))
                    elif name in ('verb', 'lstinline'):
                        
                        if j < b and not t[j].isspace():
                            delim = t[j]
                            e = t.find(delim, j + 1)
                            if e < 0:
                                e = b
                            else:
                                e += 1
                            toks.append(('keep', cmd_tok + t[j:e]))
                            j = e
                        else:
                            toks.append(('keep', cmd_tok))
                    elif name in PROTECTED_COMMANDS:
                        opt = ''
                        if j < b and t[j] == '[':
                            raw, j = parse_balanced(t, j, '[', ']')
                            opt = '[' + raw + ']'
                        w1 = ws()
                        rest = ''
                        if j < b and t[j] == '{':
                            raw, j = parse_balanced(t, j, '{', '}')
                            rest = '{' + raw + '}'
                        toks.append(('keep', cmd_tok + opt + w1 + rest))
                    else:

                        opt = ''
                        if j < b and t[j] == '[':
                            raw, j = parse_balanced(t, j, '[', ']')
                            opt = '[' + raw + ']'
                        w1 = ws()
                        rest = ''
                        if j < b and t[j] == '{':
                            raw, j = parse_balanced(t, j, '{', '}')
                            rest = '{' + raw + '}'
                        toks.append(('keep', cmd_tok + opt + w1 + rest))
            elif c in KEEP_CHARS or c in '{}':
                fl()
                toks.append(('keep', c))
                j += 1
            else:
                buf2.append(c)
                j += 1
        fl()
        return toks

    out.extend(scan(s, 0, n))
    flush()
    return out

def split_long_token(tok: str, limit: int):

    if len(tok) <= limit:
        return [tok]
    parts, cur = [], ''
    for seg in re.split(r'(?<=[.!?])\s+', tok):
        if cur and len(cur) + len(seg) + 1 > limit:
            parts.append(cur)
            cur = seg
        else:
            cur = (cur + ' ' + seg) if cur else seg
    if cur:
        parts.append(cur)
    out = []
    for p in parts:
        while len(p) > limit:
            out.append(p[:limit])
            p = p[limit:]
        out.append(p)
    return out

def build_chunks(tokens, chunk_max: int = 1350):

    text_idx = [i for i, (k, _) in enumerate(tokens) if k == 'text']
    flat = []
    for idx in text_idx:
        for tk in split_long_token(tokens[idx][1], chunk_max):
            flat.append((idx, tk))
    chunks, cur, curlen = [], [], 0
    for idx, tk in flat:
        l = len(tk) + 1
        if cur and curlen + l > chunk_max:
            chunks.append(cur)
            cur = []
            curlen = 0
        cur.append((idx, tk))
        curlen += l
    if cur:
        chunks.append(cur)
    return [{'start': c[0][0], 'end': c[-1][0], 'pieces': c} for c in chunks]

def assemble(tokens, chunks, trans_map, name: str = ''):

    out = []
    for i, (kind, content) in enumerate(tokens):
        if kind == 'keep':
            out.append(content)
            continue

        trans = None
        for ci, ch in enumerate(chunks):
            if ch['start'] <= i <= ch['end']:
                trans = trans_map.get(ci)
                if trans is None:

                    out.append(content)
                    trans = 'skip'
                    break
                if trans == 'skip':
                    break
                pieces = ch['pieces']

                parts = trans.split('\n')
                if len(parts) == len(pieces):

                    for k, (pi, pt) in enumerate(pieces):
                        if pi == i:
                            out.append(parts[k])
                            break
                else:
                    if i == ch['start']:
                        out.append(trans)
                break
        if trans is None:
            out.append(content)
    return ''.join(out)

def keep_tokens(tokens):

    return [t for t in tokens if t[0] == 'keep']

def text_tokens(tokens):

    return [t for t in tokens if t[0] == 'text']

_MD_IMAGE = re.compile(r'!\[[^\]]*\]\([^)]+\)')
_MD_LINK = re.compile(r'\[[^\]]*\]\([^)]+\)')
_MD_TAG = re.compile(r'<(sup|sub)>[^<]*</\1>', re.I)

def tokenize_markdown(s: str):
    

    n = len(s)
    tokens = []
    buf = []
    i = 0

    def flush():
        if buf:
            tokens.append(('text', ''.join(buf)))
            buf.clear()

    def scan_fence(i: int) -> int:
        marker = s[i:i + 3]
        j = s.find('\n', i)
        if j < 0:
            return n
        j += 1
        while j < n:
            line_end = s.find('\n', j)
            line_end = line_end if line_end >= 0 else n
            line = s[j:line_end]
            if line.strip() == marker:
                return line_end + 1 if line_end < n else n
            j = line_end + 1 if line_end < n else n
        return n

    while i < n:
        c = s[i]
        if c == '\n':
            flush()
            tokens.append(('keep', '\n'))
            i += 1
        elif s.startswith('```', i) or s.startswith('~~~', i):
            flush()
            end = scan_fence(i)
            tokens.append(('keep', s[i:end]))
            i = end
        elif s.startswith('$$', i):
            
            
            e = s.find('$$', i + 2)
            if e < 0:
                buf.append('$')
                i += 1
            elif '\n' not in s[i:e] and e - i > 500:
                buf.append('$')
                i += 1
            else:
                flush()
                tokens.append(('keep', s[i:e + 2]))
                i = e + 2
        elif c == '$':
            
            line_end = s.find('\n', i)
            line_end = line_end if line_end >= 0 else n
            e = s.find('$', i + 1, line_end)
            if e < 0:
                buf.append(c)
                i += 1
            else:
                flush()
                tokens.append(('keep', s[i:e + 1]))
                i = e + 1
        elif c == '`':
            
            line_end = s.find('\n', i)
            line_end = line_end if line_end >= 0 else n
            e = s.find('`', i + 1, line_end)
            if e < 0:
                buf.append(c)
                i += 1
            else:
                flush()
                tokens.append(('keep', s[i:e + 1]))
                i = e + 1
        elif s.startswith('![', i):
            m = _MD_IMAGE.match(s, i)
            if m:
                flush()
                tokens.append(('keep', m.group(0)))
                i = m.end()
            else:
                buf.append(c)
                i += 1
        elif c == '[':
            m = _MD_LINK.match(s, i)
            if m:
                flush()
                tokens.append(('keep', m.group(0)))
                i = m.end()
            else:
                buf.append(c)
                i += 1
        elif c == '<':
            m = _MD_TAG.match(s, i)
            if m:
                flush()
                tokens.append(('keep', m.group(0)))
                i = m.end()
            else:
                buf.append(c)
                i += 1
        else:
            buf.append(c)
            i += 1

    flush()
    return tokens

