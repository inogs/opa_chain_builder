import logging
import tempfile
from pathlib import Path
from types import MappingProxyType
from typing import cast

from opa_chain_builder.config import ChainConfig
from opa_chain_builder.tools.git import clone_repository
from opa_chain_builder.tools.git import is_git_lfs_installed
from opa_chain_builder.tools.micromamba import MicromambaExec
from opa_chain_builder.tools.spack import Bootstrap
from opa_chain_builder.tools.spack import create_spack_env_from_yaml
from opa_chain_builder.tools.spack import execute_spack_command

LOGGER = logging.getLogger(__name__)


REPOS = MappingProxyType(
    {
        "model_builder": "git@github.com:inogs/ModelBuild.git",
        "bit.sea": "git@github.com:inogs/bit.sea.git",
        "ogstm_preproc": "git@github.com:inogs/ogstm_preproc.git",
        "ogstm_postproc": "git@github.com:inogs/ogstm_postproc.git",
    }
)


FINAL_MESSAGE = """
Well done! Your chain is ready (almost)!

The next steps:
1. Execute `source {env_file}` to activate your environment.
2. Execute `spack -E {spack_env_dir} install` to install all chain requirements
3. Execute the model builder in {chain_home}/HOST/{chain_hostname}
4. Run `make` and `make install` inside the {chain_home}/bin/src directory

And that's it! Enjoy :-D
"""


def _build_py_env(
    python_config_dir: Path, env_prefix: Path, opa_name: str
) -> None:
    micromamba_exe = MicromambaExec.from_system_path()

    env_file = python_config_dir / "environment.yaml"
    with tempfile.TemporaryDirectory() as temporary_dir:
        temp_dir_path = Path(temporary_dir)
        temp_env_file = temp_dir_path / "environment.yaml"

        env_file_content = env_file.read_text()
        env_file_content = env_file_content.replace("<OPA_NAME>", opa_name)
        temp_env_file.write_text(env_file_content)
        micromamba_exe.create_env(env_file=temp_env_file, prefix=env_prefix)

    pip_packages = python_config_dir / "pip_packages.txt"
    if not pip_packages.exists():
        LOGGER.debug("No pip packages file found at %s", pip_packages)
        LOGGER.info("Python environment setup complete at %s", env_prefix)
        return

    LOGGER.info("Installing pip packages from %s", pip_packages)
    pip_packages_content = pip_packages.read_text().splitlines()
    for raw_line in pip_packages_content:
        # Remove comments and whitespace
        pip_package = raw_line.split("#", 1)[0].strip()
        if len(pip_package) == 0:
            continue
        LOGGER.info("Installing pip package: %s", pip_package)
        commands = ["pip", "install", *pip_package.split()]
        micromamba_exe.run(commands=commands, env_prefix=env_prefix)
    LOGGER.info("Python environment setup complete at %s", env_prefix)


def _build_spack_env(
    env_configs_dir: Path,
    spack_main_dir: Path,
    spack_env_dir: Path,
    chain_compiler: str,
    conda_env_path: Path | None = None,
) -> None:
    spack_config_dir = (env_configs_dir / "spack") / chain_compiler
    spack_bootstrap_dir = spack_config_dir / "bootstrap"
    if spack_bootstrap_dir.exists():
        LOGGER.debug(
            "Reading bootstrap directory from %s", spack_bootstrap_dir
        )
        bootstrap = Bootstrap.from_dir(spack_bootstrap_dir)
        bootstrap.execute(
            env_config_dir=spack_env_dir / "bootstrap",
            new_env_path=spack_env_dir,
            spack_main_dir=spack_main_dir,
        )
    else:
        LOGGER.debug("No bootstrap directory found in %s", spack_bootstrap_dir)

    replace_values = None
    if conda_env_path is not None:
        replace_values = {"CONDA_ENV_PATH": str(conda_env_path)}

    create_spack_env_from_yaml(
        spack_dir=spack_main_dir,
        env_dir=spack_env_dir,
        spack_yaml=spack_config_dir / "spack.yaml",
        allow_non_empty_path=True,
        replace_values=replace_values,
        concretized=False,
    )

    spack_exe = spack_main_dir / "bin" / "spack"

    if conda_env_path is not None:
        LOGGER.info("Setting up Python as external in Spack environment")
        execute_spack_command(
            spack_exe=spack_exe,
            args=["external", "find", "--path", str(conda_env_path), "python"],
            spack_env_dir=spack_env_dir,
        )

    LOGGER.info("Concretizing spack environment at %s", spack_env_dir)
    execute_spack_command(
        spack_exe=spack_exe,
        args=["concretize"],
        spack_env_dir=spack_env_dir,
    )
    LOGGER.info("Spack environment created at %s", spack_env_dir)

    LOGGER.info("Spack environment setup complete at %s", spack_env_dir)


def _write_chain_env_file(
    env_file: Path,
    chain_config: ChainConfig,
    spack_main_dir: Path,
    python_env_dir: Path,
) -> None:
    chain_name = cast("str", chain_config.name)
    LOGGER.info("Writing chain config file to %s", env_file)
    # Refuse to be sourced in a shell where another chain is already loaded
    env_file_header = (
        f'if [ -n "${{OPA_NAME+x}}" ] && [ "$OPA_NAME" != "{chain_name}" ]; '
        "then\n"
        f'    echo "Error: OPA_NAME is already set to \\"$OPA_NAME\\" '
        f'(expected \\"{chain_name}\\")" >&2\n'
        "    return 1\n"
        "fi\n"
        f'export OPA_NAME="{chain_name}"\n\n'
    )
    spack_setup_file = spack_main_dir.resolve() / "share/spack/setup-env.sh"
    env_file_header += (
        "if ! command -v spack > /dev/null 2>&1; then\n"
        f'    source "{spack_setup_file}"\n'
        "fi\n\n"
    )
    micromamba_exe = MicromambaExec.from_system_path()
    # Keep the micromamba shell function of the user, if already initialized
    # Show the chain name in the prompt instead of the full env prefix; the
    # value is parsed as YAML, so it is quoted to keep the trailing space
    env_file_footer = (
        "\nif ! declare -F micromamba > /dev/null; then\n"
        f'    eval "$("{micromamba_exe.exe_path.resolve()}" '
        'shell hook --shell bash)"\n'
        "fi\n"
        f"MAMBA_ENV_PROMPT='\"({chain_name}) \"' "
        f'micromamba activate "{python_env_dir.resolve()}"\n'
    )
    env_file.write_text(
        env_file_header
        + chain_config.prepare_environment_file()
        + env_file_footer
    )


def build_chain(
    chain_config: ChainConfig, spack_main_dir: Path, env_configs_dir: Path
) -> None:
    """
    Build an OPA chain described by ``chain_config``.

    The chain repository is cloned into the chain home, the chain
    environment file is written, and the Python (micromamba) and Spack
    environments of the current host are created inside it.

    Args:
        chain_config: Concretized configuration of the chain to build.
        spack_main_dir: Directory of the Spack installation used to create
            the Spack environment.
        env_configs_dir: Directory containing the ``conda`` and ``spack``
            environment configurations.

    Raises:
        ValueError: If ``chain_config`` has not been concretized.
        RuntimeError: If git-lfs is not installed.
        OSError: If the environment directories are not empty.

    """
    chain_name = cast("str", chain_config.name)
    chain_home = chain_config.home
    chain_hostname = chain_config.hostname
    chain_compiler = chain_config.compiler
    if chain_home is None or chain_hostname is None:
        error_msg = (
            "This procedure has been called without concretizing the "
            "configuration first"
        )
        raise ValueError(error_msg)

    if not is_git_lfs_installed():
        error_msg = (
            "git-lfs is not installed. Please install git-lfs to proceed."
        )
        raise RuntimeError(error_msg)

    LOGGER.info("Cloning chain repository")
    clone_repository(
        repo_url="git@gitlab-ssh.hpc.cineca.it:OGS/v5c.git",
        destination=chain_home,
        ref=chain_config.branches.chain,
    )

    # We need to set the right permissions on the keys file of the repo
    key_dir = chain_home / "etc" / "sftp-config"
    LOGGER.debug("Setting permissions on files of directory %s", key_dir)
    for key in key_dir.iterdir():
        if not key.is_file():
            continue
        if key.name.startswith("."):
            continue
        LOGGER.debug("Setting permissions on file %s", key)
        key.chmod(0o600)

    host_dir = chain_home / "HOST"
    current_host_dir = host_dir / chain_hostname
    spack_env_dir = current_host_dir / "spack_env"
    python_env_dir = current_host_dir / "python_env"

    env_file = chain_home / "chain_env.sh"
    _write_chain_env_file(
        env_file=env_file,
        chain_config=chain_config,
        spack_main_dir=spack_main_dir,
        python_env_dir=python_env_dir,
    )

    spack_env_dir.mkdir(parents=True, exist_ok=True)
    python_env_dir.mkdir(parents=True, exist_ok=True)

    if any(spack_env_dir.iterdir()):
        error_msg = (
            f"The directory of the spack environment {spack_env_dir} "
            "is not empty."
        )
        raise OSError(error_msg)
    if any(python_env_dir.iterdir()):
        error_msg = (
            f"The directory of the python environment {python_env_dir} "
            "is not empty."
        )
        raise OSError(error_msg)

    python_config_dir = env_configs_dir / "conda"
    _build_py_env(
        python_config_dir=python_config_dir,
        env_prefix=python_env_dir,
        opa_name=chain_name,
    )

    _build_spack_env(
        env_configs_dir=env_configs_dir,
        spack_main_dir=spack_main_dir,
        spack_env_dir=spack_env_dir,
        chain_compiler=chain_compiler,
        conda_env_path=python_env_dir,
    )

    LOGGER.info("Cloning repos...")
    for repo_name, repo_url in REPOS.items():
        repo_branch_attribute = repo_name.split("_")[-1].replace(".", "")
        repo_branch = getattr(chain_config.branches, repo_branch_attribute)
        LOGGER.info(
            "Cloning repo %s using branch %s from %s",
            repo_name,
            repo_branch,
            repo_url,
        )

        clone_repository(
            repo_url=repo_url,
            destination=current_host_dir / repo_name,
            ref=repo_branch,
        )

    LOGGER.info("Chain is ready!")

    final_message = FINAL_MESSAGE.format(
        env_file=env_file,
        spack_env_dir=spack_env_dir.resolve(),
        chain_home=chain_home.resolve(),
        chain_hostname=chain_hostname,
    )
    print(final_message)  # noqa: T201
