import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.tokenizer import assemble, build_chunks, tokenize

SAMPLE = r"""\section{The Electric Field}
The electric field $\mathbf{E}$ at a point is the force per unit charge:
\begin{equation}
    \mathbf{F} = q\mathbf{E} \quad \text{where } q \text{ is the charge}
\end{equation}
% this comment must survive
Coulomb's law states that the force varies inversely as the square
of the distance between two charges, as in $F = k_e q_1 q_2 / r^2$.
See \label{eq:coulomb} and \ref{eq:coulomb} for details, \textbf{bold text} included.
\[
    \nabla \cdot \mathbf{E} = \frac{\rho}{\epsilon_0}
\]
"""

class TestTokenizer(unittest.TestCase):

    def test_identity_roundtrip(self):

        tokens = tokenize(SAMPLE)
        chunks = build_chunks(tokens, 1350)
        trans_map = {ci: '\n'.join(p for _, p in ch['pieces'])
                     for ci, ch in enumerate(chunks)}
        out = assemble(tokens, chunks, trans_map)
        self.assertEqual(out, SAMPLE)

    def test_math_is_kept(self):
        tokens = tokenize(SAMPLE)
        keep_texts = [t[1] for t in tokens if t[0] == 'keep']
        joined = ''.join(keep_texts)

        self.assertIn(r'\begin{equation}', joined)
        self.assertIn(r'\mathbf{F} = q\mathbf{E}', joined)
        self.assertIn(r'\nabla \cdot \mathbf{E}', joined)

        self.assertIn('% this comment must survive', joined)

    def test_text_extracted_from_recurse_commands(self):
        tokens = tokenize(r'\section{The Electric Field}')
        texts = [t[1] for t in tokens if t[0] == 'text']
        self.assertTrue(any('The Electric Field' in t for t in texts))

    def test_protected_commands_not_extracted(self):
        tokens = tokenize(r'\label{eq:coulomb} and \ref{eq:coulomb}')
        texts = [t[1] for t in tokens if t[0] == 'text']

        self.assertFalse(any('eq:coulomb' in t for t in texts))

    def test_escaped_braces_in_math(self):

        s = r'Text $x \in \left\{ 1, 2 \right\}$ after.'
        tokens = tokenize(s)
        chunks = build_chunks(tokens, 1350)
        trans_map = {ci: '\n'.join(p for _, p in ch['pieces'])
                     for ci, ch in enumerate(chunks)}
        out = assemble(tokens, chunks, trans_map)
        self.assertEqual(out, s)

    def test_empty_and_plain(self):
        self.assertEqual(tokenize(''), [])
        tokens = tokenize('just plain text')
        self.assertEqual(tokens, [('text', 'just plain text')])

    def test_chunk_limits(self):
        long_text = ('A sentence with enough words to exceed limit. ' * 30)
        tokens = tokenize(long_text)
        chunks = build_chunks(tokens, 100)
        for ch in chunks:
            total = sum(len(p) + 1 for _, p in ch['pieces'])
            self.assertLessEqual(total, 100 + 60)

    def test_verbatim_env_protected(self):
        s = r'Before \begin{verbatim}for i in range(10): print(i)\end{verbatim} after'
        tokens = tokenize(s)
        texts = ''.join(t[1] for t in tokens if t[0] == 'text')
        self.assertIn('Before', texts)
        self.assertIn('after', texts)
        self.assertNotIn('range(10)', texts)
        kept = ''.join(t[1] for t in tokens if t[0] == 'keep')
        self.assertIn('print(i)', kept)

    def test_verb_and_lstinline_protected(self):
        tokens = tokenize(r'Use \verb|python3 -m pip| and \lstinline|x_1^2| here.')
        texts = ''.join(t[1] for t in tokens if t[0] == 'text')
        self.assertNotIn('python3', texts)
        self.assertNotIn('x_1', texts)
        kept = ''.join(t[1] for t in tokens if t[0] == 'keep')
        self.assertIn(r'\verb|python3 -m pip|', kept)
        self.assertIn(r'\lstinline|x_1^2|', kept)

    def test_title_author_recurse(self):
        tokens = tokenize(r'\title{A Novel Approach} \author{Jane Doe}')
        texts = ''.join(t[1] for t in tokens if t[0] == 'text')
        self.assertIn('A Novel Approach', texts)
        self.assertIn('Jane Doe', texts)

if __name__ == '__main__':
    unittest.main()

