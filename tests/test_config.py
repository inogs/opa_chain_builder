from pathlib import Path

import pytest

from opa_chain_builder.config import ChainConfig


def _build_config(**kwargs):
    fields = {
        "name": "TestChain",
        "home": "/opa/${NAME}",
        "hostname": "test_host",
        "workdir": "${HOME}/work",
        "arcdir": "${HOME}/archive",
        "inpdir": "${HOME}/inpdir",
        "account": "test_account",
    }
    fields.update(kwargs)
    return ChainConfig.model_validate(fields)


@pytest.mark.parametrize(
    ("stage", "expected"), [("prod", "qos_prio"), ("dev", "qos_dbg")]
)
def test_concretize_resolves_prod_condition(stage, expected):
    config = _build_config(stage=stage, qos="<PROD?qos_prio:qos_dbg>")
    config.concretize()

    assert config.qos == expected


@pytest.mark.parametrize(
    ("backup", "expected"),
    [(True, "/opa/TestChain/backup"), (False, "/opa/TestChain/archive")],
)
def test_concretize_resolves_backup_condition(backup, expected):
    config = _build_config(
        backup=backup, arcdir="${HOME}/<BACKUP?backup:archive>"
    )
    config.concretize()

    assert config.arcdir == Path(expected)


def test_concretize_resolves_conditions_before_placeholders():
    config = _build_config(stage="prod", name="Chain<PROD?:_dev>")
    config.concretize()

    assert config.name == "Chain"
    assert config.home == Path("/opa/Chain")


def test_concretize_resolves_multiple_and_empty_conditions():
    config = _build_config(
        stage="dev", backup=True, account="acc<PROD?_prod:><BACKUP?_bkp:>"
    )
    config.concretize()

    assert config.account == "acc_bkp"


@pytest.mark.parametrize(
    ("stage", "backup", "expected"),
    [
        ("prod", True, "a"),
        ("prod", False, "b"),
        ("dev", True, "c"),
        ("dev", False, "c"),
    ],
)
def test_concretize_resolves_nested_conditions(stage, backup, expected):
    config = _build_config(
        stage=stage, backup=backup, account="<PROD?<BACKUP?a:b>:c>"
    )
    config.concretize()

    assert config.account == expected


def test_concretize_ignores_simple_placeholders():
    config = _build_config(account="<ACCOUNT>")
    config.concretize()

    assert config.account == "<ACCOUNT>"


def test_concretize_unknown_condition():
    config = _build_config(account="<UNKNOWN?a:b>")

    with pytest.raises(ValueError, match='Unknown condition "UNKNOWN"'):
        config.concretize()
