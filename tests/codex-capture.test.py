"""Synthetic capture-tool checks; never starts Codex or reads real rollouts."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "tools/hook-capture/codex"
SHELL = os.environ.get("CAPTURE_SH", "sh")


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="codex capture ")
        self.addCleanup(self.temp.cleanup)
        self.here = Path(self.temp.name)
        for name in ("log.sh", "collect.sh"):
            shutil.copyfile(SOURCE / name, self.here / name)
        self.events = self.here / "captures/events"

    def log(self, payload, **kwargs):
        return subprocess.run(
            [SHELL, str(self.here / "log.sh")], input=payload,
            capture_output=True, check=True, timeout=1, **kwargs,
        )

    def test_subscription(self):
        config = json.loads((SOURCE / ".codex/hooks.json").read_text())
        self.assertEqual(set(config), {"hooks"})
        self.assertEqual(set(config["hooks"]), {
            "SessionStart", "UserPromptSubmit", "PreToolUse",
            "PermissionRequest", "PostToolUse", "PreCompact", "PostCompact",
            "SubagentStart", "SubagentStop", "Stop", "Interrupt",
        })
        for groups in config["hooks"].values():
            self.assertEqual(groups, [{"hooks": [{
                "type": "command", "command": "sh ./log.sh", "async": True,
            }]}])

    def test_raw_bytes_metadata_and_deadline(self):
        payload = b' {\r\n "hook_event_name": "Interrupt", "text": "\\n\\\\"\r\n}\n\n'
        env = dict(os.environ, CODEX_CAPTURE_TEST="secret-a",
                   PLUGIN_CAPTURE_TEST="secret-b", CLAUDE_CAPTURE_TEST="secret-c",
                   SHELL="/example/shell")
        started = time.monotonic()
        result = self.log(payload, env=env)
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual((result.stdout, result.stderr), (b"", b""))
        files = list(self.events.glob("*.json"))
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].read_bytes(), payload)
        meta = files[0].with_suffix(".meta").read_text()
        self.assertIn(f"ppid={os.getpid()}\n", meta)
        self.assertIn("SHELL=/example/shell\n", meta)
        self.assertIn(f"argv0={self.here / 'log.sh'}\n", meta)
        for prefix in ("CODEX", "PLUGIN", "CLAUDE"):
            self.assertIn(f"  {prefix}_CAPTURE_TEST\n", meta)
        self.assertNotIn("secret-", meta)
        # Verify every ancestor from this test process through PID 1, including
        # its full ps row (comm and args), against a separate process snapshot.
        snapshot = subprocess.check_output(
            ["ps", "-ww", "-eo", "pid=,ppid=,comm=,args="], text=True,
        )
        rows = {int(row.split()[0]): row for row in snapshot.splitlines()}
        pid = os.getpid()
        while True:
            self.assertIn("  " + rows[pid] + "\n", meta)
            if pid == 1:
                break
            pid = int(rows[pid].split()[1])
        self.assertEqual(list(self.events.glob(".*")), [])

    def test_concurrent_writes(self):
        payload = '{"hook_event_name":"Stop","text":"日本 🚀"}\n'.encode()
        processes = [subprocess.Popen(
            [SHELL, str(self.here / "log.sh")], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ) for _ in range(12)]
        for process in processes:
            self.assertEqual(process.communicate(payload, timeout=5), (b"", b""))
            self.assertEqual(process.returncode, 0)
        files = list(self.events.glob("*.json"))
        self.assertEqual(len(files), 12)
        for file in files:
            self.assertEqual(file.read_bytes(), payload)
            self.assertTrue(file.with_suffix(".meta").is_file())
        self.assertEqual(list(self.events.glob(".*")), [])

    def test_unwritable_capture_is_silent(self):
        (self.here / "captures").write_text("directory blocked")
        result = self.log(b'{"hook_event_name":"Stop"}')
        self.assertEqual((result.stdout, result.stderr), (b"", b""))

    def test_collection_parent_child_spaces_and_missing(self):
        self.events.mkdir(parents=True)
        paths = []
        for directory, content in (("parent", b"parent bytes\r\n"),
                                   ('child "quoted"', b"child bytes\n")):
            path = self.here / directory / "rollout.jsonl"
            path.parent.mkdir()
            path.write_bytes(content)
            paths.append(path)
        (self.events / "pretty.json").write_text(json.dumps({
            "transcript_path": str(paths[0]), "agent_transcript_path": str(paths[1]),
        }, indent=2))
        (self.events / "nullable.json").write_text('{"transcript_path":null}')
        command = [SHELL, str(self.here / "collect.sh")]
        subprocess.run(command, check=True, capture_output=True)
        copies = list((self.here / "captures/transcripts").glob("*/rollout.jsonl"))
        self.assertEqual(len(copies), 2)
        self.assertEqual({p.read_bytes() for p in copies}, {p.read_bytes() for p in paths})
        for copy in copies:
            original = Path((copy.parent / "source.txt").read_text().strip())
            self.assertEqual(copy.read_bytes(), original.read_bytes())
        # Re-collection updates a rollout that was still being flushed.
        paths[0].write_bytes(b"updated parent\n")
        subprocess.run(command, check=True, capture_output=True)
        self.assertIn(b"updated parent\n", {p.read_bytes() for p in copies})
        (self.events / "missing.json").write_text(json.dumps({
            "transcript_path": str(self.here / "missing.jsonl"),
        }))
        (self.events / "invalid.json").write_text("invalid JSON")
        result = subprocess.run(command, capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"missing rollout:", result.stderr)
        self.assertIn(b"cannot read invalid.json:", result.stderr)


if __name__ == "__main__":
    unittest.main()
