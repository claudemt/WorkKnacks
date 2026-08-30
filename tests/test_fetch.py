from __future__ import annotations

from src.library.fetch import (
    MetadataFetcher,
    extract_doi,
    extract_isbn,
    metadata_from_latex,
    metadata_from_markdown,
    metadata_from_text,
    _clean_pdf_author_line,
    _is_letter_spaced_header,
    _parse_ocr_output,
)
from src.library.entry import LibraryEntry


def test_metadata_from_text_does_not_crash():
    # 回归：fetch.py 曾有一条「(?i) 内联旗标在 | 之后」的非法正则，
    # 使 metadata_from_text/markdown 对任意输入抛 PatternError。
    entry = metadata_from_text('一篇论文标题\n作者：张三\n2021 年\n摘要：\n')
    assert entry is not None


def test_metadata_from_markdown_does_not_crash():
    md = '# 中文标题\n\n作者：李四\n\n2020\n\n摘要内容……\nDOI: 10.3969/j.issn.1000-1891.2019.02.007\n'
    entry = metadata_from_markdown(md, filename='x')
    assert entry is not None
    assert extract_doi(md) == '10.3969/j.issn.1000-1891.2019.02.007'


def test_extract_isbn_handles_spaces_and_prefix():
    assert extract_isbn('ISBN 978-7-114-12345-6') == '9787114123456'


def test_is_letter_spaced_header_detects_journal_running_header():
    # 回归：'P LAN ETARY SCI EN C E' 这类页眉曾被抓成标题。
    assert _is_letter_spaced_header('P LAN ETARY SCI EN C E') is True
    assert _is_letter_spaced_header('PLANETARY SCIENCE') is False
    assert _is_letter_spaced_header('Modern water at low latitudes on Mars') is False
    assert _is_letter_spaced_header('abc') is False  # 太短，不判定


def test_clean_pdf_author_line_strips_superscript_digits():
    # 回归：'Qin1,3' / 'Wu1' 里姓名后跟的单位序号曾被当成作者名一部分。
    assert _clean_pdf_author_line('Qin, C., Wu, Y., et al.') == 'Qin, C., Wu, Y., et al.'
    assert '1' not in _clean_pdf_author_line('Qin1, Wu1,3')
    assert '8868' not in _clean_pdf_author_line('Qin, C., et al., Sci. Adv., eadd8868')
    cleaned = _clean_pdf_author_line('Qin1,3, Wu1, Liu1,2')
    assert 'Qin' in cleaned and 'Wu' in cleaned and 'Liu' in cleaned



_MINERU_TEX = r'''% This LaTeX document needs to be compiled with XeLaTeX.
\documentclass[10]{article}
\usepackage{ctex}
\title{北京——都市计划的无比杰作}
\author{梁思成}
\date{2020}
\begin{document}
\maketitle
北京——都市计划的无比杰作，是……
\end{document}
'''


def test_metadata_from_latex_uses_title_author_macros():
    e = metadata_from_latex(_MINERU_TEX, filename='北京 - 都市计划的无比杰作')
    assert e.title == '北京——都市计划的无比杰作'
    assert e.creators and '梁思成' in e.creators[0].family
    assert e.year == 2020
    # 前言第一行不能被当标题
    assert not e.title.startswith('%')


def test_parse_ocr_output_dispatches_latex_vs_markdown():
    e = _parse_ocr_output(_MINERU_TEX, filename='x')
    assert e.title == '北京——都市计划的无比杰作'
    md = '# 这是一篇关于北京城市规划的中文研究论文\n\n作者：李四\n\n2020\n\n摘要……\n'
    e2 = _parse_ocr_output(md, filename='x')
    assert e2.title != '北京——都市计划的无比杰作' and '城市规划' in e2.title


def test_fetch_cjk_path_merges_openalex_instead_of_replacing(tmp_path):
    """中文路径命中 OpenAlex 时应合并填空（保留文件名标题/作者），而非整体替换。"""
    import fitz
    pdf = tmp_path / '李浩 - 2024 - 某标题.pdf'
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), 'some body text')
    doc.save(str(pdf))
    doc.close()

    net = LibraryEntry(title='某标题', publication_title='城市发展研究',
                       volume='25', issue='5', year=2024)
    net.extra['source'] = 'openalex'
    net.extra['pageStart'] = '110'

    fetcher = MetadataFetcher()
    fetcher.openalex_search = lambda title, authors: net
    fetcher.crossref_search = lambda title, authors: None

    res = fetcher.fetch(pdf)
    entry = res.entry
    assert entry is not None
    assert entry.publication_title == '城市发展研究'   # 网络补全
    assert entry.volume == '25' and entry.issue == '5'
    assert entry.extra.get('pageStart') == '110'
    assert entry.extra.get('networkFields')           # 记录补全了哪些字段
    assert res.source == 'OpenAlex'
    # 文件名解析出的标题/作者不被网络结果覆盖
    assert entry.title == '某标题'
