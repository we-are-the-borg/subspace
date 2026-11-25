"""Synthetic capture-tool checks; never starts Antigravity or reads real transcripts."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "tools/hook-capture/antigravity"
SHELL = os.environ.get("CAPTURE_SH", "sh")
EXPECTED_COMMAND = "if [ -f ../log.sh ]; then exec sh ../log.sh; else exec sh ./log.sh; fi"
FLAT_EVENTS = ("SessionStart", "PreInvocation", "PostInvocation", "Stop")
GROUPED_EVENTS = ("PreToolUse", "PostToolUse")


class AntigravityCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="antigravity capture ")
        self.addCleanup(self.temp.cleanup)
        self.here = Path(self.temp.name)
        for name in ("log.sh", "collect.sh"):
            shutil.copyfile(SOURCE / name, self.here / name)
        (self.here / ".agents").mkdir()
        shutil.copyfile(SOURCE / ".agents/hooks.json", self.here / ".agents/hooks.json")
        self.events = self.here / "captures/events"

    def log(self, payload, **kwargs):
        return subprocess.run(
            [SHELL, str(self.here / "log.sh")], input=payload,
            capture_output=True, check=True, timeout=1, **kwargs,
        )

    def test_subscription(self):
        config = json.loads((SOURCE / ".agents/hooks.json").read_text())
        self.assertEqual(set(config), {"subspace-capture"})
        group = config["subspace-capture"]
        self.assertEqual(set(group), set(FLAT_EVENTS) | set(GROUPED_EVENTS))
        handler = {"type": "command", "command": EXPECTED_COMMAND}
        for event in FLAT_EVENTS:
            self.assertEqual(group[event], [handler], msg=event)
        for event in GROUPED_EVENTS:
            self.assertEqual(
                group[event], [{"matcher": "*", "hooks": [handler]}], msg=event
            )
        # Antigravity hooks are synchronous; no async key should be declared.
        self.assertNotIn('"async"', (SOURCE / ".agents/hooks.json").read_text())

    def test_hooks_command_works_from_agents_dir_and_workspace_root(self):
        config = json.loads((self.here / ".agents/hooks.json").read_text())
        command = config["subspace-capture"]["SessionStart"][0]["command"]
        for label, cwd in (
            ("agents-dir", self.here / ".agents"),
            ("workspace-root", self.here),
        ):
            with self.subTest(label):
                payload = json.dumps({
                    "hookEventName": "SessionStart",
                    "conversationId": f"conv-{label}",
                }).encode()
                result = subprocess.run(
                    [SHELL, "-c", command], cwd=cwd, input=payload,
                    capture_output=True, check=True, timeout=1,
                )
                self.assertEqual((result.stdout, result.stderr), (b"", b""))
        files = sorted(self.events.glob("*.json"))
        self.assertEqual(len(files), 2)
        pwds = set()
        for f in files:
            meta = f.with_suffix(".meta").read_text()
            for line in meta.splitlines():
                if line.startswith("pwd="):
                    pwds.add(Path(line.split("=", 1)[1]).resolve())
        self.assertEqual(pwds, {(self.here / ".agents").resolve(), self.here.resolve()})
        self.assertEqual(list(self.events.glob(".*")), [])

    def test_raw_bytes_metadata_and_deadline(self):
        payload = (
            b' {\r\n "hookEventName": "PreToolUse",\r\n'
            b' "conversationId": "ec33ebf9-0cba-4100-8142-c61503f6c587",\r\n'
            b' "toolCall": {"id": "toolu_01", "name": "run_command", '
            b'"args": {"CommandLine": "printf \\"\\\\n\\""}}\r\n}\n\n'
        )
        env = dict(
            os.environ,
            AGY_CAPTURE_TEST="secret-a",
            ANTIGRAVITY_CAPTURE_TEST="secret-b",
            GEMINI_CAPTURE_TEST="secret-c",
            GOOGLE_CAPTURE_TEST="secret-d",
            PLUGIN_CAPTURE_TEST="secret-e",
            CLAUDE_CAPTURE_TEST="secret-f",
            TERM_PROGRAM="WarpTerminal",
            WARP_FOCUS_URL="warp://session/0123456789abcdef0123456789abcdef",
            SHELL="/example/shell",
        )
        started = time.monotonic()
        result = self.log(payload, env=env, cwd=self.here)
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual((result.stdout, result.stderr), (b"", b""))
        files = list(self.events.glob("*.json"))
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].read_bytes(), payload)
        meta = files[0].with_suffix(".meta").read_text()
        self.assertIn(f"ppid={os.getpid()}\n", meta)
        self.assertIn(f"pwd={self.here.resolve()}\n", meta)
        self.assertIn("SHELL=/example/shell\n", meta)
        self.assertIn(f"argv0={self.here / 'log.sh'}\n", meta)
        for prefix in ("AGY", "ANTIGRAVITY", "GEMINI", "GOOGLE", "PLUGIN", "CLAUDE"):
            self.assertIn(f"  {prefix}_CAPTURE_TEST\n", meta)
        self.assertNotIn("secret-", meta)
        self.assertIn("  TERM_PROGRAM=WarpTerminal\n", meta)
        self.assertIn(
            "  WARP_FOCUS_URL=warp://session/0123456789abcdef0123456789abcdef\n", meta
        )
        # Verify every ancestor from this test process through PID 1 against a
        # separate process snapshot.
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
        payload = '{"hookEventName":"Stop","terminationReason":"NO_TOOL_CALL","text":"日本 🚀"}\n'.encode()
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
        result = self.log(b'{"hookEventName":"Stop"}')
        self.assertEqual((result.stdout, result.stderr), (b"", b""))

    def test_collection_camel_case_same_basename_spaces_and_missing(self):
        self.events.mkdir(parents=True)
        paths = []
        for directory, content in (
            ("session-a", b'{"step":1}\r\n'),
            ('session "quoted"', b'{"step":2}\n'),
        ):
            path = self.here / directory / "transcript.jsonl"
            path.parent.mkdir()
            path.write_bytes(content)
            paths.append(path)
        (self.events / "pretty.json").write_text(json.dumps({
            "hookEventName": "Stop",
            "transcriptPath": str(paths[0]),
            "agentTranscriptPath": str(paths[1]),
        }, indent=2))
        (self.events / "nullable.json").write_text('{"hookEventName":"SessionStart","transcriptPath":null}')
        (self.events / "empty.json").write_text('{"hookEventName":"SessionStart","transcriptPath":""}')
        command = [SHELL, str(self.here / "collect.sh")]
        subprocess.run(command, check=True, capture_output=True)
        copies = list((self.here / "captures/transcripts").glob("*/transcript.jsonl"))
        self.assertEqual(len(copies), 2)
        self.assertEqual({p.read_bytes() for p in copies}, {p.read_bytes() for p in paths})
        for copy in copies:
            original = Path((copy.parent / "source.txt").read_text().strip())
            self.assertEqual(copy.read_bytes(), original.read_bytes())
        # Re-collection updates a transcript that was still being flushed.
        paths[0].write_bytes(b'{"step":1,"flushed":true}\n')
        subprocess.run(command, check=True, capture_output=True)
        self.assertIn(b'{"step":1,"flushed":true}\n', {p.read_bytes() for p in copies})
        (self.events / "missing.json").write_text(json.dumps({
            "transcriptPath": str(self.here / "missing.jsonl"),
        }))
        (self.events / "relative.json").write_text(json.dumps({
            "transcriptPath": "relative/transcript.jsonl",
        }))
        (self.events / "invalid.json").write_text("invalid JSON")
        result = subprocess.run(command, capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"missing transcript:", result.stderr)
        self.assertIn(b"relative transcriptPath:", result.stderr)
        self.assertIn(b"cannot read invalid.json:", result.stderr)


if __name__ == "__main__":
    unittest.main()
