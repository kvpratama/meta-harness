import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import opencode_wrapper as ow

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "opencode_run.jsonl")


class MapToolsTests(unittest.TestCase):
    def test_maps_and_dedups(self):
        perms = ow.map_tools(["Read", "Glob", "Grep", "Agent", "Write", "Edit", "Bash"])
        self.assertEqual(perms, ["read", "glob", "grep", "task", "edit", "bash"])


class AgentFileTests(unittest.TestCase):
    def test_contains_frontmatter_tools_and_body(self):
        md = ow.build_agent_file("SKILL BODY", "extra sys", ["Read", "Write", "Bash"], "anthropic/claude-opus-4")
        self.assertTrue(md.startswith("---\n"))
        self.assertIn("model: anthropic/claude-opus-4", md)
        self.assertIn("  read: true", md)
        self.assertIn("  edit: true", md)
        self.assertIn("  bash: true", md)
        self.assertIn("SKILL BODY", md)
        self.assertIn("extra sys", md)


class BuildCommandTests(unittest.TestCase):
    def test_flags(self):
        cmd = ow.build_command("do it", "anthropic/claude-opus-4", "mh-proposer-x", effort="max")
        self.assertEqual(cmd[:2], ["opencode", "run"])
        self.assertIn("--format", cmd)
        self.assertIn("json", cmd)
        self.assertIn("--dangerously-skip-permissions", cmd)
        self.assertEqual(cmd[cmd.index("--agent") + 1], "mh-proposer-x")
        self.assertEqual(cmd[cmd.index("--model") + 1], "anthropic/claude-opus-4")
        self.assertEqual(cmd[cmd.index("--variant") + 1], "max")
        self.assertIn("--pure", cmd)
        self.assertEqual(cmd[-1], "do it")


class ParseEventsTests(unittest.TestCase):
    def setUp(self):
        with open(FIXTURE) as f:
            self.stdout = f.read()

    def test_text_session_cost_tokens(self):
        r = ow.parse_events(self.stdout, "p", "m", 1.0, 0, cwd="/tmp/oc_fix")
        self.assertEqual(r.text, "Done.")
        self.assertEqual(r.session_id, "ses_test01")
        self.assertAlmostEqual(r.cost_usd, 0.003)
        self.assertEqual(r.token_usage["input_tokens"], 10312 + 73 + 53)
        self.assertEqual(r.token_usage["output_tokens"], 52 + 69 + 3)

    def test_tool_calls_and_file_stats(self):
        r = ow.parse_events(self.stdout, "p", "m", 1.0, 0, cwd="/tmp/oc_fix")
        names = [tc.name for tc in r.tool_calls]
        self.assertEqual(names, ["read", "write"])
        self.assertIn("sample.txt", r.files_read)
        self.assertEqual(r.files_read["sample.txt"]["lines"], 2)
        self.assertIn("out.txt", r.files_written)
        self.assertEqual(r.files_written["out.txt"]["lines_written"], 1)


if __name__ == "__main__":
    unittest.main()
