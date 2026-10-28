import logging
import subprocess
from pathlib import Path
from unittest.mock import ANY
from unittest.mock import call
from unittest.mock import patch

import pytest

from opa_chain_builder.tools.spack import create_spack_env_from_specs
from opa_chain_builder.tools.spack import create_spack_env_from_yaml
from opa_chain_builder.tools.spack import execute_spack_command
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
        patch(
            "opa_chain_builder.tools.spack.execute_spack_command"
        ) as mock_run_spack,
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
                install_compilers=("intel",),
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


def test_execute_spack_command_logging(caplog):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["spack", "version"],
            returncode=0,
            stdout="0.21.0\n",
            stderr="",
        )
        with caplog.at_level(logging.DEBUG):
            execute_spack_command(Path("/dummy/spack"), ["version"])

        assert any(
            "Executing Spack command" in r.message for r in caplog.records
        )


def test_execute_spack_command_failure_logging(caplog):
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd=["/dummy/spack", "install"],
            stderr="Error: build failed",
        )
        with caplog.at_level(logging.DEBUG), pytest.raises(RuntimeError):
            execute_spack_command(Path("/dummy/spack"), ["install"])

        assert any(
            "Command" in r.message and "failed with return code" in r.message
            for r in caplog.records
        )


def test_create_spack_env_from_specs_adds_specs(tmp_path):
    spack_dir = tmp_path / "spack"
    bin_dir = spack_dir / "bin"
    bin_dir.mkdir(parents=True)
    spack_exe = bin_dir / "spack"
    spack_exe.touch()
    env_dir = tmp_path / "env"

    with patch(
        "opa_chain_builder.tools.spack.execute_spack_command"
    ) as mock_run_spack:
        result = create_spack_env_from_specs(
            spack_dir=spack_dir,
            env_dir=env_dir,
            specs=["zlib", "hdf5+mpi"],
        )

    assert result == env_dir
    assert mock_run_spack.call_args_list == [
        call(
            spack_exe, ["env", "create", "--dir", str(env_dir)], system_env=ANY
        ),
        call(spack_exe, ["-e", str(env_dir), "add", "zlib"], system_env=ANY),
        call(
            spack_exe, ["-e", str(env_dir), "add", "hdf5+mpi"], system_env=ANY
        ),
        call(spack_exe, ["-e", str(env_dir), "concretize"], system_env=ANY),
    ]


def test_create_spack_env_from_specs_can_skip_concretization(tmp_path):
    spack_dir = tmp_path / "spack"
    bin_dir = spack_dir / "bin"
    bin_dir.mkdir(parents=True)
    spack_exe = bin_dir / "spack"
    spack_exe.touch()
    env_dir = tmp_path / "env"

    with patch(
        "opa_chain_builder.tools.spack.execute_spack_command"
    ) as mock_run_spack:
        create_spack_env_from_specs(
            spack_dir=spack_dir,
            env_dir=env_dir,
            specs=["zlib"],
            concretized=False,
        )

    assert mock_run_spack.call_args_list == [
        call(
            spack_exe, ["env", "create", "--dir", str(env_dir)], system_env=ANY
        ),
        call(spack_exe, ["-e", str(env_dir), "add", "zlib"], system_env=ANY),
    ]


def test_create_spack_env_from_specs_missing_executable(tmp_path):
    with (
        patch(
            "opa_chain_builder.tools.spack.execute_spack_command"
        ) as mock_run_spack,
        pytest.raises(FileNotFoundError),
    ):
        create_spack_env_from_specs(
            spack_dir=tmp_path / "spack",
            env_dir=tmp_path / "env",
            specs=["zlib"],
        )

    mock_run_spack.assert_not_called()


def test_create_spack_env_from_specs_non_empty_dir(tmp_path):
    spack_dir = tmp_path / "spack"
    bin_dir = spack_dir / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "spack").touch()
    env_dir = tmp_path / "env"
    env_dir.mkdir()
    (env_dir / "spack.yaml").touch()

    with (
        patch(
            "opa_chain_builder.tools.spack.execute_spack_command"
        ) as mock_run_spack,
        pytest.raises(FileExistsError),
    ):
        create_spack_env_from_specs(
            spack_dir=spack_dir,
            env_dir=env_dir,
            specs=["zlib"],
        )

    mock_run_spack.assert_not_called()


def test_create_spack_env_from_yaml_passes_file(tmp_path):
    spack_dir = tmp_path / "spack"
    bin_dir = spack_dir / "bin"
    bin_dir.mkdir(parents=True)
    spack_exe = bin_dir / "spack"
    spack_exe.touch()
    spack_yaml = tmp_path / "spack.yaml"
    spack_yaml.write_text("spack:\n  specs:\n  - zlib\n")
    env_dir = tmp_path / "env"

    temporary_yaml_path = None

    def check_temporary_file(*args, **kwargs):
        nonlocal temporary_yaml_path
        if args[1][1] == "create":
            temporary_yaml_path = Path(args[1][-1])
            assert temporary_yaml_path != spack_yaml
            assert temporary_yaml_path.is_file()
            assert temporary_yaml_path.read_text() == spack_yaml.read_text()

    with patch(
        "opa_chain_builder.tools.spack.execute_spack_command",
        side_effect=check_temporary_file,
    ) as mock_run_spack:
        result = create_spack_env_from_yaml(
            spack_dir=spack_dir,
            env_dir=env_dir,
            spack_yaml=spack_yaml,
        )

    assert result == env_dir
    assert mock_run_spack.call_args_list == [
        call(
            spack_exe,
            ["env", "create", "--dir", str(env_dir), str(temporary_yaml_path)],
            system_env=ANY,
        ),
        call(spack_exe, ["-e", str(env_dir), "concretize"], system_env=ANY),
    ]
    assert temporary_yaml_path is not None
    assert not temporary_yaml_path.exists()


def test_create_spack_env_from_yaml_can_skip_concretization(tmp_path):
    spack_dir = tmp_path / "spack"
    bin_dir = spack_dir / "bin"
    bin_dir.mkdir(parents=True)
    spack_exe = bin_dir / "spack"
    spack_exe.touch()
    spack_yaml = tmp_path / "spack.yaml"
    spack_yaml.write_text("spack:\n  specs:\n  - zlib\n")
    env_dir = tmp_path / "env"

    with patch(
        "opa_chain_builder.tools.spack.execute_spack_command"
    ) as mock_run_spack:
        create_spack_env_from_yaml(
            spack_dir=spack_dir,
            env_dir=env_dir,
            spack_yaml=spack_yaml,
            concretized=False,
        )

    mock_run_spack.assert_called_once()
    assert mock_run_spack.call_args.args[0] == spack_exe
    assert mock_run_spack.call_args.args[1][:4] == [
        "env",
        "create",
        "--dir",
        str(env_dir),
    ]
    assert len(mock_run_spack.call_args.args[1]) == 5


def test_create_spack_env_from_yaml_removes_temporary_file_on_failure(
    tmp_path,
):
    spack_dir = tmp_path / "spack"
    bin_dir = spack_dir / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "spack").touch()
    spack_yaml = tmp_path / "spack.yaml"
    spack_yaml.write_text("spack:\n  specs:\n  - zlib\n")
    temporary_yaml_path = None

    def fail_with_temporary_file(*args, **kwargs):
        nonlocal temporary_yaml_path
        temporary_yaml_path = Path(args[1][-1])
        assert temporary_yaml_path.is_file()
        error_msg = "Spack failed"
        raise RuntimeError(error_msg)

    with (
        patch(
            "opa_chain_builder.tools.spack.execute_spack_command",
            side_effect=fail_with_temporary_file,
        ),
        pytest.raises(RuntimeError, match="Spack failed"),
    ):
        create_spack_env_from_yaml(
            spack_dir=spack_dir,
            env_dir=tmp_path / "env",
            spack_yaml=spack_yaml,
        )

    assert temporary_yaml_path is not None
    assert not temporary_yaml_path.exists()
    assert spack_yaml.is_file()


def test_create_spack_env_from_yaml_missing_file(tmp_path):
    spack_dir = tmp_path / "spack"
    bin_dir = spack_dir / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "spack").touch()

    with (
        patch(
            "opa_chain_builder.tools.spack.execute_spack_command"
        ) as mock_run_spack,
        pytest.raises(FileNotFoundError),
    ):
        create_spack_env_from_yaml(
            spack_dir=spack_dir,
            env_dir=tmp_path / "env",
            spack_yaml=tmp_path / "missing.yaml",
        )

    mock_run_spack.assert_not_called()


def test_create_spack_env_from_yaml_non_empty_dir(tmp_path):
    spack_dir = tmp_path / "spack"
    bin_dir = spack_dir / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "spack").touch()
    spack_yaml = tmp_path / "spack.yaml"
    spack_yaml.write_text("spack:\n  specs: []\n")
    env_dir = tmp_path / "env"
    env_dir.mkdir()
    (env_dir / "spack.yaml").touch()

    with (
        patch(
            "opa_chain_builder.tools.spack.execute_spack_command"
        ) as mock_run_spack,
        pytest.raises(FileExistsError),
    ):
        create_spack_env_from_yaml(
            spack_dir=spack_dir,
            env_dir=env_dir,
            spack_yaml=spack_yaml,
        )

    mock_run_spack.assert_not_called()
