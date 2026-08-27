from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from ..base import ParseProvider, ProviderMeta, ProviderRegistry


FLASH_MAX_BYTES = 10 * 1024 * 1024
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.tif', '.tiff', '.svg', '.pdf', '.eps'}


def _run(
    cmd: list[str], *, timeout: int, cwd: str | Path | None = None, env: dict | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
        cwd=str(Path(cwd).resolve()) if cwd is not None else None,
        env=env,
    )


def _output_error(result: subprocess.CompletedProcess[str], prefix: str) -> RuntimeError:
    text = (result.stderr or result.stdout or '').strip()
    if result.returncode == 4 or '10mb' in text.casefold() or 'lightweight api limit' in text.casefold():
        return RuntimeError(
            f'{prefix}: 文件超过 MinerU flash-extract 的 10MB/20页限制。'
            '完整解析必须使用标准 extract；请先运行 mineru-open-api auth 或配置 MINERU_TOKEN。'
        )
    return RuntimeError(f'{prefix}: {text[-1200:] or f"exit {result.returncode}"}')


def _copy_unique(source: Path, destination_dir: Path) -> Path:
    destination_dir.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r'[^\w.-]+', '-', source.stem, flags=re.UNICODE).strip('-') or 'figure'
    suffix = source.suffix.lower()
    target = destination_dir / f'{stem}{suffix}'
    number = 2
    while target.exists():
        target = destination_dir / f'{stem}-{number}{suffix}'
        number += 1
    shutil.copy2(source, target)
    return target


def _neutralize_missing_figures(
    text: str,
    resolve: Callable[[str], str | None],
    missing_placeholder: Callable[[str], str],
) -> str:
    
    out: list[str] = []
    i, n = 0, len(text)
    prefix = '\\pandocbounded{'
    while i < n:
        if text.startswith(prefix, i):
            depth = 1
            j = i + len(prefix)
            while j < n and depth:
                if text[j] == '{':
                    depth += 1
                elif text[j] == '}':
                    depth -= 1
                j += 1
            inner = text[i + len(prefix): j - 1]
            match = re.match(r'\\includegraphics(\s*\[[^\]]*\])?\s*\{([^}]+)\}', inner)
            if match and resolve(match.group(2).strip()) is None:
                out.append(missing_placeholder(match.group(2).strip()))
            else:
                out.append(text[i:j])
            i = j
        else:
            out.append(text[i])
            i += 1
    return ''.join(out)


def _normalize_latex(raw_dir: Path, output_dir: Path) -> Path:
    tex_files = [p for p in raw_dir.rglob('*.tex') if p.is_file()]
    if not tex_files:
        raise RuntimeError('MinerU 标准 extract 已完成，但未找到 LaTeX 输出。请确认 CLI 支持 -f latex。')
    
    
    source_tex = max(tex_files, key=lambda p: (p.stat().st_size, p.stat().st_mtime_ns))
    text = source_tex.read_text(encoding='utf-8', errors='replace')

    figures = output_dir / 'figures'
    if figures.exists():
        shutil.rmtree(figures)
    figures.mkdir(parents=True, exist_ok=True)

    image_map: dict[str, str] = {}
    for image in raw_dir.rglob('*'):
        if not image.is_file() or image.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        target = _copy_unique(image, figures)
        replacement = f'figures/{target.name}'
        variants = {image.name, image.as_posix()}
        try:
            variants.add(image.relative_to(source_tex.parent).as_posix())
        except ValueError:
            pass
        try:
            variants.add(image.relative_to(raw_dir).as_posix())
        except ValueError:
            pass
        for variant in variants:
            image_map[variant.replace('\\', '/')] = replacement

    missing: list[str] = []

    def _resolve(raw: str) -> str | None:
        
        raw = raw.strip().replace('\\', '/')
        replacement = image_map.get(raw) or image_map.get(Path(raw).name)
        if replacement is None and not Path(raw).suffix:
            for ext in IMAGE_EXTENSIONS:
                replacement = image_map.get(raw + ext) or image_map.get(Path(raw + ext).name)
                if replacement:
                    break
        return replacement

    def _missing_placeholder(raw: str) -> str:
        missing.append(raw)
        return f'% [图缺失: {raw}]'

    def repl(match: re.Match[str]) -> str:
        opts = match.group(1) or ''
        raw = match.group(2).strip()
        replacement = _resolve(raw)
        if replacement is None:
            return _missing_placeholder(raw)
        return f'\\includegraphics{opts}{{{replacement}}}'

    
    
    
    text = _neutralize_missing_figures(text, _resolve, _missing_placeholder)
    text = re.sub(r'\\includegraphics(\s*\[[^\]]*\])?\s*\{([^}]+)\}', repl, text)
    main_tex = output_dir / 'main.tex'
    main_tex.write_text(_ensure_arxiv_document(text), encoding='utf-8')
    if missing:
        
        (output_dir / 'figures_missing.txt').write_text(
            '\n'.join(f'# {p}' for p in sorted(set(missing))) + '\n',
            encoding='utf-8',
        )
    return main_tex


_TEX_AUX_SUFFIXES = {'.aux', '.log', '.out', '.toc', '.fls', '.fdb_latexmk', '.synctex.gz', '.xdv'}


def _cleanup_tex_aux(directory: Path) -> None:
    for item in directory.iterdir():
        if not item.is_file() or item.name in {'main.tex', 'main.pdf'}:
            continue
        name = item.name.casefold()
        if any(name.endswith(suffix) for suffix in _TEX_AUX_SUFFIXES):
            item.unlink(missing_ok=True)


def _ensure_arxiv_document(text: str) -> str:
    
    normalized = text.strip()
    if '\\documentclass' in normalized:
        return normalized + '\n'
    return (
        '\\documentclass[11pt]{article}\n'
        '\\usepackage[margin=1in]{geometry}\n'
        '\\usepackage{amsmath,amssymb}\n'
        '\\usepackage{graphicx}\n'
        '\\usepackage{hyperref}\n'
        '\\graphicspath{{figures/}}\n'
        '\\begin{document}\n'
        + normalized
        + '\n\\end{document}\n'
    )


def _tex_bin_dirs() -> list[Path]:
    """Likely TeX bin dirs, from config override then common install locations."""
    dirs: list[Path] = []
    configured = os.environ.get('TEX_BIN_DIR', '').strip()
    if configured:
        dirs.append(Path(configured).expanduser())
    for drive in ('D:', 'C:', 'E:'):
        base = Path(drive + '/texlive')
        try:
            if base.is_dir():
                for year_dir in sorted(base.iterdir(), reverse=True):
                    candidate = year_dir / 'bin' / 'windows'
                    if candidate.is_dir():
                        dirs.append(candidate)
        except OSError:
            pass
    local = os.environ.get('LOCALAPPDATA') or ''
    if local:
        for rel in ('Programs/MiKTeX/miktex/bin/x64', 'Programs/MiKTeX/miktex/bin'):
            candidate = Path(local) / rel
            if candidate.is_dir():
                dirs.append(candidate)
    return dirs


def _tex_env() -> dict | None:
    dirs = [str(d) for d in _tex_bin_dirs()]
    if not dirs:
        return None
    env = dict(os.environ)
    env['PATH'] = os.pathsep.join(dirs + [env.get('PATH', '')])
    return env


def _which_tex(tool: str) -> str | None:
    found = shutil.which(tool)
    if found:
        return found
    env = _tex_env()
    if env:
        found = shutil.which(tool, path=env.get('PATH'))
        if found:
            return found
    return None


def _compile_error_tail(result, cwd: Path) -> str:
    log = cwd / 'main.log'
    if log.is_file():
        lines = [line for line in log.read_text(encoding='utf-8', errors='replace').splitlines() if line.strip()]
        return '\n'.join(lines[-15:])
    text = (result.stderr or result.stdout or '').strip()
    return '\n'.join(text.splitlines()[-15:])


def compile_latex(main_tex: str | Path) -> Path:
    tex = Path(main_tex).expanduser().resolve()
    cwd = tex.parent
    pdf = cwd / 'main.pdf'
    try:
        pdf.unlink()
    except FileNotFoundError:
        pass
    _cleanup_tex_aux(cwd)
    env = _tex_env()

    attempts: list[list[str]] = []
    if _which_tex('latexmk'):
        attempts.append([_which_tex('latexmk'), '-xelatex', '-interaction=nonstopmode', '-halt-on-error', 'main.tex'])
    if _which_tex('tectonic'):
        attempts.append([_which_tex('tectonic'), '--keep-logs', '--keep-intermediates', 'main.tex'])
    for engine in ('xelatex', 'lualatex', 'pdflatex'):
        exe = _which_tex(engine)
        if exe:
            attempts.append([exe, '-interaction=nonstopmode', '-halt-on-error', 'main.tex'])

    if not attempts:
        raise RuntimeError(
            '未找到可用的 TeX 编译器（latexmk/xelatex/lualatex/pdflatex）。'
            '请安装 TeX Live 或 MiKTeX，或在下拉配置里手动指定编译器路径（TEX_BIN_DIR）。'
        )

    last_error = ''
    for cmd in attempts:
        engine = Path(cmd[0]).name.split('.')[0].lower()
        passes = 2 if engine in {'xelatex', 'lualatex', 'pdflatex'} else 1
        ok = True
        for _ in range(passes):
            result = _run(cmd, timeout=900, cwd=cwd, env=env)
            if result.returncode != 0:
                ok = False
                last_error = _compile_error_tail(result, cwd)
                break
        if ok and pdf.exists():
            _cleanup_tex_aux(cwd)
            return pdf
    _cleanup_tex_aux(cwd)
    if pdf.exists():
        return pdf
    detail = f'\n\n编译器输出：\n{last_error}' if last_error else ''
    raise RuntimeError(f'LaTeX 编译失败。{detail}\n请检查 {cwd.name}/main.tex 与 main.log。')


def _page_bounds(spec: str, page_count: int) -> tuple[int, int]:
    
    text = str(spec or '1-6').strip()
    match = re.fullmatch(r'(\d+)(?:\s*-\s*(\d+))?', text)
    if not match:
        return 0, min(page_count, 6)
    start = max(1, int(match.group(1)))
    end = int(match.group(2) or start)
    if end < start:
        start, end = end, start
    return min(page_count, start - 1), min(page_count, end)


def _split_pdf_for_flash(source: Path, pages: str, temp_dir: Path) -> Path:
    
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(source))
    start, end = _page_bounds(pages, len(reader.pages))
    if end <= start:
        raise RuntimeError('PDF 没有可用于前页识别的页面。')
    
    for final in range(end, start, -1):
        writer = PdfWriter()
        for index in range(start, final):
            writer.add_page(reader.pages[index])
        candidate = temp_dir / f'preview-{start + 1}-{final}.pdf'
        with candidate.open('wb') as fh:
            writer.write(fh)
        if candidate.stat().st_size <= FLASH_MAX_BYTES and final - start <= 20:
            return candidate
        candidate.unlink(missing_ok=True)
    raise RuntimeError(
        'PDF 的单页体积仍超过 MinerU flash-extract 10MB 限制。'
        '请配置 MinerU Token 或运行 mineru-open-api auth 后使用标准 extract。'
    )


def _likely_scanned_pdf(source: Path, sample_pages: int = 4) -> bool:
    if source.suffix.lower() != '.pdf':
        return False
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(source))
        pages = reader.pages[: min(sample_pages, len(reader.pages))]
        if not pages:
            return False
        chars = sum(len((page.extract_text() or '').strip()) for page in pages)
        return chars < 80 * len(pages)
    except Exception:
        return False


class MinerUParseProvider(ParseProvider):
    meta = ProviderMeta(
        provider_id='mineru',
        name='MinerU',
        category='parse',
        description='PDF/图片/DOCX/PPTX → LaTeX',
        max_chunk_chars=0,
        max_chunks_per_sec=0,
        requires_auth=True,
        required_keys=[],
        supported_formats=['.pdf', '.png', '.jpg', '.jpeg', '.docx', '.pptx'],
    )

    
    
    
    def _conn_args(self) -> list[str]:
        args: list[str] = []
        base_url = (self.config.get('MINERU_BASE_URL') or '').strip()
        if base_url:
            args += ['--base-url', base_url]
        token = (self.config.get('MINERU_TOKEN') or '').strip()
        if token:
            args += ['--token', token]
        return args

    def _model_value(self) -> str:
        return (self.config.get('MINERU_MODEL') or 'auto').strip() or 'auto'

    def _cli_available(self) -> tuple[bool, str]:
        try:
            result = _run(['mineru-open-api', 'version'], timeout=30)
        except FileNotFoundError:
            return False, 'mineru-open-api 未安装'
        except Exception as exc:
            return False, f'MinerU CLI 检测失败：{exc}'
        return (True, 'mineru-open-api 可用') if result.returncode == 0 else (False, 'mineru-open-api 不可用')

    def _precision_authenticated(self) -> tuple[bool, str]:
        ok, message = self._cli_available()
        if not ok:
            return ok, message
        
        
        
        try:
            verify = _run(['mineru-open-api', 'auth', '--verify', *self._conn_args()], timeout=45)
        except Exception as exc:
            return False, f'MinerU 标准 API 登录检测失败：{exc}'
        if verify.returncode == 0:
            return True, 'MinerU 标准 extract Token 已配置'
        if self.config.get('MINERU_TOKEN'):
            return True, 'MinerU Token 已配置'
        return False, 'MinerU 标准 extract 需要登录：请运行 mineru-open-api auth 或配置 MINERU_TOKEN'

    def validate_auth(self) -> tuple[bool, str]:
        return self._precision_authenticated()

    def preview_file(
        self,
        input_path: str,
        output_path: str,
        *,
        pages: str = '1-6',
        ocr: bool = False,
        language: str = '',
    ) -> str:
        
        source = Path(input_path).expanduser().resolve()
        target = Path(output_path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        lang = str(language or '').strip()
        precision, _ = self._precision_authenticated()

        with tempfile.TemporaryDirectory(prefix='workknacks-mineru-preview-') as temp_name:
            temp_root = Path(temp_name)
            raw = temp_root / 'out'
            raw.mkdir(parents=True, exist_ok=True)
            upload = source
            if precision:
                cmd = [
                    'mineru-open-api', 'extract', str(source), '-o', str(raw),
                    '-f', 'md', '--pages', pages, '--model', self._model_value(), '--timeout', '900',
                    *self._conn_args(),
                ]
                if ocr or _likely_scanned_pdf(source):
                    cmd.append('--ocr')
            else:
                if source.suffix.lower() == '.pdf':
                    upload = _split_pdf_for_flash(source, pages, temp_root)
                    cmd = [
                        'mineru-open-api', 'flash-extract', str(upload), '-o', str(raw),
                        '--timeout', '900', *self._conn_args(),
                    ]
                else:
                    if source.stat().st_size > FLASH_MAX_BYTES:
                        raise RuntimeError(
                            '文件超过 MinerU flash-extract 10MB 限制。请配置 MinerU Token 或运行 mineru-open-api auth。'
                        )
                    cmd = [
                        'mineru-open-api', 'flash-extract', str(source), '-o', str(raw),
                        '--pages', pages, '--timeout', '900', *self._conn_args(),
                    ]
                if ocr:
                    cmd.append('--ocr')
            if lang:
                cmd.extend(['--language', lang])
            result = _run(cmd, timeout=1000)
            if result.returncode != 0:
                raise _output_error(result, 'MinerU 前页识别失败')

            candidates = sorted(
                (item for item in raw.rglob('*.md') if item.is_file()),
                key=lambda item: item.stat().st_mtime_ns,
                reverse=True,
            )
            if candidates:
                shutil.copy2(candidates[0], target)
                return str(target)
            
            
            stdout = (result.stdout or '').strip()
            if stdout and len(stdout) > 20:
                target.write_text(stdout + '\n', encoding='utf-8')
                return str(target)
        raise RuntimeError('MinerU 前页识别完成但未找到 Markdown 结果')

    def process_file(self, input_path: str, output_dir: str) -> str:
        source = Path(input_path).expanduser().resolve()
        target = Path(output_dir).expanduser().resolve()
        target.mkdir(parents=True, exist_ok=True)
        ok, message = self._precision_authenticated()
        if not ok:
            raise RuntimeError(message)

        
        
        raw = target / '.mineru-raw'
        if raw.exists():
            shutil.rmtree(raw, ignore_errors=True)
        raw.mkdir(parents=True, exist_ok=True)
        cmd = [
            'mineru-open-api', 'extract', str(source), '-o', str(raw),
            '-f', 'latex', '--model', self._model_value(), '--timeout', '1800',
            *self._conn_args(),
        ]
        if _likely_scanned_pdf(source):
            cmd.append('--ocr')
        result = _run(cmd, timeout=1900)
        if result.returncode != 0:
            raise _output_error(result, 'MinerU 标准解析失败')
        try:
            main_tex = _normalize_latex(raw, target)
        finally:
            shutil.rmtree(raw, ignore_errors=True)
        try:
            pdf = compile_latex(main_tex)
        except Exception:
            pdf = None
        return str(main_tex) + (f' + {pdf}' if pdf else '')


ProviderRegistry.register(MinerUParseProvider)
