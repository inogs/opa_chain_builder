import logging
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from opa_chain_builder.tools.ssh import SshKeyStatus
from opa_chain_builder.tools.ssh import check_ssh_keys
from opa_chain_builder.tools.ssh import ssh_host_from_url
from opa_chain_builder.tools.ssh import ssh_identity_files


@pytest.mark.parametrize(
    ("repo_url", "expected"),
    [
        ("git@gitlab.example.org:OGS/v5c.git", "gitlab.example.org"),
        ("gitlab.example.org:OGS/v5c.git", "gitlab.example.org"),
        ("ssh://git@gitlab.example.org/OGS/v5c.git", "gitlab.example.org"),
        ("https://github.com/owner/repo.git", None),
        ("/local/path/repo", None),
    ],
)
def test_ssh_host_from_url(repo_url, expected):
    assert ssh_host_from_url(repo_url) == expected


def test_ssh_identity_files_keeps_existing_keys(tmp_path):
    existing = tmp_path / "id_ed25519"
    existing.touch()
    missing = tmp_path / "id_rsa"
    ssh_output = f"user git\nidentityfile {existing}\nidentityfile {missing}\n"

    with patch(
        "opa_chain_builder.tools.ssh.subprocess.run",
        return_value=subprocess.CompletedProcess(
            args=["ssh"], returncode=0, stdout=ssh_output, stderr=""
        ),
    ):
        assert ssh_identity_files("host") == [existing]


def test_key_status_needs_passphrase():
    encrypted = SshKeyStatus(Path("k"), encrypted=True, loaded_in_agent=False)
    loaded = SshKeyStatus(Path("k"), encrypted=True, loaded_in_agent=True)
    plain = SshKeyStatus(Path("k"), encrypted=False, loaded_in_agent=False)

    assert encrypted.needs_passphrase
    assert not loaded.needs_passphrase
    assert not plain.needs_passphrase


def test_check_ssh_keys_warns_for_encrypted_key(tmp_path, caplog):
    key = tmp_path / "id_ed25519"
    key.touch()
    status = SshKeyStatus(key, encrypted=True, loaded_in_agent=False)

    with (
        patch(
            "opa_chain_builder.tools.ssh.inspect_ssh_keys",
            return_value=[status],
        ),
        caplog.at_level(logging.INFO),
    ):
        check_ssh_keys("git@example.org:repo.git")

    assert "a passphrase will be requested" in caplog.text
    assert caplog.records[0].levelno == logging.WARNING


def test_check_ssh_keys_ignores_non_ssh_url():
    with patch("opa_chain_builder.tools.ssh.ssh_identity_files") as mock_ids:
        assert check_ssh_keys("https://github.com/owner/repo.git") == []

    mock_ids.assert_not_called()
