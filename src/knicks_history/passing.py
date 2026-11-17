"""Validate authorized player-passing exports and prepare visualization edges."""
import csv
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

FIELDS = (
    "season", "passer_player_id", "passer_name", "receiver_player_id",
    "receiver_name", "passes", "assists", "games", "source_url",
    "rights_basis", "synthetic",
)
RESEARCH_FIELDS = (
    "season", "passer_player_id", "passer_name", "receiver_player_id",
    "receiver_name", "games", "passes", "assists", "fgm", "fga",
    "fg3m", "fg3a", "source_url", "retrieved_at", "source_sha256",
    "rights_basis", "synthetic",
)
SEASON = re.compile(r"20\d{2}-\d{2}")


def _boolean(value):
    normalized = str(value).strip().lower()
    if normalized not in {"true", "false"}:
        raise ValueError("synthetic must be true or false")
    return normalized == "true"


def load_passing_edges(path, require_synthetic=None):
    """Load a closed CSV contract without making a network request."""
    with Path(path).open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise ValueError(f"Passing CSV fields must be exactly: {', '.join(FIELDS)}")
        source = list(reader)
    rows, seen = [], set()
    for number, item in enumerate(source, 2):
        if not SEASON.fullmatch(item["season"]):
            raise ValueError(f"Row {number} has an invalid season")
        if not item["passer_player_id"].isdigit() or not item["receiver_player_id"].isdigit():
            raise ValueError(f"Row {number} player IDs must be digit strings")
        if item["passer_player_id"] == item["receiver_player_id"]:
            raise ValueError(f"Row {number} is a self-pass")
        key = (item["season"], item["passer_player_id"], item["receiver_player_id"])
        if key in seen:
            raise ValueError(f"Duplicate passing edge: {key}")
        seen.add(key)
        row = dict(item)
        for field in ("passes", "assists", "games"):
            try:
                row[field] = int(row[field])
            except ValueError as exc:
                raise ValueError(f"Row {number} {field} must be an integer") from exc
            if row[field] < 0:
                raise ValueError(f"Row {number} {field} must be nonnegative")
        if row["assists"] > row["passes"]:
            raise ValueError(f"Row {number} assists exceed passes")
        if not row["source_url"].strip() or not row["rights_basis"].strip():
            raise ValueError(f"Row {number} requires source_url and rights_basis")
        row["synthetic"] = _boolean(row["synthetic"])
        if require_synthetic is not None and row["synthetic"] is not require_synthetic:
            raise ValueError(f"Row {number} does not match the required synthetic state")
        rows.append(row)
    if not rows:
        raise ValueError("Passing CSV is empty")
    return rows


def aggregate_passing_edges(rows, top_players=12, top_edges=40):
    """Aggregate five-year passes while limiting visual density deterministically."""
    seasons = sorted({row["season"] for row in rows})
    if len(seasons) != 5:
        raise ValueError(f"The passing lab requires exactly five seasons, found {len(seasons)}")
    totals, names, volume = defaultdict(int), {}, defaultdict(int)
    for row in rows:
        passer, receiver = row["passer_player_id"], row["receiver_player_id"]
        names[passer], names[receiver] = row["passer_name"], row["receiver_name"]
        totals[(passer, receiver)] += row["passes"]
        volume[passer] += row["passes"]
        volume[receiver] += row["passes"]
    players = {player for player, _ in sorted(volume.items(), key=lambda item: (-item[1], item[0]))[:top_players]}
    edges = [(pair, passes) for pair, passes in totals.items()
             if pair[0] in players and pair[1] in players]
    edges.sort(key=lambda item: (-item[1], names[item[0][0]], names[item[0][1]]))
    # D3's Sankey layout requires an acyclic graph. Role-qualified nodes keep
    # reciprocal player relationships while making the network bipartite.
    return [{"source": f"Passer · {names[pair[0]]}",
             "target": f"Receiver · {names[pair[1]]}", "weight": passes}
            for pair, passes in edges[:top_edges]], seasons


def response_dataset(payload, name):
    """Return one named NBA Stats result set without depending on pandas."""
    sets = payload.get("resultSets", payload.get("resultSet"))
    if isinstance(sets, dict):
        sets = [sets]
    matches = [item for item in sets or [] if item.get("name") == name]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one {name} dataset")
    headers = matches[0].get("headers", [])
    if len(headers) != len(set(headers)):
        raise ValueError(f"{name} has duplicate headers")
    output = []
    for values in matches[0].get("rowSet", []):
        if len(values) != len(headers):
            raise ValueError(f"{name} row width differs from headers")
        output.append(dict(zip(headers, values)))
    return output


def participant_ids(payload, team_id=1610612752):
    rows = response_dataset(payload, "LeagueDashPlayerStats")
    players = {str(row["PLAYER_ID"]): str(row["PLAYER_NAME"]).strip()
               for row in rows if str(row.get("TEAM_ID")) == str(team_id)}
    if not players:
        raise ValueError("NBA Stats returned no season participants for the Knicks")
    return players


def _count(value, field):
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer count")
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be an integer count") from exc
    if result < 0 or isinstance(value, float) and result != value:
        raise ValueError(f"{field} must be a nonnegative integer")
    return result


def normalize_passes_made(payload, season, passer_id, participants, source_url,
                          retrieved_at, rights_basis, raw_bytes=None):
    """Normalize one player's season-total PassesMade response."""
    if not SEASON.fullmatch(season):
        raise ValueError("Invalid passing season")
    passer_id = str(passer_id)
    if passer_id not in participants:
        raise ValueError("Passer is not in the season participant set")
    if not rights_basis.strip():
        raise ValueError("A private research rights basis is required")
    raw = raw_bytes if raw_bytes is not None else json.dumps(payload, sort_keys=True).encode()
    source_sha = hashlib.sha256(raw).hexdigest()
    output, seen = [], set()
    for number, item in enumerate(response_dataset(payload, "PassesMade"), 1):
        source_id = str(item.get("PLAYER_ID"))
        receiver_id = str(item.get("PASS_TEAMMATE_PLAYER_ID"))
        if source_id != passer_id:
            raise ValueError(f"PassesMade row {number} belongs to another passer")
        if receiver_id == passer_id:
            raise ValueError(f"PassesMade row {number} is a self-pass")
        if receiver_id not in participants:
            raise ValueError(f"PassesMade row {number} has an unknown receiver")
        key = (season, passer_id, receiver_id)
        if key in seen:
            raise ValueError(f"Duplicate passing edge: {key}")
        seen.add(key)
        counts = {field: _count(item.get(source), source)
                  for field, source in (("games", "G"), ("passes", "PASS"),
                                        ("assists", "AST"), ("fgm", "FGM"),
                                        ("fga", "FGA"), ("fg3m", "FG3M"),
                                        ("fg3a", "FG3A"))}
        if counts["assists"] > counts["passes"]:
            raise ValueError(f"PassesMade row {number} assists exceed passes")
        if counts["fgm"] > counts["fga"] or counts["fg3m"] > counts["fg3a"]:
            raise ValueError(f"PassesMade row {number} made shots exceed attempts")
        output.append({"season": season, "passer_player_id": passer_id,
                       "passer_name": participants[passer_id],
                       "receiver_player_id": receiver_id,
                       "receiver_name": participants[receiver_id], **counts,
                       "source_url": source_url, "retrieved_at": retrieved_at,
                       "source_sha256": source_sha, "rights_basis": rights_basis,
                       "synthetic": False})
    if not output:
        raise ValueError("NBA Stats returned an empty PassesMade dataset")
    return output


def load_research_edges(path):
    with Path(path).open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != RESEARCH_FIELDS:
            raise ValueError("Research passing CSV does not match schema version 1")
        rows = list(reader)
    normalized = []
    for item in rows:
        item = dict(item)
        for field in ("games", "passes", "assists", "fgm", "fga", "fg3m", "fg3a"):
            item[field] = _count(item[field], field)
        item["synthetic"] = _boolean(item["synthetic"])
        normalized.append(item)
    if not normalized:
        raise ValueError("Research passing CSV is empty")
    return normalized
