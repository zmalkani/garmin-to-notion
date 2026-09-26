from __future__ import annotations

import os
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from garmin_to_notion.clients import TOKEN_REFRESH_INSTRUCTIONS, init_clients
from garmin_to_notion.config import Settings, load_settings


class LoadSettingsTests(unittest.TestCase):
    def test_load_settings_allows_sync_without_garmin_credentials(self) -> None:
        env = {
            "GARMIN_TOKENS": "token_bundle",
            "NOTION_TOKEN": "ntn_test",
            "TIMEZONE": "America/Toronto",
        }

        with patch.dict(os.environ, env, clear=True):
            settings = load_settings()

        self.assertEqual(settings.notion_token, "ntn_test")
        self.assertEqual(settings.timezone, ZoneInfo("America/Toronto"))

    def test_load_settings_allows_notion_only_commands_without_garmin_auth(self) -> None:
        env = {
            "NOTION_TOKEN": "ntn_test",
            "TIMEZONE": "America/Toronto",
        }

        with patch.dict(os.environ, env, clear=True):
            settings = load_settings(require_garmin=False)

        self.assertEqual(settings.notion_token, "ntn_test")

    def test_load_settings_requires_token_source_for_garmin_syncs(self) -> None:
        env = {
            "NOTION_TOKEN": "ntn_test",
            "TIMEZONE": "America/Toronto",
        }

        with patch.dict(os.environ, env, clear=True):
            with patch("garmin_to_notion.config._has_cached_garmin_tokens", return_value=False):
                with self.assertRaises(SystemExit):
                    load_settings()


class InitClientsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            notion_token="ntn_test",
            activities_db_id=None,
            pr_db_id=None,
            steps_db_id=None,
            sleep_db_id=None,
            workouts_db_id=None,
            summary_db_id=None,
            timezone=ZoneInfo("UTC"),
            fetch_limit=100,
            days_back=30,
        )

    def test_init_clients_uses_cached_tokens_without_credential_login(self) -> None:
        class FakeGarmin:
            display_name = "runner"

        fake_tokens = {"oauth1": {"oauth_token": "a"}, "oauth2": {"access_token": "b"}}
        fake_garmin = FakeGarmin()
        fake_notion = object()

        with (
            patch("garmin_to_notion.clients._load_tokens_from_env", return_value=None),
            patch("garmin_to_notion.clients._load_tokens_from_disk", return_value=fake_tokens),
            patch("garmin_to_notion.clients._init_garmin_with_tokens", return_value=fake_garmin),
            patch("garmin_to_notion.clients._wrap_garmin_retries", return_value=fake_garmin),
            patch("garmin_to_notion.clients.NotionClient", return_value=fake_notion),
            patch("garmin_to_notion.clients._save_tokens_to_disk"),
            patch("garmin_to_notion.clients.GarminClient") as garmin_client_cls,
        ):
            clients = init_clients(self.settings)

        self.assertIs(clients.garmin, fake_garmin)
        self.assertIs(clients.notion, fake_notion)
        garmin_client_cls.assert_not_called()

    def test_init_clients_exits_with_refresh_instructions_when_tokens_fail(self) -> None:
        token_error = RuntimeError("expired token")

        with (
            patch("garmin_to_notion.clients._load_tokens_from_env", return_value={"oauth1": {}, "oauth2": {}}),
            patch("garmin_to_notion.clients._load_tokens_from_disk", return_value=None),
            patch("garmin_to_notion.clients._init_garmin_with_tokens", side_effect=token_error),
            patch("garmin_to_notion.clients.GarminClient") as garmin_client_cls,
        ):
            with self.assertRaises(SystemExit) as exc:
                init_clients(self.settings)

        self.assertEqual(str(exc.exception), TOKEN_REFRESH_INSTRUCTIONS)
        garmin_client_cls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
