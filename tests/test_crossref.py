from __future__ import annotations

import json

from src.library.crossref import (
    _openalex_abstract,
    entry_from_crossref,
    entry_from_openalex,
    merge_network_metadata,
    resolve_crossref_doi,
    resolve_openalex_doi,
    search_crossref,
    search_openalex,
)


def _cronel(message: dict) -> str:
    return json.dumps({'message': message}, ensure_ascii=False)


def _oael(item: dict) -> str:
    return json.dumps(item, ensure_ascii=False)


def test_crossref_message_mapping():
    entry = entry_from_crossref({
        'title': ['北京城市历史研究——以梁陈方案为例.'],
        'container-title': ['城市发展研究'],
        'author': [
            {'given': '', 'family': '李浩', 'affiliation': []},
            {'given': '小明', 'family': '张', 'affiliation': []},
        ],
        'published-print': {'date-parts': [[2019, 5, 1]]},
        'volume': '25',
        'issue': '5',
        'DOI': '10.3969/j.issn.1000-1891.2019.02.007',
        'publisher': '某某学会',
    })
    assert entry is not None
    assert entry.title == '北京城市历史研究——以梁陈方案为例'
    assert entry.language == 'zh'
    assert entry.year == 2019
    assert entry.publication_title == '城市发展研究'
    assert entry.volume == '25'
    assert entry.issue == '5'
    assert entry.doi == '10.3969/j.issn.1000-1891.2019.02.007'
    assert entry.creators[0].family == '李浩'
    assert entry.creators[1].given == '小明'


def test_resolve_crossref_doi():
    msg = {'title': ['中文测试标题'], 'container-title': ['测试学报'],
           'author': [{'given': '', 'family': '王五'}],
           'issued': {'date-parts': [[2021]]}, 'DOI': '10.9999/x.123', 'publisher': 'p'}
    entry = resolve_crossref_doi('10.9999/x.123', lambda url: _cronel(msg))
    assert entry is not None
    assert entry.title == '中文测试标题'
    assert entry.creators[0].family == '王五'
    assert entry.year == 2021


def test_resolve_crossref_doi_network_error_returns_none():
    def boom(url):
        raise RuntimeError('offline')
    assert resolve_crossref_doi('10.9999/x.123', boom) is None


def test_search_crossref_accepts_cjk_high_similarity():
    items = [
        {'title': ['北京城市历史研究——以梁陈方案为例'], 'author': [{'family': '李浩'}],
         'container-title': ['城市发展研究'], 'issued': {'date-parts': [[2019]]}, 'DOI': '10.1/x'},
        {'title': ['An Unrelated English Paper About Cities'], 'author': [{'family': 'Smith'}],
         'container-title': ['J Urban'], 'issued': {'date-parts': [[2019]]}, 'DOI': '10.2/y'},
    ]
    payload = json.dumps({'message': {'items': items}}, ensure_ascii=False)
    entry = search_crossref('北京城市历史研究', ['李浩'], lambda url: payload)
    assert entry is not None
    assert entry.title.startswith('北京城市历史研究')


def test_search_crossref_rejects_low_similarity():
    items = [{'title': ['完全不同的中文标题乙丙丁'], 'author': [{'family': '赵'}],
              'container-title': ['某刊'], 'issued': {'date-parts': [[2020]]}, 'DOI': '10.1/a'}]
    payload = json.dumps({'message': {'items': items}}, ensure_ascii=False)
    assert search_crossref('北京城市历史研究', ['李浩'], lambda url: payload) is None


def test_openalex_message_mapping():
    entry = entry_from_openalex({
        'title': '北京城市历史研究',
        'publication_year': 2019,
        'authorships': [{'author': {'display_name': '李浩'}}],
        'primary_location': {'source': {'display_name': '城市发展研究'}},
        'biblio': {'volume': '25', 'issue': '5'},
        'doi': 'https://doi.org/10.3969/j.issn.1000-1891.2019.02.007',
        'language': 'zh-cn',
    })
    assert entry is not None
    assert entry.title == '北京城市历史研究'
    assert entry.language == 'zh'
    assert entry.year == 2019
    assert entry.publication_title == '城市发展研究'
    assert entry.creators[0].family == '李浩'
    assert entry.doi == '10.3969/j.issn.1000-1891.2019.02.007'


def test_resolve_openalex_doi():
    payload = _oael({'title': 'OpenAlex 中文测试', 'publication_year': 2022,
                     'authorships': [], 'primary_location': {'source': {}}, 'biblio': {}})
    entry = resolve_openalex_doi('10.1/x', lambda url: payload)
    assert entry is not None and entry.title == 'OpenAlex 中文测试'


def test_search_openalex_rejects_english():
    payload = json.dumps({'results': [
        {'title': 'English Urban Study', 'publication_year': 2020, 'authorships': [],
         'primary_location': {'source': {}}, 'biblio': {}},
    ]}, ensure_ascii=False)
    assert search_openalex('北京城市历史研究', ['李浩'], lambda url: payload) is None


def test_openalex_abstract_reassembles_inverted_index():
    # 无序倒排词表 → 按位置重组为有序句子
    item = {'abstract_inverted_index': {
        '规划': [0, 4], '北京': [1], '城市': [2], '研究': [3], '分析': [5],
    }}
    assert _openalex_abstract(item) == '规划 北京 城市 研究 规划 分析'


def test_openalex_mapping_parses_abstract_and_pages():
    entry = entry_from_openalex({
        'title': '北京城市历史研究',
        'publication_year': 2019,
        'authorships': [{'author': {'display_name': '李浩'}}],
        'primary_location': {'source': {'display_name': '城市发展研究'}},
        'biblio': {'volume': '25', 'issue': '5', 'first_page': '110', 'last_page': '118'},
        'abstract_inverted_index': {'摘要': [0], '内容': [1]},
        'doi': 'https://doi.org/10.3969/j.issn.1000-1891.2019.02.007',
    })
    assert entry.pages == '110-118'
    assert entry.abstract == '摘要 内容'
    assert entry.extra['pageStart'] == '110'
    assert entry.extra['pageEnd'] == '118'


def test_merge_network_metadata_fills_empty_only():
    local = entry_from_openalex({'title': '苏联因素', 'publication_year': 2018,
                                 'authorships': [{'author': {'display_name': '李 扬'}}],
                                 'primary_location': {'source': {}}, 'biblio': {}})
    net = entry_from_openalex({
        'title': '20世纪50年代北京城市规划中的苏联因素', 'publication_year': 2018,
        'authorships': [], 'primary_location': {'source': {'display_name': '当代中国史研究'}},
        'biblio': {'volume': '25', 'issue': '3', 'first_page': '97', 'last_page': '105'},
        'abstract_inverted_index': {'苏联': [0]},
        'doi': 'https://doi.org/10.1/x',
    })
    # 模拟文件名路径已填标题/作者：不得被覆盖
    local.title = '20世纪50年代北京城市规划中的苏联因素'
    filled = merge_network_metadata(local, net)
    assert local.title == '20世纪50年代北京城市规划中的苏联因素'  # 标题不被覆盖
    assert local.publication_title == '当代中国史研究'
    assert local.volume == '25' and local.issue == '3'
    assert local.pages == '97-105'
    assert local.extra['pageStart'] == '97'
    assert local.abstract == '苏联'
    assert local.extra['networkEnriched'] == 'openalex'
    assert 'journal' in filled or 'publication_title' in filled


def test_search_openalex_prefers_title_filter_then_falls_back():
    called: list[str] = []
    hit = {'title': '北京城市历史研究', 'publication_year': 2019, 'authorships': [],
           'primary_location': {'source': {}}, 'biblio': {}}

    def first_url_hits(url):
        called.append(url)
        return json.dumps({'results': [hit]}, ensure_ascii=False)

    entry = search_openalex('北京城市历史研究', ['李浩'], first_url_hits)
    assert entry is not None
    assert 'filter=title.search' in called[0]

    # 第一段（title.filter）无结果 → 回退 search=
    def first_empty_then_hit(url):
        called2.append(url)
        return json.dumps({'results': [hit]}, ensure_ascii=False) if 'search=' in url and 'filter=' not in url \
            else json.dumps({'results': []}, ensure_ascii=False)

    called2: list[str] = []
    entry2 = search_openalex('北京城市历史研究', ['李浩'], first_empty_then_hit)
    assert entry2 is not None
    assert any('search=' in u and 'filter=' not in u for u in called2)
