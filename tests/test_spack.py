import logging
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from opa_chain_builder.tools.spack import _run_spack
from opa_chain_builder.tools.spack import install_spack


def test_install_spack_logging(tmp_path, caplog):
    spack_dir = tmp_path / "spack"
    bin_dir = spack_dir / "bin"
    bin_dir.mkdir(parents=True)
    spack_exe = bin_dir / "spack"
    spack_exe.touch()

    with (
        patch("opa_chain_builder.tools.spack.clone_repository") as mock_clone,
        patch("opa_chain_builder.tools.spack.checkout_ref") as mock_checkout,
        patch("opa_chain_builder.tools.spack._run_spack") as mock_run_spack,
    ):
        mock_run_spack.return_value = subprocess.CompletedProcess(
            args=["spack"],
            returncode=0,
            stdout="export TEST_VAR='test_val'\n",
            stderr="",
        )

        with caplog.at_level(logging.DEBUG):
            result = install_spack(
                install_dir=spack_dir,
                version="v0.21.0",
                spack_config=["config:install_tree:padded_length:128"],
                compiler_spec="intel-oneapi-compilers",
                compiler_scope="site",
            )

        assert result == spack_dir
        mock_clone.assert_called_once()
        mock_checkout.assert_called_once()

        # Check that expected logs are captured
        log_records = [r.message for r in caplog.records]
        assert any("Starting Spack installation" in msg for msg in log_records)
        assert any("Cloning Spack repository" in msg for msg in log_records)
        assert any("Checking out Spack ref" in msg for msg in log_records)
        assert any("Applying Spack config" in msg for msg in log_records)
        assert any("Installing compiler package" in msg for msg in log_records)
        assert any("Loading environment" in msg for msg in log_records)
        assert any("Registering compiler" in msg for msg in log_records)
        assert any(
            "Spack installation and configuration completed successfully"
            in msg
            for msg in log_records
        )


def test_run_spack_logging(caplog):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["spack", "version"],
            returncode=0,
            stdout="0.21.0\n",
            stderr="",
        )
        with caplog.at_level(logging.DEBUG):
            _run_spack(Path("/dummy/spack"), ["version"])

        assert any(
            "Executing Spack command" in r.message for r in caplog.records
        )


def test_run_spack_failure_logging(caplog):
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd=["/dummy/spack", "install"],
            stderr="Error: build failed",
        )
        with caplog.at_level(logging.DEBUG), pytest.raises(RuntimeError):
            _run_spack(Path("/dummy/spack"), ["install"])

        assert any(
            "Command" in r.message and "failed with return code" in r.message
            for r in caplog.records
        )
