import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.tokenizer import assemble, build_chunks, tokenize_markdown
from src.core.pipeline import _translate_chunk, estimate_job


SAMPLE_MD = r"""# The Electric Field

The field is given by $E = mc^2$ and the mass by $m = E / c^2$.

$$
\nabla \cdot \mathbf{E} = \frac{\rho}{\varepsilon_0} \tag{1}
$$

As shown in Eq. (1),<sup>3</sup> the result follows. The code is:

```python
for i in range(10):
    print(i)
```

![](images/fig1.jpg)
FIG. 1. The setup.
"""


class FakeProvider:
    """模拟翻译：默认按原样返回（行数不变），可配置合并行触发兜底。"""

    def __init__(self, merge_lines=False):
        self.calls = []
        self.merge_lines = merge_lines

    def _translate(self, text, target_lang, source_lang='en'):
        self.calls.append(text)
        if self.merge_lines and '\n' in text:
            return text.replace('\n', ' ')
        return '【' + text + '】'


class TestMarkdownTokenizer(unittest.TestCase):

    def test_identity_roundtrip(self):
        tokens = tokenize_markdown(SAMPLE_MD)
        chunks = build_chunks(tokens, 1350)
        trans_map = {ci: '\n'.join(p for _, p in ch['pieces'])
                     for ci, ch in enumerate(chunks)}
        out = assemble(tokens, chunks, trans_map)
        self.assertEqual(out, SAMPLE_MD)

    def test_formulas_kept(self):
        tokens = tokenize_markdown(SAMPLE_MD)
        kept = ''.join(c for k, c in tokens if k == 'keep')
        self.assertIn(r'$E = mc^2$', kept)
        self.assertIn(r'\nabla \cdot \mathbf{E}', kept)
        self.assertIn(r'\tag{1}', kept)

    def test_code_and_links_kept(self):
        tokens = tokenize_markdown(SAMPLE_MD)
        kept = ''.join(c for k, c in tokens if k == 'keep')
        self.assertIn('```python', kept)
        self.assertIn('print(i)', kept)
        self.assertIn('![](images/fig1.jpg)', kept)
        self.assertIn('<sup>3</sup>', kept)

    def test_text_tokens_have_no_newlines(self):
        tokens = tokenize_markdown(SAMPLE_MD)
        for kind, content in tokens:
            if kind == 'text':
                self.assertNotIn('\n', content)

    def test_prose_is_translated(self):
        tokens = tokenize_markdown(SAMPLE_MD)
        texts = ''.join(c for k, c in tokens if k == 'text')
        self.assertIn('The field is given by', texts)

    def test_plain_markdown_no_false_protection(self):
        tokens = tokenize_markdown('hello **world** and _italics_ here')
        self.assertEqual(''.join(c for k, c in tokens if k == 'text'),
                         'hello **world** and _italics_ here')

    def test_lone_dollar_does_not_swallow_rest(self):
        # 孤立 $（如货币符号）不能吞掉后续正文
        doc = 'The cost is US$ 5 per unit.\n\nMust still be translated.'
        tokens = tokenize_markdown(doc)
        texts = ''.join(c for k, c in tokens if k == 'text')
        self.assertIn('Must still be translated', texts)

    def test_inline_math_same_line_only(self):
        # 孤立 $（无同行闭合）按普通文本
        tokens = tokenize_markdown('Price $5 here.')
        self.assertIn('$5', ''.join(c for k, c in tokens if k == 'text'))
        # 正常行内公式仍被保护
        tokens = tokenize_markdown('Math $E = mc^2$ stays.')
        self.assertIn('$E = mc^2$', ''.join(c for k, c in tokens if k == 'keep'))

    def test_block_math_across_lines(self):
        doc = 'Prose here.\n\n$$\n\\nabla \\phi = 0 \\tag{1}\n$$\n\nMore prose.'
        tokens = tokenize_markdown(doc)
        kept = ''.join(c for k, c in tokens if k == 'keep')
        self.assertIn(r'\nabla \phi = 0', kept)
        self.assertIn('Prose here.', ''.join(c for k, c in tokens if k == 'text'))

    def test_unclosed_backtick_does_not_swallow_rest(self):
        doc = 'Text with `unclosed code and more text after.'
        tokens = tokenize_markdown(doc)
        texts = ''.join(c for k, c in tokens if k == 'text')
        self.assertIn('more text after', texts)


class TestChunkFallback(unittest.TestCase):

    def test_normal_path_single_call(self):
        chunk = {'pieces': [(0, 'First piece.'), (1, 'Second piece.')]}
        provider = FakeProvider()
        result = _translate_chunk(provider, chunk, 'zh-Hans', 'en')
        self.assertEqual(result, '【First piece.\nSecond piece.】')
        self.assertEqual(len(provider.calls), 1)

    def test_merged_lines_fallback_per_piece(self):
        chunk = {'pieces': [(0, 'First piece.'), (1, 'Second piece.')]}
        provider = FakeProvider(merge_lines=True)
        result = _translate_chunk(provider, chunk, 'zh-Hans', 'en')
        self.assertEqual(result.count('\n'), 1)
        self.assertEqual(len(provider.calls), 3)
        self.assertEqual(provider.calls[1], 'First piece.')
        self.assertEqual(provider.calls[2], 'Second piece.')


class TestEstimateJob(unittest.TestCase):

    def _provider(self):
        return SimpleNamespace(meta=SimpleNamespace(
            max_chunk_chars=1350, max_chunks_per_sec=1.0))

    def test_md_estimate(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'paper.md'
            p.write_text(SAMPLE_MD * 30, encoding='utf-8')
            est = estimate_job(str(p), self._provider())
            self.assertGreater(est['chunks'], 1)
            self.assertGreater(est['chars'], 0)
            self.assertGreater(est['seconds'], 0)

    def test_plain_estimate(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'note.txt'
            p.write_text('A sentence here. ' * 500, encoding='utf-8')
            est = estimate_job(str(p), self._provider())
            self.assertGreater(est['chunks'], 1)
            self.assertGreater(est['chars'], 0)


if __name__ == '__main__':
    unittest.main()
