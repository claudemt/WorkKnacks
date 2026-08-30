#!/usr/bin/env python3
"""整库中文文献识别覆盖率评估（ScienceMetaBench 式闭环）。

用法:
    python tools/eval_cn.py "E:\\...\\文献集"
    python tools/eval_cn.py "E:\\...\\文献集" --json out.json

对目录下每个 PDF 跑 extract_cn_metadata，输出逐篇覆盖表 + 汇总（标题/作者/年份/
卷期/单位/期刊/文章编号 的覆盖率），并用文本层是否为空的判定标记扫描件。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import fitz  # noqa: E402

from src.library.cn_meta import extract_cn_metadata  # noqa: E402


def _probe_openalex(timeout: int = 10) -> str:
    """一次轻量 OpenAlex 连通性探测（判断本机能否用 OpenAlex 回填）。"""
    import ssl
    import urllib.request
    try:
        ctx = ssl.create_default_context()
        url = 'https://api.openalex.org/works?per-page=1&mailto=workknacks@localhost'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 WorkKnacks/3.0'})
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return f'可达 (HTTP {r.status})'
    except urllib.error.HTTPError as e:  # noqa: F821
        return f'HTTP {e.code}（限流/需稍后重试）'
    except Exception as e:
        return f'不可达（{type(e).__name__}）'

FIELDS = [
    ('title', '标题'),
    ('authors', '作者'),
    ('year', '年份'),
    ('vol_issue', '卷期'),
    ('affiliation', '单位'),
    ('journal', '期刊'),
    ('article_no', '文章编号'),
]


def _has_text_layer(pdf: Path) -> bool:
    try:
        doc = fitz.open(str(pdf))
        if doc.page_count < 1:
            return False
        page = doc[0]
        return bool(page.get_text('dict').get('blocks', []))
    except Exception:
        return False
    finally:
        try:
            doc.close()
        except Exception:
            pass


def _run(pdf: Path) -> dict:
    entry, source = extract_cn_metadata(path=pdf)
    scanned = not _has_text_layer(pdf)
    row: dict = {
        'file': pdf.stem,
        'source': source,
        'scanned': scanned,
    }
    if entry is None:
        row['title'] = row['authors'] = row['year'] = ''
        row['vol_issue'] = row['affiliation'] = row['journal'] = row['article_no'] = ''
        return row
    extra = entry.extra or {}
    vi = ''
    if entry.volume or entry.issue:
        vi = f"{entry.volume or '?'}/{entry.issue or '?'}"
    row['title'] = entry.title or ''
    row['authors'] = '、'.join(c.family for c in entry.creators)
    row['year'] = str(entry.year or '')
    row['vol_issue'] = vi
    row['affiliation'] = extra.get('affiliation') or ''
    row['journal'] = extra.get('journal') or ''
    row['article_no'] = extra.get('articleNo') or ''
    return row


def _run_enriched(pdf: Path, fetcher) -> dict:
    """走网络回填（MetadataFetcher.fetch）：本地解析 + OpenAlex/Crossref 合并填空。"""
    res = fetcher.fetch(pdf)
    scanned = not _has_text_layer(pdf)
    row: dict = {'file': pdf.stem, 'scanned': scanned, 'source': res.source}
    entry = res.entry
    if entry is None:
        for k in ('title', 'authors', 'year', 'vol_issue', 'journal', 'net', 'filled'):
            row[k] = ''
        return row
    extra = entry.extra or {}
    netfields = extra.get('networkFields') or []
    vi = f"{entry.volume or '?'}/{entry.issue or '?'}" if (entry.volume or entry.issue) else ''
    row['title'] = entry.title or ''
    row['authors'] = '、'.join(c.family for c in entry.creators)
    row['year'] = str(entry.year or '')
    row['vol_issue'] = vi
    row['journal'] = (extra.get('journal') or entry.publication_title or '')
    row['net'] = res.source if netfields else '-'
    row['filled'] = '、'.join(netfields)
    return row


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='中文文献识别覆盖率评估（本地 or --enrich 网络回填）')
    ap.add_argument('root', help='文献集根目录')
    ap.add_argument('--json', default='', help='可选：把结果写成 JSON')
    ap.add_argument('--enrich', action='store_true',
                    help='走网络回填（OpenAlex/Crossref 合并填空），并打印 OpenAlex 可达性与命中率')
    args = ap.parse_args(argv)

    root = Path(args.root).expanduser().resolve()
    pdfs = sorted(
        p for p in root.rglob('*.pdf')
        if p.is_file() and not any(part.startswith('.') for part in p.relative_to(root).parts)
    )
    if not pdfs:
        print(f'未找到 PDF: {root}', file=sys.stderr)
        return 1

    if args.enrich:
        from src.library.fetch import MetadataFetcher  # noqa: E402
        print('OpenAlex 连通性:', _probe_openalex(), '\n')
        fetcher = MetadataFetcher()
        rows = [_run_enriched(p, fetcher) for p in pdfs]

        print(f'共 {len(pdfs)} 个 PDF（网络回填）\n')
        hdr = f"{'文件':<26}{'扫描':<4}{'标题':<16}{'作者':<12}{'年':<6}{'卷/期':<6}{'期刊':<12}{'网络':<9}{'补全字段'}"
        print(hdr)
        print('-' * len(hdr))
        for r in rows:
            scanned = '●' if r['scanned'] else ' '
            print(f"{r['file'][:24]:<26}{scanned:<4}{r['title'][:14]:<16}{r['authors'][:10]:<12}"
                  f"{r['year'][:4]:<6}{r['vol_issue']:<6}{r['journal'][:10]:<12}"
                  f"{r['net']:<9}{r['filled'][:30]}")
        n_hit = sum(1 for r in rows if r['net'] != '-')
        n_total = len(rows)
        print(f"\nOpenAlex/Crossref 网络命中: {n_hit}/{n_total} 篇"
              f"（其余走本地解析；书籍/扫描件本无网络可补的期刊字段）")
        nscan = sum(1 for r in rows if r['scanned'])
        print(f'扫描件: {nscan} 篇（无文本层，走 OCR）')
    else:
        rows = [_run(p) for p in pdfs]

        # 逐篇表
        print(f'共 {len(pdfs)} 个 PDF\n')
        hdr = f"{'文件':<26}{'扫描':<4}{'标题':<16}{'作者':<14}{'年':<6}{'卷/期':<6}{'期刊':<10}{'单位':<18}{'文章编号':<22}"
        print(hdr)
        print('-' * len(hdr))
        for r in rows:
            file = r['file'][:24]
            scanned = '●' if r['scanned'] else ' '
            print(f"{file:<26}{scanned:<4}{r['title'][:14]:<16}{r['authors'][:12]:<14}"
                  f"{r['year'][:4]:<6}{r['vol_issue']:<6}{r['journal'][:8]:<10}"
                  f"{r['affiliation'][:16]:<18}{r['article_no'][:20]:<22}")

        # 覆盖率汇总（扫描件不计入正文类字段）
        print('\n覆盖率（标题/年份含扫描件；作者/卷期/单位/期刊/文章编号仅算有文本层者）')
        total = len(rows)
        for key, label in FIELDS:
            if key == 'title' or key == 'year':
                base = rows
            else:
                base = [r for r in rows if not r['scanned']]
            if not base:
                print(f'  {label:<4}  - (无有文本层样本)')
                continue
            n = sum(1 for r in base if r.get(key))
            print(f'  {label:<4}  {n:>3}/{len(base):<3} = {n / len(base) * 100:5.1f}%')
        nscan = sum(1 for r in rows if r['scanned'])
        print(f'  扫描   {nscan:>3}/{total:<3} 件（无文本层，走 OCR）')

    if args.json:
        Path(args.json).write_text(
            json.dumps({'total': total, 'rows': rows}, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
        print(f'\n已写 JSON: {args.json}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
