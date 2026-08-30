from __future__ import annotations

import re
from pathlib import Path

from src.core.pipeline import translate_file
from src.providers import registry
from src.providers.parse.mineru import compile_latex
from src.policies import load_policy

from .artifacts import ArtifactLayout
from .arxiv_source import arxiv_id_for_title, fetch_arxiv_source
from .fetch import extract_arxiv_id, extract_pdf_text


class ParseRequiredError(RuntimeError):
    pass




def parsed_latex_path(source: str | Path) -> Path:
    return ArtifactLayout.for_source(source).parsed_tex


def has_parsed_latex(source: str | Path) -> bool:
    return parsed_latex_path(source).is_file()


def parse_document(
    source: str | Path,
    provider_id: str | None = None,
    *,
    project_root: str | Path | None = None,
    polish: bool = True,
    status_cb=None,
    arxiv_id: str | None = None,
    prefer_arxiv: bool = True,
    arxiv_only: bool = False,
    title: str = '',
    authors: list[str] | None = None,
    year: int | None = None,
) -> Path:

    def status(text: str):
        if status_cb:
            try:
                status_cb(text)
            except Exception:
                pass

    path = Path(source).expanduser().resolve()
    layout = ArtifactLayout.for_source(path)
    output_dir = layout.ensure_parse_dir()

    arxiv = _resolve_arxiv_id(arxiv_id, path, title, authors=authors, year=year)
    if arxiv_only:
        if not arxiv:
            raise RuntimeError('未能识别该文献的 arXiv 编号，无法用 arXiv 源码解析。可先用 MinerU。')
        tex_path = _parse_from_arxiv(path, output_dir, arxiv, project_root, polish, status)
        if tex_path is None:
            raise RuntimeError('arXiv 上没有可下载的 TeX 源码，无法用 arXiv 解析。可改用 MinerU。')
        return tex_path

    if prefer_arxiv and arxiv:
        tex_path = _parse_from_arxiv(path, output_dir, arxiv, project_root, polish, status)
        if tex_path is not None:
            return tex_path

    provider_id = provider_id or registry.default_for('parse') or 'mineru'
    provider = registry.get(provider_id)
    if not provider:
        raise RuntimeError(f'找不到解析供应商：{provider_id}')
    ok, message = provider.validate_auth()
    if not ok:
        raise RuntimeError(message)
    status('MinerU 正在解析 PDF…')
    result = provider.process_file(str(path), str(output_dir))
    tex_path = layout.parsed_tex
    if not tex_path.exists():
        candidates = sorted(output_dir.rglob('*.tex'), key=lambda item: item.stat().st_mtime_ns, reverse=True)
        if not candidates:
            raise RuntimeError('MinerU 解析完成但未找到 LaTeX 结果')
        candidates[0].replace(tex_path)

    root = Path(project_root).expanduser().resolve() if project_root else _discover_project_root(path)
    if polish:
        status('AI 正在校对整理 LaTeX…')
        _polish_parsed_latex(root, path, tex_path)
    status('正在编译 main.pdf…')
    compile_latex(tex_path)
    return tex_path


def _resolve_arxiv_id(
    explicit: str | None,
    path: Path,
    title: str = '',
    authors: list[str] | None = None,
    year: int | None = None,
) -> str:
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    if path.suffix.lower() == '.pdf':
        name_id = extract_arxiv_id(path.name)
        if name_id:
            return name_id
        text = extract_pdf_text(path, max_pages=3)
        embedded = extract_arxiv_id(text)
        if embedded:
            return embedded
    if title:
        try:
            found = arxiv_id_for_title(title, authors=authors, year=year)
        except Exception:
            found = ''
        if found:
            return re.sub(r'v\d+$', '', found, flags=re.IGNORECASE)
    return ''


def _parse_from_arxiv(
    path: Path,
    output_dir: Path,
    arxiv: str,
    project_root: str | Path | None,
    polish: bool,
    status,
) -> Path | None:
    tex_path = fetch_arxiv_source(arxiv, output_dir, status=status)
    if tex_path is None:
        return None


    status('正在编译 main.pdf…')
    try:
        compile_latex(tex_path)
    except Exception as exc:
        status(f'编译 main.pdf 失败，但 arXiv 源码已保留：{exc}')
    return tex_path


def ensure_pdf_latex(source: str | Path, *, project_root: str | Path | None = None) -> Path:
    path = Path(source).expanduser().resolve()
    tex = parsed_latex_path(path)
    return tex if tex.exists() else parse_document(path, project_root=project_root)


def translate_document(
    source: str | Path,
    provider,
    *,
    target_lang: str = 'zh-Hans',
    source_lang: str = 'en',
    resume: bool = True,
    progress_path: str | None = None,
    progress_cb=None,
    status_cb=None,
    usage_cb=None,
    project_root: str | Path | None = None,
    polish: bool = True,
) -> Path:

    def status(text: str):
        if status_cb:
            try:
                status_cb(text)
            except Exception:
                pass

    path = Path(source).expanduser().resolve()
    input_path = path
    layout = ArtifactLayout.for_source(path)
    if path.suffix.lower() == '.pdf':
        if not layout.parsed_tex.exists():
            raise ParseRequiredError('PDF 尚未解析。请先完成 MinerU 解析，再开始翻译。')
        input_path = layout.parsed_tex
        layout.ensure_translations()
        output = layout.translation_path(target_lang, '.tex')
    else:
        layout.ensure_translations()
        suffix = path.suffix if path.suffix.lower() in {'.md', '.markdown', '.txt', '.tex', '.srt', '.vtt'} else '.txt'
        output = layout.translation_path(target_lang, suffix)
    status('正在翻译文档…')
    result = Path(translate_file(
        str(input_path),
        provider,
        target_lang=target_lang,
        source_lang=source_lang,
        output_path=str(output),
        resume=resume,
        progress_path=progress_path,
        progress_cb=progress_cb,
        usage_cb=usage_cb,
    ))
    root = Path(project_root).expanduser().resolve() if project_root else None
    if polish and root is not None:
        status('AI 正在润色译文…')
        _polish_translation(root, input_path, result)
    return result


def _polish_translation(root: Path, original: Path, translated: Path) -> str:
    from src.agent import ProjectAgent

    try:
        rel_original = original.relative_to(root).as_posix()
        rel_translated = translated.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError('翻译润色文件必须位于当前项目内') from exc

    message = (
        load_policy('translation') + '\n\n'
        f'@file "{rel_original}"\n'
        f'@file "{rel_translated}"\n'
        '请按以上规范执行一次翻译后润色，逐段对照原文与译文，只编辑译文文件。'
    )
    agent = ProjectAgent(root)
    run = agent.run_automatic(message, task_kind='翻译润色', extra_skills=('polish',))
    allowed = [change for change in run.pending_changes if change.relative_path == rel_translated]
    if allowed:
        agent.apply_changes(allowed)


        try:
            from src.providers.parse.mineru import compile_latex
            compile_latex(translated)
        except Exception:
            pass
    return run.output


def _discover_project_root(path: Path) -> Path:
    for parent in [path.parent, *path.parents]:
        if (parent / '.workknacks').exists():
            return parent.resolve()
    raise RuntimeError('无法定位项目根目录；解析润色需要从 WorkKnacks 项目内启动。')


def _polish_parsed_latex(root: Path, source: Path, tex_path: Path) -> str:

    from src.agent import ProjectAgent

    try:
        rel_tex = tex_path.relative_to(root).as_posix()
        rel_source = source.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError('解析文件必须位于当前项目内') from exc

    message = (
        load_policy('parsing') + '\n\n'
        f'@file "{rel_tex}"\n'
        f'这是 MinerU 从 {rel_source} 自动生成的 LaTeX。请按以上规范执行一次解析后润色，直接编辑该 main.tex。'
    )
    agent = ProjectAgent(root)
    result = agent.run_automatic(message, task_kind='解析润色', extra_skills=('polish',))
    allowed = []
    for change in result.pending_changes:
        if change.relative_path == rel_tex:
            allowed.append(change)
    if allowed:
        agent.apply_changes(allowed)
    return result.output
