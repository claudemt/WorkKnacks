import html
import re
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..core.runtime import runtime_dir

ROOT = Path(__file__).resolve().parent.parent.parent
DOCS_ROOT = ROOT / 'src' / 'docs'
HTML_DIR = runtime_dir() / 'docs'
_server = None
_server_lock = threading.Lock()

_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{ font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
         max-width: 860px; margin: 40px auto; padding: 0 24px;
         line-height: 1.7; color: #24292f; }}
  h1 {{ border-bottom: 1px solid #d8dee4; padding-bottom: 10px; }}
  h2 {{ margin-top: 32px; }}
  code {{ background: #f6f8fa; padding: 2px 6px; border-radius: 4px;
          font-family: Consolas, monospace; font-size: 0.92em; }}
  pre {{ background: #f6f8fa; padding: 14px; border-radius: 6px; overflow-x: auto; }}
  pre code {{ background: none; padding: 0; }}
  table {{ border-collapse: collapse; }}
  th, td {{ border: 1px solid #d8dee4; padding: 6px 12px; }}
  th {{ background: #f6f8fa; }}
  blockquote {{ border-left: 4px solid #d8dee4; margin-left: 0;
                padding-left: 16px; color: #57606a; }}
  a {{ color: #0969da; }}
</style>
</head>
<body>
{body}
<hr>
<p style="color:#8b949e;font-size:0.85em">由 WorkKnacks 文档浏览器渲染 · <a href="{back}">返回索引</a></p>
</body>
</html>
"""

def _md_to_html(md_text: str) -> str:

    try:
        import markdown as md_lib
        return md_lib.markdown(md_text, extensions=['tables', 'fenced_code'])
    except ImportError:

        out = []
        in_code = False
        for line in md_text.split('\n'):
            if line.startswith('```'):
                in_code = not in_code
                out.append('<pre>' if in_code else '</pre>')
                continue
            if in_code:
                out.append(html.escape(line))
                continue
            if line.startswith('# '):
                out.append(f'<h1>{html.escape(line[2:])}</h1>')
            elif line.startswith('## '):
                out.append(f'<h2>{html.escape(line[3:])}</h2>')
            elif line.startswith('### '):
                out.append(f'<h3>{html.escape(line[4:])}</h3>')
            elif line.startswith('- '):
                item = html.escape(line[2:])
                item = re.sub(
                    r'\[([^\]]+)\]\(([^)]+)\)',
                    r'<a href="\2">\1</a>',
                    item,
                )
                out.append(f'<li>{item}</li>')
            elif line.strip():
                paragraph = html.escape(line)
                paragraph = re.sub(
                    r'\[([^\]]+)\]\(([^)]+)\)',
                    r'<a href="\2">\1</a>',
                    paragraph,
                )
                out.append(f'<p>{paragraph}</p>')
        return '\n'.join(out)

def _rewrite_doc_links(html_text: str) -> str:
    return re.sub(
        r'href="([^"]+)\.md(\#[^"]*)?"',
        lambda m: f'href="{m.group(1)}.html{m.group(2) or ""}"',
        html_text,
    )

def _render_page(md_path: Path) -> str:

    md_text = md_path.read_text(encoding='utf-8')
    body = _md_to_html(md_text)
    title = md_text.split('\n', 1)[0].lstrip('# ').strip() or md_path.stem
    html = _PAGE_TEMPLATE.format(title=title, body=body, back='index.html')
    html = _rewrite_doc_links(html)
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    out = HTML_DIR / f'{md_path.stem}.html'
    out.write_text(html, encoding='utf-8')
    return str(out)

def render_all_docs() -> list[str]:
    rendered = []
    if not DOCS_ROOT.exists():
        return rendered
    for md_path in sorted(DOCS_ROOT.glob('*.md')):
        rendered.append(_render_page(md_path))
    return rendered


def _serve_docs() -> str:
    global _server
    with _server_lock:
        if _server is None:
            HTML_DIR.mkdir(parents=True, exist_ok=True)
            handler = lambda *args, **kwargs: SimpleHTTPRequestHandler(
                *args,
                directory=str(HTML_DIR),
                **kwargs,
            )
            _server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
            thread = threading.Thread(
                target=_server.serve_forever,
                name='workknacks-docs',
                daemon=True,
            )
            thread.start()
        return f'http://127.0.0.1:{_server.server_port}'

def open_docs(doc_name: str = 'index'):

    path = DOCS_ROOT / f'{doc_name}.md'
    if not path.exists():
        path = DOCS_ROOT / 'index.md'
    if not path.exists():
        return False
    render_all_docs()
    _render_page(path)
    webbrowser.open(f'{_serve_docs()}/{path.stem}.html')
    return True


