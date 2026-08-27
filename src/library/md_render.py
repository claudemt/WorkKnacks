from __future__ import annotations

import html
import re
from pathlib import Path


BASE_CSS = r'''
:root { color-scheme: light dark; }
body { max-width: 980px; margin: 0 auto; padding: 42px 48px 80px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei UI", sans-serif; line-height: 1.72; }
img { max-width: 100%; height: auto; }
pre { overflow-x: auto; padding: 14px 16px; border-radius: 8px; background: rgba(127,127,127,.12); }
code { font-family: "Cascadia Code", Consolas, monospace; }
:not(pre) > code { padding: .12em .35em; border-radius: 4px; background: rgba(127,127,127,.12); }
blockquote { margin-left: 0; padding-left: 1rem; border-left: 4px solid #888; opacity: .9; }
table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
th, td { border: 1px solid #9996; padding: .5rem .65rem; text-align: left; }
a { text-decoration: none; } a:hover { text-decoration: underline; }
hr { border: 0; border-top: 1px solid #9996; margin: 2rem 0; }
'''


MATHJAX = r'''
<script>
window.MathJax = {
  tex: {inlineMath: [['$', '$'], ['\\(', '\\)']], displayMath: [['$$','$$'], ['\\[','\\]']]},
  options: {skipHtmlTags: ['script','noscript','style','textarea','pre','code']}
};
</script>
<script defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
'''


HIGHLIGHT = r'''
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/highlight.js@11.10.0/styles/github.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/highlight.js@11.10.0/lib/common.min.js" onload="document.querySelectorAll('pre code').forEach(el => hljs.highlightElement(el))"></script>
'''


def markdown_to_fragment(text: str) -> str:
    
    try:
        import markdown  
        return markdown.markdown(
            text,
            extensions=['extra', 'fenced_code', 'tables', 'sane_lists'],
            output_format='html5',
        )
    except Exception:
        return _fallback_markdown(text)


def md_to_html(text: str, *, title: str = 'Markdown', base_href: str = '', include_mathjax: bool = True, include_highlight: bool = True) -> str:
    fragment = markdown_to_fragment(text)
    base = f'<base href="{html.escape(base_href, quote=True)}">' if base_href else ''
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
{base}
<style>{BASE_CSS}</style>
{HIGHLIGHT if include_highlight else ''}
{MATHJAX if include_mathjax else ''}
</head>
<body>
<article class="markdown-body">{fragment}</article>
</body>
</html>'''


def md_file_to_html(path: str | Path) -> str:
    file_path = Path(path).expanduser().resolve()
    text = file_path.read_text(encoding='utf-8', errors='replace')
    return md_to_html(text, title=file_path.name, base_href=file_path.parent.as_uri() + '/')


def _fallback_markdown(text: str) -> str:
    
    lines = str(text or '').splitlines()
    out: list[str] = []
    paragraph: list[str] = []
    in_code = False
    code_lang = ''
    code_lines: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            content = ' '.join(part.strip() for part in paragraph)
            out.append(f'<p>{_inline(content)}</p>')
            paragraph = []

    for line in lines:
        if line.startswith('```'):
            if in_code:
                out.append(f'<pre><code class="language-{html.escape(code_lang)}">{html.escape(chr(10).join(code_lines))}</code></pre>')
                in_code = False
                code_lang = ''
                code_lines = []
            else:
                flush_paragraph()
                in_code = True
                code_lang = line[3:].strip()
            continue
        if in_code:
            code_lines.append(line)
            continue
        if not line.strip():
            flush_paragraph()
            continue
        heading = re.match(r'^(#{1,6})\s+(.*)$', line)
        if heading:
            flush_paragraph()
            level = len(heading.group(1))
            out.append(f'<h{level}>{_inline(heading.group(2))}</h{level}>')
            continue
        if line.startswith('> '):
            flush_paragraph()
            out.append(f'<blockquote>{_inline(line[2:])}</blockquote>')
            continue
        if re.match(r'^[-*+]\s+', line):
            flush_paragraph()
            
            out.append(f'<li>{_inline(re.sub(r"^[-*+]\\s+", "", line))}</li>')
            continue
        paragraph.append(line)
    flush_paragraph()
    if in_code:
        out.append(f'<pre><code class="language-{html.escape(code_lang)}">{html.escape(chr(10).join(code_lines))}</code></pre>')
    joined = '\n'.join(out)
    joined = re.sub(r'(?s)(?:<li>.*?</li>\n?)+', lambda m: '<ul>\n' + m.group(0) + '\n</ul>', joined)
    return joined


def _inline(value: str) -> str:
    escaped = html.escape(value)
    escaped = re.sub(r'`([^`]+)`', r'<code>\1</code>', escaped)
    escaped = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', escaped)
    escaped = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<em>\1</em>', escaped)
    escaped = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', escaped)
    return escaped
