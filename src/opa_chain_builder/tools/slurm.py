"""Helpers to interact with a local Slurm installation."""

import getpass
import logging
import shutil
import subprocess

LOGGER = logging.getLogger(__name__)


def is_slurm_installed() -> bool:
    """Return ``True`` if a Slurm installation is available on this host."""
    return shutil.which("sacctmgr") is not None


def get_default_account(username: str | None = None) -> str | None:
    """
    Return the Slurm default account of a user.

    Args:
        username: User whose default account is looked up. Defaults to the
            user running the current process.

    Returns:
        The default Slurm account configured for ``username``, or ``None``
        if Slurm is not installed on this machine or the user has no
        default account configured.

    Raises:
        RuntimeError: If Slurm is installed but the ``sacctmgr`` command
            fails.

    """
    if not is_slurm_installed():
        LOGGER.debug("Slurm is not installed on this machine")
        return None

    if username is None:
        username = getpass.getuser()

    args = [
        "sacctmgr",
        "show",
        "user",
        username,
        "--noheader",
        "--parsable2",
        "format=DefaultAccount",
    ]
    cmd_str = " ".join(args)
    LOGGER.debug("Executing Slurm command: %s", cmd_str)

    try:
        result = subprocess.run(
            args,
            check=True,
            capture_output=True,
            text=True,
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

    default_account = result.stdout.strip()
    if not default_account:
        LOGGER.debug("No default Slurm account found for user '%s'", username)
        return None

    return default_account
