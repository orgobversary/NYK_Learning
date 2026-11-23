import json
import unittest

from knicks_history.nba_client import fetch_league_game_log, validate_endpoint_contract


PAYLOAD = {
    "resultSets": [
        {
            "name": "LeagueGameLog",
            "headers": ["TEAM_ID", "GAME_ID", "GAME_DATE", "MATCHUP", "WL", "PTS"],
            "rowSet": [],
        }
    ]
}


class FakeLeagueGameLog:
    expected_data = {
        "LeagueGameLog": ["TEAM_ID", "GAME_ID", "GAME_DATE", "MATCHUP", "WL", "PTS"]
    }
    constructed = []
    request_failures = 0

    def __init__(
        self,
        season,
        season_type_all_star,
        player_or_team_abbreviation,
        league_id,
        timeout=30,
        proxy=None,
        get_request=True,
    ):
        self.options = locals().copy()
        type(self).constructed.append(self.options)
        if get_request:
            raise AssertionError("endpoint construction must not send the request")

    def get_request(self):
        if type(self).request_failures:
            type(self).request_failures -= 1
            raise TimeoutError("simulated timeout")

    def get_response(self):
        return json.dumps(PAYLOAD)


class NbaClientTests(unittest.TestCase):
    def setUp(self):
        FakeLeagueGameLog.constructed = []
        FakeLeagueGameLog.request_failures = 0

    def test_deferred_request_uses_explicit_endpoint_parameters(self):
        raw = fetch_league_game_log(
            "2024-25",
            "Regular Season",
            timeout=45,
            proxy="http://proxy.invalid",
            endpoint_class=FakeLeagueGameLog,
        )
        self.assertEqual(json.loads(raw), PAYLOAD)
        options = FakeLeagueGameLog.constructed[0]
        self.assertFalse(options["get_request"])
        self.assertEqual(options["season"], "2024-25")
        self.assertEqual(options["season_type_all_star"], "Regular Season")
        self.assertEqual(options["player_or_team_abbreviation"], "T")
        self.assertEqual(options["league_id"], "00")
        self.assertEqual(options["timeout"], 45)
        self.assertEqual(options["proxy"], "http://proxy.invalid")

    def test_retry_reconstructs_endpoint_and_uses_backoff(self):
        FakeLeagueGameLog.request_failures = 2
        delays = []
        fetch_league_game_log(
            "2024-25",
            "Playoffs",
            attempts=3,
            retry_delay=2,
            endpoint_class=FakeLeagueGameLog,
            transient_errors=(TimeoutError,),
            sleep=delays.append,
        )
        self.assertEqual(len(FakeLeagueGameLog.constructed), 3)
        self.assertEqual(delays, [2, 4])

    def test_contract_rejects_parameter_drift_before_request(self):
        class Drifted:
            expected_data = FakeLeagueGameLog.expected_data

            def __init__(self, season):
                pass

        with self.assertRaisesRegex(RuntimeError, "parameters changed"):
            validate_endpoint_contract(Drifted)

    def test_contract_rejects_schema_drift_before_request(self):
        class Drifted(FakeLeagueGameLog):
            expected_data = {"LeagueGameLog": ["GAME_ID"]}

        with self.assertRaisesRegex(RuntimeError, "schema changed"):
            validate_endpoint_contract(Drifted)

    def test_invalid_provider_response_is_not_retried(self):
        class HtmlResponse(FakeLeagueGameLog):
            def get_response(self):
                return "<html>removed endpoint</html>"

        delays = []
        with self.assertRaises(json.JSONDecodeError):
            fetch_league_game_log(
                "2024-25",
                "Regular Season",
                endpoint_class=HtmlResponse,
                transient_errors=(TimeoutError,),
                sleep=delays.append,
            )
        self.assertEqual(len(HtmlResponse.constructed), 1)
        self.assertEqual(delays, [])

    def test_missing_named_result_set_is_not_cached(self):
        class MissingDataSet(FakeLeagueGameLog):
            def get_response(self):
                return json.dumps({"resultSets": []})

        with self.assertRaisesRegex(ValueError, "exactly one LeagueGameLog"):
            fetch_league_game_log(
                "2024-25",
                "Regular Season",
                endpoint_class=MissingDataSet,
                transient_errors=(TimeoutError,),
            )


if __name__ == "__main__":
    unittest.main()
