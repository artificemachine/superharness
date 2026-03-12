def test_repository_smoke() -> None:
    assert True


def test_test_layers_exist(repo_root) -> None:
    assert (repo_root / "tests" / "unit").is_dir()
    assert (repo_root / "tests" / "integration").is_dir()
    assert (repo_root / "tests" / "e2e").is_dir()
