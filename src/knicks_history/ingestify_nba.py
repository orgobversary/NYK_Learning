"""Ingestify source for cached, revisioned nba_api LeagueGameLog responses."""
from datetime import datetime, timezone

from ingestify import DatasetResource, Source
from ingestify.domain.models.dataset.dataset import DatasetState
from ingestify.domain.models.dataset.file import DraftFile

from .nba_client import fetch_league_game_log
from .pipeline import KINDS, check_season


DATASET_TYPE = "league_game_log"
DATA_FEED = "league_game_log"
DATA_SPEC_VERSION = "nba-api-v1"


def refresh_bucket(days, now=None):
    """Return a stable UTC timestamp for a configurable refresh window."""
    if not isinstance(days, int) or days < 1:
        raise ValueError("refresh_days must be a positive integer")
    current = now or datetime.now(timezone.utc)
    seconds = days * 24 * 60 * 60
    bucket = int(current.timestamp()) // seconds * seconds
    return datetime.fromtimestamp(bucket, tz=timezone.utc)


class NbaStatsSource(Source):
    """One atomic raw LeagueGameLog response per season and season type."""

    provider = "nba_stats"
    max_concurrency = 1

    def __init__(self, name, timeout=45, proxy=None, refresh_days=7):
        super().__init__(name=name)
        self.timeout = int(timeout)
        self.proxy = proxy or None
        self.refresh_days = int(refresh_days)
        refresh_bucket(self.refresh_days)

    def find_datasets(
        self,
        dataset_type,
        season,
        season_type="Regular Season",
        data_spec_versions=None,
        dataset_collection_metadata=None,
        **kwargs,
    ):
        if dataset_type != DATASET_TYPE:
            raise ValueError(f"NbaStatsSource supports only {DATASET_TYPE!r}")
        check_season(season)
        if season_type not in KINDS:
            raise ValueError(f"Unsupported season type: {season_type}")
        modified_at = refresh_bucket(self.refresh_days)
        version = (
            data_spec_versions.get_version(DATA_FEED, DATA_SPEC_VERSION)
            if data_spec_versions is not None
            else DATA_SPEC_VERSION
        )
        resource = DatasetResource(
            dataset_resource_id={"season": season, "season_type": season_type},
            dataset_type=DATASET_TYPE,
            provider=self.provider,
            name=f"NBA Stats LeagueGameLog {season} {season_type}",
            metadata={
                "endpoint": "LeagueGameLog",
                "league_id": "00",
                "player_or_team": "T",
                "season": season,
                "season_type": season_type,
            },
            state=DatasetState.COMPLETE,
        )
        resource.add_file(
            last_modified=modified_at,
            data_feed_key=DATA_FEED,
            data_spec_version=version,
            data_serialization_format="json",
            file_loader=self._load_raw,
            loader_kwargs={"season": season, "season_type": season_type},
        )
        yield resource

    def _load_raw(self, file_resource, current_file=None, *, season, season_type):
        raw = fetch_league_game_log(
            season,
            season_type,
            timeout=self.timeout,
            proxy=self.proxy,
        )
        return DraftFile.from_input(
            raw,
            data_feed_key=file_resource.data_feed_key,
            data_spec_version=file_resource.data_spec_version,
            data_serialization_format="json",
            modified_at=file_resource.last_modified,
        )
