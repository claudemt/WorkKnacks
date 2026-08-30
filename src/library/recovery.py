from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

from src.agent import ProjectAgent
from src.core.project_paths import ProjectPaths
from src.providers import registry

from .entry import LibraryEntry, normalize_doi
from .fetch import (
    MetadataFetcher,
    extract_arxiv_id,
    extract_doi,
    extract_isbn,
    extract_pdf_text,
    metadata_from_markdown,
)
from .supplement import SupplementDetection, detect_supplement


@dataclass(slots=True)
class RecoveryCandidate:
    source: str
    entry: LibraryEntry
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)

    def to_prompt_dict(self, index: int) -> dict:
        return {
            'index': index,
            'source': self.source,
            'score': round(self.score, 4),
            'itemType': self.entry.item_type,
            'title': self.entry.title,
            'authors': [author.display() for author in self.entry.authors],
            'year': self.entry.year,
            'venue': self.entry.publication_title,
            'publisher': self.entry.publisher,
            'DOI': self.entry.doi,
            'arXiv': self.entry.arxiv_id,
            'ISBN': self.entry.isbn,
            'url': self.entry.url,
        }


@dataclass(slots=True)
class RecoveryReport:
    local_entry: LibraryEntry
    preview_text: str
    preview_source: str
    scan_likely: bool
    candidates: list[RecoveryCandidate] = field(default_factory=list)
    recommended_index: int = -1
    ai_used: bool = False
    ai_confidence: float = 0.0
    ai_reason: str = ''
    warnings: list[str] = field(default_factory=list)
    supplement: SupplementDetection = field(default_factory=SupplementDetection)

    @property
    def recommended(self) -> RecoveryCandidate | None:
        if 0 <= self.recommended_index < len(self.candidates):
            return self.candidates[self.recommended_index]
        return None


class MetadataRecoveryService:


    def __init__(
        self,
        root: str | Path,
        *,
        fetcher: MetadataFetcher | None = None,
        agent: ProjectAgent | None = None,
    ):
        self.root = Path(root).expanduser().resolve()
        self.paths = ProjectPaths.for_root(self.root).ensure()
        self.fetcher = fetcher or MetadataFetcher(cache_dir=self.paths.metadata_cache)
        self.agent = agent or ProjectAgent(self.root)

    def recover(
        self,
        pdf_path: str | Path,
        *,
        pages: int = 6,
        use_ai: bool = True,
    ) -> RecoveryReport:
        path = Path(pdf_path).expanduser().resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise ValueError('识别文件必须位于当前项目内') from exc
        if path.suffix.lower() != '.pdf':
            raise ValueError('AI 复核仅处理 PDF')

        native = extract_pdf_text(path, max_pages=max(1, min(int(pages), 10)))
        scan_likely = _looks_scanned(native)
        preview, preview_source, warnings = self._preview(path, pages=pages, ocr=scan_likely, fallback=native)
        local = metadata_from_markdown(preview, filename=path.stem)
        local.extra['recoveryPreview'] = preview_source
        if scan_likely:
            local.extra['scanLikely'] = True

        supplement = detect_supplement(
            preview,
            filename=path.name,
            extracted_doi=extract_doi(preview),
        )
        candidates = self._search_candidates(local, preview)
        report = RecoveryReport(
            local_entry=local,
            preview_text=preview,
            preview_source=preview_source,
            scan_likely=scan_likely,
            candidates=candidates,
            warnings=warnings,
            supplement=supplement,
        )
        if candidates:
            report.recommended_index = 0
        if use_ai:
            self._ai_adjudicate(report)
        return report

    def _preview(self, path: Path, *, pages: int, ocr: bool, fallback: str) -> tuple[str, str, list[str]]:
        warnings: list[str] = []
        stat = path.stat()
        cache_key = f'{path.relative_to(self.root).as_posix()}:{stat.st_size}:{stat.st_mtime_ns}:p1-{pages}:ocr={int(ocr)}'
        target = self.paths.cache_file('identify', cache_key, '.md')
        if target.exists():
            try:
                text = target.read_text(encoding='utf-8', errors='replace')
                if text.strip():
                    return text, f'MinerU cache · pages 1-{pages}', warnings
            except OSError:
                pass

        provider = registry.get('mineru')
        if provider and hasattr(provider, 'preview_file'):
            try:


                result = provider.preview_file(
                    str(path),
                    str(target),
                    pages=f'1-{max(1, int(pages))}',
                    ocr=ocr,
                )
                output = Path(result)
                text = output.read_text(encoding='utf-8', errors='replace')
                if text.strip():
                    return text, f'MinerU pages 1-{pages}' + (' · OCR' if ocr else ''), warnings
            except Exception as exc:
                warnings.append(str(exc))
        else:
            warnings.append('MinerU 不可用，已退回 PDF 文本层。')

        if fallback.strip():
            return fallback, f'PDF text layer · pages 1-{pages}', warnings
        return path.stem, 'filename only', warnings + ['前几页未提取到可用文字，请人工补充标题/作者/ISBN/DOI。']

    def _search_candidates(self, local: LibraryEntry, preview: str) -> list[RecoveryCandidate]:
        doi = extract_doi(preview) or local.doi
        arxiv = extract_arxiv_id(preview) or local.arxiv_id
        isbn = extract_isbn(preview) or local.isbn
        found: list[RecoveryCandidate] = []

        def add(source: str, entries: Iterable[LibraryEntry], identifier_bonus: float = 0.0) -> None:
            for entry in entries:
                if not entry or not entry.title:
                    continue
                score, reasons = _score_candidate(local, entry, doi=doi, arxiv=arxiv, isbn=isbn)
                score = min(1.0, score + identifier_bonus)
                found.append(RecoveryCandidate(source=source, entry=entry, score=score, reasons=reasons))

        if arxiv:
            try:
                entry = self.fetcher.arxiv_by_id(arxiv)
                add('arXiv · ID', [entry] if entry else [], 0.30)
            except Exception:
                pass

        return _dedupe_candidates(found)[:18]

    def _ai_adjudicate(self, report: RecoveryReport) -> None:
        preview = report.preview_text[:7000]
        candidates = [item.to_prompt_dict(i) for i, item in enumerate(report.candidates)]
        payload = {
            'ocr_preview': preview,
            'local_guess': report.local_entry.to_dict(),
            'candidates': candidates,
        }
        prompt = (
            '信息 AI复核：只根据首页识别与候选数据库比较，不凭记忆补造。'
            '输出 JSON：{"recommended":索引或-1,"confidence":0到1,"reason":"一句话","warnings":[]}。\n'
            + json.dumps(payload, ensure_ascii=False)
        )
        try:
            run = self.agent.run_automatic(prompt, task_kind='元数据 AI 复核')
            parsed = _extract_json_object(run.output)
            index = int(parsed.get('recommended', -1))
            report.recommended_index = index if 0 <= index < len(report.candidates) else -1
            report.ai_confidence = max(0.0, min(1.0, float(parsed.get('confidence') or 0.0)))
            report.ai_reason = str(parsed.get('reason') or '').strip()
            report.ai_used = True
            for warning in parsed.get('warnings') or []:
                text = str(warning).strip()
                if text:
                    report.warnings.append('AI核对：' + text)
        except Exception as exc:
            report.warnings.append(f'AI 候选核对失败：{exc}')


def _looks_scanned(text: str) -> bool:
    sample = str(text or '')[:30000]
    if not sample.strip():
        return True

    words = re.findall(r'[A-Za-z\u4e00-\u9fff]{3,}', sample)
    printable = sum(ch.isprintable() for ch in sample)
    ratio = printable / max(1, len(sample))
    pdf_object_noise = len(re.findall(r'/(?:Type|Length|Filter|Font|XObject)\b', sample))
    return len(' '.join(words)) < 700 or ratio < 0.82 or (pdf_object_noise > 25 and len(words) < 120)


def _score_candidate(local: LibraryEntry, candidate: LibraryEntry, *, doi: str, arxiv: str, isbn: str) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    title_score = _title_similarity(local.title, candidate.title) if local.title and candidate.title else 0.0
    score += 0.58 * title_score
    if title_score >= 0.82:
        reasons.append(f'标题相似 {title_score:.0%}')
    if doi and normalize_doi(candidate.doi) == normalize_doi(doi):
        score += 0.35; reasons.append('DOI 精确')
    if arxiv and str(candidate.arxiv_id).casefold() == str(arxiv).casefold():
        score += 0.35; reasons.append('arXiv 精确')
    if isbn and re.sub(r'[^0-9Xx]', '', candidate.isbn).upper() == re.sub(r'[^0-9Xx]', '', isbn).upper():
        score += 0.35; reasons.append('ISBN 精确')
    if local.year and candidate.year and str(local.year)[:4] == str(candidate.year)[:4]:
        score += 0.06; reasons.append('年份一致')
    local_names = {_norm_name(a.family or a.given) for a in local.authors if a.family or a.given}
    cand_names = {_norm_name(a.family or a.given) for a in candidate.authors if a.family or a.given}
    overlap = len(local_names & cand_names)
    if overlap:
        score += min(0.12, 0.05 * overlap); reasons.append(f'作者姓氏匹配 {overlap}')
    if local.item_type == 'book' and candidate.item_type == 'book':
        score += 0.05; reasons.append('文献类型一致')
    return min(1.0, score), reasons


def _dedupe_candidates(items: list[RecoveryCandidate]) -> list[RecoveryCandidate]:
    best: dict[str, RecoveryCandidate] = {}
    for item in items:
        entry = item.entry
        key = ''
        if entry.doi:
            key = 'doi:' + normalize_doi(entry.doi)
        elif entry.isbn:
            key = 'isbn:' + re.sub(r'[^0-9Xx]', '', entry.isbn).upper()
        else:
            key = 'title:' + re.sub(r'[^\w\u0080-\uffff]+', '', entry.title.casefold())[:220]
        current = best.get(key)
        if current is None or item.score > current.score:
            best[key] = item
        elif item.source not in current.source:
            current.source += ' + ' + item.source
    return sorted(best.values(), key=lambda item: (-item.score, item.entry.title.casefold()))


def _title_similarity(left: str, right: str) -> float:
    norm = lambda value: ' '.join(re.sub(r'[^\w\u0080-\uffff]+', ' ', str(value).casefold()).split())
    return SequenceMatcher(None, norm(left), norm(right)).ratio()


def _norm_name(value: str) -> str:
    return re.sub(r'[^\w\u0080-\uffff]+', '', str(value).casefold())


def _extract_json_object(text: str) -> dict:
    raw = str(text or '').strip()
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        pass
    start = raw.find('{')
    end = raw.rfind('}')
    if start >= 0 and end > start:
        try:
            value = json.loads(raw[start:end + 1])
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            pass
    return {}
