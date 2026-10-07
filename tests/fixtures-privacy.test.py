#!/usr/bin/env python3
"""Fails on personal data in the repository, above all in captured fixtures.

The rules are generic on purpose: they name no real person, account or
machine. See fixtures/README.md ("Anonymization") for what a capture must
replace before it is added.
"""
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SELF = Path(__file__).resolve()

ZERO_UUID = "00000000-0000-0000-0000-000000000000"
ALLOWED_EMAIL_DOMAINS = {"example.com", "example.org", "github.com"}
ACCOUNT_KEYS = ("organizationUuid", "organization_uuid", "accountUuid",
                "account_uuid", "account_id", "creator_account_id",
                "user_id", "creator_user_id")
ACCOUNT_PLACEHOLDERS = {ZERO_UUID, "user-REDACTED", ""}

FORBIDDEN = {
    "home directory other than /Users/user": re.compile(r"/Users/(?!user(?:/|\b))[^/\s\"'`]+"),
    "Linux home directory other than /home/user": re.compile(r"/home/(?!user(?:/|\b))[^/\s\"'`]+"),
    "Windows home directory": re.compile(r"[A-Za-z]:\\\\?Users\\\\?(?!user\b)\w+"),
    "encoded home other than -Users-user-": re.compile(r"-Users-(?!user-)[A-Za-z0-9._]+-"),
    "macOS per-user temp folder": re.compile(r"/var/folders/[\w+]{2}/"),
    "credential": re.compile(r"sk-ant-[\w-]+|\bghp_\w{20,}|\bgithub_pat_\w+|\bxox[abp]-[\w-]+|\bAKIA[0-9A-Z]{16}\b|-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "instruction-file dump": re.compile(r"Contents of /\S+ \((?:user's|project instructions)|private global instructions"),
}
EMAIL = re.compile(r"[\w.%+-]+@([\w-]+(?:\.[\w-]+)+)")
ACCOUNT = re.compile(r'"(%s)"\s*:\s*"([^"]*)"' % "|".join(ACCOUNT_KEYS))


def text_files():
    for path in sorted(REPO.rglob("*")):
        if not path.is_file() or ".git" in path.relative_to(REPO).parts:
            continue
        if path == SELF or "captures" in path.relative_to(REPO).parts:
            continue
        try:
            yield path, path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue


class PrivacyTests(unittest.TestCase):
    def test_no_personal_data(self):
        problems = []
        for path, text in text_files():
            rel = path.relative_to(REPO)
            for what, pattern in FORBIDDEN.items():
                for match in pattern.finditer(text):
                    problems.append(f"{rel}: {what}: {match.group(0)[:80]}")
            for match in EMAIL.finditer(text):
                if match.group(1).lower() not in ALLOWED_EMAIL_DOMAINS and \
                        not match.group(1).lower().endswith(".noreply.github.com"):
                    problems.append(f"{rel}: e-mail address: {match.group(0)}")
            for match in ACCOUNT.finditer(text):
                if match.group(2) not in ACCOUNT_PLACEHOLDERS:
                    problems.append(f"{rel}: account identifier {match.group(1)}")
        self.assertEqual(problems, [], "\n" + "\n".join(problems[:50]))

    def test_no_full_transcripts_in_fixtures(self):
        dirs = [p for p in (REPO / "fixtures").rglob("transcript") if p.is_dir()]
        self.assertEqual(dirs, [])


if __name__ == "__main__":
    unittest.main()
