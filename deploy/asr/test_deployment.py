"""Offline failure checks for deployment helpers (no model or cloud access)."""

import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tomllib

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


entry = load("entry", HERE / "entrypoint.py")
download = load("download", HERE / "download-model.py")
parameters = load("parameters", HERE.parents[1] / "infra/azure/check-parameters.py")


class DeploymentTests(unittest.TestCase):
    def test_secret_renders_valid_toml_without_changing_model(self):
        template = (HERE / "config.toml").read_text()
        result = tomllib.loads(entry.render(template, "a" * 48))
        self.assertEqual(result["authorized_ids"], ["a" * 48])
        self.assertEqual(result["modules"], tomllib.loads(template)["modules"])

    def test_secret_injection_and_public_token_rejected(self):
        for key in ["public_token", "a" * 32 + "\n[evil]", "a" * 129, ""]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                entry.render("authorized_ids = []", key)

    def test_missing_or_duplicate_secret_placeholder_rejected(self):
        for template in ["", "authorized_ids = []\nauthorized_ids = []"]:
            with self.assertRaises(ValueError):
                entry.render(template, "a" * 48)

    def test_corrupt_download_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "model.safetensors"
            dest.write_bytes(b"previous")
            lock = {
                "repository": "example/model",
                "revision": "fixed",
                "files": {dest.name: {"sha256": "0" * 64, "size": 3}},
            }
            with (
                patch.object(download.Path, "read_text", return_value=json.dumps(lock)),
                patch.object(
                    download.urllib.request, "urlopen", return_value=io.BytesIO(b"bad")
                ),
                patch("sys.argv", ["download-model.py", tmp]),
                self.assertRaises(ValueError),
            ):
                download.main()
            self.assertEqual(dest.read_bytes(), b"previous")
            self.assertFalse(dest.with_name(dest.name + ".partial").exists())

    def test_unsafe_parameter_values_rejected(self):
        good = {
            "operatorCidr": "8.8.8.8/32",
            "ubuntuImageVersion": "24.04.202601010",
            "sshPublicKey": "ssh-ed25519 test",
        }
        parameters.validate({"parameters": {k: {"value": v} for k, v in good.items()}})
        for field, value in [
            ("operatorCidr", "0.0.0.0/0"),
            ("operatorCidr", "10.0.0.1/32"),
            ("ubuntuImageVersion", "latest"),
            ("sshPublicKey", "PRIVATE KEY"),
        ]:
            bad = {**good, field: value}
            with self.subTest(field=field), self.assertRaises(ValueError):
                parameters.validate(
                    {"parameters": {k: {"value": v} for k, v in bad.items()}}
                )


if __name__ == "__main__":
    unittest.main()
