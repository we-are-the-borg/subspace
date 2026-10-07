"""Checks the shipped Codex adapter and the source-aware end-to-end checker."""
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
ADAPTER = REPO / "adapters/codex"
SPOOL = ADAPTER / "scripts/spool.sh"
CHECK = REPO / "tools/e2e/check.sh"
STAGE = REPO / "tools/e2e/codex-stage.py"
SHELL = os.environ.get("ADAPTER_SH", "sh")
EVENTS = {
    "SessionStart", "UserPromptSubmit", "PreToolUse", "PermissionRequest",
    "PostToolUse", "PreCompact", "PostCompact", "SubagentStart",
    "SubagentStop", "Stop", "Interrupt",
}


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="codex adapter ")
        self.addCleanup(self.temp.cleanup)
        self.here = Path(self.temp.name)

    def run_spool(self, payload, *, root=None, plugin_data=None, event=None):
        env = os.environ.copy()
        for name in ("SUBSPACE_DIR", "CLAUDE_PLUGIN_DATA",
                     "CLAUDE_PLUGIN_OPTION_RETENTION_DAYS"):
            env.pop(name, None)
        if root is not None:
            env["SUBSPACE_DIR"] = str(root)
        if plugin_data is not None:
            env["CLAUDE_PLUGIN_DATA"] = str(plugin_data)
        return subprocess.run(
            [SHELL, str(SPOOL), "codex"] + ([event] if event else []), input=payload,
            capture_output=True, env=env, timeout=3,
        )

    @staticmethod
    def files(root):
        return list((root / "events").glob("*/*.json"))

    def test_manifest_hooks_marketplace_and_release_config(self):
        manifest = json.loads((ADAPTER / ".codex-plugin/plugin.json").read_text())
        self.assertEqual(manifest["name"], "subspace")
        version = manifest["version"]
        self.assertNotIn("userConfig", manifest)
        self.assertNotIn("Never blocks", manifest["description"])

        hooks = json.loads((ADAPTER / "hooks/hooks.json").read_text())["hooks"]
        self.assertEqual(set(hooks), EVENTS)
        for event, groups in hooks.items():
            marker = " session-start" if event == "SessionStart" else ""
            self.assertEqual(groups, [{"hooks": [{
                "type": "command",
                "command": 'sh "${PLUGIN_ROOT}/scripts/spool.sh" codex' + marker,
                "async": True,
            }]}])

        # The marketplace lives in the dist repo we-are-the-borg/subspace-codex,
        # whose root is the plugin; tools/dist/assemble.sh copies this template.
        marketplace = json.loads(
            (REPO / "tools/dist/codex/.agents/plugins/marketplace.json").read_text()
        )
        plugin = marketplace["plugins"][0]
        self.assertEqual(marketplace["name"], "subspace")
        self.assertEqual(plugin["name"], "subspace")
        self.assertEqual(plugin["source"], "./")

        releases = json.loads((REPO / "release-please-config.json").read_text())
        package = releases["packages"]["adapters/codex"]
        self.assertEqual(package["component"], "codex")
        # The first release from this repository is the go-live release.
        self.assertEqual(package.get("initial-version"), "1.0.0")
        self.assertEqual(package["extra-files"], [
            {"type": "json", "path": ".codex-plugin/plugin.json",
             "jsonpath": "$.version"},
        ])
        versions = json.loads((REPO / ".release-please-manifest.json").read_text())
        # Empty until the first release.
        self.assertEqual(versions.get("adapters/codex", version), version)

    def test_plugin_data_fallback_spaces_raw_bytes_and_isolation(self):
        root = self.here / "plugin data with spaces"
        ignored = self.here / "ignored plugin data"
        payload = (' {\r\n "hook_event_name":"Stop",'
                   '"text":"\\n \\u65e5\\u672c \\ud83d\\ude80"\r\n}\n').encode()
        result = self.run_spool(payload, plugin_data=root)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"", b""))
        event = self.files(root)[0]
        envelope = event.read_bytes()
        self.assertTrue(envelope.endswith(b'"payload":' + payload + b"}"))
        self.assertEqual(json.loads(envelope)["source"], "codex")

        result = self.run_spool(b'{"hook_event_name":"Stop"}',
                                root=root, plugin_data=ignored)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"", b""))
        self.assertEqual(len(self.files(root)), 2)
        self.assertEqual(self.files(ignored), [])

    def test_hook_command_works_through_outer_shell_with_spaced_plugin_root(self):
        plugin_root = self.here / "plugin root with spaces"
        shutil.copytree(ADAPTER, plugin_root)
        root = self.here / "data root with spaces"
        command = json.loads((plugin_root / "hooks/hooks.json").read_text())[
            "hooks"
        ]["Stop"][0]["hooks"][0]["command"]
        env = os.environ.copy()
        env.update(PLUGIN_ROOT=str(plugin_root), CLAUDE_PLUGIN_DATA=str(root))
        env.pop("SUBSPACE_DIR", None)
        result = subprocess.run(
            [SHELL, "-c", command], input=b'{"hook_event_name":"Stop"}',
            capture_output=True, env=env, timeout=3,
        )
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, b"", b""))
        self.assertEqual(json.loads(self.files(root)[0].read_text())["source"], "codex")

    def test_session_start_writes_version_schema_and_default_retention(self):
        root = self.here / "root"
        today = datetime.datetime.now(datetime.timezone.utc).date()
        for age in (3, 4):
            old = root / "events" / str(today - datetime.timedelta(days=age))
            old.mkdir(parents=True)
        payload = b'{"hook_event_name":"SessionStart","transcript_path":null}'
        result = self.run_spool(payload, root=root, event="session-start")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"", b""))
        version = json.loads(
            (ADAPTER / ".codex-plugin/plugin.json").read_text()
        )["version"]
        self.assertEqual(json.loads((root / "plugin.json").read_text()),
                         {"v": 1, "version": version})
        self.assertEqual((root / "schema/envelope.v1.json").read_bytes(),
                         (ADAPTER / "schema/envelope.v1.json").read_bytes())
        self.assertEqual((root / "model/codex.json").read_bytes(),
                         (ADAPTER / "model/codex.json").read_bytes())
        self.assertTrue((root / "events" / str(today - datetime.timedelta(days=3))).is_dir())
        self.assertFalse((root / "events" / str(today - datetime.timedelta(days=4))).exists())

    def test_unset_and_write_errors_are_silent(self):
        result = self.run_spool(b'{"hook_event_name":"Stop"}')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"", b""))
        blocked = self.here / "blocked"
        blocked.write_text("not a directory")
        result = self.run_spool(b'{"hook_event_name":"Stop"}', root=blocked)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"", b""))
        self.assertEqual(blocked.read_text(), "not a directory")

    def test_disposable_marketplace_staging_revisions_and_no_overwrite(self):
        expected = {
            "baseline": ("0.0.0", False),
            "version-only": ("0.0.1", False),
            "changed-hook": ("0.0.2", True),
        }
        source_command = json.loads((ADAPTER / "hooks/hooks.json").read_text())[
            "hooks"
        ]["SessionStart"][0]["hooks"][0]["command"]
        for revision, (version, changed) in expected.items():
            destination = self.here / f"stage {revision}"
            result = subprocess.run(
                ["python3", str(STAGE), str(destination),
                 "--revision", revision],
                capture_output=True, text=True, timeout=5,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(
                (destination / "codex/.codex-plugin/plugin.json").read_text()
            )
            self.assertEqual(manifest["version"], version)
            staged_command = json.loads(
                (destination / "codex/hooks/hooks.json").read_text()
            )["hooks"]["SessionStart"][0]["hooks"][0]["command"]
            self.assertEqual(staged_command, source_command + (" " if changed else ""))
            marketplace = json.loads(
                (destination / ".agents/plugins/marketplace.json").read_text()
            )
            self.assertEqual(marketplace["plugins"][0]["source"], "./codex")

            marker = destination / "keep"
            marker.write_text("unchanged")
            again = subprocess.run(
                ["python3", str(STAGE), str(destination)],
                capture_output=True, text=True, timeout=5,
            )
            self.assertNotEqual(again.returncode, 0)
            self.assertEqual(marker.read_text(), "unchanged")


class FixtureTests(unittest.TestCase):
    def test_session_meta_excerpt_links_children_to_spawn_responses(self):
        scenario = (REPO / "fixtures/codex/0.159.3/"
                    "1-headless-parallel-reused-child-failure")
        records = [json.loads(line) for line in
                   (scenario / "rollouts/session_meta.jsonl").read_text().splitlines()]
        self.assertEqual(len(records), 3)
        for record in records:
            self.assertEqual(record["type"], "session_meta")
            metadata = record["payload"]
            self.assertEqual(metadata["creator_user_id"], "user-REDACTED")
            self.assertEqual(metadata["creator_account_id"],
                             "00000000-0000-0000-0000-000000000000")
            self.assertEqual(metadata["base_instructions"]["text"], "<omitted>")

        root, *children = [record["payload"] for record in records]
        self.assertEqual(root["id"], root["session_id"])
        self.assertEqual(root["source"], "exec")
        self.assertNotIn("parent_thread_id", root)
        events = [json.loads(path.read_text())
                  for path in sorted((scenario / "events").glob("*.json"))]
        spawn_paths = set()
        for event in events:
            self.assertEqual(event["session_id"], root["id"])
            if (event["hook_event_name"] == "PostToolUse" and
                    event.get("tool_name") == "collaborationspawn_agent"):
                self.assertNotIn("agent_id", event)
                spawn_paths.add(json.loads(event["tool_response"])["task_name"])
        self.assertEqual(spawn_paths, {"/root/alpha", "/root/beta"})
        self.assertEqual([child["source"]["subagent"]["thread_spawn"]["agent_path"]
                          for child in children], ["/root/alpha", "/root/beta"])
        self.assertEqual(len({root["id"], *(child["id"] for child in children)}), 3)
        self.assertEqual({event["agent_id"] for event in events if "agent_id" in event},
                         {child["id"] for child in children})
        for child in children:
            self.assertEqual(child["session_id"], root["id"])
            self.assertEqual(child["parent_thread_id"], root["id"])
            spawn = child["source"]["subagent"]["thread_spawn"]
            self.assertEqual(spawn["parent_thread_id"], root["id"])
            self.assertEqual(child["agent_path"], spawn["agent_path"])
            self.assertIn(spawn["agent_path"], spawn_paths)
            starts = [event for event in events
                      if event["hook_event_name"] == "SubagentStart" and
                      event.get("agent_id") == child["id"]]
            self.assertEqual(len(starts), 1)
            self.assertIn(child["id"], Path(starts[0]["transcript_path"]).name)


class CheckerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="codex checker ")
        self.addCleanup(self.temp.cleanup)
        self.here = Path(self.temp.name)
        self.fixture = self.here / "fixtures"
        self.fixture.mkdir(mode=0o700)
        (self.fixture / "Stop.json").write_text(
            '{"hook_event_name":"Stop","transcript_path":null}'
        )

    def day(self, envelopes):
        day = self.here / f"day-{len(list(self.here.glob('day-*')))}"
        day.mkdir(mode=0o700)
        for index, envelope in enumerate(envelopes):
            path = day / f"{index}.json"
            if isinstance(envelope, dict):
                path.write_text(json.dumps(envelope))
            else:
                path.write_text(envelope)
            path.chmod(0o600)
        return day

    @staticmethod
    def envelope(source="codex", **changes):
        value = {
            "v": 1, "source": source, "ts": 1, "pid": 2,
            "payload": {"hook_event_name": "Stop", "transcript_path": None},
        }
        value.update(changes)
        return value

    def check(self, day, *fixtures):
        return subprocess.run(
            [SHELL, str(CHECK), str(day), *(str(x) for x in fixtures)],
            capture_output=True, text=True, timeout=5,
        )

    def test_explicit_fixtures_accept_both_sources_and_null_transcript(self):
        for source in ("claude-code", "codex"):
            with self.subTest(source=source):
                result = self.check(self.day([self.envelope(source)]), self.fixture)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("OK", result.stdout)

    def test_default_fixtures_follow_source(self):
        for source in ("claude-code", "codex"):
            with self.subTest(source=source):
                fixture = next((REPO / "fixtures" / source).glob("*/*/events/*.json"))
                payload = json.loads(fixture.read_text())
                result = self.check(self.day([self.envelope(source, payload=payload)]))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_rejects_mixed_unsupported_and_malformed_sources(self):
        cases = {
            "mixed": [self.envelope("codex"), self.envelope("claude-code")],
            "unsupported": [self.envelope("other")],
            "malformed": ["not json"],
            "multiple": [json.dumps(self.envelope()) + "\n" +
                         json.dumps(self.envelope())],
        }
        for name, envelopes in cases.items():
            with self.subTest(name=name):
                result = self.check(self.day(envelopes), self.fixture)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("FAILED", result.stdout)

    def test_rejects_invalid_envelope_values_and_payload_types(self):
        invalid = {
            "extra": self.envelope(extra=True),
            "version": self.envelope(v=2),
            "source": self.envelope(source=None),
            "ts-negative": self.envelope(ts=-1),
            "ts-fraction": self.envelope(ts=1.5),
            "pid-zero": self.envelope(pid=0),
            "pid-string": self.envelope(pid="2"),
            "payload": self.envelope(payload=[]),
            "event": self.envelope(payload={"hook_event_name": None}),
            "transcript": self.envelope(payload={
                "hook_event_name": "Stop", "transcript_path": 3,
            }),
        }
        for name, envelope in invalid.items():
            with self.subTest(name=name):
                result = self.check(self.day([envelope]), self.fixture)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("FAILED", result.stdout)


if __name__ == "__main__":
    unittest.main()
