import json
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app import auth, reqlog


class AuthTests(unittest.TestCase):
    def test_empty_token_disables_auth(self):
        with patch.object(auth.settings, "admin_token", ""):
            auth.admin_auth(None)

    def test_valid_bearer_token_is_accepted(self):
        with patch.object(auth.settings, "gateway_key", "secret"):
            auth.gateway_auth("Bearer secret")

    def test_missing_or_wrong_token_is_rejected(self):
        with patch.object(auth.settings, "admin_token", "secret"):
            for header in (None, "Bearer wrong", "secret-without-prefix"):
                with self.subTest(header=header), self.assertRaises(HTTPException) as error:
                    auth.admin_auth(header)
                self.assertEqual(error.exception.status_code, 401)


class RequestLogTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        patcher = patch.object(reqlog.settings, "log_dir", self.dir.name)
        patcher.start()
        self.addCleanup(patcher.stop)

    def event(self, **changes):
        return {
            "source": "gateway",
            "router_id": "support",
            "status": "ok",
            "request": {"messages": [{"role": "user", "content": "hello"}]},
            "response": {"text": "world", "usage": {}},
            **changes,
        }

    def test_event_is_appended_as_json_line(self):
        reqlog.log_event(self.event())
        reqlog.log_event(self.event(source="studio"))
        files = os.listdir(self.dir.name)
        self.assertEqual(len(files), 1)
        with open(os.path.join(self.dir.name, files[0])) as f:
            lines = [json.loads(line) for line in f]
        self.assertEqual([x["source"] for x in lines], ["gateway", "studio"])
        self.assertTrue(all("id" in x and "ts" in x for x in lines))

    def test_bodies_can_be_disabled(self):
        with patch.object(reqlog.settings, "log_bodies", False):
            reqlog.log_event(self.event())
        entry = reqlog.read_logs()[0]
        self.assertEqual(entry["request"], {"messages": 1, "chars": 5})
        self.assertEqual(entry["response"]["chars"], 5)
        self.assertNotIn("hello", json.dumps(entry))

    def test_read_logs_returns_newest_first_with_filters_and_offset(self):
        for i in range(3):
            reqlog.log_event(self.event(note=f"entry-{i}"))
        reqlog.log_event(self.event(source="studio", router_id="other", note="needle"))
        self.assertEqual(reqlog.read_logs()[0]["note"], "needle")
        self.assertEqual([x["note"] for x in reqlog.read_logs(source="gateway")], ["entry-2", "entry-1", "entry-0"])
        self.assertEqual(len(reqlog.read_logs(router_id="other")), 1)
        self.assertEqual(reqlog.read_logs(q="NEEDLE")[0]["note"], "needle")
        self.assertEqual([x["note"] for x in reqlog.read_logs(limit=2, offset=1)], ["entry-2", "entry-1"])

    def test_corrupt_lines_are_skipped(self):
        reqlog.log_event(self.event(note="good"))
        path = os.path.join(self.dir.name, os.listdir(self.dir.name)[0])
        with open(path, "a") as f:
            f.write("not json\n")
        self.assertEqual([x["note"] for x in reqlog.read_logs()], ["good"])

    def test_unwritable_log_dir_does_not_raise(self):
        with patch.object(reqlog.settings, "log_dir", os.path.join(self.dir.name, "file")):
            open(reqlog.settings.log_dir, "w").close()
            reqlog.log_event(self.event())

    def test_info_lists_files(self):
        reqlog.log_event(self.event())
        info = reqlog.info()
        self.assertEqual(len(info["files"]), 1)
        self.assertTrue(info["bodies"])


if __name__ == "__main__":
    unittest.main()
