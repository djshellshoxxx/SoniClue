"""Release provenance identifies changed inputs and bundled runtime components."""

import importlib.util
import json
import subprocess
from importlib import metadata
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def load_script(relative):
    spec = importlib.util.spec_from_file_location(Path(relative).stem, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_identity_tracks_build_inputs_and_ignores_generated_files(tmp_path):
    build = load_script("packaging/build.py")
    source = tmp_path / "src/sonicclue"
    source.mkdir(parents=True)
    app_file = source / "__init__.py"
    app_file.write_text("version = '1'\n")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                    "commit", "-qm", "baseline"], check=True)
    original = build.source_metadata(tmp_path)
    assert original["git_dirty"] is False
    assert len(original["source_sha256"]) == 64
    for relative in ("work/cache", "build/cache", "dist/bundle", "src/sonicclue/_build.py", "src/sonicclue/__pycache__/cache.pyc"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("generated")
    assert build.source_metadata(tmp_path)["source_sha256"] == original["source_sha256"]
    app_file.write_text("version = '2'\n")
    changed = build.source_metadata(tmp_path)
    assert changed["git_dirty"] is True
    assert changed["source_sha256"] != original["source_sha256"]
    (tmp_path / "requirements.lock").write_text("numpy==2.0.0\n")
    assert build.source_metadata(tmp_path)["source_sha256"] != changed["source_sha256"]


def test_runtime_notices_include_update_crypto_and_record_installed_versions(tmp_path):
    notices = load_script("tools/gen_notices.py")
    notices.main(tmp_path)
    components = {c["name"]: c["version"] for c in json.loads((tmp_path / "SBOM.json").read_text())["components"]}
    assert components["cryptography"] == metadata.version("cryptography")
    assert "| cryptography |" in (tmp_path / "THIRD_PARTY_NOTICES.md").read_text()
    assert notices.runtime_versions()["cryptography"] == components["cryptography"]
    assert notices.runtime_versions()["numpy"] == metadata.version("numpy")
