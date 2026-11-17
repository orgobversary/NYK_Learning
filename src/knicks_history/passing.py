"""Validate authorized player-passing exports and prepare visualization edges."""
import csv
import re
from collections import defaultdict
from pathlib import Path

FIELDS = (
    "season", "passer_player_id", "passer_name", "receiver_player_id",
    "receiver_name", "passes", "assists", "games", "source_url",
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
