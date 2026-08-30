from __future__ import annotations

from src.library.cn_meta import (
    _extract_cn_authors,
    _extract_cn_affiliation,
    _extract_cn_identifiers,
    _extract_cn_journal,
    _extract_cn_vol_issue,
    _looks_like_person_name,
    _split_authors,
    _YEAR_RE,
    parse_cn_filename,
)


def test_year_matches_inline_chinese():
    # 回归：\b 在汉字两侧失效（汉字是 Unicode 词字符），导致「于2005年」匹配不到
    assert _YEAR_RE.search('于2005年5月1日起施行').group(0) == '2005'
    assert _YEAR_RE.search('2025 Vol.40, No.5').group(0) == '2025'
    assert _YEAR_RE.search('12005年') is None  # 不是更长数字的一部分


def test_split_space_separated_multi_author():
    assert _split_authors('许皓 李百浩') == ['许皓', '李百浩']
    assert _split_authors('许皓和李百浩') == ['许皓', '李百浩']
    # 双字名内部的空格不能拆（李 扬 → 一个名字）
    assert _split_authors('李 扬') == ['李 扬']


def test_author_line_with_english_romanization():
    # 中文期刊作者行常附英文转写：只取开头中文段
    meta: dict = {}
    title = {'y1': 100.0, 'size': 18.0}
    blocks = [
        {'y0': 110, 'y1': 120, 'size': 9, 'text': '许皓 李百浩XU Hao, LI Baihao'},
    ]
    authors = _extract_cn_authors(blocks, title, page_h=800)
    assert authors == ['许皓', '李百浩']


def test_author_line_rejects_body_fragment():
    # 正文片段（含引号/书名号/长句）不能误当作者
    title = {'y1': 100.0, 'size': 18.0}
    blocks = [
        {'y0': 110, 'y1': 120, 'size': 9, 'text': '史而言，“梁陈方案”是一个无法回避的重要问题'},
    ]
    assert _extract_cn_authors(blocks, title, page_h=800) == []


def test_vol_issue_chinese_pair():
    meta: dict = {}
    _extract_cn_vol_issue(meta, '城市规划 2025年第5期 第49卷 页码 123-128')
    assert meta['volume'] == '49'
    assert meta['issue'] == '5'
    assert meta['page_start'] == '123'
    assert meta['page_end'] == '128'


def test_dunhao_split_into_multiple_authors():
    meta = parse_cn_filename('张三、李四 - 2020 - 北京城市研究')
    assert meta['authors'] == ['张三', '李四']
    assert meta['title'] == '北京城市研究'
    assert meta['year'] == 2020


def test_compound_surname_recall():
    assert _looks_like_person_name('欧阳娜娜') is True
    meta = parse_cn_filename('欧阳娜娜 - 2020 - 城市设计')
    assert meta['authors'] == ['欧阳娜娜']


def test_rare_surname_recall():
    assert _looks_like_person_name('逯宇铎') is True
    meta = parse_cn_filename('逯宇铎 - 2020 - 城市规划')
    assert meta['authors'] == ['逯宇铎']


def test_title_not_stripped_as_author():
    # 无年份、无作者时，标题片段不能误当作者
    meta = parse_cn_filename('规划北京 - 梁陈方案新考')
    assert meta['authors'] == []
    assert '规划北京' in meta['title']


def test_identifiers_extraction():
    meta: dict = {}
    _extract_cn_identifiers(meta, (
        '文章编号：1000-1891(2019)02-0123-07  '
        '中图分类号：TP391  '
        '收稿日期：2019-03-15  '
        'DOI:10.3969/j.issn.1000-1891.2019.02.007'
    ))
    assert meta['article_no'] == '1000-1891(2019)02-0123-07'
    assert meta['clc'] == 'TP391'
    assert meta['received_date'] == '2019-03-15'
    assert meta['doi'] == '10.3969/j.issn.1000-1891.2019.02.007'


def test_journal_from_vol_issue_strip():
    # 刊名与「第X卷 第X期」同页眉条（苏联因素 版式）：应取到纯中文刊名
    meta: dict = {}
    lines = [
        {'text': '2018 年5 月', 'y0': 59.0},
        {'text': '当代中国史研究', 'y0': 72.0},
        {'text': '第25 卷 第3 期', 'y0': 72.5},
        {'text': 'Vol. 25 No. 3', 'y0': 72.5},
    ]
    _extract_cn_journal(meta, lines)
    assert meta.get('journal') == '当代中国史研究'


def test_journal_not_from_far_away_line():
    # 卷期条附近若无可信纯中文刊名，则不应误取远处正文行
    meta: dict = {}
    lines = [
        {'text': '第25 卷 第3 期', 'y0': 72.5},
        {'text': '与此同时，规划思想发生转变', 'y0': 400.0},
    ]
    _extract_cn_journal(meta, lines)
    assert 'journal' not in meta


def test_affiliation_from_author_bio_footnote():
    # 页脚「作者：X，单位，职务」兜底取机构（韩林飞 版式）
    lines = [
        {'text': '作者：韩林飞，建筑学博士，北京交通大学建筑与艺术学院，教授', 'y0': 710.0},
    ]
    aff = _extract_cn_affiliation(lines, title_y1=200.0, page_h=842.0)
    assert '北京交通大学建筑与艺术学院' in aff


def test_affiliation_from_parenthesized_top_band():
    lines = [
        {'text': '作者', 'y0': 300.0},
        {'text': '（北京市城市规划设计研究院，北京 100045）', 'y0': 320.0},
    ]
    aff = _extract_cn_affiliation(lines, title_y1=250.0, page_h=842.0)
    assert '北京市城市规划设计研究院' in aff


def test_isbn_only_when_valid_length():
    meta: dict = {}
    _extract_cn_identifiers(meta, 'ISBN：978-7-114-12345-6')
    assert meta['isbn'] == '9787114123456'
    # 文章编号里的数字串不能误判为 ISBN
    meta2: dict = {}
    _extract_cn_identifiers(meta2, '文章编号：1000-1891(2019)02-0123-07')
    assert 'isbn' not in meta2 or not meta2['isbn']
