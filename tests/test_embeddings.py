import unittest

from raggg.indexing.embeddings import tokenize


class EmbeddingTokenTests(unittest.TestCase):
    def test_chinese_tokens_include_overlapping_bigrams(self) -> None:
        tokens = tokenize("波端口方向")

        self.assertIn("端口", tokens)
        self.assertIn("方向", tokens)
        self.assertIn("口方", tokens)
        self.assertIn("口", tokens)

    def test_ascii_terms_remain_whole_and_lowercase(self) -> None:
        self.assertEqual(tokenize("WavEDA S11"), ["waveda", "s11"])


if __name__ == "__main__":
    unittest.main()
