"""Helpers to locate and install the micromamba executable."""

import io
import logging
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path
from typing import Self

MICROMAMBA_EXE_NAME = "micromamba"
MICROMAMBA_ARCHIVE_MEMBER = "bin/micromamba"
MICROMAMBA_URL_TEMPLATE = "https://micro.mamba.pm/api/micromamba/{}/latest"
MICROMAMBA_DOWNLOAD_TIMEOUT = 120

_PLATFORMS = {
    ("linux", "x86_64"): "linux-64",
    ("linux", "aarch64"): "linux-aarch64",
    ("linux", "ppc64le"): "linux-ppc64le",
    ("darwin", "x86_64"): "osx-64",
    ("darwin", "arm64"): "osx-arm64",
}


LOGGER = logging.getLogger(__name__)


def _micromamba_platform() -> str:
    key = (sys.platform, platform.machine().lower())
    if key not in _PLATFORMS:
        error_msg = f"Unsupported platform for micromamba: {key}"
        raise RuntimeError(error_msg)
    return _PLATFORMS[key]


class MicromambaNotFoundError(RuntimeError):
    """Raised when micromamba cannot be found in the system path."""


class MicromambaExec:
    """Wrapper around a micromamba executable."""

    def __init__(self, exe_path: str | Path) -> None:
        """
        Create a wrapper for the micromamba executable at ``exe_path``.

        Args:
            exe_path: Path to the micromamba executable.

        """
        self.exe_path = Path(exe_path)

    @classmethod
    def from_path(cls, path: str | Path) -> Self:
        """
        Detect the micromamba executable from ``path``.

        Args:
            path: Either the micromamba executable itself or a directory
                containing a ``micromamba`` executable.

        Returns:
            A ``MicromambaExec`` pointing to the detected executable.

        Raises:
            RuntimeError: If no executable is found at ``path``, or the
                file found is not executable.

        """
        path = Path(path)
        exe_path = path / MICROMAMBA_EXE_NAME if path.is_dir() else path

        if not exe_path.is_file():
            error_msg = f"micromamba executable not found at '{exe_path}'"
            raise RuntimeError(error_msg)
        if not os.access(exe_path, os.X_OK):
            error_msg = f"micromamba at '{exe_path}' is not executable"
            raise RuntimeError(error_msg)

        return cls(exe_path)

    @classmethod
    def from_system_path(cls) -> Self:
        """
        Find the micromamba executable in the system ``PATH``.

        Returns:
            A ``MicromambaExec`` pointing to the executable found.

        Raises:
            MicromambaNotFoundError: If micromamba is not in the ``PATH``.

        """
        found = shutil.which(MICROMAMBA_EXE_NAME)
        if found is None:
            error_msg = "micromamba executable not found in the system PATH"
            raise MicromambaNotFoundError(error_msg)
        return cls(found)

    @staticmethod
    def install(install_dir: str | Path) -> "MicromambaExec":
        """
        Install the latest micromamba release into ``install_dir``.

        The release is downloaded from the official micromamba API for the
        current platform. Only Linux and macOS are supported.

        Args:
            install_dir: Directory the ``micromamba`` executable is written
                to. It is created if it does not exist.

        Returns:
            A ``MicromambaExec`` pointing to the installed executable.

        Raises:
            RuntimeError: If the platform is unsupported, the download fails,
                or the archive does not contain the micromamba executable.

        """
        install_dir = Path(install_dir)
        url = MICROMAMBA_URL_TEMPLATE.format(_micromamba_platform())

        LOGGER.info("Downloading latest micromamba from '%s'", url)
        try:
            # The URL is built from a fixed https template, so no file: or
            # custom scheme can be used here
            with urllib.request.urlopen(  # noqa: S310  # nosec B310
                url, timeout=MICROMAMBA_DOWNLOAD_TIMEOUT
            ) as response:
                archive = response.read()
        except OSError as exc:
            error_msg = f"Failed to download micromamba from '{url}': {exc}"
            raise RuntimeError(error_msg) from exc

        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:bz2") as tar:
            try:
                member = tar.extractfile(MICROMAMBA_ARCHIVE_MEMBER)
            except KeyError as exc:
                error_msg = (
                    f"'{MICROMAMBA_ARCHIVE_MEMBER}' not found in the "
                    f"micromamba archive downloaded from '{url}'"
                )
                raise RuntimeError(error_msg) from exc
            if member is None:
                error_msg = (
                    f"'{MICROMAMBA_ARCHIVE_MEMBER}' is not a regular file "
                    "in the micromamba archive"
                )
                raise RuntimeError(error_msg)
            executable = member.read()

        install_dir.mkdir(parents=True, exist_ok=True)
        exe_path = install_dir / MICROMAMBA_EXE_NAME
        exe_path.write_bytes(executable)
        exe_path.chmod(0o755)

        LOGGER.info("Installed micromamba at '%s'", exe_path)
        return MicromambaExec(exe_path)

    def create_env(self, env_file: Path, prefix: Path | None = None) -> None:
        """
        Create a micromamba environment from an environment file.

        Args:
            env_file: Path to the environment file.
            prefix: Optional path to the environment prefix. If not provided,
                the prefix is read from the environment file.

        """
        path = [str(self.exe_path), "create", "--yes", "--file", str(env_file)]
        if prefix is not None:
            path.extend(["--prefix", str(prefix)])
        LOGGER.info("Creating micromamba environment from '%s'", env_file)
        subprocess.run(path, check=True)
        LOGGER.info("Created micromamba environment")

    def run(self, commands: list[str], env_prefix: Path | None = None) -> None:
        """
        Run a command in the micromamba environment.

        Args:
            commands: List of command arguments to run. If not provided,
                the default shell is run.
            env_prefix: Optional path to the prefix of the environment the
                command is run in.

        """
        path = [str(self.exe_path), "run"]
        if env_prefix is not None:
            path.extend(["--prefix", str(env_prefix)])
        path.extend(commands)
        LOGGER.debug("Running command in micromamba environment: %s", commands)
        subprocess.run(path, check=True)
        LOGGER.debug("Command finished successfully")
