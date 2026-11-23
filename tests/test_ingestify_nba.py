import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

try:
    from ingestify.domain import DataSpecVersionCollection
    from knicks_history.ingestify_nba import NbaStatsSource, refresh_bucket
except ModuleNotFoundError as exc:
    if exc.name != "ingestify":
        raise
    DataSpecVersionCollection = None
    NbaStatsSource = None
    refresh_bucket = None


@unittest.skipUnless(NbaStatsSource, "Install the lake extra to test Ingestify integration")
class IngestifyNbaTests(unittest.TestCase):
    def test_source_is_serial_and_discovery_does_not_call_network(self):
        source = NbaStatsSource("nba", refresh_days=7)
        versions = DataSpecVersionCollection.from_dict(
            {"league_game_log": "nba-api-test"}
        )
        with patch("knicks_history.ingestify_nba.fetch_league_game_log") as fetch:
            resources = list(
                source.find_datasets(
                    "league_game_log",
                    season="2024-25",
                    season_type="Regular Season",
                    data_spec_versions=versions,
                )
            )
        fetch.assert_not_called()
        self.assertEqual(source.max_concurrency, 1)
        self.assertEqual(resources[0].dataset_resource_id["season"], "2024-25")
        file_resource = resources[0].files["league_game_log__nba-api-test"]
        self.assertEqual(file_resource.data_serialization_format, "json")

    def test_file_loader_fetches_raw_response_lazily(self):
        source = NbaStatsSource("nba")
        resource = next(
            source.find_datasets(
                "league_game_log", season="2024-25", season_type="Playoffs"
            )
        )
        file_resource = next(iter(resource.files.values()))
        raw = json.dumps({"resultSets": []}).encode()
        with patch(
            "knicks_history.ingestify_nba.fetch_league_game_log", return_value=raw
        ) as fetch:
            draft = file_resource.file_loader(
                file_resource, None, **file_resource.loader_kwargs
            )
        fetch.assert_called_once_with(
            "2024-25", "Playoffs", timeout=45, proxy=None
        )
        try:
            self.assertEqual(draft.stream.read(), raw)
        finally:
            draft.stream.close()

    def test_refresh_bucket_is_stable_within_window(self):
        first = datetime(2026, 11, 22, 1, tzinfo=timezone.utc)
        second = datetime(2026, 11, 22, 23, tzinfo=timezone.utc)
        self.assertEqual(refresh_bucket(7, first), refresh_bucket(7, second))

    def test_rejects_invalid_partition(self):
        source = NbaStatsSource("nba")
        with self.assertRaises(ValueError):
            list(
                source.find_datasets(
                    "league_game_log", season="2024", season_type="Regular Season"
                )
            )


if __name__ == "__main__":
    unittest.main()
