import argparse
import logging
from pathlib import Path
from sys import exit as sys_exit

from opa_chain_builder.actions import build_chain
from opa_chain_builder.config import ENV_VAR_NAME
from opa_chain_builder.config import IS_OPA_CONFIG_DIR
from opa_chain_builder.config import ChainConfig
from opa_chain_builder.config import SpackConfig
from opa_chain_builder.config import get_default_config_path
from opa_chain_builder.tools.spack import install_spack

INSTALL_SPACK_ACTION = "install_spack"
BUILD_CHAIN_ACTION = "build_chain"


LOGGER = logging.getLogger(__name__)


def build_arg_parser() -> argparse.ArgumentParser:
    """
    Build the main argparse parser for the ``opa-chain-builder`` CLI.

    The parser exposes a required "action" subcommand with two choices,
    ``install_spack`` and ``build_chain``, each backed by its own subparser
    so that action-specific arguments can be added independently.
    """
    parser = argparse.ArgumentParser(
        prog="opa-chain-builder",
        description="Tools to build OPA chains via Spack.",
    )

    def _existing_path(path: str) -> Path:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            error_msg = f"Path '{p}' does not exist"
            raise argparse.ArgumentTypeError(error_msg)
        return p

    parser.add_argument(
        "-c",
        "--config",
        type=_existing_path,
        required=False,
        default=get_default_config_path(),
        help="Path to the directory containing the config files. If this is "
        f"not specified, this code will read the env variable {ENV_VAR_NAME} "
        "to find the config directory or, if this is not defined, it will "
        "look for a directory named configurations that contains a "
        f'file named "{IS_OPA_CONFIG_DIR}" in the current working directory.',
    )

    subparsers = parser.add_subparsers(dest="action", required=True)

    subparsers.add_parser(
        INSTALL_SPACK_ACTION,
        help="Install a Spack instance and register a compiler.",
    )
    chain_parser = subparsers.add_parser(
        BUILD_CHAIN_ACTION,
        help="Build a toolchain using an installed Spack instance.",
    )

    chain_parser.add_argument(
        "-n",
        "--chain-name",
        type=str,
        required=False,
        default=None,
        help="Name of the chain to build.",
    )

    chain_parser.add_argument(
        "-o",
        "--opa-home",
        type=str,
        required=False,
        default=None,
        help="The main directory of the chain, where the repo will be cloned",
    )

    chain_parser.add_argument(
        "-w",
        "--workdir",
        type=str,
        required=False,
        default=None,
        help="Path of the work dir",
    )

    chain_parser.add_argument(
        "-i",
        "--inpdir",
        type=str,
        required=False,
        default=None,
        help="Path of the input dir",
    )

    chain_parser.add_argument(
        "-z",
        "--arcdir",
        type=str,
        required=False,
        default=None,
        help="Path of the archive dir",
    )

    chain_parser.add_argument(
        "-l",
        "--compiler",
        type=str,
        choices=["gcc", "intel"],
        required=False,
        default=None,
    )

    chain_parser.add_argument(
        "-s",
        "--stage",
        type=str,
        choices=["dev", "prod"],
        required=False,
        default=None,
    )

    chain_parser.add_argument(
        "-a",
        "--account",
        type=str,
        required=False,
        default=None,
    )

    return parser


def main() -> int:
    """
    Parse CLI arguments and run the requested action.

    Returns:
        The process exit code: ``0`` on success, ``1`` on failure.

    """
    parser = build_arg_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if args.config is None:
        LOGGER.error(
            "No config argument provided and no default configuration "
            "directory found."
        )
        return 1

    if args.action == INSTALL_SPACK_ACTION:
        spack_config = SpackConfig.read_from_disk(args.config)
        install_spack(
            install_dir=spack_config.main_dir,
            version=spack_config.commit,
            spack_config=spack_config.config,
            search_for_local_compilers=True,
            install_compilers=(),
        )
        return 0

    if args.action == BUILD_CHAIN_ACTION:
        chain_config = ChainConfig.read_from_disk(args.config)
        spack_config = SpackConfig.read_from_disk(args.config)

        # Put the values read from the cli into the config object
        _add_to_config = (
            "chain_name",
            "opa_home",
            "workdir",
            "inpdir",
            "arcdir",
            "compiler",
            "stage",
            "account",
        )
        for field in _add_to_config:
            config_field_name = field
            if field == "opa_home":
                config_field_name = "home"
            if field == "chain_name":
                config_field_name = "name"
            if (field_value := getattr(args, field)) is not None:
                LOGGER.debug(
                    'Setting value "%s" inside the config field "%s" because '
                    "of what has been read from the command line argument "
                    '"%s"',
                    field_value,
                    config_field_name,
                    field,
                )
                setattr(chain_config, config_field_name, field_value)

        chain_config.concretize()

        build_chain(
            chain_config=chain_config,
            spack_main_dir=spack_config.main_dir,
            env_configs_dir=args.config.parent.parent / "environments",
        )
        return 0

    LOGGER.error("Unknown action: %s", args.action)
    return 1


if __name__ == "__main__":
    sys_exit(main())
