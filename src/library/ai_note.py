from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.agent import ProjectAgent
from src.agent.skills import get_skill

from .artifacts import ArtifactLayout, artifact_relpath
from .index import LibraryIndex
from .operations import ensure_pdf_latex
from .tags import merge_tags, parse_keywords_from_note, suggest_rule_tags


LENGTH_HINTS = {
    'brief': '使用 brief 档：只保留一句物理结论、核心方法/方程链、3 个关键结果和一个限制。',
    'standard': '使用 standard 档：保持精炼，但完整讲清问题、物理图像、关键推导/方法链、结果、适用区间和复现路径。',
    'detailed': '使用 detailed 档：增加关键符号、近似清单、方程 sanity check、图表证据与复现参数。',
    'deep-reading': '使用 deep-reading 档：在 detailed 基础上追加 claim-evidence ledger 与优先级明确的复现/核验任务。',
}


def generate_note(
    root: str | Path,
    pdf_path: str | Path,
    *,
    length: str = 'standard',
    focus: str = '',
) -> Path:
    root_path = Path(root).expanduser().resolve()
    pdf = Path(pdf_path).expanduser().resolve()
    try:
        pdf.relative_to(root_path)
    except ValueError as exc:
        raise ValueError('PDF 必须位于项目根目录内') from exc

    parsed = ensure_pdf_latex(pdf, project_root=root_path)
    if not get_skill('summarize', root_path):
        raise RuntimeError('summarize 全局 Skill 不可用')

    index = LibraryIndex(root_path)
    entry = index.entry_for_path(pdf)
    metadata = ''
    if entry:
        metadata = (
            f'条目元信息：title={entry.title!r}; year={entry.year!r}; '
            f'DOI={entry.doi!r}; arXiv={entry.arxiv_id!r}; publication={entry.publication_title!r}.'
        )

    parsed_rel = parsed.relative_to(root_path).as_posix()
    rel_pdf = pdf.relative_to(root_path).as_posix()
    message = '\n'.join(filter(None, [
        f'@file "{parsed_rel}"',
        f'总结 {rel_pdf}；完整阅读 main.tex。',
        metadata,
        LENGTH_HINTS.get(length, LENGTH_HINTS['standard']),
        f'重点：{focus}' if focus else '',
        '物理论文优先给出关键推导、近似、物理图像和可复现检查；结论必须能在正文中定位。',
    ]))
    agent = ProjectAgent(root_path)
    run = agent.run_automatic(message, task_kind='论文总结', extra_skills=('summarize',))
    output = run.output

    layout = ArtifactLayout.for_source(pdf)
    layout.ensure_notes()
    note_path = layout.note_path('summary')
    note_path.write_text(output.rstrip() + '\n', encoding='utf-8')

    if entry:
        keywords = parse_keywords_from_note(output)
        merge_tags(entry, [*suggest_rule_tags(entry), *keywords])
        note_rel = artifact_relpath(pdf.parent, note_path)
        parse_rel = artifact_relpath(pdf.parent, parsed.parent)
        attachment = next(
            (item for item in entry.attachments if item.path and Path(item.path).name == pdf.name),
            None,
        )
        if attachment:
            attachment.artifacts['note'] = note_rel
            attachment.artifacts['parseDir'] = parse_rel
        if not attachment or attachment.role == 'primary':
            entry.files['note'] = note_rel
            entry.files['parseDir'] = parse_rel
            entry.ai_note = {
                'status': 'done',
                'path': note_rel,
                'length': length,
                'summary': _summary_line(output),
                'generatedAt': datetime.now().isoformat(timespec='seconds'),
                'grounding': 'full parsed LaTeX',
            }
        index.upsert(entry)
    return note_path


def _summary_line(markdown: str) -> str:
    for line in str(markdown or '').splitlines():
        text = line.strip().lstrip('#>').strip()
        if text and len(text) > 20:
            return text[:240]
    return ''
