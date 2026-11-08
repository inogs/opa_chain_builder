from unittest.mock import patch

import pytest

from opa_chain_builder.actions.opa_build_chain import _build_py_env

MODULE = "opa_chain_builder.actions.opa_build_chain"

LOCK_CONTENT = """# This file may be used to create an environment using:
# $ conda create --name <env> --file <this file>
# platform: {platform}
@EXPLICIT
https://conda.anaconda.org/conda-forge/noarch/pip-26.2.2-pyh145f28c_0.conda
"""


@pytest.fixture
def conda_dir(tmp_path):
    conda_dir = tmp_path / "conda"
    conda_dir.mkdir()
    (conda_dir / "environment.yaml").write_text("name: <OPA_NAME>\n")
    return conda_dir


def _run_build(conda_dir, env_prefix, current_platform="linux-64"):
    created_from = {}

    def fake_create_env(env_file, prefix=None):
        created_from["path"] = env_file
        created_from["content"] = env_file.read_text()
        created_from["prefix"] = prefix

    with (
        patch(f"{MODULE}.MicromambaExec") as mock_exec_cls,
        patch(f"{MODULE}.micromamba_platform", return_value=current_platform),
    ):
        mock_exe = mock_exec_cls.from_system_path.return_value
        mock_exe.create_env.side_effect = fake_create_env
        _build_py_env(
            python_config_dir=conda_dir,
            env_prefix=env_prefix,
            opa_name="my_opa",
        )
    return created_from


def test_build_py_env_without_lock_uses_yaml(conda_dir, tmp_path):
    env_prefix = tmp_path / "env"
    created_from = _run_build(conda_dir, env_prefix)

    assert created_from["path"].name == "environment.yaml"
    assert created_from["content"] == "name: my_opa\n"
    assert created_from["prefix"] == env_prefix


def test_build_py_env_with_lock_uses_lock(conda_dir, tmp_path):
    lock_file = conda_dir / "environment.lock"
    lock_file.write_text(LOCK_CONTENT.format(platform="linux-64"))
    env_prefix = tmp_path / "env"

    created_from = _run_build(conda_dir, env_prefix)

    assert created_from["path"] == lock_file
    assert created_from["prefix"] == env_prefix


def test_build_py_env_ignores_lock_of_other_platform(
    conda_dir, tmp_path, caplog
):
    lock_file = conda_dir / "environment.lock"
    lock_file.write_text(LOCK_CONTENT.format(platform="osx-arm64"))

    created_from = _run_build(
        conda_dir, tmp_path / "env", current_platform="linux-64"
    )

    assert created_from["path"].name == "environment.yaml"
    assert "osx-arm64" in caplog.text


def test_build_py_env_with_lock_still_installs_pip_packages(
    conda_dir, tmp_path
):
    (conda_dir / "environment.lock").write_text(
        LOCK_CONTENT.format(platform="linux-64")
    )
    (conda_dir / "pip_packages.txt").write_text("foo  # comment\n\nbar\n")
    env_prefix = tmp_path / "env"

    with (
        patch(f"{MODULE}.MicromambaExec") as mock_exec_cls,
        patch(f"{MODULE}.micromamba_platform", return_value="linux-64"),
    ):
        _build_py_env(
            python_config_dir=conda_dir,
            env_prefix=env_prefix,
            opa_name="my_opa",
        )
        mock_exe = mock_exec_cls.from_system_path.return_value
        commands = [c.kwargs["commands"] for c in mock_exe.run.call_args_list]

    assert commands == [["pip", "install", "foo"], ["pip", "install", "bar"]]
