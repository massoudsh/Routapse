import os
import tempfile
import unittest
from unittest.mock import patch

from app import vault


def event(**changes):
    return {
        "id": "abc123",
        "ts": "2026-03-05T14:30:01.250+00:00",
        "source": "gateway",
        "status": "ok",
        "router_id": "support",
        "target_model": "gpt-4o",
        "request": {"messages": [
            {"role": "system", "content": "be nice"},
            {"role": "user", "content": "We were billed twice for March."},
        ]},
        "response": {"text": "Sorry about that, refunding.", "usage": {"prompt_tokens": 12, "completion_tokens": 7}},
        "decision": {"label": "billing", "confidence": 0.91, "reason": "laya", "action": "forward"},
        "latency_ms": 120,
        **changes,
    }


class VaultTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.vault = self.dir.name

    def read(self, rel):
        with open(os.path.join(self.vault, rel), encoding="utf-8") as f:
            return f.read()

    def test_disabled_without_a_vault_dir(self):
        with patch.object(vault.settings, "vault_dir", ""):
            with self.assertRaises(RuntimeError):
                vault.export([])

    def test_note_has_frontmatter_body_and_wikilinks(self):
        name, text = vault.note(event())
        self.assertEqual(name, "20260305-143001-gateway.md")
        self.assertTrue(text.startswith("---\n"))
        self.assertIn('router: "support"', text)
        self.assertIn('lane: "billing"', text)
        self.assertIn('confidence: 0.91', text)
        self.assertIn('usage:\n  "completion_tokens": 7\n  "prompt_tokens": 12', text)
        self.assertIn("[[support]] · [[billing]] · [[gpt-4o]]", text)
        self.assertIn("We were billed twice for March.", text)
        self.assertIn("Sorry about that, refunding.", text)
        self.assertIn("`abc123`", text)

    def test_note_links_and_tags_the_fallback(self):
        ev = event(fallback_from="fast", fallback_reason="timeout", status="error")
        _, text = vault.note(ev)
        self.assertIn('fallback_from: "fast"', text)
        self.assertIn('"status/error"', text)

    def test_bodies_redacted_still_export_without_request_text(self):
        ev = event(request={"messages": 1, "chars": 5}, response={"chars": 5, "usage": None})
        _, text = vault.note(ev)
        self.assertIn("1 messages × 5 chars", text)
        self.assertIn("Bodies are not logged", text)
        self.assertNotIn("billed twice", text)

    def test_titles_and_names_are_stripped_of_unsafe_characters(self):
        ev = event(source="a/b", router_id="a/b c", request={"messages": [{"role": "user", "content": "hi\n\n   there"}]})
        name, text = vault.note(ev)
        self.assertNotIn("/", name)
        self.assertIn('aliases: ["hi there"]', text)
        self.assertIn("[[a/b c]]", text)
        self.assertIn('"router/ab c"', text)

    def test_export_writes_notes_and_indexes(self):
        result = vault.export([event(), event(id="d2", router_id="sales", decision={"label": "quote"})], vault=self.vault)
        self.assertEqual(result["requests"], 2)
        self.assertEqual(result["errors"], 0)
        self.assertTrue(os.path.exists(os.path.join(self.vault, "requests", "20260305-143001-gateway.md")))
        self.assertEqual(sorted(os.listdir(os.path.join(self.vault, "by-router"))), ["sales.md", "support.md"])
        self.assertTrue(os.path.exists(os.path.join(self.vault, "by-lane", "billing.md")))
        self.assertTrue(os.path.exists(os.path.join(self.vault, "by-model", "gpt-4o.md")))
        self.assertTrue(os.path.exists(os.path.join(self.vault, "by-source", "gateway.md")))

    def test_index_lists_newest_first_and_counts_records(self):
        old = event(id="o", ts="2026-01-01T00:00:00+00:00")
        new = event(id="n", ts="2026-06-01T00:00:00+00:00")
        vault.export([old, new], vault=self.vault)
        index = self.read(os.path.join("by-router", "support.md"))
        self.assertIn("_2 records_", index)
        self.assertLess(index.index("[[20260601"), index.index("[[20260101"))

    def test_export_is_idempotent(self):
        vault.export([event()], vault=self.vault)
        first = self.read(os.path.join("requests", "20260305-143001-gateway.md"))
        vault.export([event()], vault=self.vault)
        self.assertEqual(self.read(os.path.join("requests", "20260305-143001-gateway.md")), first)

    def test_records_without_an_id_are_skipped(self):
        result = vault.export([event(id=None)], vault=self.vault)
        self.assertEqual(result["requests"], 0)


if __name__ == "__main__":
    unittest.main()
