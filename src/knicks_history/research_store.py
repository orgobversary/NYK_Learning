"""Closed, immutable release contracts for private Hugging Face Bucket research."""
import hashlib
import json
import re
import subprocess
import tomllib
from datetime import datetime, timezone
from pathlib import Path

BUCKET_ID = "obversarystudios/nyk-world-research"
RELEASE_ID = re.compile(r"\d{8}T\d{6}Z-[a-f0-9]{8}")
MANIFEST_NAME = "research-manifest.json"
FORBIDDEN_PUBLIC = ("public", "dataset", "spaces/")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def repository_state(root=None):
    root = Path(root or Path(__file__).resolve().parents[2])
    sha = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                         check=True, capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
                           check=True, capture_output=True, text=True).stdout.strip()
    return {"git_sha": sha, "git_dirty": bool(dirty)}


def load_policy(path="config/huggingface-publication.toml"):
    with Path(path).open("rb") as stream:
        policy = tomllib.load(stream)
    required = ("private_research_storage_enabled", "private_research_preview_enabled",
                "research_bucket", "automatic_public_promotion_enabled")
    missing = [key for key in required if key not in policy]
    if missing:
        raise ValueError(f"Research policy is missing: {', '.join(missing)}")
    if policy["automatic_public_promotion_enabled"]:
        raise ValueError("Automatic public promotion must remain disabled")
    return policy


def release_id(now=None, suffix="00000000"):
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y%m%dT%H%M%SZ") + "-" + suffix


def write_closed_manifest(root, metadata):
    root = Path(root)
    if not root.is_dir():
        raise ValueError("Research release root does not exist")
    files = {
        path.relative_to(root).as_posix(): {"sha256": digest(path), "bytes": path.stat().st_size}
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != MANIFEST_NAME
    }
    manifest = {"format_version": 1, **metadata, "files": files}
    (root / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def validate_closed_release(root, require_private=True):
    root = Path(root)
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file():
        raise ValueError(f"Missing {MANIFEST_NAME}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = set(manifest.get("files", {}))
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*")
              if path.is_file() and path.name != MANIFEST_NAME}
    errors = [f"missing file: {path}" for path in sorted(expected - actual)]
    errors += [f"unexpected file: {path}" for path in sorted(actual - expected)]
    errors += [f"checksum mismatch: {path}" for path in sorted(expected & actual)
               if digest(root / path) != manifest["files"][path]["sha256"]]
    if require_private and manifest.get("usage_scope") != "private_research_only":
        errors.append("usage_scope must be private_research_only")
    if manifest.get("public_publishable") is not False:
        errors.append("public_publishable must be false")
    if manifest.get("synthetic") is not False:
        errors.append("private research release must identify real rows with synthetic=false")
    if errors:
        raise ValueError("Research release validation failed:\n- " + "\n- ".join(errors))
    return manifest


def bucket_release_uri(release, bucket=BUCKET_ID):
    if not RELEASE_ID.fullmatch(release):
        raise ValueError("Invalid immutable research release ID")
    if bucket != BUCKET_ID:
        raise ValueError("Research release target is not the approved private Bucket")
    return f"hf://buckets/{bucket}/releases/{release}/"
