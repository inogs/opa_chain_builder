from unittest.mock import patch

from opa_chain_builder.tools.git import clone_repository


def test_clone_repository_checks_ssh_keys_for_ssh_url(tmp_path):
    with (
        patch("opa_chain_builder.tools.git.check_ssh_keys") as mock_check,
        patch("opa_chain_builder.tools.git._run_git"),
    ):
        clone_repository("git@example.org:OGS/v5c.git", tmp_path / "repo")

    mock_check.assert_called_once_with("git@example.org:OGS/v5c.git")


def test_clone_repository_skips_ssh_check_for_https_url(tmp_path):
    with (
        patch("opa_chain_builder.tools.git.check_ssh_keys") as mock_check,
        patch("opa_chain_builder.tools.git._run_git"),
    ):
        clone_repository("https://github.com/owner/repo.git", tmp_path / "r")

    mock_check.assert_not_called()
