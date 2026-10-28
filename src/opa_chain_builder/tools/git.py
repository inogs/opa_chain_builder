"""Helpers to interact with git repositories."""

import logging
import shutil
import subprocess
from pathlib import Path

from opa_chain_builder.tools.ssh import check_ssh_keys
from opa_chain_builder.tools.ssh import ssh_host_from_url

LOGGER = logging.getLogger(__name__)


def _run_git(
    args: list[str], cwd: Path | None = None
) -> subprocess.CompletedProcess:
    git_exe = shutil.which("git")
    if git_exe is None:
        error_msg = "git executable not found; please install git"
        raise RuntimeError(error_msg)

    cmd_line = [git_exe, *args]
    LOGGER.info("Executing %s", " ".join(cmd_line))
    try:
        result = subprocess.run(
            cmd_line,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        command = " ".join(["git", *args])
        error_msg = f"Command '{command}' failed:\n{exc.stderr}"
        raise RuntimeError(error_msg) from exc

    LOGGER.info("Execution completed!")
    return result


def is_git_lfs_installed() -> bool:
    """Return ``True`` if ``git-lfs`` is available in the system PATH."""
    return shutil.which("git-lfs") is not None


def clone_repository(
    repo_url: str,
    destination: str | Path,
    ref: str | None = None,
    depth: int | None = None,
) -> Path:
    """
    Clone a git repository into ``destination``.

    Args:
        repo_url: URL (or local path) of the repository to clone.
        destination: Directory the repository is cloned into. It must not
            already exist, or must be empty.
        ref: Optional branch or tag to check out during the clone. Passed
            straight to ``git clone --branch``, so it cannot be an arbitrary
            commit SHA when combined with ``depth`` (git only allows shallow
            clones of branches/tags, not arbitrary commits).
        depth: Optional depth for a shallow clone.

    For SSH URLs, the SSH keys that would be used are logged beforehand,
    with a warning when a passphrase is going to be requested.

    Returns:
        The path to the cloned repository.

    Raises:
        FileExistsError: If ``destination`` already exists and is not empty.
        RuntimeError: If the ``git`` executable is missing or the clone
            fails.

    """
    destination = Path(destination)

    if destination.exists() and any(destination.iterdir()):
        error_msg = (
            f"Destination '{destination}' already exists and is not empty"
        )
        raise FileExistsError(error_msg)

    destination.parent.mkdir(parents=True, exist_ok=True)

    args = ["clone"]
    if ref is not None:
        args += ["--branch", ref]
    if depth is not None:
        args += ["--depth", str(depth)]
    args += [repo_url, str(destination)]

    if ssh_host_from_url(repo_url) is not None:
        LOGGER.debug("The repo will be downloaded using SSH")
        check_ssh_keys(repo_url)
    else:
        LOGGER.debug("The repo will *NOT* be downloaded using SSH")

    _run_git(args)

    return destination


def checkout_ref(repo_dir: str | Path, ref: str) -> None:
    """
    Check out ``ref`` (branch, tag, or commit SHA) in an existing clone.

    Args:
        repo_dir: Path to an existing git repository.
        ref: Branch, tag, or commit SHA to check out.

    Raises:
        RuntimeError: If the checkout fails, e.g. because ``ref`` is unknown
            or the repository was cloned with a depth that does not include
            it.

    """
    _run_git(["checkout", ref], cwd=Path(repo_dir))
