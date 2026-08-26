"""Helpers to install and configure a Spack instance."""

import logging
import os
import subprocess
from pathlib import Path

from opa_chain_builder.tools.git import checkout_ref
from opa_chain_builder.tools.git import clone_repository

SPACK_REPO_URL = "https://github.com/spack/spack.git"
INTEL_ONEAPI_COMPILERS_SPEC = "intel-oneapi-compilers"
_MIN_QUOTED_VALUE_LENGTH = 2


LOGGER = logging.getLogger(__name__)


def _run_spack(
    spack_exe: Path,
    args: list[str],
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    cmd_str = " ".join([str(spack_exe), *args])
    LOGGER.debug("Executing Spack command: %s", cmd_str)

    env = env.copy() if env is not None else {}
    env["TERM"] = "dumb"
    env["SPACK_COLOR"] = "never"

    try:
        return subprocess.run(
            [str(spack_exe), *args],
            check=True,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            text=True,
            env=env,
            timeout=1200,
        )
    except subprocess.CalledProcessError as exc:
        LOGGER.exception(
            "Command '%s' failed with return code %s:\n%s",
            cmd_str,
            exc.returncode,
            exc.stderr,
        )
        error_msg = f"Command '{cmd_str}' failed:\n{exc.stderr}"
        raise RuntimeError(error_msg) from exc
    except subprocess.TimeoutExpired as exc:
        LOGGER.exception(
            "Command '%s' timed out after %s seconds:\n%s\n\n%s",
            cmd_str,
            exc.timeout,
            exc.stdout,
            exc.stderr,
        )
        error_msg = (
            f"Command '{cmd_str}' timed out after {exc.timeout} seconds"
        )
        raise RuntimeError(error_msg) from exc


def _env_after_loading_package(
    spack_exe: Path, spec: str, base_env: dict[str, str]
) -> dict[str, str]:
    """
    Compute the environment obtained by ``spack load`` for ``spec``.

    ``spack load`` normally works as a shell function sourced from
    ``setup-env.sh`` and mutates the *current* shell. Since we run spack as a
    subprocess, we instead ask spack to print the POSIX shell commands that
    would be evaluated (``spack load --sh``) and apply the resulting
    ``export`` statements to a copy of ``base_env``, which can then be used
    to run further spack commands (e.g. ``spack compiler find``) able to see
    the loaded package's executables on ``PATH``.
    """
    LOGGER.debug("Extracting environment modifications for package '%s'", spec)
    result = _run_spack(spack_exe, ["load", "--sh", spec], env=base_env)

    env = dict(base_env)
    for raw_line in result.stdout.splitlines():
        stripped_line = raw_line.strip()
        if not stripped_line.startswith("export "):
            continue
        assignment = stripped_line[len("export ") :]
        key, sep, value = assignment.partition("=")
        if not sep:
            continue
        value = value.strip()
        is_quoted = (
            len(value) >= _MIN_QUOTED_VALUE_LENGTH
            and value[0] == value[-1]
            and value[0] in ("'", '"')
        )
        if is_quoted:
            value = value[1:-1]
        env[key] = value

    return env


def install_spack(
    install_dir: str | os.PathLike,
    version: str,
    spack_config: list[str] | None = None,
    compiler_spec: str = INTEL_ONEAPI_COMPILERS_SPEC,
    compiler_scope: str = "site",
) -> Path:
    """
    Install a specific version of Spack and register an Intel compiler.

    This clones Spack into ``install_dir``, checks out ``version`` (a branch
    name or a commit SHA), installs the ``intel-oneapi-compilers`` package
    with that Spack instance, and registers the resulting compiler in
    Spack's configuration under the given scope.

    Args:
        version: Branch name or commit SHA of Spack to install.
        install_dir: Directory Spack is installed into. It must not already
            exist, or must be empty.
        spack_config: Optional list of Spack configuration directives to
            submit to the Spack config file.
        compiler_spec: Spack spec of the compiler package to install.
            Defaults to ``intel-oneapi-compilers``.
        compiler_scope: Configuration scope ``spack compiler find`` should
            register the compiler under (e.g. ``site``, ``user``).

    Returns:
        The path to the Spack installation (``install_dir``).

    Raises:
        FileExistsError: If ``install_dir`` already exists and is not
            empty.
        RuntimeError: If cloning Spack, checking out ``version``, installing
            the compiler package, or registering the compiler fails.

    """
    install_dir = Path(install_dir)
    LOGGER.info(
        "Starting Spack installation in '%s' with commit version '%s'",
        install_dir,
        version,
    )

    LOGGER.info(
        "Cloning Spack repository from %s into '%s'",
        SPACK_REPO_URL,
        install_dir,
    )
    clone_repository(SPACK_REPO_URL, install_dir)

    LOGGER.info("Checking out Spack ref '%s'", version)
    checkout_ref(install_dir, version)

    spack_exe = install_dir / "bin" / "spack"
    if not spack_exe.is_file():
        LOGGER.error("Spack executable not found at '%s'", spack_exe)
        error_msg = f"Spack executable not found at '{spack_exe}'"
        raise RuntimeError(error_msg)

    base_env = os.environ.copy()

    if spack_config is None:
        spack_config = []

    if len(spack_config) > 0:
        LOGGER.info(
            "Applying %d Spack configuration directives", len(spack_config)
        )
    else:
        LOGGER.debug("No Spack configuration directives provided")
    for config_value in spack_config:
        LOGGER.debug("Applying Spack config: %s", config_value)
        _run_spack(
            spack_exe,
            ["config", "--scope", "site", "add", config_value],
            env=base_env,
        )

    LOGGER.info("Installing compiler package '%s'", compiler_spec)
    _run_spack(spack_exe, ["install", compiler_spec], env=base_env)

    LOGGER.debug(
        "Loading environment for compiler package '%s'", compiler_spec
    )
    env_with_compiler = _env_after_loading_package(
        spack_exe, compiler_spec, base_env
    )

    LOGGER.debug(
        "Registering compiler with Spack under scope '%s'", compiler_scope
    )
    _run_spack(
        spack_exe,
        ["compiler", "find", "--scope", compiler_scope],
        env=env_with_compiler,
    )

    LOGGER.info(
        "Spack installation and configuration completed successfully at '%s'",
        install_dir,
    )
    return install_dir
