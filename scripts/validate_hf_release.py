"""Validate generated Hugging Face artifacts without mutating the Hub."""
import argparse
import json
from pathlib import Path

from knicks_history.hub_release import validate_hub_release


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path, nargs="?", default=Path("build/huggingface"))
    args = parser.parse_args()
    print(json.dumps(validate_hub_release(args.output), indent=2))


if __name__ == "__main__":
    main()
