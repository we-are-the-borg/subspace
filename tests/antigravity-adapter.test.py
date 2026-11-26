"""Checks the shipped Antigravity adapter, fixture excerpts and e2e checker."""
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
ADAPTER = REPO / "adapters/antigravity"
SPOOL = ADAPTER / "scripts/spool.sh"
CHECK = REPO / "tools/e2e/check.sh"
SHELL = os.environ.get("ADAPTER_SH", "sh")
FLAT_EVENTS = ("SessionStart", "PreInvocation", "PostInvocation", "Stop")
GROUPED_EVENTS = ("PreToolUse", "PostToolUse")


class AntigravityAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="antigravity adapter ")
        self.addCleanup(self.temp.cleanup)
        self.here = Path(self.temp.name)

    def run_spool(self, payload, *, root=None, plugin_data=None, event=None):
        env = os.environ.copy()
        for name in (
            "SUBSPACE_DIR", "CLAUDE_PLUGIN_DATA", "PLUGIN_DATA",
            "CLAUDE_PLUGIN_OPTION_RETENTION_DAYS",
        ):
            env.pop(name, None)
        if root is not None:
            env["SUBSPACE_DIR"] = str(root)
        if plugin_data is not None:
            env["PLUGIN_DATA"] = str(plugin_data)
        return subprocess.run(
            [SHELL, str(SPOOL), "antigravity"] + ([event] if event else []),
            input=payload, capture_output=True, env=env, timeout=3,
        )

    @staticmethod
    def files(root):
        return list((root / "events").glob("*/*.json"))

    def test_manifest_hooks_dist_and_release_config(self):
        manifest = json.loads((ADAPTER / ".antigravity-plugin/plugin.json").read_text())
        self.assertEqual(manifest["name"], "subspace")
        version = manifest["version"]
        self.assertNotIn("userConfig", manifest)
        self.assertTrue((ADAPTER / manifest["logo"]).is_file())
        # Native plugins must place hooks.json at the plugin root, not hooks/hooks.json.
        self.assertFalse((ADAPTER / "hooks/hooks.json").exists())

        hooks_text = (ADAPTER / "hooks.json").read_text()
        self.assertNotIn('"async"', hooks_text)
        hooks = json.loads(hooks_text)
        self.assertEqual(set(hooks), {"subspace"})
        group = hooks["subspace"]
        self.assertEqual(set(group), set(FLAT_EVENTS) | set(GROUPED_EVENTS))
        for event in FLAT_EVENTS:
            marker = " session-start" if event == "SessionStart" else ""
            self.assertEqual(group[event], [{
                "type": "command",
                "command": "sh ./scripts/spool.sh antigravity" + marker,
            }], msg=event)
        for event in GROUPED_EVENTS:
            self.assertEqual(group[event], [{
                "matcher": "*",
                "hooks": [{
                    "type": "command",
                    "command": "sh ./scripts/spool.sh antigravity",
                }],
            }], msg=event)

        self.assertTrue((REPO / "tools/dist/antigravity/README.md").is_file())

        releases = json.loads((REPO / "release-please-config.json").read_text())
        package = releases["packages"]["adapters/antigravity"]
        self.assertEqual(package["component"], "antigravity")
        self.assertEqual(package.get("initial-version"), "1.0.0")
        self.assertEqual(package["extra-files"], [
            {"type": "json", "path": ".antigravity-plugin/plugin.json",
             "jsonpath": "$.version"},
        ])
        versions = json.loads((REPO / ".release-please-manifest.json").read_text())
        self.assertEqual(versions.get("adapters/antigravity", version), version)

    def test_plugin_data_fallback_spaces_raw_bytes_and_isolation(self):
        root = self.here / "plugin data with spaces"
        ignored = self.here / "ignored plugin data"
        payload = (
            ' {\r\n "hookEventName":"Stop",'
            '"terminationReason":"NO_TOOL_CALL",'
            '"text":"\\n \\u65e5\\u672c \\ud83d\\ude80"\r\n}\n'
        ).encode()
        result = self.run_spool(payload, plugin_data=root)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"", b""))
        event = self.files(root)[0]
        envelope = event.read_bytes()
        self.assertTrue(envelope.endswith(b'"payload":' + payload + b"}"))
        self.assertEqual(json.loads(envelope)["source"], "antigravity")

        result = self.run_spool(
            b'{"hookEventName":"Stop"}', root=root, plugin_data=ignored,
        )
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"", b""))
        self.assertEqual(len(self.files(root)), 2)
        self.assertEqual(self.files(ignored), [])

    def test_hook_command_works_from_spaced_plugin_root(self):
        plugin_root = self.here / "plugin root with spaces"
        shutil.copytree(ADAPTER, plugin_root)
        root = self.here / "data root with spaces"
        command = json.loads((plugin_root / "hooks.json").read_text())[
            "subspace"
        ]["Stop"][0]["command"]
        env = os.environ.copy()
        env.update(PLUGIN_ROOT=str(plugin_root), PLUGIN_DATA=str(root))
        for name in ("SUBSPACE_DIR", "CLAUDE_PLUGIN_DATA"):
            env.pop(name, None)
        result = subprocess.run(
            [SHELL, "-c", command], cwd=plugin_root,
            input=b'{"hookEventName":"Stop"}',
            capture_output=True, env=env, timeout=3,
        )
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"", b""))
        self.assertEqual(json.loads(self.files(root)[0].read_text())["source"], "antigravity")

    def test_session_start_writes_version_schema_model_and_default_retention(self):
        root = self.here / "root"
        today = datetime.datetime.now(datetime.timezone.utc).date()
        for age in (3, 4):
            (root / "events" / str(today - datetime.timedelta(days=age))).mkdir(parents=True)
        payload = b'{"hookEventName":"SessionStart","conversationId":"conv-1"}'
        result = self.run_spool(payload, root=root, event="session-start")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"", b""))
        version = json.loads((ADAPTER / ".antigravity-plugin/plugin.json").read_text())["version"]
        self.assertEqual(json.loads((root / "plugin.json").read_text()),
                         {"v": 1, "version": version})
        for name in ("envelope.v1.json", "mapping.v1.json", "result.v1.json"):
            self.assertEqual((root / "schema" / name).read_bytes(),
                             (ADAPTER / "schema" / name).read_bytes())
        self.assertEqual((root / "model/antigravity.json").read_bytes(),
                         (ADAPTER / "model/antigravity.json").read_bytes())
        self.assertTrue((root / "events" / str(today - datetime.timedelta(days=3))).is_dir())
        self.assertFalse((root / "events" / str(today - datetime.timedelta(days=4))).exists())

    def test_unset_and_write_errors_are_silent(self):
        result = self.run_spool(b'{"hookEventName":"Stop"}')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"", b""))
        blocked = self.here / "blocked"
        blocked.write_text("not a directory")
        result = self.run_spool(b'{"hookEventName":"Stop"}', root=blocked)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"", b""))
        self.assertEqual(blocked.read_text(), "not a directory")


class AntigravityFixtureTests(unittest.TestCase):
    def test_transcript_excerpts_link_parallel_children_to_parent(self):
        scenario = REPO / "fixtures/antigravity/1.5.17/2-parallel-subagents"
        records = [json.loads(line) for line in
                   (scenario / "transcripts/excerpt.jsonl").read_text().splitlines()]
        parent = "9387948b-0c36-40db-986f-d38d89d7b6dc"
        children = {
            "91921677-ee57-400f-8371-5ea165c7bfd2",
            "eb79fbb4-b523-43b2-ba16-e221db8df6f5",
        }
        parent_spawns = [r for r in records if r["conversation_id"] == parent]
        self.assertEqual(len(parent_spawns), 2)
        for child in children:
            self.assertTrue(any(child in r["content"] for r in parent_spawns))
            child_recs = [r for r in records if r["conversation_id"] == child]
            self.assertEqual(len(child_recs), 1)
            self.assertIn(f"sender={parent}", child_recs[0]["content"])

        events = [json.loads(p.read_text()) for p in sorted((scenario / "events").glob("*.json"))]
        recipients = {
            e["conversationId"]: e["toolCall"]["args"]["Recipient"]
            for e in events
            if e["hookEventName"] == "PreToolUse" and e["toolCall"]["name"] == "send_message"
        }
        self.assertEqual(recipients, {child: parent for child in children})


class AntigravityCheckerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="antigravity checker ")
        self.addCleanup(self.temp.cleanup)
        self.here = Path(self.temp.name)

    def day(self, envelopes):
        day = self.here / f"day-{len(list(self.here.glob('day-*')))}"
        day.mkdir(mode=0o700)
        for index, envelope in enumerate(envelopes):
            path = day / f"{index}.json"
            path.write_text(json.dumps(envelope))
            path.chmod(0o600)
        return day

    def test_e2e_checker_validates_antigravity_fixtures_and_rejects_bad_event_key(self):
        fixture = next((REPO / "fixtures/antigravity").glob("*/*/events/*.json"))
        payload = json.loads(fixture.read_text())
        env = {"v": 1, "source": "antigravity", "ts": 1, "pid": 2, "payload": payload}
        result = subprocess.run(
            [SHELL, str(CHECK), str(self.day([env]))],
            capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("OK", result.stdout)

        bad = {"v": 1, "source": "antigravity", "ts": 1, "pid": 2,
               "payload": {"hookEventName": 42}}
        result = subprocess.run(
            [SHELL, str(CHECK), str(self.day([bad]))],
            capture_output=True, text=True, timeout=5,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FAILED", result.stdout)


if __name__ == "__main__":
    unittest.main()
