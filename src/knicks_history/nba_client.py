"""Careful, inspectable access to the NBA Stats league game log."""
import builtins
import inspect
import json
import time


REQUIRED_COLUMNS = {"TEAM_ID", "GAME_ID", "GAME_DATE", "MATCHUP", "WL", "PTS"}
REQUIRED_PARAMETERS = {
    "season",
    "season_type_all_star",
    "player_or_team_abbreviation",
    "league_id",
    "timeout",
    "get_request",
}


def _league_game_log_class():
    from nba_api.stats.endpoints.leaguegamelog import LeagueGameLog

    return LeagueGameLog


def _transient_request_errors():
    try:
        from requests.exceptions import ConnectionError, Timeout
    except ImportError:  # Base/offline tests do not install the live extra.
        return (builtins.ConnectionError, TimeoutError)

    return (ConnectionError, Timeout)


def validate_endpoint_contract(endpoint_class):
    """Fail before networking when the installed nba_api contract has drifted."""
    parameters = set(inspect.signature(endpoint_class.__init__).parameters)
    missing_parameters = REQUIRED_PARAMETERS - parameters
    if missing_parameters:
        raise RuntimeError(
            f"nba_api LeagueGameLog parameters changed: missing {sorted(missing_parameters)}"
        )
    expected = getattr(endpoint_class, "expected_data", {})
    columns = set(expected.get("LeagueGameLog", ()))
    missing_columns = REQUIRED_COLUMNS - columns
    if missing_columns:
        raise RuntimeError(
            f"nba_api LeagueGameLog schema changed: missing {sorted(missing_columns)}"
        )


def fetch_league_game_log(
    season,
    season_type,
    *,
    timeout=30,
    proxy=None,
    attempts=3,
    retry_delay=5,
    endpoint_class=None,
    transient_errors=None,
    sleep=time.sleep,
):
    """Return raw NBA Stats JSON bytes after deferred, retryable requests.

    The endpoint is constructed with ``get_request=False`` on every attempt.
    This keeps object construction separate from the network operation and makes
    retries explicit. Callers performing a multi-season loop remain responsible
    for pacing successful requests.
    """
    if attempts < 1:
        raise ValueError("attempts must be at least one")
    endpoint_class = endpoint_class or _league_game_log_class()
    transient_errors = transient_errors or _transient_request_errors()
    validate_endpoint_contract(endpoint_class)
    request_options = {
        "season": season,
        "season_type_all_star": season_type,
        "player_or_team_abbreviation": "T",
        "league_id": "00",
        "timeout": timeout,
        "get_request": False,
    }
    if proxy is not None:
        request_options["proxy"] = proxy
    for attempt in range(attempts):
        endpoint = endpoint_class(**request_options)
        try:
            endpoint.get_request()
        except transient_errors:
            if attempt + 1 == attempts:
                raise
            sleep(retry_delay * (2**attempt))
            continue
        raw = endpoint.get_response()
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        if not isinstance(raw, bytes):
            raise TypeError("nba_api returned a non-text response")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("NBA Stats response must be a JSON object")
        # Validate the actual named result set before Ingestify can accept the
        # response as a complete raw revision. Empty row sets remain valid here;
        # the archive policy decides whether an empty partition is acceptable.
        from .pipeline import response_rows

        response_rows(payload)
        return raw
    raise RuntimeError("NBA Stats request did not complete")
