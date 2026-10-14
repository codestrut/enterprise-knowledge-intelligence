import subprocess


def _git(repo, *args):
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def test_changed_paths_keep_the_first_character_of_the_first_path(
    tmp_path, monkeypatch
):
    from scripts import freeze_eval_manifest as freeze

    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    hidden = tmp_path / ".hidden-config"
    hidden.write_text("one\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "init")
    hidden.write_text("two\n", encoding="utf-8")

    monkeypatch.setattr(freeze, "ROOT", tmp_path)
    manifest = freeze.build_manifest("data/raw/missing.pdf")

    # Stripping the whole porcelain output used to yield "hidden-config".
    assert ".hidden-config" in manifest["git"]["changed_paths"]
