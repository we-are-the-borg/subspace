#!/usr/bin/env python3
"""Reference interpreter for subspace mapping documents (docs/model.md §5).

Applies a mapping document (model/<source>.json, format 1) to one raw hook
payload and prints the result object:

    python3 tools/model/apply.py model/codex.json < payload.json

Test tooling for CI and for checking golden files, never part of the hook.
Apps implement their own interpreter against the same golden files; this one
is the reference for what §5 means.
"""

import json
import sys

FORMAT = 1
RULE_KEYS = {"when", "path", "parse", "pick", "each", "map", "type", "default", "note"}
CONDITION_KEYS = {"path", "in"}

# Sentinel for "no value", distinct from a JSON null.
NONE = object()


def resolve(doc, pointer):
    """RFC 6901 JSON Pointer; NONE when it leads nowhere."""
    if not isinstance(pointer, str) or (pointer and not pointer.startswith("/")):
        return NONE
    if pointer == "":
        return doc
    value = doc
    for token in pointer[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict):
            if token not in value:
                return NONE
            value = value[token]
        elif isinstance(value, list):
            if not token.isdigit() or (len(token) > 1 and token[0] == "0"):
                return NONE
            index = int(token)
            if index >= len(value):
                return NONE
            value = value[index]
        else:
            return NONE
    return value


def has_type(value, name):
    if name == "any":
        return True
    if name == "string":
        return isinstance(value, str)
    if name == "id":
        return isinstance(value, str) and value != ""
    if name == "boolean":
        return isinstance(value, bool)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "null":
        return value is None
    return False  # an unknown type name never matches


def holds(condition, payload):
    if not isinstance(condition, dict) or set(condition) - CONDITION_KEYS:
        return False
    allowed = condition.get("in")
    if not isinstance(allowed, list):
        return False
    value = resolve(payload, condition.get("path"))
    return isinstance(value, str) and value in allowed


def applies(rule, payload):
    if not isinstance(rule, dict):
        return False
    when = rule.get("when", [])
    return isinstance(when, list) and all(holds(c, payload) for c in when)


def evaluate(rule, payload):
    """The rule's value, or NONE. The rule's `when` already held."""
    if set(rule) - RULE_KEYS:
        return NONE  # unknown operation: absent, never guessed
    paths = rule.get("path")
    paths = paths if isinstance(paths, list) else [paths]
    value = NONE
    for p in paths:
        value = resolve(payload, p)
        if value is not NONE:
            break
    if value is not NONE and "parse" in rule:
        if rule["parse"] != "json" or not isinstance(value, str):
            value = NONE
        else:
            try:
                value = json.loads(value)
            except ValueError:
                value = NONE
    if "pick" in rule:
        value = NONE if value is NONE or "parse" not in rule else resolve(value, rule["pick"])
    if value is not NONE and "each" in rule:
        if isinstance(value, list):
            value = [v for v in (field(rule["each"], item) for item in value) if v is not NONE]
        else:
            value = NONE
    if value is not NONE and "map" in rule:
        table = rule["map"]
        value = table[value] if isinstance(table, dict) and isinstance(value, str) and value in table else NONE
    if value is not NONE and "type" in rule:
        types = rule["type"] if isinstance(rule["type"], list) else [rule["type"]]
        if not any(isinstance(t, str) and has_type(value, t) for t in types):
            value = NONE
    if value is NONE and "default" in rule:
        value = rule["default"]
    return value


def field(spec, payload):
    rules = spec if isinstance(spec, list) else [spec]
    for rule in rules:
        if applies(rule, payload):
            return evaluate(rule, payload)
    return NONE


def apply(mapping, payload):
    """The result object for one payload; {} for an unknown format."""
    if not isinstance(mapping, dict) or mapping.get("format") != FORMAT:
        return {}
    result = {}
    for name, spec in (mapping.get("core") or {}).items():
        value = field(spec, payload)
        if value is not NONE:
            result[name] = value
    block = {}
    for name, spec in (mapping.get("fields") or {}).items():
        value = field(spec, payload)
        if value is not NONE:
            block[name] = value
    result[mapping.get("block")] = block
    return result


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: apply.py <mapping document> < payload.json")
    with open(sys.argv[1], encoding="utf-8") as f:
        mapping = json.load(f)
    payload = json.load(sys.stdin)
    json.dump(apply(mapping, payload), sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
