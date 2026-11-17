"""Plan or execute an immutable private research release upload."""
import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from knicks_history.research_store import (BUCKET_ID, MANIFEST_NAME, bucket_release_uri,
                                           digest, load_policy, repository_state,
                                           validate_closed_release)


def run(command, capture=False):
    print(" ".join(map(str, command)))
    return subprocess.run(command, check=True, text=True, capture_output=capture)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=Path("config/huggingface-publication.toml"))
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    manifest = validate_closed_release(args.release)
    policy = load_policy(args.policy)
    if not policy["private_research_storage_enabled"] or policy["research_bucket"] != BUCKET_ID:
        raise SystemExit("Checked-in policy does not authorize this private Bucket")
    destination = bucket_release_uri(manifest["release_id"])
    command = ["hf", "buckets", "sync", str(args.release), destination, "--ignore-existing"]
    if not args.execute:
        run(command + ["--dry-run"])
        print(json.dumps({"dry_run": True, "destination": destination}, indent=2))
        return
    state = repository_state()
    if state["git_dirty"] or state["git_sha"] != manifest["builder_git_sha"]:
        raise SystemExit("Execution requires the clean Git commit recorded by the release")
    run(["hf", "auth", "whoami", "--format", "json"])
    run(command)
    with tempfile.TemporaryDirectory(prefix="nyk-research-verify-") as folder:
        run(["hf", "buckets", "sync", destination, folder, "--include", MANIFEST_NAME])
        remote = Path(folder) / MANIFEST_NAME
        if digest(remote) != digest(args.release / MANIFEST_NAME):
            raise SystemExit("Remote research manifest does not match the local release")
    pointer = args.release / "latest-research.json"
    pointer.write_text(json.dumps({"release_id": manifest["release_id"],
                                   "manifest_sha256": digest(args.release / MANIFEST_NAME),
                                   "builder_git_sha": manifest["builder_git_sha"]}, indent=2) + "\n",
                       encoding="utf-8")
    try:
        run(["hf", "buckets", "cp", str(pointer),
             f"hf://buckets/{BUCKET_ID}/registry/latest-research.json"])
    finally:
        pointer.unlink(missing_ok=True)
    print(json.dumps({"uploaded": True, "destination": destination}, indent=2))


if __name__ == "__main__":
    main()
