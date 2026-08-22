import os
import time

from .progress import ProgressManager
from .tokenizer import (
    GLOSSARY, assemble, build_chunks, tokenize, tokenize_markdown,
)
from .chunker import TextChunker

PLAIN_FORMATS = ('.txt', '.srt', '.vtt', '.json', '.csv')
MD_FORMATS = ('.md', '.markdown')


def translate_file(file_path: str, provider, target_lang: str = 'zh-Hans',
                   source_lang: str = 'en', output_path: str = None,
                   resume: bool = True, progress_cb=None, cancel_flag=None,
                   progress_path: str = None, usage_cb=None) -> str:

    with open(file_path, encoding='utf-8') as f:
        content = f.read()

    suffix = os.path.splitext(file_path)[1].lower()
    progress = ProgressManager(progress_path) if resume else None

    if output_path is None:
        base, ext = os.path.splitext(file_path)
        output_path = f'{base}-翻译{ext}'

    try:
        if suffix == '.tex':
            result = _translate_tokens(
                file_path, tokenize(content), provider, target_lang,
                source_lang, progress, progress_cb, cancel_flag, usage_cb)
        elif suffix in MD_FORMATS:
            result = _translate_tokens(
                file_path, tokenize_markdown(content), provider, target_lang,
                source_lang, progress, progress_cb, cancel_flag, usage_cb)
        else:
            result = _translate_plain(
                file_path, content, provider, target_lang, source_lang,
                progress, progress_cb, cancel_flag, usage_cb)
    finally:
        if progress:
            progress.flush()

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(result)
    return output_path


def _translate_tokens(file_path: str, tokens, provider, target_lang,
                      source_lang, progress, progress_cb, cancel_flag,
                      usage_cb) -> str:

    chunks = build_chunks(tokens, provider.meta.max_chunk_chars or 1350)
    total = len(chunks)
    trans_map = {}

    for ci, ch in enumerate(chunks):
        if cancel_flag and cancel_flag():
            raise InterruptedError('用户取消')
        cached = progress.get_chunk(file_path, ci) if progress else None
        if cached is not None:
            trans_map[ci] = cached
        else:
            translated = _translate_chunk(provider, ch, target_lang, source_lang)
            trans_map[ci] = translated
            if usage_cb:
                usage_cb(sum(len(piece) for _, piece in ch['pieces']))
            if progress:
                progress.set_chunk(file_path, ci, translated)
            _pace(provider)
        if progress_cb:
            progress_cb(ci + 1, total, f'块 {ci + 1}/{total}')

    result = assemble(tokens, chunks, trans_map)
    for a, b in GLOSSARY:
        result = result.replace(a, b)
    return result


def _translate_chunk(provider, chunk, target_lang, source_lang) -> str:
    """翻译一个块；译文行数与原文段数对不上时，逐段单独翻译兜底。"""

    pieces = chunk['pieces']
    text = '\n'.join(piece for _, piece in pieces)
    translated = _call_with_retry(provider, text, target_lang, source_lang)
    if translated.count('\n') == len(pieces) - 1:
        return translated

    # 行数对应不上（DeepL 合并/拆分了换行）：逐段单独请求，
    # 保证 assemble 的逐行映射成立，代价是本次多几次请求。
    parts = []
    for _, piece in pieces:
        parts.append(_call_with_retry(provider, piece, target_lang, source_lang))
    return '\n'.join(parts)


def _translate_plain(file_path: str, content: str, provider, target_lang,
                     source_lang, progress, progress_cb, cancel_flag,
                     usage_cb) -> str:

    max_chars = provider.meta.max_chunk_chars or 1350
    chunker = TextChunker(max_chars)
    chunks = chunker.chunk(content)
    total = len(chunks)
    results = []

    for i, ch in enumerate(chunks):
        if cancel_flag and cancel_flag():
            raise InterruptedError('用户取消')
        cached = progress.get_chunk(file_path, i) if progress else None
        if cached is not None:
            results.append(cached)
        else:
            translated = _call_with_retry(provider, ch, target_lang, source_lang)
            results.append(translated)
            if usage_cb:
                usage_cb(len(ch))
            if progress:
                progress.set_chunk(file_path, i, translated)
            _pace(provider)
        if progress_cb:
            progress_cb(i + 1, total, f'块 {i + 1}/{total}')

    result = '\n\n'.join(results)
    for a, b in GLOSSARY:
        result = result.replace(a, b)
    return result


def estimate_job(file_path: str, provider) -> dict:
    """开工前预估：块数、字符数、预计耗时（不发起任何网络请求）。"""

    with open(file_path, encoding='utf-8') as f:
        content = f.read()

    suffix = os.path.splitext(file_path)[1].lower()
    max_chars = provider.meta.max_chunk_chars or 1350
    if suffix == '.tex':
        chunks = build_chunks(tokenize(content), max_chars)
        chars = sum(len(piece) for ch in chunks for _, piece in ch['pieces'])
    elif suffix in MD_FORMATS:
        chunks = build_chunks(tokenize_markdown(content), max_chars)
        chars = sum(len(piece) for ch in chunks for _, piece in ch['pieces'])
    else:
        plain = TextChunker(max_chars).chunk(content)
        chunks = [{'pieces': [(i, ch)]} for i, ch in enumerate(plain)]
        chars = sum(len(ch) for ch in plain)

    rps = provider.meta.max_chunks_per_sec or 1.0
    return {
        'chunks': len(chunks),
        'chars': chars,
        'seconds': len(chunks) / rps,
    }


def _call_with_retry(provider, text: str, target_lang: str,
                     source_lang: str = 'en', max_retries: int = 5,
                     cooldown_base: float = 60.0):

    cooldown = cooldown_base
    for attempt in range(max_retries):
        translated = provider._translate(text, target_lang, source_lang)
        if translated is not None:
            return translated

        time.sleep(cooldown)
        cooldown = min(cooldown * 1.4, 15 * 60)
    raise RuntimeError('连续 429 限流，放弃')


def _pace(provider):

    rps = provider.meta.max_chunks_per_sec or 1.0
    if rps > 0:
        time.sleep(1.0 / rps)
