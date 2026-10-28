"""Helpers to install and configure a Spack instance."""

import logging
import os
import subprocess
import tempfile
from collections.abc import Iterable
from pathlib import Path

from opa_chain_builder.tools.git import checkout_ref
from opa_chain_builder.tools.git import clone_repository

SPACK_REPO_URL = "https://github.com/spack/spack.git"
INTEL_ONEAPI_COMPILERS_SPEC = "intel-oneapi-compilers@2025.3.2"
GCC_COMPILER_SPEC = "gcc@15"


LOGGER = logging.getLogger(__name__)


class Bootstrap:
    """
    Configuration for commands that must be run before creating a new env.

    A BootstrapConfig is a collection of Spack configuration files that are
    applied to the Spack instance before creating a new environment. This is
    useful to set up mirrors, add custom package repositories, or configure
    compilers before creating an environment that depends on them.

    Even if the name suggests otherwise, this class has nothing to do with
    Spack's bootstrap process, and is only used to prepare spack to generate
    a new environment.
    """

    def __init__(
        self,
        exec_commands: Iterable[Iterable[str]],
        config_files: Iterable[str | os.PathLike],
    ) -> None:
        """
        Create a Bootstrap from its commands and configuration files.

        Args:
            exec_commands: Spack commands to execute, each one given as the
                sequence of its arguments (without the spack executable).
            config_files: Spack configuration files to copy into the
                environment before executing the commands.

        """
        self.exec_commands = tuple(tuple(cmd) for cmd in exec_commands)
        self.config_files = tuple(Path(d) for d in config_files)

    @classmethod
    def from_dir(cls, config_dir: str | os.PathLike) -> "Bootstrap":
        """
        Create a BootstrapConfig from a directory of Spack config files.

        Args:
            config_dir: Directory containing Spack configuration files.

        """
        config_dir = Path(config_dir)
        if not config_dir.is_dir():
            error_msg = f"'{config_dir}' is not a directory"
            raise ValueError(error_msg)

        config_files = [
            f
            for f in config_dir.iterdir()
            if f.is_file()
            if f.name != "run_commands.txt"
        ]

        run_commands_file = config_dir / "run_commands.txt"
        exec_commands = []
        for raw_line in run_commands_file.read_text().splitlines():
            cmd_line = raw_line.split("#", 1)[0].strip()
            if not cmd_line:
                continue
            exec_commands.append(tuple(cmd_line.split()))
        return cls(exec_commands, config_files)

    def _copy_in_env(
        self,
        env_config_dir: str | os.PathLike,
        replace_values: dict[str, str] | None = None,
    ) -> None:
        """
        Copy the configuration of this `Bootstrap` into a new directory.

        The new files will be "concretized", meaning that any placeholder of
        the form `<PLACEHOLDER>` will be replaced with the corresponding value
        in `replace_values`.

        Usually, this is used to copy the configuration into a new Spack
        environment's config directory, so that we can run the bootstrap
        commands after having loaded this configuration.
        """
        for file in self.config_files:
            dest_file = Path(env_config_dir) / file.name
            file_content = file.read_text()
            if replace_values:
                for old, new in replace_values.items():
                    file_content = file_content.replace(
                        f"<{old.upper()}>", new
                    )
            LOGGER.debug("Copying config file '%s' to '%s'", file, dest_file)
            dest_file.write_text(file_content)

    def execute(
        self,
        env_config_dir: str | os.PathLike,
        new_env_path: str | os.PathLike,
        spack_main_dir: str | os.PathLike,
    ) -> None:
        """
        Execute the commands of this `Bootstrap` in a new environment.

        The commands are executed in the order they were added to the
        `Bootstrap`, and the environment is passed to each command. If any
        command fails, an exception is raised and the process is aborted.
        """
        _replace_values = {
            "ENV_DIR": str(new_env_path),
            "INTEL_COMPILER": str(INTEL_ONEAPI_COMPILERS_SPEC),
            "GCC_COMPILER": str(GCC_COMPILER_SPEC),
        }

        spack_exe = Path(spack_main_dir) / "bin" / "spack"

        Path(env_config_dir).mkdir(parents=False, exist_ok=True)
        self._copy_in_env(env_config_dir, replace_values=_replace_values)

        for raw_cmd in self.exec_commands:
            cmd = [str(spack_exe), "-C", str(env_config_dir)]
            for raw_element in raw_cmd:
                element = raw_element
                for old, new in _replace_values.items():
                    element = element.replace(f"<{old.upper()}>", new)
                cmd.append(element)

            LOGGER.debug("Executing bootstrap command: %s", " ".join(cmd))
            try:
                subprocess.run(
                    cmd,
                    check=True,
                    capture_output=True,
                    stdin=subprocess.DEVNULL,
                    text=True,
                )
            except subprocess.CalledProcessError as exc:
                LOGGER.exception(
                    "Bootstrap command '%s' failed with return code %s:\n%s",
                    " ".join(cmd),
                    exc.returncode,
                    exc.stderr,
                )
                error_msg = (
                    f"Bootstrap command '{' '.join(cmd)}' failed:\n"
                    f"{exc.stderr}"
                )
                raise RuntimeError(error_msg) from exc


def execute_spack_command(
    spack_exe: Path,
    args: list[str],
    spack_env_dir: Path | None = None,
    system_env: dict[str, str] | None = None,
    timeout: int | None = 1200,
) -> subprocess.CompletedProcess:
    """
    Execute a Spack command and return its completed process.

    Args:
        spack_exe: Path to the Spack executable.
        args: Command-line arguments to pass to Spack.
        spack_env_dir: If given, the Spack environment directory to use for
            the command. This is passed to Spack with ``-e <spack_env_dir>``.
        system_env: Environment variables for the command. ``TERM`` and
            ``SPACK_COLOR`` are set to stable, non-interactive values.
        timeout: Maximum execution time in seconds, or ``None`` for no
            timeout.

    Returns:
        The completed subprocess result, including its captured output.

    Raises:
        RuntimeError: If the command fails or times out.

    """
    cmd_str = " ".join([str(spack_exe), *args])
    LOGGER.debug("Executing Spack command: %s", cmd_str)

    system_env = (
        system_env.copy() if system_env is not None else os.environ.copy()
    )
    system_env["TERM"] = "dumb"
    system_env["SPACK_COLOR"] = "never"

    subprocess_kwargs = {
        "capture_output": True,
        "stdin": subprocess.DEVNULL,
        "text": True,
        "env": system_env,
    }
    if timeout is not None:
        subprocess_kwargs["timeout"] = timeout

    commands = [str(spack_exe)]
    if spack_env_dir is not None:
        commands.extend(["-e", str(spack_env_dir)])
    commands.extend(args)

    try:
        return subprocess.run(commands, check=True, **subprocess_kwargs)
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
    result = execute_spack_command(
        spack_exe, ["load", "--sh", spec], system_env=base_env
    )

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
            len(value) > 1 and value[0] == value[-1] and value[0] in ("'", '"')
        )
        if is_quoted:
            value = value[1:-1]
        env[key] = value

    return env


def _install_compiler(
    spack_dir: Path,
    compiler_spec: str,
    compiler_scope: str | None,
) -> None:
    """
    Install a compiler package with Spack and register it in its scope.

    Shared implementation of the ``install_spack_*_compiler`` functions.
    """
    spack_exe = spack_dir / "bin" / "spack"
    base_env = os.environ.copy()

    LOGGER.info("Installing compiler package '%s'", compiler_spec)
    execute_spack_command(
        spack_exe, ["install", compiler_spec], system_env=base_env
    )

    if compiler_scope is not None:
        LOGGER.debug(
            "Loading environment for compiler package '%s'", compiler_spec
        )
        env_with_compiler = _env_after_loading_package(
            spack_exe, compiler_spec, base_env
        )

        LOGGER.debug(
            "Registering compiler with Spack under scope '%s'", compiler_scope
        )
        execute_spack_command(
            spack_exe,
            ["compiler", "find", "--scope", compiler_scope],
            system_env=env_with_compiler,
        )


def install_spack_intel_compiler(
    spack_dir: str | os.PathLike,
    compiler_spec: str = INTEL_ONEAPI_COMPILERS_SPEC,
    compiler_scope: str | None = "site",
) -> None:
    """
    Install an Intel compiler with Spack and register it in its configuration.

    The compiler package is installed with the Spack instance in ``spack_dir``,
    its environment is loaded, and ``spack compiler find`` registers the
    resulting compiler under ``compiler_scope``.

    Args:
        spack_dir: Directory of an existing Spack installation, as returned
            by ``install_spack``.
        compiler_spec: Spack spec of the compiler package to install.
            Defaults to ``intel-oneapi-compilers``.
        compiler_scope: Configuration scope ``spack compiler find`` should
            register the compiler under (e.g. ``site``, ``user``).
            If ``None``, the compiler is not registered in any scope.

    Raises:
        RuntimeError: If installing the compiler package or registering the
            compiler fails.

    """
    _install_compiler(Path(spack_dir), compiler_spec, compiler_scope)


def install_spack_gcc_compiler(
    spack_dir: str | os.PathLike,
    compiler_spec: str = GCC_COMPILER_SPEC,
    compiler_scope: str | None = "site",
) -> None:
    """
    Install a recent GCC with Spack and register it in its configuration.

    The compiler package is installed with the Spack instance in ``spack_dir``,
    its environment is loaded, and ``spack compiler find`` registers the
    resulting compiler under ``compiler_scope``.

    Args:
        spack_dir: Directory of an existing Spack installation, as returned
            by ``install_spack``.
        compiler_spec: Spack spec of the GCC package to install.
            Defaults to ``gcc@15``.
        compiler_scope: Configuration scope ``spack compiler find`` should
            register the compiler under (e.g. ``site``, ``user``). If
            ``None``, the compiler is not registered in any scope.

    Raises:
        RuntimeError: If installing the GCC package or registering the
            compiler fails.

    """
    _install_compiler(Path(spack_dir), compiler_spec, compiler_scope)


COMPILER_INSTALLERS = {
    "intel": install_spack_intel_compiler,
    "gcc": install_spack_gcc_compiler,
}


def install_spack(  # noqa: PLR0913
    install_dir: str | os.PathLike,
    version: str,
    spack_config: list[str] | None = None,
    *,
    search_for_local_compilers: bool = False,
    install_compilers: tuple[str, ...] = ("gcc",),
    compiler_scope: str | None = "spack",
) -> Path:
    """
    Install a specific version of Spack and register the chosen compilers.

    This clones Spack into ``install_dir``, checks out ``version`` (a branch
    name or a commit SHA), and installs each compiler in
    ``install_compilers`` with that Spack instance, registering it in
    Spack's configuration under the given scope.

    Args:
        version: Branch name or commit SHA of Spack to install.
        install_dir: Directory Spack is installed into. It must not already
            exist, or must be empty.
        spack_config: Optional list of Spack configuration directives to
            submit to the Spack config file.
        search_for_local_compilers: If ``True``, run ``spack compiler find``
            (under ``compiler_scope``, if given) to register compilers already
            present on the machine before installing the new ones. The scope
            is always "site" for the compilers found by this function.
        install_compilers: Compilers to install, chosen among ``"intel"``
            (``intel-oneapi-compilers``) and ``"gcc"`` (a recent GCC). Use
            ``("intel", "gcc")`` to install both, or an empty tuple to skip
            compilers.
        compiler_scope: Configuration scope ``spack compiler find`` should
            register the compilers under (e.g. ``site``, ``user``). If
            ``None``, the compiler is not registered in any scope.

    Returns:
        The path to the Spack installation (``install_dir``).

    Raises:
        ValueError: If ``install_compilers`` contains an unknown compiler
            name. Checked before anything is cloned or installed.
        FileExistsError: If ``install_dir`` already exists and is not
            empty.
        RuntimeError: If cloning Spack, checking out ``version``, installing
            a compiler package, or registering a compiler fails.

    """
    unknown_compilers = [
        c for c in install_compilers if c not in COMPILER_INSTALLERS
    ]
    if unknown_compilers:
        error_msg = (
            f"Unknown compiler(s) {unknown_compilers}, expected a subset of "
            f"{list(COMPILER_INSTALLERS)}"
        )
        raise ValueError(error_msg)

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
        execute_spack_command(
            spack_exe,
            ["config", "--scope", "spack", "add", config_value],
            system_env=base_env,
        )

    if search_for_local_compilers:
        LOGGER.info("Searching for compilers already present on the machine")
        find_args = ["compiler", "find", "--scope", compiler_scope]
        execute_spack_command(spack_exe, find_args, system_env=base_env)

    for compiler in install_compilers:
        installer = COMPILER_INSTALLERS[compiler]
        installer(install_dir, compiler_scope=compiler_scope)

    LOGGER.info(
        "Spack installation and configuration completed successfully at '%s'",
        install_dir,
    )
    return install_dir


def _check_spack_env_inputs(
    spack_dir: Path,
    env_dir: Path,
    *,
    allow_non_empty_path: bool = False,
) -> Path:
    """
    Check that ``spack_dir`` holds a Spack executable and ``env_dir`` is free.

    If ``allow_non_empty_path`` is True, the function will not raise an error
    if ``env_dir`` is not empty.

    Returns:
        The path to the Spack executable.

    Raises:
        FileNotFoundError: If no Spack executable is found in ``spack_dir``.
        FileExistsError: If ``env_dir`` already exists and is not empty.

    """
    spack_exe = spack_dir / "bin" / "spack"
    if not spack_exe.is_file():
        LOGGER.error("Spack executable not found at '%s'", spack_exe)
        error_msg = f"Spack executable not found at '{spack_exe}'"
        raise FileNotFoundError(error_msg)

    if (
        env_dir.exists()
        and not allow_non_empty_path
        and any(env_dir.iterdir())
    ):
        LOGGER.error("Environment directory '%s' is not empty", env_dir)
        error_msg = f"Environment directory '{env_dir}' is not empty"
        raise FileExistsError(error_msg)

    return spack_exe


def create_spack_env_from_specs(
    spack_dir: str | os.PathLike,
    env_dir: str | os.PathLike,
    specs: list[str],
    *,
    concretized: bool = True,
) -> Path:
    """
    Create a directory-based Spack environment containing ``specs``.

    The environment is generated and concretized by default, but not
    installed: the packages are installed afterwards with
    ``spack -e <env_dir> install``.

    Args:
        spack_dir: Directory of an existing Spack installation, as returned
            by ``install_spack``.
        env_dir: Directory the Spack environment is created in. It must not
            already exist, or must be empty.
        specs: Spack specs to add to the environment.
        concretized: If True, concretize the environment before returning.

    Returns:
        The path to the Spack environment (``env_dir``).

    Raises:
        FileNotFoundError: If no Spack executable is found in ``spack_dir``.
        FileExistsError: If ``env_dir`` already exists and is not empty.
        RuntimeError: If creating, adding a spec, or concretizing fails.

    """
    spack_dir = Path(spack_dir)
    env_dir = Path(env_dir)
    LOGGER.info(
        "Creating Spack environment in '%s' with %d specs",
        env_dir,
        len(specs),
    )

    spack_exe = _check_spack_env_inputs(spack_dir, env_dir)

    base_env = os.environ.copy()

    execute_spack_command(
        spack_exe,
        ["env", "create", "--dir", str(env_dir)],
        system_env=base_env,
    )

    for spec in specs:
        LOGGER.debug("Adding spec '%s' to environment '%s'", spec, env_dir)
        execute_spack_command(
            spack_exe,
            ["-e", str(env_dir), "add", spec],
            system_env=base_env,
        )

    if concretized:
        execute_spack_command(
            spack_exe,
            ["-e", str(env_dir), "concretize"],
            system_env=base_env,
        )

    LOGGER.info("Spack environment created successfully at '%s'", env_dir)
    return env_dir


def create_spack_env_from_yaml(  # noqa: PLR0913
    spack_dir: str | os.PathLike,
    env_dir: str | os.PathLike,
    spack_yaml: str | os.PathLike,
    *,
    allow_non_empty_path: bool = False,
    replace_values: dict[str, str] | None = None,
    concretized: bool = True,
) -> Path:
    """
    Create a directory-based Spack environment from an existing spack.yaml.

    The file is copied into the environment as its ``spack.yaml``, so its
    specs, configuration and views are used as they are. As with
    ``create_spack_env_from_specs``, the environment is generated and
    concretized by default, but not installed: the packages are installed
    afterwards with ``spack -e <env_dir> install``.

    Args:
        spack_dir: Directory of an existing Spack installation, as returned
            by ``install_spack``.
        env_dir: Directory the Spack environment is created in. It must not
            already exist, or must be empty.
        spack_yaml: Path to the spack.yaml describing the environment.
        allow_non_empty_path: If True, the function will not raise an error
            if ``env_dir`` is not empty.
        replace_values: A dictionary of values to replace in the spack.yaml
            file. If the spack.yaml contains placeholders of the form
            ``<PLACEHOLDER>``, they will be replaced with the corresponding
            value in this dictionary by looking up the key ``PLACEHOLDER``.
            Some placeholders are always replaced, such as ``<SPACK_DIR>``
            (which is the main directory where spack is installed),
            ``<ENV_DIR>`` (which is the directory where the environment is
            created), and the compiler specs ``<INTEL_COMPILER>`` and
            ``<GCC_COMPILER>``.
        concretized: If True, concretize the environment before returning.

    Returns:
        The path to the Spack environment (``env_dir``).

    Raises:
        FileNotFoundError: If no Spack executable is found in ``spack_dir``,
            or if ``spack_yaml`` does not exist.
        FileExistsError: If ``env_dir`` already exists and is not empty.
        RuntimeError: If creating or concretizing the environment fails.

    """
    spack_dir = Path(spack_dir)
    env_dir = Path(env_dir)
    spack_yaml = Path(spack_yaml)
    LOGGER.info(
        "Creating Spack environment in '%s' from '%s'",
        env_dir,
        spack_yaml,
    )

    spack_exe = _check_spack_env_inputs(
        spack_dir, env_dir, allow_non_empty_path=allow_non_empty_path
    )
    if not spack_yaml.is_file():
        LOGGER.error("Spack environment file not found at '%s'", spack_yaml)
        error_msg = f"Spack environment file not found at '{spack_yaml}'"
        raise FileNotFoundError(error_msg)

    base_env = os.environ.copy()

    _replace_values = {}
    if replace_values:
        replace_values["SPACK_DIR"] = str(spack_dir)
        replace_values["ENV_DIR"] = str(env_dir)
        replace_values["INTEL_COMPILER"] = str(INTEL_ONEAPI_COMPILERS_SPEC)
        replace_values["GCC_COMPILER"] = str(GCC_COMPILER_SPEC)
        _replace_values.update(replace_values)

    with tempfile.TemporaryDirectory() as temporary_dir:
        temporary_yaml = Path(temporary_dir) / spack_yaml.name
        yaml_content = spack_yaml.read_text()

        for old, new in _replace_values.items():
            yaml_content = yaml_content.replace(f"<{old.upper()}>", new)

        temporary_yaml.write_text(yaml_content)
        execute_spack_command(
            spack_exe,
            ["env", "create", "--dir", str(env_dir), str(temporary_yaml)],
            system_env=base_env,
        )

    if concretized:
        execute_spack_command(
            spack_exe,
            ["-e", str(env_dir), "concretize"],
            system_env=base_env,
        )

    LOGGER.info("Spack environment created successfully at '%s'", env_dir)
    return env_dir
