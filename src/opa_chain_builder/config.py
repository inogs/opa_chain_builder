import os
import socket
import tomllib
from abc import ABC
from abc import abstractmethod
from logging import getLogger
from pathlib import Path
from typing import Literal
from typing import Self

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator

from opa_chain_builder.tools.slurm import get_default_account

# If this file is inside the config directory, we can assume that
# we can read the configurations from here.
ENV_VAR_NAME = "OPA_CONFIG_DIR"
IS_OPA_CONFIG_DIR = ".opa_config_dir"


LOGGER = getLogger(__name__)


class IncompleteConfigError(Exception):
    """Raised when a config object is missing a required field."""

    @staticmethod
    def because_of_missing_field(
        field_name: str, class_name: str
    ) -> "IncompleteConfigError":
        """Build the error for a missing ``field_name`` on ``class_name``."""
        msg = (
            f"Missing field '{field_name}' inside configuration for "
            f"{class_name}."
        )
        return IncompleteConfigError(msg)


def _find_config_directory() -> Path | None:
    # The config dir can be set by the user via the OPA_CONFIG_DIR
    # environment variable.
    if os.environ.get(ENV_VAR_NAME, None) is not None:
        return Path(os.environ[ENV_VAR_NAME])

    # Otherwise, we look for a config directory in the current working
    # directory (that contains the IS_OPA_CONFIG_DIR file)
    if Path("configurations").exists():
        config_dir = Path("configurations")
        if config_dir.is_dir() and (config_dir / IS_OPA_CONFIG_DIR).exists():
            return config_dir

    if Path("../configurations").exists():
        config_dir = Path("../configurations")
        if config_dir.is_dir() and (config_dir / IS_OPA_CONFIG_DIR).exists():
            return config_dir

    return None


def get_default_config_path() -> Path | None:
    """Return the ``defaults`` subdirectory of the config dir, if any."""
    config_dir = _find_config_directory()
    if config_dir is None:
        return None

    candidate = config_dir / "defaults"
    if candidate.exists():
        return candidate

    return None


class OpaConfig(BaseModel, ABC):
    """Base class for the TOML-backed configuration objects."""

    model_config = ConfigDict(validate_assignment=True)

    @classmethod
    @abstractmethod
    def _config_name(cls) -> str:
        raise NotImplementedError

    @classmethod
    def read_from_disk(cls, config_dir: Path) -> Self:
        """Read and validate this config's section from ``config_dir``."""
        config_name = cls._config_name()
        config_file = config_dir / f"{config_name}.toml"
        if not config_file.exists():
            error_msg = f"Spack config file not found at {config_file}"
            raise FileNotFoundError(error_msg)
        with config_file.open("rb") as f:
            config_dict = tomllib.load(f)
        if config_name not in config_dict:
            error_msg = (
                f"{config_name} config file does not contain a "
                f"'{config_name}' section"
            )
            raise ValueError(error_msg)
        return cls.model_validate(config_dict[config_name])


class SpackConfig(OpaConfig):
    """Configuration needed to install and set up a Spack instance."""

    main_dir: Path
    commit: str
    config: list[str] = Field(default_factory=list)

    @classmethod
    def _config_name(cls) -> str:
        return "spack"

    @field_validator("main_dir", mode="before")
    @classmethod
    def validate_main_dir(cls, v: str | Path) -> Path:
        """Expand ``~`` in ``main_dir`` before validation."""
        return Path(v).expanduser()


class ChainConfig(OpaConfig):
    """Configuration used to build a toolchain environment file."""

    name: str | None = None
    home: Path | None = None
    hostname: str | None = None
    workdir: Path | None = None
    arcdir: Path | None = None
    inpdir: Path | None = None
    account: str | None = None
    compiler: Literal["intel", "gcc"] = "intel"
    stage: Literal["dev", "prod"] = "dev"
    os: Literal["linux"] = "linux"
    backup: bool = False
    arch: str = "x86_64"

    @classmethod
    def _config_name(cls) -> str:
        return "chain"

    def _replace_field(self, field_name: str) -> None:
        field_value = str(getattr(self, field_name))
        if field_value is None:
            raise IncompleteConfigError.because_of_missing_field(
                field_name, self.__class__.__name__
            )

        replace_string = "${" + field_name.upper() + "}"
        if replace_string in field_value:
            error_msg = (
                f'Field named "{field_name}" may not contain the '
                f'string "{replace_string}"'
            )
            raise ValueError(error_msg)
        for field in self.model_fields:
            if field == field_name:
                continue
            current_field_value = str(getattr(self, field))
            if replace_string in current_field_value:
                current_field_value = current_field_value.replace(
                    replace_string, field_value
                )
                setattr(self, field, current_field_value)

    def _prepare_hostname_placeholder(self) -> str:
        # When we have to replace a string like ${NAME} with the value of
        # self.name, we have the method "replace_field". Unfortunately, this
        # does not work out-of-the-box with the hostname field because we
        # must compute the $HOSTNAME value instead of using the value of the
        # field. So we use a dirty trick; we compute the value, we put it in
        # the field, and then we replace the placeholder with the value of
        # the field (in `_restore_hostname_placeholder`). To save the value
        # of the original field, we return it here so that it can be
        # restored later.
        current_hostname_value = self.hostname
        self.hostname = socket.gethostname()
        if current_hostname_value is None:
            current_hostname_value = self.hostname
        return current_hostname_value

    def _restore_hostname_placeholder(
        self, current_hostname_value: str
    ) -> None:
        # We need to be sure that the original value of the hostname did not
        # contain the placeholder ${HOSTNAME} before we replace it.
        if "${HOSTNAME}" in current_hostname_value:
            current_hostname_value = current_hostname_value.replace(
                "${HOSTNAME}", self.hostname
            )

        # Finally, we can put back the value of the original field hostname
        self.hostname = current_hostname_value

    def _replace_slurm_account_placeholder(self) -> None:
        # Do we need to replace the ${SLURM_DEFAULT_ACCOUNT} placeholder?
        replace_slurm_account = False
        for field in self.model_fields:
            field_value = getattr(self, field)
            if field_value is None:
                continue
            if "${SLURM_DEFAULT_ACCOUNT}" in str(field_value):
                replace_slurm_account = True

        # If we do not, there is nothing else to do
        if not replace_slurm_account:
            return

        unable_to_get_account_msg = (
            "Unable to get the default slurm account; do not use "
            "the ${SLURM_DEFAULT_ACCOUNT} placeholder"
        )
        try:
            slurm_account = get_default_account()
        except Exception as e:
            raise ValueError(unable_to_get_account_msg) from e
        if slurm_account is None:
            raise ValueError(unable_to_get_account_msg)

        for field in self.model_fields:
            field_value = getattr(self, field)
            if field_value is None:
                continue
            if "${SLURM_DEFAULT_ACCOUNT}" in str(field_value):
                field_value = str(field_value).replace(
                    "${SLURM_DEFAULT_ACCOUNT}", slurm_account
                )
                setattr(self, field, field_value)

    def _check_no_missing_fields(self) -> None:
        for field in self.model_fields:
            field_value = getattr(self, field)
            if field_value is None:
                raise IncompleteConfigError.because_of_missing_field(
                    field, self.__class__.__name__
                )

    def _absolutize_paths(self) -> None:
        for field in ("home", "workdir", "arcdir", "inpdir"):
            field_value = getattr(self, field)
            setattr(self, field, field_value.absolute())

    def concretize(self) -> None:
        """
        Replace the placeholders inside the values with their values.

        This method looks for the following strings in its object's attribute
        (exactly in the following order):
        - ${NAME}
        - ${HOSTNAME}
        - ${HOME}
        - ${SLURM_DEFAULT_ACCOUNT}

        First, the `${NAME}` value is replaced everywhere with the value of
        the `name` attribute (that is forbidden to contain the `${NAME}`
        string).
        Then `${HOSTNAME}` is replaced with the hostname of the current
        machine (independently of the value of the `hostname` attribute).
        Later, ${HOME} is replaced with the value of the `home` attribute.
        Finally, ${SLURM_DEFAULT_ACCOUNT} is replaced with the value of the
        user default slurm account if slurm is installed on this machine. If
        this placeholder is used but slurm is not installed, this will raise
        a ValueError.
        """
        current_hostname_value = self._prepare_hostname_placeholder()

        self._replace_field("name")
        self._replace_field("hostname")

        self._restore_hostname_placeholder(current_hostname_value)

        self._replace_field("home")
        self._replace_slurm_account_placeholder()
        self._check_no_missing_fields()
        self._absolutize_paths()

    def prepare_environment_file(self) -> str:
        """Render the shell environment file exporting this chain's config."""
        bin_dir = self.home.resolve() / "bin"
        env_file = ""
        env_file += f'export OPA_HOME="{self.home}"\n'
        env_file += f'export OPA_HOSTNAME="{self.hostname}"\n'
        env_file += f'export OPA_WORKDIR="{self.workdir}"\n'
        env_file += f'export OPA_ARCDIR="{self.arcdir}"\n'
        env_file += f'export OPA_INPDIR="{self.inpdir}"\n'
        env_file += f'export OPA_ACCOUNT="{self.account}"\n'
        env_file += f'export OPA_ARCH="{self.arch}"\n'
        env_file += f'export OPA_BACKUP="{str(self.backup).lower()}"\n'
        env_file += f'export OPA_OS="{self.os}"\n'
        env_file += f'export OPA_COMPILER="{self.compiler}"\n'
        env_file += f'export OPA_VERSION="{self.name}"\n'
        env_file += f'export OPA_STAGE="{self.stage}"\n'
        env_file += f"\nexport PATH={bin_dir}:$PATH\n"
        return env_file


class MicromambaConfig(OpaConfig):
    """Configuration needed to locate a Micromamba installation."""

    exec_path: Path | None = None
    prefix: Path | None = None
