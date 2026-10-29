import unittest

from raggg.generation.prompt_builder import build_prompt


class PromptCitationTests(unittest.TestCase):
    def test_prompt_requires_sentence_end_citations(self) -> None:
        prompt = build_prompt("端口如何设置？", [])

        self.assertIn("[1][2]", prompt)
        self.assertIn("句末", prompt)
        self.assertIn("不得编造", prompt)


if __name__ == "__main__":
    unittest.main()
