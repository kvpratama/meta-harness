import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import claude_wrapper

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "claude_stream.jsonl")


class ClaudeParseTests(unittest.TestCase):
    def setUp(self):
        with open(FIXTURE) as f:
            self.stdout = f.read()

    def test_parse_text_tokens_cost_session(self):
        r = claude_wrapper.parse_stream_events(
            self.stdout, "p", "opus", 1.0, 0, cwd="/work"
        )
        self.assertEqual(r.text, "All done.")
        self.assertEqual(r.session_id, "sess_abc")
        self.assertAlmostEqual(r.cost_usd, 0.0123)
        self.assertEqual(r.token_usage["input_tokens"], 150)
        self.assertEqual(r.token_usage["output_tokens"], 30)

    def test_parse_file_stats(self):
        r = claude_wrapper.parse_stream_events(
            self.stdout, "p", "opus", 1.0, 0, cwd="/work"
        )
        self.assertIn("a.py", r.files_read)
        self.assertEqual(r.files_read["a.py"]["reads"], 1)
        self.assertEqual(r.files_read["a.py"]["lines"], 2)
        self.assertIn("b.py", r.files_written)
        self.assertEqual(r.files_written["b.py"]["lines_written"], 3)

    def test_build_command_flags(self):
        cmd = claude_wrapper.build_command(
            "do it", "opus", ["Read", "Write"], "sys", effort="max"
        )
        self.assertEqual(cmd[0], "claude")
        self.assertIn("--dangerously-skip-permissions", cmd)
        self.assertIn("stream-json", cmd)
        self.assertIn("--append-system-prompt", cmd)
        self.assertIn("--effort", cmd)
        self.assertIn("opus", cmd)


if __name__ == "__main__":
    unittest.main()
