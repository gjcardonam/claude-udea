import unittest
from unittest.mock import patch

from claude_udea.deps import check_and_install
from claude_udea.ollama_chat import parse_ollama_model_flag


class OllamaCliTests(unittest.TestCase):
    def test_extracts_model_flag_without_treating_it_as_course(self):
        args, model = parse_ollama_model_flag([
            "calidad-de-software",
            "--ollama-model",
            "mistral",
            "--ollama",
        ])

        self.assertEqual(args, ["calidad-de-software", "--ollama"])
        self.assertEqual(model, "mistral")

    def test_extracts_equals_model_flag(self):
        args, model = parse_ollama_model_flag(["--ollama-model=llama3.2:latest"])

        self.assertEqual(args, [])
        self.assertEqual(model, "llama3.2:latest")

    @patch("claude_udea.deps._choose_assistant", side_effect=AssertionError)
    @patch("claude_udea.deps._try_import", return_value=True)
    def test_skip_assistant_does_not_select_or_install_an_ai_cli(
        self,
        _try_import,
        _choose_assistant,
    ):
        self.assertTrue(check_and_install(skip_assistant=True))


if __name__ == "__main__":
    unittest.main()