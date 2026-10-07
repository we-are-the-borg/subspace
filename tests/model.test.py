#!/usr/bin/env python3
"""Mapping documents (model/<source>.json) against the golden files, and the
reference interpreter (tools/model/apply.py) against docs/model.md §5.

    python3 tests/model.test.py
"""

import importlib.util
import json
import pathlib
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("apply", REPO / "tools/model/apply.py")
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class GoldenFiles(unittest.TestCase):
    """docs/model.md §7: every fixture event and its expected result."""

    def runs(self):
        return sorted(p.parent for p in REPO.glob("fixtures/*/*/*/events"))

    def test_there_are_fixtures(self):
        self.assertTrue(self.runs())

    def test_events_and_expected_pair_up(self):
        for run in self.runs():
            with self.subTest(run=str(run.relative_to(REPO))):
                events = sorted(p.name for p in (run / "events").glob("*.json"))
                expected = sorted(p.name for p in (run / "expected").glob("*.json"))
                self.assertEqual(events, expected)

    def test_mapping_reproduces_every_golden_file(self):
        for run in self.runs():
            source = run.relative_to(REPO / "fixtures").parts[0]
            mapping = load(REPO / "model" / f"{source}.json")
            self.assertEqual(mapping["source"], source)
            for event in sorted((run / "events").glob("*.json")):
                with self.subTest(event=str(event.relative_to(REPO))):
                    self.assertEqual(model.apply(mapping, load(event)),
                                     load(run / "expected" / event.name))

    def test_adapters_ship_their_own_mapping(self):
        for adapter in sorted(REPO.glob("adapters/*/")):
            with self.subTest(adapter=adapter.name):
                own = [n for n in (f"{adapter.name}.json", f"{adapter.name}-session.json")
                       if (REPO / "model" / n).exists()]
                shipped = sorted(p.name for p in (adapter / "model").glob("*.json"))
                self.assertEqual(shipped, sorted(own))
                for n in own:
                    self.assertEqual((adapter / "model" / n).read_bytes(),
                                     (REPO / "model" / n).read_bytes())


class SchemasPerSource(unittest.TestCase):
    """Each adapter ships the shared schemas plus its own (tools/sync.sh), and the
    per-source result schemas agree on the core (docs/model.md §2, §11)."""

    def test_adapters_ship_shared_and_own_schemas(self):
        shared = sorted(p.name for p in (REPO / "schema").glob("*.json"))
        for adapter in sorted(REPO.glob("adapters/*/")):
            with self.subTest(adapter=adapter.name):
                own = sorted(p.name for p in (REPO / "schema" / adapter.name).glob("*.json"))
                shipped = sorted(p.name for p in (adapter / "schema").glob("*.json"))
                self.assertEqual(shipped, sorted(shared + own))

    def test_result_schemas_share_the_core(self):
        def core(source):
            schema = load(REPO / "schema" / source / "result.v1.json")
            result = schema["$defs"]["result"]
            block = source.replace("-", "_")
            props = {k: v for k, v in result["properties"].items() if k != block}
            return props, result["required"][:-1], schema["$defs"]["id"]
        sources = sorted(p.name for p in (REPO / "schema").iterdir() if p.is_dir())
        self.assertEqual(sources, ["claude-code", "codex"])
        self.assertEqual(core("claude-code"), core("codex"))


class SessionStatusGoldenFiles(unittest.TestCase):
    """docs/model.md §12: every status snapshot and its expected result."""

    def runs(self):
        return sorted(p.parent for p in REPO.glob("fixtures/*/*/*/status"))

    def test_there_are_status_fixtures(self):
        self.assertTrue(self.runs())

    def test_status_and_expected_pair_up(self):
        for run in self.runs():
            with self.subTest(run=str(run.relative_to(REPO))):
                status = sorted(p.name for p in (run / "status").glob("*.json"))
                expected = sorted(p.name for p in (run / "status-expected").glob("*.json"))
                self.assertEqual(status, expected)

    def test_mapping_reproduces_every_golden_file(self):
        for run in self.runs():
            source = run.relative_to(REPO / "fixtures").parts[0]
            mapping = load(REPO / "model" / f"{source}-session.json")
            self.assertEqual((mapping["source"], mapping["document"]), (source, "session-status"))
            for snapshot in sorted((run / "status").glob("*.json")):
                with self.subTest(snapshot=str(snapshot.relative_to(REPO))):
                    self.assertEqual(model.apply(mapping, load(snapshot)),
                                     load(run / "status-expected" / snapshot.name))

    def test_timeline_names_every_file(self):
        for run in self.runs():
            with self.subTest(run=str(run.relative_to(REPO))):
                with open(run / "timeline.jsonl", encoding="utf-8") as f:
                    named = sorted(json.loads(line)["file"] for line in f if '"file"' in line)
                files = sorted(f"{d}/{p.name}" for d in ("events", "status")
                               for p in (run / d).glob("*.json"))
                self.assertEqual(named, files)

    def test_unknown_status_leaves_state_absent(self):
        mapping = load(REPO / "model" / "claude-code-session.json")
        result = model.apply(mapping, {"sessionId": "s", "status": "thinking"})
        self.assertEqual(result, {"session": "s", "claude_code_session": {"status": "thinking"}})
        result = model.apply(mapping, {"status": "waiting", "waitingFor": "something new"})
        self.assertEqual(result, {"state": "waiting", "claude_code_session": {
            "status": "waiting", "waiting_text": "something new"}})


def doc(fields=None, core=None, fmt=1):
    return {"format": fmt, "source": "t", "block": "t", "core": core or {},
            "fields": fields or {}}


def run(fields, payload):
    return model.apply(doc(fields), payload)["t"]


class Interpreter(unittest.TestCase):
    """docs/model.md §5.1, rule by rule."""

    def test_unknown_format_applies_nothing(self):
        self.assertEqual(model.apply(doc({"a": {"path": "/a"}}, fmt=2), {"a": 1}), {})
        self.assertEqual(model.apply({"core": {}, "fields": {}}, {}), {})

    def test_block_is_always_present_and_core_on_top(self):
        result = model.apply(doc({"a": {"path": "/x"}}, core={"s": {"path": "/s"}}), {"s": "1"})
        self.assertEqual(result, {"s": "1", "t": {}})

    def test_path_pointer_and_escaping(self):
        payload = {"a": {"b/c": {"~d": [10, 20]}}}
        self.assertEqual(run({"v": {"path": "/a/b~1c/~0d/1"}}, payload), {"v": 20})
        self.assertEqual(run({"v": {"path": "/a/b~1c/~0d/2"}}, payload), {})
        self.assertEqual(run({"v": {"path": "/a/b~1c/~0d/01"}}, payload), {})
        self.assertEqual(run({"v": {"path": "no-slash"}}, payload), {})

    def test_fallback_paths_first_existing_wins_and_null_exists(self):
        spec = {"path": ["/new", "/old"]}
        self.assertEqual(run({"v": spec}, {"old": 1}), {"v": 1})
        self.assertEqual(run({"v": spec}, {"new": 2, "old": 1}), {"v": 2})
        self.assertEqual(run({"v": spec}, {"new": None, "old": 1}), {"v": None})

    def test_first_applying_rule_decides_even_without_value(self):
        spec = [{"when": [{"path": "/h", "in": ["Stop"]}], "path": "/child"},
                {"path": "/parent"}]
        self.assertEqual(run({"v": spec}, {"h": "Stop", "parent": "p"}), {})
        self.assertEqual(run({"v": spec}, {"h": "Other", "parent": "p"}), {"v": "p"})

    def test_when_needs_a_listed_string(self):
        spec = {"when": [{"path": "/h", "in": ["1"]}], "path": "/v"}
        self.assertEqual(run({"v": spec}, {"h": 1, "v": "x"}), {})
        self.assertEqual(run({"v": spec}, {"v": "x"}), {})

    def test_parse_and_pick(self):
        spec = {"path": "/r", "parse": "json", "pick": "/task"}
        self.assertEqual(run({"v": spec}, {"r": '{"task":"/root/a"}'}), {"v": "/root/a"})
        self.assertEqual(run({"v": spec}, {"r": "not json"}), {})
        self.assertEqual(run({"v": spec}, {"r": {"task": "x"}}), {})
        self.assertEqual(run({"v": {"path": "/r", "pick": "/task"}}, {"r": {"task": "x"}}), {})

    def test_each_projects_and_filters_elements(self):
        spec = {"path": "/tasks",
                "each": {"when": [{"path": "/type", "in": ["agent"]}], "path": "/id", "type": "id"}}
        tasks = [{"type": "agent", "id": "a"}, {"type": "shell", "id": "s"},
                 {"type": "agent", "id": ""}, {"type": "agent"}, "text", {"type": "agent", "id": "b"}]
        self.assertEqual(run({"v": spec}, {"tasks": tasks}), {"v": ["a", "b"]})
        self.assertEqual(run({"v": spec}, {"tasks": []}), {"v": []})
        self.assertEqual(run({"v": spec}, {"tasks": {"type": "agent", "id": "a"}}), {})
        self.assertEqual(run({"v": spec}, {}), {})
        rules = [{"when": [{"path": "/k", "in": ["x"]}], "path": "/x"}, {"path": "/y"}]
        self.assertEqual(run({"v": {"path": "/l", "each": rules}},
                             {"l": [{"k": "x", "x": 1, "y": 2}, {"y": 3}, {"k": "x", "y": 4}]}),
                         {"v": [1, 3]})
        self.assertEqual(run({"v": {"path": "/l", "each": {"path": "/i", "split": ","}}},
                             {"l": [{"i": "a,b"}]}), {"v": []})

    def test_map(self):
        spec = {"path": "/h", "map": {"Stop": "turn.stop"}, "default": "unknown"}
        self.assertEqual(run({"v": spec}, {"h": "Stop"}), {"v": "turn.stop"})
        self.assertEqual(run({"v": spec}, {"h": "New"}), {"v": "unknown"})
        self.assertEqual(run({"v": spec}, {}), {"v": "unknown"})

    def test_types(self):
        def typed(t, value):
            return run({"v": {"path": "/v", "type": t}}, {"v": value})
        self.assertEqual(typed("id", ""), {})
        self.assertEqual(typed("id", "x"), {"v": "x"})
        self.assertEqual(typed("integer", True), {})
        self.assertEqual(typed("integer", 3), {"v": 3})
        self.assertEqual(typed("number", 1.5), {"v": 1.5})
        self.assertEqual(typed(["string", "null"], None), {"v": None})
        self.assertEqual(typed("object", []), {})
        self.assertEqual(typed("nonsense", "x"), {})

    def test_values_are_copied_unchanged(self):
        opaque = {"a": [1, None, {"b": 2.5}]}
        self.assertEqual(run({"v": {"path": "/o"}}, {"o": opaque}), {"v": opaque})

    def test_unknown_keys_make_the_field_absent(self):
        self.assertEqual(run({"v": {"path": "/v", "split": ","}}, {"v": "a,b"}), {})
        self.assertEqual(run({"v": {"path": "/v", "split": ",", "default": "d"}}, {"v": "a"}), {})
        spec = {"when": [{"path": "/h", "in": ["x"], "regex": "."}], "path": "/v"}
        self.assertEqual(run({"v": spec}, {"h": "x", "v": 1}), {})

    def test_never_fails_on_malformed_payloads(self):
        for payload in (None, [], "text", 3, {"hook_event_name": 5}):
            with self.subTest(payload=payload):
                for source in ("claude-code", "codex"):
                    result = model.apply(load(REPO / "model" / f"{source}.json"), payload)
                    self.assertEqual(result["kind"], "unknown")
                result = model.apply(load(REPO / "model" / "claude-code-session.json"), payload)
                self.assertEqual(result, {"claude_code_session": {}})


if __name__ == "__main__":
    unittest.main()
