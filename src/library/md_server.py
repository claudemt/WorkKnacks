from __future__ import annotations

import html
import json
import secrets
import threading
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .md_render import BASE_CSS, HIGHLIGHT, MATHJAX, markdown_to_fragment, md_file_to_html


class MarkdownServer:
    

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.token = secrets.token_urlsafe(24)
        self.httpd: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        if not self.httpd:
            return ''
        host, port = self.httpd.server_address[:2]
        return f'http://{host}:{port}'

    def start(self) -> 'MarkdownServer':
        if self.httpd:
            return self
        handler = self._make_handler()
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True, name='WorkKnacksMarkdownServer')
        self.thread.start()
        return self

    def stop(self) -> None:
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
        self.httpd = None
        self.thread = None

    def view_url(self, path: str | Path) -> str:
        rel = self._relative(path)
        return f'{self.base_url}/view?path={urllib.parse.quote(rel)}'

    def edit_url(self, path: str | Path) -> str:
        rel = self._relative(path)
        return f'{self.base_url}/edit?path={urllib.parse.quote(rel)}&token={urllib.parse.quote(self.token)}'

    def open_view(self, path: str | Path) -> str:
        self.start()
        url = self.view_url(path)
        webbrowser.open(url)
        return url

    def open_edit(self, path: str | Path) -> str:
        self.start()
        url = self.edit_url(path)
        webbrowser.open(url)
        return url

    def _relative(self, path: str | Path) -> str:
        resolved = Path(path).expanduser().resolve()
        try:
            return resolved.relative_to(self.root).as_posix()
        except ValueError as exc:
            raise ValueError('Markdown 文件必须位于项目根目录内') from exc

    def _resolve(self, raw: str) -> Path:
        candidate = (self.root / urllib.parse.unquote(raw)).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise PermissionError('路径越界') from exc
        if candidate.suffix.lower() not in {'.md', '.markdown'}:
            raise PermissionError('只允许编辑 Markdown 文件')
        return candidate

    def _make_handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            server_version = 'WorkKnacksMarkdown/1.0'

            def log_message(self, _format: str, *args) -> None:
                return

            def do_GET(self) -> None:  
                parsed = urllib.parse.urlparse(self.path)
                query = urllib.parse.parse_qs(parsed.query)
                try:
                    if parsed.path == '/view':
                        path = server._resolve((query.get('path') or [''])[0])
                        self._html(md_file_to_html(path))
                        return
                    if parsed.path == '/edit':
                        token = (query.get('token') or [''])[0]
                        if not secrets.compare_digest(token, server.token):
                            self.send_error(HTTPStatus.FORBIDDEN)
                            return
                        path = server._resolve((query.get('path') or [''])[0])
                        self._html(_editor_html(path, server.token, path.read_text(encoding='utf-8', errors='replace')))
                        return
                    if parsed.path == '/health':
                        self._json({'ok': True})
                        return
                    self.send_error(HTTPStatus.NOT_FOUND)
                except FileNotFoundError:
                    self.send_error(HTTPStatus.NOT_FOUND)
                except PermissionError:
                    self.send_error(HTTPStatus.FORBIDDEN)
                except Exception as exc:
                    self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

            def do_POST(self) -> None:  
                parsed = urllib.parse.urlparse(self.path)
                length = min(int(self.headers.get('Content-Length') or 0), 20_000_000)
                try:
                    payload = json.loads(self.rfile.read(length).decode('utf-8'))
                except Exception:
                    self.send_error(HTTPStatus.BAD_REQUEST)
                    return
                if parsed.path == '/render':
                    self._json({'html': markdown_to_fragment(str(payload.get('text') or ''))})
                    return
                if parsed.path == '/save':
                    token = str(payload.get('token') or '')
                    if not secrets.compare_digest(token, server.token):
                        self.send_error(HTTPStatus.FORBIDDEN)
                        return
                    try:
                        path = server._resolve(str(payload.get('path') or ''))
                        path.write_text(str(payload.get('text') or ''), encoding='utf-8')
                        self._json({'ok': True})
                    except PermissionError:
                        self.send_error(HTTPStatus.FORBIDDEN)
                    except Exception as exc:
                        self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
                    return
                self.send_error(HTTPStatus.NOT_FOUND)

            def _html(self, text: str) -> None:
                raw = text.encode('utf-8')
                self.send_response(HTTPStatus.OK)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _json(self, data: dict) -> None:
                raw = json.dumps(data, ensure_ascii=False).encode('utf-8')
                self.send_response(HTTPStatus.OK)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        return Handler


def _editor_html(path: Path, token: str, source: str) -> str:
    relative_path = path.name
    
    return f'''<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>编辑 · {html.escape(path.name)}</title>
<style>
{BASE_CSS}
html, body {{ max-width:none; margin:0; padding:0; height:100%; overflow:hidden; }}
.toolbar {{ height:44px; display:flex; align-items:center; gap:12px; padding:0 14px; border-bottom:1px solid #9995; }}
.grid {{ display:grid; grid-template-columns:1fr 1fr; height:calc(100vh - 45px); }}
textarea {{ width:100%; height:100%; resize:none; box-sizing:border-box; border:0; border-right:1px solid #9995; padding:18px; font:14px/1.6 "Cascadia Code", Consolas, monospace; outline:none; background:transparent; color:inherit; }}
.preview {{ overflow:auto; padding:18px 28px 70px; }}
.status {{ margin-left:auto; opacity:.7; }}
</style>{HIGHLIGHT}{MATHJAX}</head>
<body>
<div class="toolbar"><strong>{html.escape(path.name)}</strong><span>实时预览 · 自动保存</span><span class="status" id="status">已加载</span></div>
<div class="grid"><textarea id="source">{html.escape(source)}</textarea><article class="preview" id="preview"></article></div>
<script>
const source = document.getElementById('source');
const preview = document.getElementById('preview');
const statusEl = document.getElementById('status');
const qs = new URLSearchParams(location.search);
const path = qs.get('path') || {json.dumps(relative_path)};
const token = {json.dumps(token)};
let timer = null;
async function renderAndSave() {{
  statusEl.textContent = '保存中…';
  const text = source.value;
  const [renderResp, saveResp] = await Promise.all([
    fetch('/render', {{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{text}})}}),
    fetch('/save', {{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{path,text,token}})}})
  ]);
  if (!saveResp.ok) {{ statusEl.textContent = '保存失败'; return; }}
  const data = await renderResp.json();
  preview.innerHTML = data.html;
  statusEl.textContent = '已保存';
  if (window.hljs) preview.querySelectorAll('pre code').forEach(el => hljs.highlightElement(el));
  if (window.MathJax?.typesetPromise) MathJax.typesetPromise([preview]);
}}
function schedule() {{ clearTimeout(timer); timer = setTimeout(renderAndSave, 650); }}
source.addEventListener('input', schedule);
renderAndSave();
</script>
</body></html>'''
