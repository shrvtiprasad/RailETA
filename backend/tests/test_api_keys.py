from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.api.services import api_keys


class APIKeyStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database = Path(self.temp_dir.name) / "api-keys.sqlite"

        def temporary_connection():
            return sqlite3.connect(database)

        self.connection_patch = patch("backend.api.services.api_keys.get_connection", side_effect=temporary_connection)
        self.connection_patch.start()

    def tearDown(self) -> None:
        self.connection_patch.stop()
        self.temp_dir.cleanup()

    def test_generation_is_secure_and_listing_never_returns_plaintext(self) -> None:
        created = api_keys.create_api_key("account-a", "My Application")
        self.assertTrue(created["key"].startswith("rail_live_"))
        self.assertGreaterEqual(len(created["key"]), 40)
        listed = api_keys.list_api_keys("account-a")
        self.assertEqual(len(listed), 1)
        self.assertNotIn("key", listed[0])
        self.assertNotIn(created["key"], str(listed[0]))
        self.assertTrue(listed[0]["masked_key"].startswith("rail_live_"))

    def test_account_scoping_and_revocation(self) -> None:
        own = api_keys.create_api_key("account-a", "Own")
        other = api_keys.create_api_key("account-b", "Other")
        self.assertEqual(len(api_keys.list_api_keys("account-a")), 1)
        self.assertFalse(api_keys.revoke_api_key("account-a", other["id"]))
        self.assertTrue(api_keys.authenticate_api_key(own["key"]))
        self.assertTrue(api_keys.revoke_api_key("account-a", own["id"]))
        self.assertFalse(api_keys.authenticate_api_key(own["key"]))

    def test_development_account_identity_is_configurable(self) -> None:
        with patch.dict(os.environ, {"RAILETA_REQUIRE_ACCOUNT_AUTH": "false", "RAILETA_DEVELOPMENT_ACCOUNT_ID": "local-test"}, clear=False):
            self.assertEqual(api_keys.account_id_from_environment({}), "local-test")
        with patch.dict(os.environ, {"RAILETA_REQUIRE_ACCOUNT_AUTH": "true"}, clear=False):
            self.assertIsNone(api_keys.account_id_from_environment({}))
            self.assertEqual(api_keys.account_id_from_environment({"X-Account-ID": "account-a"}), "account-a")


if __name__ == "__main__":
    unittest.main()
