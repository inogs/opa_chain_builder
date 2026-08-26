# opa-chain-builder

Tooling to build OPA compiler/toolchain chains via Spack.

## Layout

- `src/opa_chain_builder/tools/git.py` — clone a git repository (`clone_repository`) and check out a ref (`checkout_ref`).
- `src/opa_chain_builder/tools/spack.py` — install a specific version of Spack, install `intel-oneapi-compilers`, and register it as a compiler (`install_spack`).

## Development

```bash
poetry install
poetry run pytest
```
