import json
import tempfile
import unittest
from pathlib import Path

from knicks_history.research_store import (
    bucket_release_uri,
    validate_closed_release,
    write_closed_manifest,
)


class ResearchStoreTests(unittest.TestCase):
    def test_closed_private_release_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "metrics.json").write_text("{}\n", encoding="utf-8")
            write_closed_manifest(root, {"usage_scope": "private_research_only",
                                         "public_publishable": False, "synthetic": False})
            self.assertEqual(validate_closed_release(root)["format_version"], 1)
            (root / "metrics.json").write_text('{"changed": true}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                validate_closed_release(root)

    def test_release_is_never_public_publishable(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "data.json").write_text("{}\n", encoding="utf-8")
            write_closed_manifest(root, {"usage_scope": "private_research_only",
                                         "public_publishable": True, "synthetic": False})
            with self.assertRaisesRegex(ValueError, "public_publishable"):
                validate_closed_release(root)

    def test_bucket_uri_is_closed_to_approved_namespace(self):
        release = "20261117T120000Z-1234abcd"
        self.assertEqual(bucket_release_uri(release),
                         f"hf://buckets/obversarystudios/nyk-world-research/releases/{release}/")
        with self.assertRaises(ValueError):
            bucket_release_uri(release, "someone/public")


if __name__ == "__main__":
    unittest.main()
