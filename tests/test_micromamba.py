"""Tests for the micromamba helpers."""

from pathlib import Path

import pytest

from opa_chain_builder.tools.micromamba import (
    MICROMAMBA_EXE_NAME,
    MicromambaExec,
    MicromambaNotFoundError,
)


def _make_exe(directory: Path, name: str = MICROMAMBA_EXE_NAME) -> Path:
    exe = directory / name
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    return exe


def test_from_current_env_uses_mamba_exe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe = _make_exe(tmp_path)
    monkeypatch.setenv("MAMBA_EXE", str(exe))
    monkeypatch.setenv("PATH", "")

    assert MicromambaExec.from_current_env().exe_path == exe


def test_from_current_env_ignores_wrong_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = _make_exe(tmp_path, name="mamba")
    path_dir = tmp_path / "bin"
    path_dir.mkdir()
    exe = _make_exe(path_dir)
    monkeypatch.setenv("MAMBA_EXE", str(other))
    monkeypatch.setenv("PATH", str(path_dir))

    assert MicromambaExec.from_current_env().exe_path == exe


def test_from_current_env_ignores_non_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    not_exe = tmp_path / MICROMAMBA_EXE_NAME
    not_exe.write_text("")
    not_exe.chmod(0o644)
    path_dir = tmp_path / "bin"
    path_dir.mkdir()
    exe = _make_exe(path_dir)
    monkeypatch.setenv("MAMBA_EXE", str(not_exe))
    monkeypatch.setenv("PATH", str(path_dir))

    assert MicromambaExec.from_current_env().exe_path == exe


def test_from_current_env_falls_back_to_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe = _make_exe(tmp_path)
    monkeypatch.delenv("MAMBA_EXE", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))

    assert MicromambaExec.from_current_env().exe_path == exe


def test_from_current_env_raises_when_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAMBA_EXE", str(tmp_path / MICROMAMBA_EXE_NAME))
    monkeypatch.setenv("PATH", str(tmp_path))

    with pytest.raises(MicromambaNotFoundError):
        MicromambaExec.from_current_env()
