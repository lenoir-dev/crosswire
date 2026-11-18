"""Negative controls for the independent raw-byte gate, using synthetic sources."""
import base64
import importlib.util
import json
from pathlib import Path
import subprocess
import tarfile

import pytest


spec = importlib.util.spec_from_file_location("t21_equality", Path(__file__).parents[1] / "benchmarks/t21_equality.py")
t21 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t21)


def raw(stdout=b"", stderr=b"", code=0):
    return t21.encoded(subprocess.CompletedProcess([], code, stdout, stderr))


@pytest.mark.parametrize("before,after,field,offset", [
    (raw(b"a\r\n"), raw(b"a\n"), "stdout", 1),
    (raw(b"a\n"), raw(b"a"), "stdout", 1),
    (raw(b"\xff\x00"), raw(b"\xfe\x00"), "stdout", 0),
    (raw(stderr=b"warning\n"), raw(stderr=b"warning!\n"), "stderr", 7),
    (raw(code=0), raw(code=1), "exit", None),
])
def test_byte_and_exit_mutations_are_detected_without_projection(before, after, field, offset):
    found = t21.differences(before, after)
    assert list(found) == [field]
    if offset is not None:
        assert found[field]["offset"] == offset
    assert not t21.differences(before, before)


def test_json_order_is_not_normalized():
    assert "stdout" in t21.differences(raw(b'{"a":1,"b":2}\n'), raw(b'{"b":2,"a":1}\n'))


def test_matrix_preserves_alternate_repo_roots_cwd_and_original_permutations():
    fixture = {"repo": "/unused/original", "root": "/fixture", "invocations": [
        {"argv": ["check", "--repo", "bare.git", "--src", "lib source", "--src", "consumer sources",
                  "--format", "json", "C", "A", "B"], "cwd": "/fixture"},
        {"argv": ["check", "--repo", "bare.git", "--src", "lib source", "--src", "consumer sources",
                  "--format", "sarif", "B", "C", "A"], "cwd": "/fixture"},
    ]}
    specs = t21.specifications(fixture)
    observed = [s for s in specs if s["kind"] == "observed"]
    assert [s["argv"] for s in observed] == [i["argv"] for i in fixture["invocations"]]
    matrix = [s for s in specs if s["kind"] == "matrix"]
    assert len(matrix) == 2 * 10 * 5
    assert {(s["mode"], s["format"]) for s in matrix} == {
        (mode, fmt) for mode, formats in t21.FORMATS.items() for fmt in formats}
    for item in matrix:
        args = item["argv"]
        assert args[args.index("--repo") + 1] == "bare.git"
        assert "lib source" in args and "consumer sources" in args and item["cwd"] == "/fixture"
    assert {tuple(s["order"]) for s in matrix} == {("C", "A", "B"), ("B", "A", "C")}


def test_subset_probes_remain_observed_while_full_branch_set_gets_matrix():
    fixture = {"repo": "/repo", "root": "/fixture", "invocations": [
        {"argv": ["check", "--repo", "/repo", "--target", "main", "--combined", *branches], "cwd": "/fixture"}
        for branches in (("A", "B"), ("C", "B", "A"), ("A", "C"))]}
    specs = t21.specifications(fixture)
    assert [s["argv"] for s in specs if s["kind"] == "observed"] == [i["argv"] for i in fixture["invocations"]]
    matrix = [s for s in specs if s["kind"] == "matrix"]
    assert len(matrix) == 100 and all(set(s["order"]) == {"A", "B", "C"} for s in matrix)


def test_subprocess_imports_selected_source_and_keeps_binary_streams(tmp_path):
    source = tmp_path / "checkout"
    package = source / "src/crosswire"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "__main__.py").write_text("from .cli import main\nraise SystemExit(main())\n")
    (package / "cli.py").write_text(
        "import os\ndef main(argv=None):\n"
        "    os.write(1,b'\\xff\\r\\n')\n"
        "    os.write(2,b'\\x00warning\\n')\n"
        "    return 7\n"
    )
    result = t21.run_cli(source, {"argv": ["--version"], "cwd": str(tmp_path)})
    assert result.returncode == 7 and result.stdout == b"\xff\r\n" and result.stderr == b"\x00warning\n"
    assert t21.differences(raw(code=7), t21.encoded(result))


def test_preseeded_and_malformed_cache_restore_exact_release_bytes(tmp_path):
    cache = tmp_path / "repo/.git/crosswire/cache/v1/key.json"
    payload = {str(cache.relative_to(tmp_path)): base64.b64encode(b'{"schema_version":3}').decode()}
    t21.install_cache(tmp_path, payload)
    assert t21.cache_payload(tmp_path) == payload
    t21.install_cache(tmp_path, payload, b"null")
    assert cache.read_bytes() == b"null"
    t21.install_cache(tmp_path, {})
    assert not t21.cache_files(tmp_path)
    with pytest.raises(ValueError, match="escaped"):
        t21.install_cache(tmp_path, {"../outside": ""})


def test_readonly_guard_catches_index_refs_dirty_files_and_symlinks(tmp_path):
    (tmp_path / ".git/refs/heads").mkdir(parents=True)
    index = tmp_path / ".git/index"
    index.write_bytes(b"index")
    before = t21.protected_state(tmp_path)
    index.write_bytes(b"mutated")
    assert t21.protected_state(tmp_path) != before
    index.write_bytes(b"index")
    (tmp_path / "untracked").symlink_to("missing")
    assert t21.protected_state(tmp_path) != before


def test_restore_refuses_arbitrary_directory_and_archive_tampering(tmp_path, monkeypatch):
    owned = tmp_path / "owned"
    monkeypatch.setattr(t21, "FIXTURE_ROOT", owned)
    archive = tmp_path / "fixture.tar.gz"
    with tarfile.open(archive, "w:gz"):
        pass
    fixture = {"root": str(owned / "test"), "archive": archive.name, "sha256": t21.sha(archive.read_bytes()), "id": "test"}
    t21.restore(tmp_path, fixture)
    archive.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="changed"):
        t21.restore(tmp_path, fixture)
    fixture["root"] = str(tmp_path / "other")
    with pytest.raises(ValueError, match="outside"):
        t21.restore(tmp_path, fixture)


def test_record_and_replay_fail_only_changed_candidate_stream(tmp_path, monkeypatch):
    owned = tmp_path / "owned"
    monkeypatch.setattr(t21, "FIXTURE_ROOT", owned)
    root = owned / "case"
    root.mkdir(parents=True)
    (root / "tracked.txt").write_bytes(b"leave untouched\n")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    archive = artifacts / "case.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        stream.add(root, arcname=".")
    fixture = {"root": str(root), "repo": str(root), "archive": archive.name,
               "sha256": t21.sha(archive.read_bytes()), "id": "case", "invocations": []}
    spec = {"id": "command", "kind": "matrix", "mode": "combined", "format": "json",
            "cache": "cold", "argv": [], "cwd": str(root)}
    monkeypatch.setattr(t21, "specifications", lambda fixture: [spec])
    for name, output in (("baseline", "stable\\n"), ("candidate", "changed\\n")):
        package = tmp_path / name / "src/crosswire"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("")
        (package / "__main__.py").write_text("from .cli import main\nraise SystemExit(main())\n")
        (package / "cli.py").write_text(f"def main(argv=None):\n    print('{output}', end='')\n    return 0\n")
    frozen = t21.record_fixture(artifacts, fixture, tmp_path / "baseline", 5)
    before = (artifacts / frozen["outputs"]).read_bytes()
    delta, observations, counts = t21.replay_fixture(
        artifacts, fixture, frozen, tmp_path / "baseline", tmp_path / "candidate", 5)
    assert len(delta) == 2 and all(item["side"] == "candidate" for item in delta)
    assert all(list(item["differences"]) == ["stdout"] for item in delta)
    assert counts["baseline"] == counts["candidate"] == 2
    assert (artifacts / frozen["outputs"]).read_bytes() == before
    assert (root / "tracked.txt").read_bytes() == b"leave untouched\n"


def test_recording_recovery_refuses_changed_completed_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(t21, "FIXTURE_ROOT", tmp_path / "owned")
    checkout = tmp_path / "checkout"
    package = checkout / "src/crosswire"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    monkeypatch.setattr(t21, "release_provenance", lambda path: {"tag": "synthetic"})
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "inventory.json").write_text(json.dumps({"exitstatus": 0, "tests": {}, "fixtures": []}))
    output = artifacts / "completed.gz"
    output.write_bytes(b"changed")
    checkpoint = {"completed": [{"outputs": output.name, "outputs_sha256": t21.sha(b"original"),
                                 "seed": "unused.json", "seed_sha256": "unused"}]}
    (artifacts / "recording-checkpoint.json").write_text(json.dumps(checkpoint))
    with pytest.raises(ValueError, match="will not regenerate"):
        t21.main(["--baseline", str(checkout), "--candidate", str(checkout), "--artifacts", str(artifacts),
                  "--record-baseline", "--resume-recording"])
    assert output.read_bytes() == b"changed"


def test_package_entry_point_regression_and_namespace_contention_are_detected(tmp_path, monkeypatch):
    package = tmp_path / "src/crosswire"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "cli.py").write_text("def main(argv):\n    return 0\n")
    (package / "__main__.py").write_text("raise SystemExit(9)\n")
    assert t21.run_cli(tmp_path, {"argv": [], "cwd": str(tmp_path)}).returncode == 9
    monkeypatch.setattr(t21, "FIXTURE_ROOT", tmp_path / "owned")
    handle = t21.acquire_lock()
    try:
        with pytest.raises(ValueError, match="Another comparator"):
            t21.acquire_lock()
    finally:
        handle.close()
