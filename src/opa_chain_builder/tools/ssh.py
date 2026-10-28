"""Helpers to inspect the SSH keys used to reach a git remote."""

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

LOGGER = logging.getLogger(__name__)

_SCP_LIKE_RE = re.compile(r"^(?:[^@/:]+@)?(?P<host>[^@/:]+):(?!//)")
_FINGERPRINT_INDEX = 1


@dataclass(frozen=True)
class SshKeyStatus:
    """Status of a private key that ssh may use for a host."""

    path: Path
    encrypted: bool
    loaded_in_agent: bool

    @property
    def needs_passphrase(self) -> bool:
        """Whether a passphrase would be requested when using this key."""
        return self.encrypted and not self.loaded_in_agent


def _find_exe(name: str) -> str:
    exe = shutil.which(name)
    if exe is None:
        error_msg = f"'{name}' executable not found; please install OpenSSH"
        raise RuntimeError(error_msg)
    return exe


def ssh_host_from_url(repo_url: str) -> str | None:
    """
    Extract the host of an SSH git URL.

    Args:
        repo_url: Repository URL, either ``ssh://[user@]host/path`` or the
            scp-like ``[user@]host:path`` form.

    Returns:
        The host name, or ``None`` if ``repo_url`` is not an SSH URL.

    """
    if repo_url.startswith("ssh://"):
        return urlparse(repo_url).hostname

    if "://" in repo_url:
        return None

    match = _SCP_LIKE_RE.match(repo_url)
    return match.group("host") if match else None


def ssh_identity_files(host: str) -> list[Path]:
    """
    List the private key files ssh would offer when connecting to ``host``.

    Args:
        host: Host name, possibly an alias defined in ``~/.ssh/config``.

    Returns:
        Existing private key files, in the order ssh would try them.

    """
    result = subprocess.run(
        [_find_exe("ssh"), "-G", host],
        capture_output=True,
        text=True,
        check=True,
        stdin=subprocess.DEVNULL,
    )

    keys: list[Path] = []
    for line in result.stdout.splitlines():
        keyword, _, value = line.partition(" ")
        if keyword != "identityfile":
            continue
        path = Path(value).expanduser()
        if path.is_file() and path not in keys:
            keys.append(path)
    return keys


def key_is_encrypted(key_path: Path) -> bool:
    """
    Check whether the private key at ``key_path`` is protected by a passphrase.

    Args:
        key_path: Path to a private key file.

    Returns:
        ``True`` if the key is encrypted, ``False`` otherwise.

    Raises:
        RuntimeError: If the key cannot be read for reasons other than a
            passphrase.

    """
    result = subprocess.run(
        [_find_exe("ssh-keygen"), "-y", "-P", "", "-f", str(key_path)],
        capture_output=True,
        text=True,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    if result.returncode == 0:
        return False
    if "incorrect passphrase" in result.stderr:
        return True

    error_msg = f"Cannot read SSH key '{key_path}': {result.stderr.strip()}"
    raise RuntimeError(error_msg)


def _agent_fingerprints() -> set[str]:
    ssh_add = shutil.which("ssh-add")
    if ssh_add is None:
        return set()

    # Exit code 1 means no identities are loaded, 2 means no agent is running.
    result = subprocess.run(
        [ssh_add, "-l"],
        capture_output=True,
        text=True,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        return set()

    return {
        fields[_FINGERPRINT_INDEX]
        for fields in (line.split() for line in result.stdout.splitlines())
        if len(fields) > _FINGERPRINT_INDEX
    }


def _public_key_fingerprint(key_path: Path) -> str | None:
    pub_path = key_path.with_name(key_path.name + ".pub")
    if not pub_path.is_file():
        return None

    result = subprocess.run(
        [_find_exe("ssh-keygen"), "-lf", str(pub_path)],
        capture_output=True,
        text=True,
        check=True,
        stdin=subprocess.DEVNULL,
    )
    return result.stdout.split()[_FINGERPRINT_INDEX]


def inspect_ssh_keys(repo_url: str) -> list[SshKeyStatus]:
    """
    Inspect the keys ssh would use to access the host of ``repo_url``.

    Args:
        repo_url: Repository URL. Non-SSH URLs yield an empty list.

    Returns:
        The status of each candidate private key, in the order ssh would try
        them.

    """
    host = ssh_host_from_url(repo_url)
    if host is None:
        return []

    agent = _agent_fingerprints()
    return [
        SshKeyStatus(
            path=key_path,
            encrypted=key_is_encrypted(key_path),
            loaded_in_agent=_public_key_fingerprint(key_path) in agent,
        )
        for key_path in ssh_identity_files(host)
    ]


def check_ssh_keys(repo_url: str) -> list[SshKeyStatus]:
    """
    Log which SSH keys would be used for ``repo_url`` and whether they prompt.

    Args:
        repo_url: Repository URL. Non-SSH URLs are ignored.

    Returns:
        The status of each candidate private key.

    """
    statuses = inspect_ssh_keys(repo_url)
    if not statuses and ssh_host_from_url(repo_url) is not None:
        LOGGER.warning("No SSH private key found for %s", repo_url)

    for status in statuses:
        if status.needs_passphrase:
            LOGGER.warning(
                "SSH key %s is encrypted and not loaded in the agent: "
                "a passphrase will be requested",
                status.path,
            )
        else:
            LOGGER.info(
                "SSH key %s can be used without a passphrase", status.path
            )

    return statuses
