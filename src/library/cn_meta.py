from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .entry import Creator, LibraryEntry

_CJK_RE = re.compile(r'[一-鿿]')
# 注意：Python3 的 \w/\b 是 Unicode 感知，汉字也算"词字符"，故 \b 在「于2005年」两侧失效。
# 用「前后非数字」的环视代替 \b，才能匹配紧邻中文的年份。
_YEAR_RE = re.compile(r'(?<![0-9])(?:19|20)\d{2}(?![0-9])')
_JOURNAL_HEADER_RE = re.compile(r'(?i)\bVol[.．]?\s*\d+\s*[,，]?\s*(?:No[.．]?\s*\d+\b|\b\d{1,3}$)|^\s*\d{4}\s*Vol')
_SENTENCE_END = re.compile(r'[。；，、！？：]$')
_NOISE_WORDS = re.compile(r'摘要|关键词|参考文献|doi\s*[:：]|引言|作者简介|评论|综述|书评|编者按|按语|编辑部|编辑部按')
_BOOK_MARK_RE = re.compile(r'全集|选集|文集|全书|读本|辞典|词典|会要|实录|校注|译注')
_BOOK_ROLE_RE = re.compile(r'(?:著|编著|主编|编撰|译注)$')

_CURRENT_YEAR = datetime.now().year


def _has_cjk(text: Any) -> bool:
    return bool(_CJK_RE.search(str(text or '')))


def _cjk_count(text: Any) -> int:
    return len(_CJK_RE.findall(str(text or '')))


def _clean_text(value: Any) -> str:
    t = str(value or '')
    t = t.replace('　', ' ').replace(' ', ' ').replace('​', '')
    return re.sub(r'\s+', ' ', t).strip()


def _is_plausible_title(text: Any, min_cjk: int = 3) -> bool:
    t = _clean_text(text)
    if not t:
        return False
    if _JOURNAL_HEADER_RE.search(t):
        return False
    if re.search(r'(?:19|20)\d{2}\s*年\s*第?\s*\d+\s*期', t):  # CNKI 页眉「刊名 2025年第5期」
        return False
    if re.fullmatch(r'[\d\s.,;:()\-—_~～\[\]]+', t):
        return False
    if _cjk_count(t) < min_cjk:
        return False
    if _SENTENCE_END.search(t):
        return False
    if _NOISE_WORDS.search(t):
        return False
    if not (min_cjk <= len(t) <= 80):
        return False
    return True


def _detect_book(name: str) -> bool:
    if _BOOK_MARK_RE.search(name):
        return True
    if _BOOK_ROLE_RE.search(name):
        return True
    return False


_DATA_DIR = Path(__file__).resolve().parent / 'data'


def _load_surnames() -> tuple[frozenset[str], frozenset[str]]:
    """从 data/cn_surnames.txt 加载姓氏：1 字→单姓，2 字→复姓。

    文件缺失或为空时回退到内嵌核心姓，保证功能不空。文件不在运行时依赖。
    """
    single: set[str] = set()
    double: set[str] = set()
    try:
        text = (_DATA_DIR / 'cn_surnames.txt').read_text(encoding='utf-8')
    except OSError:
        text = ''
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        if len(s) == 1:
            single.add(s)
        elif len(s) == 2:
            double.add(s)
    _CORE_SINGLE = ('李王张刘陈杨赵黄周吴徐孙胡朱高林何郭马罗梁宋郑谢韩唐冯于董萧程曹袁邓许傅沈曾彭吕苏卢蒋蔡贾丁魏薛叶阎余潘杜戴夏钟汪田任姜范方石姚谭廖邹熊金陆郝孔白崔康毛邱秦江史顾侯邵孟龙万段钱汤尹黎易常武乔贺赖龚文严欧包左卜华安禄姜邓查金封宣沈艾殷俞杜阮蓝闵席季麻强贾路娄危童颜盛林刁钟邱骆高夏蔡田胡凌霍虞万支柯卢莫经房裘缪干解应宗丁贲郁杭洪包诸石崔钮程嵇邢滑裴陆荣翁荀羊惠甄曲家封芮储靳汲糜松井富巫乌焦巴弓牧隗山谷车侯宓蓬全都班仰秋仲伊宫宁仇栾暴甘厉戎祖武符刘景詹束龙叶幸司韶郜黎蓟薄印宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙池乔阴郁胥能苍双闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍桑桂濮牛寿通边扈燕冀浦尚农温别庄晏柴瞿阎充慕连茹习宦艾鱼容向古易慎戈廖庾终暨居衡步都耿满弘匡国文寇广禄阙欧殳沃利蔚越夔隆师巩厍聂晁勾敖融冷訾辛阚那简饶空曾毋沙乜养鞠须丰巢关蒯相查后荆红游竺权逯盖益桓亢门海帅商牟佘伯赏南墨哈谯笪年爱阳佟言福')
    _CORE_DOUBLE = ('欧阳司马诸葛上官皇甫令狐宇文东方公孙独孤南宫夏侯司徒尉迟万俟闻人慕容赫连宗政濮阳仲孙轩辕钟离长孙鲜于闾丘司空')
    if not single:
        single.update(_CORE_SINGLE)
    if not double:
        double.update(_CORE_DOUBLE)
    return frozenset(single), frozenset(double)


_SINGLE_SURNAMES, _DOUBLE_SURNAMES = _load_surnames()
_PERSON_BLOCK_RE = re.compile(
    r'方案|规划|建议|研究|论文|分析|历史|北京|城市|中国|问题|讨论|考察|设计|建筑|全集|报告|成果|关于|对于|有关|研究'
)
_PERSON_FORBIDDEN = re.compile(r'[0-9A-Za-z《》“”、，。]')


def _looks_like_person_name(seg: Any) -> bool:
    """文件名里「作者 - 」开头的段是否更像人名而非标题片段。

    用「姓 + 长度 + 无结构性词」三条件，区分 李浩/马国馨 这类真名
    与 规划北京/梁陈方案新考 这类标题片段，避免把标题误当作者。
    支持顿号分隔的多作者段（张三、李四）：每一子段都必须像人名。
    """
    s = _clean_text(seg)
    if not s or _PERSON_BLOCK_RE.search(s):
        return False
    parts = [p.strip() for p in re.split(r'[、，]', s) if p.strip()]
    if not parts:
        return False
    for p in parts:
        if _PERSON_BLOCK_RE.search(p) or _PERSON_FORBIDDEN.search(p):
            return False
        n = len(p)
        if not (2 <= n <= 6):
            return False
        if p[:2] in _DOUBLE_SURNAMES:
            continue
        if p[0] not in _SINGLE_SURNAMES:
            return False
    return True


def parse_cn_filename(stem: Any) -> dict[str, Any]:
    name = _clean_text(stem)
    meta: dict[str, Any] = {
        'title': '', 'authors': [], 'year': None, 'is_book': False, 'confidence': 0.0,
    }
    if not name:
        return meta

    if ' - ' in name:
        segs = [s.strip() for s in name.split(' - ')]
        yi = next(
            (i for i, s in enumerate(segs) if re.fullmatch(r'(?:19|20)\d{2}', s)),
            None,
        )
        if yi is not None:
            # 有年份：年份前的段都是作者，年份后才是标题（应用内规范 author - year - title）
            meta['year'] = int(segs[yi])
            seen: set[str] = set()
            author_raw = []
            for a in segs[:yi]:
                author_raw.extend(_split_authors(a))
            meta['authors'] = [a for a in author_raw if not (a in seen or seen.add(a))]
            title = segs[yi + 1:]
            # 剥掉标题开头与年份重复的年份段（2003 - 2003 - 城记 → 城记）
            while (title and re.fullmatch(r'(?:19|20)\d{2}', title[0])
                   and int(title[0]) == meta['year']):
                title = title[1:]
            title_str = _clean_text(' - '.join(title))
            if _is_plausible_title(title_str, 2):
                meta['title'] = title_str
        else:
            # 无年份：只剥开头的“人名”段为作者（人名启发式，避免吞标题片段如“规划北京”）
            authors: list[str] = []
            i = 0
            while i < len(segs) and _looks_like_person_name(segs[i]):
                authors.extend(_split_authors(segs[i]))
                i += 1
            seen = set()
            meta['authors'] = [a for a in authors if not (a in seen or seen.add(a))]
            title_str = _clean_text(' - '.join(segs[i:]))
            if _is_plausible_title(title_str, 2):
                meta['title'] = title_str

    if not meta['title'] and _is_plausible_title(name, 2):
        meta['title'] = _clean_text(name)

    meta['is_book'] = _detect_book(name)
    meta['confidence'] = 1.0 if meta['title'] else 0.0
    return meta


def _collect_blocks(path: Path) -> tuple[list[dict[str, Any]], float]:
    try:
        import fitz
    except ImportError:
        return [], 0.0
    try:
        doc = fitz.open(str(path))
    except Exception:
        return [], 0.0
    try:
        if doc.page_count < 1:
            return [], 0.0
        page = doc[0]
        page_h = float(page.rect.height)
        blocks: list[dict[str, Any]] = []
        for b in page.get_text('dict').get('blocks', []):
            if 'lines' not in b:
                continue
            spans = [s for line in b.get('lines', []) for s in line.get('spans', [])]
            text = _clean_text(''.join(s.get('text', '') for s in spans))
            if not text:
                continue
            size = max((float(s.get('size') or 0) for s in spans), default=0.0)
            x0, y0, x1, y1 = b.get('bbox', (0, 0, 0, 0))
            blocks.append({
                'text': text,
                'size': float(size),
                'x0': float(x0),
                'y0': float(y0),
                'y1': float(y1),
            })
        return blocks, page_h
    finally:
        doc.close()


def _collect_lines(path: Path) -> tuple[list[dict[str, Any]], float]:
    """按「行」聚合第 1 页文本（版面驱动）。

    借鉴 PDF-Extract-Kit / PaddleX 的版面思想：标题/作者/摘要按「行 + 字号」定位，
    而非对合并后的 block 跑正则。每行记录 文本 / 主导字号 / 包围盒。跨行同段由调用方拼接。
    """
    try:
        import fitz
    except ImportError:
        return [], 0.0
    try:
        doc = fitz.open(str(path))
    except Exception:
        return [], 0.0
    try:
        if doc.page_count < 1:
            return [], 0.0
        page = doc[0]
        page_h = float(page.rect.height)
        lines: list[dict[str, Any]] = []
        for b in page.get_text('dict').get('blocks', []):
            for line in b.get('lines', []) if 'lines' in b else []:
                spans = line.get('spans', [])
                if not spans:
                    continue
                text = _clean_text(''.join(s.get('text', '') for s in spans))
                if not text:
                    continue
                size = max((float(s.get('size') or 0) for s in spans), default=0.0)
                x0, y0, x1, y1 = line.get('bbox', (0, 0, 0, 0))
                lines.append({
                    'text': text,
                    'size': float(size),
                    'x0': float(x0),
                    'y0': float(y0),
                    'y1': float(y1),
                })
        lines.sort(key=lambda ln: (round(ln['y0']), ln['x0']))
        return lines, page_h
    finally:
        doc.close()


def _recover_rotated(single: list[dict[str, Any]]) -> dict[str, Any]:
    cols: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for b in single:
        cols[round(b['x0'] / 2) * 2].append(b)
    lines = []
    for col in cols.values():
        col.sort(key=lambda b: b['y0'])
        lines.append(''.join(b['text'] for b in col))
    out: dict[str, Any] = {
        'title': '', 'authors': [], 'year': None, 'journal': '',
        'volume': '', 'issue': '', 'is_book': False, 'confidence': 0.3,
    }
    for line in sorted(lines, key=len, reverse=True):
        if not out['title'] and _is_plausible_title(line, 4):
            out['title'] = _clean_text(line)
        elif 2 <= len(line) <= 12 and _cjk_count(line) >= 2:
            out['authors'].append(line)
    return out


_DOI_RE = re.compile(r'\b10\.\d{4,9}/[-._;()/:A-Z0-9]+', re.I)
_ISBN_RE = re.compile(r'(?i)\b(?:ISBN(?:-1[03])?\s*[:：]?\s*)?((?:97[89][ -]?)?[0-9][0-9Xx -]{8,16}[0-9Xx])\b')


def _extract_doi(text: Any) -> str:
    match = _DOI_RE.search(str(text or '').replace('​', '').replace('﻿', ''))
    return match.group(0) if match else ''


_ARTICLE_NO_LABEL_RE = re.compile(r'文章编号[：:]?\s*([0-9A-Za-z][0-9A-Za-z\-–—()（）.]*\d)')
_ARTICLE_NO_CNKI_RE = re.compile(r'\d{4}[-–—]\d{4}[（(]?\d{4}[)）]?\d{1,2}[-–—]\d{3,4}[-–—]\d{1,2}')
_CLC_RE = re.compile(r'(?:中图分类号|CLC|分类号)[：:]\s*([A-Z][A-Z0-9]*(?:\.[0-9]+)?(?:\s*[;；]\s*[A-Z][A-Z0-9]*(?:\.[0-9]+)?)*)')
_RECEIVED_DATE_RE = re.compile(r'收稿日期[：:]?\s*((?:19|20)\d{2}[-/年.]\d{1,2}[-/月.]\d{1,2}日?)')


def _extract_cn_identifiers(meta: dict[str, Any], head: str) -> None:
    """识别中文期刊首页的文献标识码：文章编号 / 中图分类号 / 收稿日期 / DOI / ISBN。"""
    m = _ARTICLE_NO_LABEL_RE.search(head)
    if m:
        meta['article_no'] = m.group(1).strip(' .）).-–—')
    else:
        m = _ARTICLE_NO_CNKI_RE.search(head)
        if m:
            meta['article_no'] = m.group(0).strip()
    m = _CLC_RE.search(head)
    if m:
        meta['clc'] = m.group(1).strip()
    m = _RECEIVED_DATE_RE.search(head)
    if m:
        meta['received_date'] = m.group(1).strip()
    doi = _extract_doi(head)
    if doi:
        meta['doi'] = doi
    isbn = _ISBN_RE.search(head)
    if isbn:
        digits = re.sub(r'[^0-9Xx]', '', isbn.group(1)).upper()
        if len(digits) in (10, 13):
            meta['isbn'] = digits


def _split_authors(text: str) -> list[str]:
    """把作者段按 顿号/逗号/空格/"和" 拆成多个作者。

    中文文件名/首页常用「张三、李四」「许皓 李百浩」「许皓和李百浩」表示多作者。
    「和」与「空格」仅在两侧/各段都像人名时才拆，避免误拆标题里的「和」与双字名。
    """
    parts: list[str] = []
    for tok in re.split(r'[、，]', text):
        tok = tok.strip()
        if not tok:
            continue
        # 空格分隔的多作者（许皓 李百浩）：仅当各段都像人名才拆
        sub_toks = [s for s in tok.split() if s]
        if len(sub_toks) >= 2 and all(_looks_like_person_name(s) for s in sub_toks):
            parts.extend(sub_toks)
            continue
        if '和' in tok:
            subs = [s.strip() for s in tok.split('和') if s.strip()]
            if len(subs) >= 2 and all(_looks_like_person_name(s) for s in subs):
                parts.extend(subs)
                continue
        parts.append(tok)
    return parts


def _extract_cn_authors(blocks: list[dict[str, Any]], title_block: dict[str, Any], page_h: float) -> list[str]:
    """标题正下方作者行的稳健抽取：只接受「纯中文短行 + 姓氏启发式」。

    支持 顿号/逗号/空格/和 分隔的多作者，容忍上标脚注（许皓1,2 → 许皓）。
    拒斥：含句末标点、含拉丁字母（期刊名/单位/邮箱）、以「——」开头的副标题、
    摘要/关键词等噪声行。
    """
    band = title_block['y1'] + page_h * 0.24
    below = sorted(
        (b for b in blocks if b['y0'] > title_block['y1'] and b['y0'] <= band),
        key=lambda x: x['y0'],
    )
    for b in below:
        text = _clean_text(b['text'])
        if not text or _cjk_count(text) < 2:
            continue
        # 作者行不含书名号/引号/句末标点/噪声词
        if _NOISE_WORDS.search(text) or re.search(r'[。；！？《》“”]', text):
            continue
        if text.lstrip().startswith('——'):
            continue
        # 去掉装饰符（■ 等）再取开头的连续中文段；作者行常附英文转写（「许皓 李百浩XU Hao」），
        # 故长度门只作用于中文段，不作用于整行。
        text = re.sub(r'^[■●◆▣□○·★☆※]+', '', text).strip()
        m = re.match(r'^[一-鿿、，和\s]+', text)
        author_part = m.group(0).strip() if m else ''
        if _cjk_count(author_part) < 2 or len(author_part) > 26:
            continue
        names = _split_authors(author_part)
        # 去掉每个名字尾部上标脚注（许皓1,2 → 许皓）
        names = [re.sub(r'[（(]?[\d,，、\s\-]+[)）]?$', '', n).strip(' ,，、') for n in names]
        names = [n for n in names if _cjk_count(n) >= 2]
        if not names:
            continue
        # 作者行应「全部」都像人名，才能整体采纳（防止正文片段被切进来）
        valid = [_looks_like_person_name(n) for n in names]
        if all(valid):
            return names
        # 单作者回退：整行是一个 2-6 字人名且首字为常见姓
        if len(names) == 1 and 2 <= len(names[0]) <= 6:
            if names[0][:2] in _DOUBLE_SURNAMES or names[0][0] in _SINGLE_SURNAMES:
                return names
    return []


# 中文期刊卷期/页码：卷/期成对出现才采纳，降低把正文数字误当卷期的风险。
_VOL_ISSUE_RE = re.compile(r'(?:(?:第)?(\d{1,3})\s*卷\s*[,，、]?\s*第?\s*(\d{1,3})\s*期)')
_ISSUE_VOL_RE = re.compile(r'第\s*(\d{1,3})\s*期\s*[,，、]?\s*(?:第)?(\d{1,3})\s*卷')
_PAGE_RANGE_RE = re.compile(r'(?:页码\s*[:：]?|页\s*码\s*[:：]?|pp\.?|pages?)\s*[:：]?\s*(\d{1,4})\s*[-–—]\s*(\d{1,4})(?:\s*页)?')


def _extract_cn_vol_issue(meta: dict[str, Any], wide: str) -> None:
    """中文期刊「第49卷 第5期 / 第5期 第49卷 / 页码 123-128」抽取（卷期需成对）。"""
    m = _VOL_ISSUE_RE.search(wide)
    m2 = _ISSUE_VOL_RE.search(wide)
    if m:
        meta['volume'] = m.group(1)
        meta['issue'] = m.group(2)
    elif m2:
        meta['issue'] = m2.group(1)
        meta['volume'] = m2.group(2) or ''
    pm = _PAGE_RANGE_RE.search(wide)
    if pm:
        meta['page_start'] = pm.group(1)
        meta['page_end'] = pm.group(2)


_AFFIL_PAREN_RE = re.compile(r'^[（(]\s*([^（()）]{2,70})\s*[)）]$')
_AFFIL_KEY_RE = re.compile(
    r'省|市|自治区|自治区|特别行政区|区|县|学院|大学|研究院|研究所|研究中心|研究部|'
    r'中心|系|院|所|集团|有限公司|邮编|邮政编码|100\d{3}|200\d{3}|[0-9]{6}'
)
_VOL_ISSUE_MARK_RE = re.compile(r'第\s*\d{1,3}\s*卷|Vol[.．]?\s*\d+|(?:19|20)\d{2}\s*年\s*第?\s*\d+\s*期', re.I)
_JOURNAL_LABELS = {'摘要', '关键词', '引言', '参考文献', '作者简介', '规划研究', '本刊专稿'}


def _extract_cn_journal(meta: dict[str, Any], lines: list[dict[str, Any]]) -> None:
    """CNKI 页眉/页脚条中的刊名：刊名通常与「第X卷 第X期 / Vol.X No.Y」同行或紧邻。

    只在与卷期条相邻（±18px）的纯中文短行里找，降低把章节标题/正文误当刊名的风险。
    """
    anchor_y = None
    for ln in lines:
        if _VOL_ISSUE_MARK_RE.search(ln['text']):
            anchor_y = ln['y0']
            break
    if anchor_y is None:
        return
    for ln in lines:
        if abs(ln['y0'] - anchor_y) > 18:
            continue
        t = _clean_text(ln['text'])
        if not t or re.search(r'[0-9A-Za-z《》“”、，。；：]', t):
            continue
        if _cjk_count(t) < 2 or len(t) > 14 or t in _JOURNAL_LABELS:
            continue
        if _NOISE_WORDS.search(t):
            continue
        meta['journal'] = t
        return


_AFFIL_BIOSEG_RE = re.compile(r'(?<!作者)([一-鿿A-Za-z（）()]{4,40}(?:大学|学院|研究院|研究所|系|中心)[一-鿿A-Za-z（）()]{0,20})')


def _extract_cn_affiliation(lines: list[dict[str, Any]], title_y1: float, page_h: float) -> str:
    """作者行下方单位行。两级尽力：
    1) 顶部作者带里的（单位 城市 邮编）括号行；
    2) 页脚「作者(简介)：X，单位，职务」行里含 大学/学院/研究院 的分段。
    """
    # 优先：作者带内的括号单位行
    for ln in lines:
        if ln['y0'] <= title_y1:
            continue
        if ln['y0'] > title_y1 + page_h * 0.45:
            break
        text = _clean_text(ln['text'])
        m = _AFFIL_PAREN_RE.match(text)
        if m and _AFFIL_KEY_RE.search(m.group(1)):
            return m.group(1).strip()
    # 兜底：整页「作者(简介)：」脚注行里的机构分段
    for ln in lines:
        text = _clean_text(ln['text'])
        if not re.match(r'^作者(简介)?\s*[:：]', text):
            continue
        m = _AFFIL_BIOSEG_RE.search(text)
        if m:
            return m.group(1).strip()
    return ''


def _join_title_lines(lines: list[dict[str, Any]], anchor: dict[str, Any]) -> tuple[str, float]:
    """标题跨行拼接：与锚行字号相近、紧邻其下的行视为标题续行。返回 (拼接文本, 底 y1)。"""
    parts = [_clean_text(anchor['text'])]
    y1 = anchor['y1']
    base = anchor['size']
    for ln in lines:
        if ln is anchor:
            continue
        if abs(ln['size'] - base) > 1.5:
            continue
        if not (ln['y0'] > y1 - 1.0 and ln['y0'] <= y1 + max(6.0, base * 1.6)):
            continue
        t = _clean_text(ln['text'])
        if not t or not _is_plausible_title(t, 2):
            continue
        parts.append(t)
        y1 = ln['y1']
    return ' '.join(parts), y1


def _extract_cn_frontmatter(path: Path) -> dict[str, Any]:
    meta: dict[str, Any] = {
        'title': '', 'authors': [], 'year': None, 'journal': '',
        'volume': '', 'issue': '', 'is_book': False, 'confidence': 0.0,
        'article_no': '', 'clc': '', 'doi': '', 'received_date': '', 'isbn': '',
        'page_start': '', 'page_end': '', 'affiliation': '',
    }
    # 版面驱动：按「行 + 字号」定位，而非对合并后的 block 跑正则
    lines, page_h = _collect_lines(path)
    if not lines:
        return meta

    # 旋转扫描件（逐字竖排）走老路径
    blocks, _ = _collect_blocks(path)
    single = [b for b in blocks if len(b['text']) == 1 and _cjk_count(b['text']) == 1]
    if len(single) >= 6:
        rotated = _recover_rotated(single)
        if rotated.get('title') or rotated.get('authors'):
            return rotated

    head = ' '.join(ln['text'] for ln in lines[:10])
    for match in _YEAR_RE.finditer(head):
        candidate = int(match.group())
        if 1900 <= candidate <= _CURRENT_YEAR + 1:
            meta['year'] = candidate
            break

    # 卷期/页码常出现在页眉/页脚（running head），扫整页而非仅前几行
    wide = ' '.join(ln['text'] for ln in lines)
    vol = re.search(r'(?i)\b(?:19|20)\d{2}\s*Vol[.．]?\s*(\d+)\s*[,，]?\s*(?:No[.．]?\s*(\d+))?', wide)
    if vol:
        meta['volume'] = vol.group(1) or ''
        meta['issue'] = vol.group(2) or ''

    _extract_cn_vol_issue(meta, wide)
    _extract_cn_identifiers(meta, wide)
    _extract_cn_journal(meta, lines)

    top = [ln for ln in lines if ln['y0'] < page_h * 0.55 and _cjk_count(ln['text']) >= 3]
    title_lines = [ln for ln in top if _is_plausible_title(ln['text'], 3)]
    if title_lines:
        anchor = max(title_lines, key=lambda ln: (ln['size'], -ln['y0']))
        joined, title_y1 = _join_title_lines(lines, anchor)
        meta['title'] = joined
        # 同一标题被重复两遍时（部分版式把标题拆成两行同文）取半
        half = len(meta['title']) // 2
        if half >= 4 and meta['title'][:half] == meta['title'][half:half + half]:
            meta['title'] = meta['title'][:half]
        meta['confidence'] = 0.85
        title_block = {'y1': title_y1, 'size': anchor['size']}
        meta['authors'] = _extract_cn_authors(lines, title_block, page_h)
        meta['affiliation'] = _extract_cn_affiliation(lines, title_y1, page_h)
        if re.search(r'图书在版编目|CIP|ISBN', head):
            meta['is_book'] = True

    return meta


def _year_from_text(text: Any, title: str) -> int | None:
    body = str(text or '')
    cut = re.search(r'摘要|关键词|abstract', body, flags=re.I)
    if cut:
        body = body[:cut.start()]
    probe = title + ' ' + body[:400]
    for match in _YEAR_RE.finditer(probe):
        candidate = int(match.group())
        if 1900 <= candidate <= _CURRENT_YEAR + 1:
            return candidate
    return None


def extract_cn_metadata(
    text: str = '',
    filename: str = '',
    path: str | Path | None = None,
) -> tuple[LibraryEntry | None, str]:
    src = Path(path).expanduser().resolve() if path else None
    stem = src.stem if src is not None else filename
    fn = parse_cn_filename(stem)
    fm = _extract_cn_frontmatter(src) if src is not None else {}

    title = fn.get('title') or fm.get('title')
    if not title:
        return None, ''

    source = 'cn-filename' if fn.get('title') else 'cn-frontmatter'
    is_book = bool(fn.get('is_book') or fm.get('is_book'))
    entry = LibraryEntry(
        item_type='book' if is_book else 'journalArticle',
        title=title,
        language='zh',
    )
    authors = fn.get('authors') or fm.get('authors') or []
    entry.creators = [Creator(family=name) for name in authors if name]
    entry.year = fn.get('year') or fm.get('year') or _year_from_text(text, title)
    if not entry.year:
        # 兜底：文章编号里的（YYYY）即年份，如 1000-3363(2019)05-01
        _am = re.search(r'[（(](20\d{2})[)）]', fm.get('article_no') or '')
        if _am:
            entry.year = int(_am.group(1))
    entry.volume = fm.get('volume') or ''
    entry.issue = fm.get('issue') or ''
    entry.doi = fm.get('doi') or ''
    entry.publication_title = fm.get('journal') or ''
    if is_book:
        entry.isbn = fm.get('isbn') or ''
    extra = {}
    for key, label in (
        ('article_no', 'articleNo'),
        ('clc', 'clc'),
        ('received_date', 'receivedDate'),
        ('page_start', 'pageStart'),
        ('page_end', 'pageEnd'),
        ('journal', 'journal'),
        ('affiliation', 'affiliation'),
    ):
        value = fm.get(key)
        if value:
            extra[label] = value
    if extra:
        entry.extra.update(extra)
    return entry, source
