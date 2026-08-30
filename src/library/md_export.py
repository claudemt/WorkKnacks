from __future__ import annotations

import os
import shutil
from pathlib import Path

from .md_render import md_file_to_html


def _system_chromium() -> str | None:

    for name in ('chromium', 'chromium-browser', 'google-chrome', 'google-chrome-stable', 'microsoft-edge', 'msedge'):
        found = shutil.which(name)
        if found:
            return found
    if os.name == 'nt':
        candidates = [
            Path(os.environ.get('PROGRAMFILES', '')) / 'Google/Chrome/Application/chrome.exe',
            Path(os.environ.get('PROGRAMFILES(X86)', '')) / 'Google/Chrome/Application/chrome.exe',
            Path(os.environ.get('PROGRAMFILES', '')) / 'Microsoft/Edge/Application/msedge.exe',
            Path(os.environ.get('PROGRAMFILES(X86)', '')) / 'Microsoft/Edge/Application/msedge.exe',
        ]
    elif sys_platform() == 'darwin':
        candidates = [
            Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),
            Path('/Applications/Chromium.app/Contents/MacOS/Chromium'),
            Path('/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'),
        ]
    else:
        candidates = []
    return next((str(path) for path in candidates if str(path) and path.exists()), None)


def sys_platform() -> str:
    import sys
    return sys.platform


def md_to_pdf(md_path: str | Path, output_path: str | Path | None = None) -> Path:
    source = Path(md_path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(str(source))
    target = Path(output_path).expanduser().resolve() if output_path else source.with_suffix('.pdf')
    target.parent.mkdir(parents=True, exist_ok=True)
    html = md_file_to_html(source)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError('导出 PDF 需要 playwright：pip install playwright') from exc

    with sync_playwright() as playwright:
        browser = None
        first_error: Exception | None = None
        try:
            browser = playwright.chromium.launch(headless=True)
        except Exception as exc:
            first_error = exc
            executable = _system_chromium()
            if executable:
                try:
                    browser = playwright.chromium.launch(headless=True, executable_path=executable)
                except Exception:
                    browser = None
        if browser is None:
            detail = f'（Playwright 浏览器启动失败：{first_error}）' if first_error else ''
            raise RuntimeError(
                '未找到可用的 Chromium。请执行 `playwright install chromium`，或安装系统 Chrome/Chromium。' + detail
            )
        try:
            page = browser.new_page(viewport={'width': 1200, 'height': 1600})
            page.set_content(html, wait_until='domcontentloaded')

            try:
                page.wait_for_function('!window.MathJax || !MathJax.startup || MathJax.startup.promise !== undefined', timeout=5000)
                page.evaluate('window.MathJax?.startup?.promise ? MathJax.startup.promise : Promise.resolve()')
            except Exception:
                pass
            page.pdf(
                path=str(target),
                format='A4',
                print_background=True,
                margin={'top': '18mm', 'right': '16mm', 'bottom': '18mm', 'left': '16mm'},
            )
        finally:
            browser.close()
    return target
