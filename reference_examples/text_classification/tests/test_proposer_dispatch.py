import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import meta_harness


def _fake_result(exit_code=0):
    r = types.SimpleNamespace(exit_code=exit_code, stderr="", show=lambda: None)
    return r


class DispatchTests(unittest.TestCase):
    def test_dispatch_opencode(self):
        with mock.patch.object(meta_harness.opencode_wrapper, "run", return_value=_fake_result()) as oc, \
             mock.patch.object(meta_harness.claude_wrapper, "run") as cc, \
             mock.patch.object(meta_harness, "PENDING_EVAL") as pe:
            pe.exists.return_value = True
            ok = meta_harness.propose("task", 1, backend="opencode", model="prov/m", effort="max")
        self.assertTrue(ok)
        oc.assert_called_once()
        cc.assert_not_called()
        self.assertEqual(oc.call_args.kwargs["model"], "prov/m")

    def test_dispatch_claude(self):
        with mock.patch.object(meta_harness.claude_wrapper, "run", return_value=_fake_result()) as cc, \
             mock.patch.object(meta_harness.opencode_wrapper, "run") as oc, \
             mock.patch.object(meta_harness, "PENDING_EVAL") as pe:
            pe.exists.return_value = True
            ok = meta_harness.propose("task", 1, backend="claude", model="opus", effort="max")
        self.assertTrue(ok)
        cc.assert_called_once()
        oc.assert_not_called()


if __name__ == "__main__":
    unittest.main()
