"""Stage closed Hub payloads through reviewable Hugging Face pull requests."""
import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from knicks_history.hub_release import (
    MANIFEST_NAME,
    digest,
    load_publication_gate,
    public_payload_allowed,
    validate_hub_release,
)


LEGACY_SPACE_SHA = "4242276723a1f65145027d0db8691158dad17d12"
LEGACY_TAG = "legacy-docker-4242276"


def run(command, execute=True, capture=False):
    print(" ".join(command))
    if not execute:
        return None
    return subprocess.run(command, check=True, text=True, capture_output=capture)


def verify_remote_dataset(dataset, revision, local_manifest):
    with tempfile.TemporaryDirectory(prefix="nyk-hub-verify-") as folder:
        run(["hf", "datasets", "info", dataset, "--revision", revision, "--format", "json"], capture=True)
        run(["hf", "download", dataset, MANIFEST_NAME, "--type", "dataset",
             "--revision", revision, "--local-dir", folder], capture=True)
        remote = Path(folder) / MANIFEST_NAME
        if digest(remote) != digest(local_manifest):
            raise SystemExit("Remote dataset manifest does not match the local visual source")


def ensure_legacy_tag(space, execute):
    tags = run(["hf", "repos", "tag", "list", space, "--type", "space", "--format", "json"],
               capture=True)
    if LEGACY_TAG in tags.stdout:
        return
    result = run(["hf", "spaces", "info", space, "--format", "json"], capture=True)
    current = json.loads(result.stdout)
    if current.get("sha") != LEGACY_SPACE_SHA:
        raise SystemExit(f"Legacy Space moved from expected revision {LEGACY_SPACE_SHA}")
    run(["hf", "repos", "tag", "create", space, LEGACY_TAG, "--revision", LEGACY_SPACE_SHA,
         "--type", "space"], execute)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("build/huggingface"))
    parser.add_argument("--dataset", default="obversarystudios/nyk-world-data")
    parser.add_argument("--space", default="obversarystudios/nyk_world")
    parser.add_argument("--target", choices=("dataset", "space"), required=True)
    parser.add_argument("--policy", type=Path,
                        default=Path("config/huggingface-publication.toml"))
    parser.add_argument("--execute", action="store_true",
                        help="perform writes; otherwise print the exact reviewable commands")
    args = parser.parse_args()
    release = validate_hub_release(args.input)
    manifest = release[args.target]
    policy = load_publication_gate(args.policy)
    if not public_payload_allowed(policy, manifest.get("synthetic")):
        raise SystemExit(
            "Publication blocked by the checked-in research policy: Hub publication is "
            "disabled, and real research data and real-data visualizations stay local"
        )
    if not manifest.get(f"{args.target}_publishable"):
        reason = "rights review, clean matching source/builder commits"
        if args.target == "space":
            reason += ", and a verified dataset commit"
        raise SystemExit(f"{args.target.title()} publication blocked: requires {reason}")
    message = f"Stage NYK World {', '.join(manifest['seasons'])} {args.target} release"
    run(["hf", "auth", "whoami", "--format", "json"], args.execute)
    if args.target == "dataset":
        run(["hf", "repos", "create", args.dataset, "--type", "dataset", "--private", "--exist-ok"],
            args.execute)
        run(["hf", "upload", args.dataset, str(args.input / "dataset"), ".", "--type", "dataset",
             "--delete", "*", "--create-pr", "--commit-message", message], args.execute)
    else:
        verify_remote_dataset(args.dataset, manifest["dataset_revision"],
                              args.input / "dataset" / MANIFEST_NAME)
        ensure_legacy_tag(args.space, args.execute)
        run(["hf", "upload", args.space, str(args.input / "space"), ".", "--type", "space",
             "--delete", "*", "--create-pr", "--commit-message", message], args.execute)
    if not args.execute:
        print(json.dumps({"dry_run": True, "target": args.target, "closed_payload": True}, indent=2))


if __name__ == "__main__":
    main()
