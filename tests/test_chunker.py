import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.chunker import TextChunker

class TestTextChunker(unittest.TestCase):

    def test_short_text_single_chunk(self):
        c = TextChunker(100)
        self.assertEqual(c.chunk('hello world'), ['hello world'])

    def test_empty_text(self):
        c = TextChunker(100)
        self.assertEqual(c.chunk(''), [])
        self.assertEqual(c.chunk('   \n  '), [])

    def test_max_size_respected(self):
        c = TextChunker(100)
        text = 'A sentence here. ' * 50
        chunks = c.chunk(text)
        self.assertGreater(len(chunks), 1)
        for ch in chunks:
            self.assertLessEqual(len(ch), 100)

    def test_no_data_loss(self):

        c = TextChunker(80)
        text = 'First part here. Second part goes on. Third keeps going. ' * 10
        chunks = c.chunk(text)
        joined = ''.join(''.join(ch.split()) for ch in chunks)
        original = ''.join(text.split())
        self.assertEqual(joined, original)

    def test_prefers_sentence_boundary(self):
        c = TextChunker(60)
        text = ('Short sentence one. ' * 10)
        chunks = c.chunk(text)

        for ch in chunks[:-1]:
            self.assertTrue(ch.rstrip().endswith('.'))

    def test_cjk_without_punctuation_terminates(self):
        # 无 .?! 也无空格的纯中文长文本不应死循环
        c = TextChunker(200)
        text = '这是一段没有标点没有空格的中文长文本' * 50
        chunks = c.chunk(text)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(''.join(chunks), text)

if __name__ == '__main__':
    unittest.main()

