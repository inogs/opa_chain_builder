# opa-chain-builder

`opa-chain-builder` installs the oceanographic chain used at
[OGS](https://www.ogs.it), which is built around the `ogstm`
biogeochemical model. It takes care of everything needed to go from an
empty directory to a chain ready to be compiled and run:

- it installs (once per machine) a [Spack](https://spack.io) instance;
- it clones the chain repository and the auxiliary repositories
  (model builder, pre-processing, post-processing, `bit.sea`);
- it creates a Python environment (via micromamba) with all the Python
  packages used by the chain;
- it creates a Spack environment that describes all the compiled
  dependencies of the model (compilers, MPI, NetCDF, PETSc, ...);
- it writes a `chain_env.sh` file that activates the whole chain with a
  single `source`.

The goal is to make the installation of a chain reproducible and
independent of the software available on the machine: the libraries are
not taken from the system modules but are built by Spack, with the
versions and the variants defined inside this repository.

## Table of contents

- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Commands](#commands)
  - [`install_spack`](#install_spack)
  - [`build_chain`](#build_chain)
- [Configuration files](#configuration-files)
  - [How the configuration directory is found](#how-the-configuration-directory-is-found)
  - [`spack.toml`](#spacktoml)
  - [`chain.toml`](#chaintoml)
  - [Placeholders](#placeholders)
  - [Conditional values](#conditional-values)
- [Environment templates](#environment-templates)
  - [How the environment directory is found](#how-the-environment-directory-is-found)
  - [Python environment](#python-environment)
  - [Spack environments](#spack-environments)
- [Dependencies provided by the chain](#dependencies-provided-by-the-chain)
- [Workflow: installing a new chain](#workflow-installing-a-new-chain)
- [Layout of an installed chain](#layout-of-an-installed-chain)
- [Development](#development)

## Prerequisites

The following tools must already be available on the machine:

| Tool | Why it is needed |
| --- | --- |
| Python >= 3.11 | to run `opa-chain-builder` itself |
| `git` | to clone Spack and the chain repositories |
| `git-lfs` | the chain repository stores some files with Git LFS; `build_chain` refuses to start without it |
| `micromamba` (in the `PATH`) | to create the Python environment of the chain |
| OpenSSH (`ssh`, `ssh-keygen`, `ssh-add`) | the chain repositories are cloned via SSH |
| a C/C++/Fortran compiler | used by Spack to bootstrap the build of the other compilers and libraries |
| Slurm (`sacctmgr`), optional | only needed if the configuration uses the `${SLURM_DEFAULT_ACCOUNT}` placeholder |

You also need SSH access to:

- `gitlab-ssh.hpc.cineca.it` (repository `OGS/v5c`, the chain itself);
- `github.com` (repositories of the `inogs` organization).

Before cloning a repository via SSH, `opa-chain-builder` checks which keys
SSH would use and prints a warning if a key is protected by a passphrase
and is not loaded in the `ssh-agent`. Since the procedure clones several
repositories, it is advisable to load your keys with `ssh-add` before
starting, so that the passphrase is not asked over and over again.

## Installation

The package is managed with [Poetry](https://python-poetry.org):

```bash
poetry install
```

This registers the `opa-chain-builder` console script inside the Poetry
environment (`poetry run opa-chain-builder ...`, or activate the
environment first). Alternatively, the package can be installed with
`pip install .` in any Python >= 3.11 environment.

## Commands

The general syntax is:

```bash
opa-chain-builder [-c CONFIG_DIR] {install_spack,build_chain} [OPTIONS]
```

`-c/--config` is a global option, so it must be written **before** the
name of the action. It points to the directory containing `spack.toml`
and `chain.toml`; when it is omitted, the directory is found automatically
(see [How the configuration directory is found](#how-the-configuration-directory-is-found)).

### `install_spack`

```bash
opa-chain-builder install_spack
```

Installs the Spack instance shared by all the chains of the machine. It
reads only `spack.toml` and:

1. clones the Spack repository from GitHub into `main_dir` (which must not
   exist or must be empty);
2. checks out the `commit` (a branch, tag or commit SHA);
3. applies each directive listed in `config` with
   `spack config --scope spack add <directive>`;
4. runs `spack compiler find` to register the compilers already available
   on the machine.

This command must be executed only once per machine (or whenever you want
a new Spack instance); every chain built afterwards reuses it.

### `build_chain`

```bash
opa-chain-builder build_chain [-e ENV_DIR] [-n NAME] [-o HOME] [-w WORKDIR]
                              [-i INPDIR] [-z ARCDIR] [-l {gcc,intel}]
                              [-s {dev,prod}] [-a ACCOUNT]
```

Builds a new chain. It reads both `chain.toml` and `spack.toml` (the
latter to know where Spack is installed). The options override the
corresponding values of `chain.toml`:

| Option | Field of `chain.toml` | Meaning |
| --- | --- | --- |
| `-e`, `--environment-dir` | — | directory with the environment templates (see [Environment templates](#environment-templates)) |
| `-n`, `--chain-name` | `name` | name of the chain |
| `-o`, `--opa-home` | `home` | main directory of the chain, where the chain repository is cloned |
| `-w`, `--workdir` | `workdir` | work directory |
| `-i`, `--inpdir` | `inpdir` | input directory |
| `-z`, `--arcdir` | `arcdir` | archive directory |
| `-l`, `--compiler` | `compiler` | compiler family: `intel` or `gcc` |
| `-s`, `--stage` | `stage` | `dev` or `prod` |
| `-a`, `--account` | `account` | account used to submit the jobs |

The values given on the command line are applied **before** the
placeholders are resolved, so they can contain placeholders too (e.g.
`-w '${HOME}/my_work'`).

The command performs the following steps:

1. resolves the placeholders of the configuration and checks that no
   required field is missing;
2. checks that `git-lfs` is installed;
3. clones the chain repository (`OGS/v5c` on the CINECA GitLab) into
   `home`, using the branch `branches.chain`, and sets the permissions of
   the keys in `etc/sftp-config` to `600`;
4. writes the `chain_env.sh` file in `home`;
5. creates the directories `HOST/<hostname>/python_env` and
   `HOST/<hostname>/spack_env` (they must be empty);
6. creates the Python environment with micromamba and installs the pip
   packages;
7. creates the Spack environment for the chosen compiler, registers the
   Python of the micromamba environment as an external package and
   concretizes the environment (**the packages are not installed yet**,
   see the [workflow](#workflow-installing-a-new-chain));
8. clones the auxiliary repositories inside `HOST/<hostname>`:

   | Repository | Directory | Branch taken from |
   | --- | --- | --- |
   | `inogs/ModelBuild` | `model_builder` | `branches.builder` |
   | `inogs/bit.sea` | `bit.sea` | `branches.bitsea` |
   | `inogs/ogstm_preproc` | `ogstm_preproc` | `branches.preproc` |
   | `inogs/ogstm_postproc` | `ogstm_postproc` | `branches.postproc` |

At the end, a message summarizes the steps that are left to the user.

## Configuration files

### How the configuration directory is found

The configurations live in a directory (`configurations/` in this
repository) that contains one subdirectory for each HPC system plus a
`defaults` subdirectory:

```
configurations/
├── .opa_config_dir      # marker file: identifies this as a config directory
├── defaults/
│   ├── chain.toml
│   └── spack.toml
└── g100/
    ├── chain.toml
    └── spack.toml
```

If `-c` is not given, the configuration is located as follows:

1. the configuration root is
   - the directory stored in the env variable `OPA_CONFIG_DIR`, if set;
   - otherwise, a directory named `configurations` in the current working
     directory, provided that it contains a file named `.opa_config_dir`;
   - otherwise, the same in the parent of the current working directory;
2. inside the root, the subdirectory used is
   - `$HPC_SYSTEM`, if the env variable `HPC_SYSTEM` is set and a
     subdirectory with that name exists;
   - otherwise, `defaults`.

If nothing is found the command exits with an error. Note that `-c`, on
the contrary, must point directly to the directory that contains the
`.toml` files (e.g. `-c configurations/g100`), not to the root.

To add a new machine, create a new subdirectory with its own `chain.toml`
and `spack.toml`, and set `HPC_SYSTEM` accordingly (or use `-c`).

### `spack.toml`

```toml
[spack]
main_dir = "~/spack"                  # where Spack is (or will be) installed
commit = "develop"                    # branch, tag or commit SHA of Spack
config = ["config:verify_ssl:false"]  # optional
```

| Field | Required | Description |
| --- | --- | --- |
| `main_dir` | yes | installation directory of Spack; `~` is expanded |
| `commit` | yes | version of Spack to check out |
| `config` | no | list of directives passed to `spack config add` during `install_spack` |

### `chain.toml`

```toml
[chain]
name = "V13CTest"
home = "${NAME}"
hostname = "${HOSTNAME}"
workdir = "${HOME}/work"
arcdir = "${HOME}/archive"
inpdir = "${HOME}/inpdir"
account = "${SLURM_DEFAULT_ACCOUNT}"
qos = "qos_prio"
compiler = "intel"
stage = "dev"
os = "linux"
backup = false
arch = "x86_64"

[chain.branches]
chain = "main"
preproc = "main"
bitsea = "master"
postproc = "main"
builder = "main"
```

| Field | Default | Description | Exported as |
| --- | --- | --- | --- |
| `name` | — | name of the chain | `OPA_NAME`, `OPA_VERSION` |
| `home` | — | main directory of the chain | `OPA_HOME` |
| `hostname` | — | name of the host; it is also the name of the directory `HOST/<hostname>` | `OPA_HOSTNAME` |
| `workdir` | — | work directory | `OPA_WORKDIR` |
| `arcdir` | — | archive directory | `OPA_ARCDIR` |
| `inpdir` | — | input directory | `OPA_INPDIR` |
| `account` | — | account for the job submission | `OPA_ACCOUNT` |
| `qos` | none | Slurm QoS for the parallel jobs (the only optional field) | `OPA_PAR_QOS` |
| `compiler` | `intel` | `intel` or `gcc`; selects the Spack environment | `OPA_COMPILER` |
| `stage` | `dev` | `dev` or `prod` | `OPA_STAGE` |
| `os` | `linux` | only `linux` is supported | `OPA_OS` |
| `backup` | `false` | whether the chain performs backups | `OPA_BACKUP` |
| `arch` | `x86_64` | architecture | `OPA_ARCH` |
| `branches.*` | see above | branch checked out for each repository | — |

All the fields without a default must have a value at the end, either
from the file or from the command line; otherwise `build_chain` stops
with an `IncompleteConfigError`. For example, `configurations/g100/chain.toml`
deliberately does not define `name` and `home`, which must therefore be
passed with `-n` and `-o`.

Relative paths (`home`, `workdir`, `arcdir`, `inpdir`) are interpreted
with respect to the current working directory and converted to absolute
paths.

### Placeholders

The string values of `chain.toml` (and of the command-line overrides) may
contain the following placeholders, which are resolved in this order:

| Placeholder | Replaced with |
| --- | --- |
| `${NAME}` | the value of the `name` field |
| `${HOSTNAME}` | the hostname of the current machine (as returned by the system, independently of the `hostname` field) |
| `${HOME}` | the value of the `home` field, i.e. the home **of the chain** (not the home directory of the user!) |
| `${SLURM_DEFAULT_ACCOUNT}` | the default Slurm account of the user, read with `sacctmgr`; an error is raised if Slurm is not available or no default account is configured |

Because of the order, `home` can use `${NAME}` and `${HOSTNAME}`, and the
other paths can use `${HOME}`, but a field cannot refer to itself (e.g.
`name` cannot contain `${NAME}`).

### Conditional values

A value may also contain conditional parts of the form `<COND?V1:V2>`,
which are replaced with `V1` if the condition `COND` is true and with `V2`
otherwise. The available conditions are:

| Condition | True when |
| --- | --- |
| `BACKUP` | `backup` is `true` |
| `PROD` | `stage` is `"prod"` |

For example:

```toml
[chain]
qos = "<PROD?qos_prio:qos_dbg>"          # "qos_prio" in prod, "qos_dbg" in dev
name = "V13C<PROD?:_dev>"                # empty values are allowed
arcdir = "${HOME}/<BACKUP?backup:archive>"
```

Conditional values are resolved **before** the placeholders, so `V1` and
`V2` may contain placeholders, and the conditions follow the values given
on the command line (e.g. `-s prod`). Conditionals can be nested
(`<PROD?<BACKUP?a:b>:c>`). `V1` and `V2` may not contain the characters
`<`, `>`, `?` and `:`; an unknown condition stops `build_chain` with an
error.

## Environment templates

The definition of the software environments is kept in a second
directory (`environments/` in this repository):

```
environments/
├── .opa_env_templates          # marker file
├── conda/
│   ├── environment.yaml        # micromamba environment
│   └── pip_packages.txt        # extra packages installed with pip
└── spack/
    ├── gcc/
    │   └── spack.yaml
    └── intel/
        ├── spack.yaml
        └── bootstrap/          # optional, see below
            ├── config.yaml
            ├── packages.yaml
            └── run_commands.txt
```

### How the environment directory is found

If `-e` is not given, `build_chain` uses:

1. the directory stored in the env variable `OPA_ENV_TEMPLATES`, if set
   (an error is raised if it does not exist or is not a directory);
2. otherwise, a directory named `environments` in the current working
   directory that contains a file named `.opa_env_templates`;
3. otherwise, the same in the parent of the current working directory.

In practice, running `opa-chain-builder` from the root of this repository
(or from one of its direct subdirectories) finds both the configuration
and the environment directories without any extra option.

### Python environment

`conda/environment.yaml` is a standard conda environment file; the
placeholder `<OPA_NAME>` is replaced with the name of the chain. The
environment is created with micromamba at `HOST/<hostname>/python_env`.

Afterwards, each line of `conda/pip_packages.txt` (if the file exists) is
passed to `pip install` inside the environment. A line may contain more
than one package and extra pip arguments (e.g. `--index-url ...`); text
after `#` is treated as a comment.

### Spack environments

`build_chain` uses the template `spack/<compiler>/spack.yaml`, where
`<compiler>` is the value of the `compiler` field. The environment is
created at `HOST/<hostname>/spack_env`, with its own install tree
(`$env/opt`), so different chains (and different compilers) never share
installed packages.

Before being used, the following placeholders are replaced in the
template:

| Placeholder | Value |
| --- | --- |
| `<SPACK_DIR>` | installation directory of Spack |
| `<ENV_DIR>` | directory of the Spack environment |
| `<INTEL_COMPILER>` | `intel-oneapi-compilers@2025.3.2` |
| `<GCC_COMPILER>` | `gcc@15` |
| `<CONDA_ENV_PATH>` | directory of the Python environment |

The Python interpreter is not built by Spack: the one of the micromamba
environment is registered as an external package
(`spack external find --path <python_env> python`), so that Spack and the
Python tools of the chain use the same interpreter.

#### The `bootstrap` directory

Spack can only use a compiler that is already installed. When a compiler
must be built by Spack itself (as for the Intel oneAPI compilers), the
template directory contains a `bootstrap/` subdirectory with:

- a set of Spack configuration files (`*.yaml`), which are copied into
  `spack_env/bootstrap/` after replacing the placeholders `<ENV_DIR>`,
  `<INTEL_COMPILER>` and `<GCC_COMPILER>`;
- a `run_commands.txt` file, with one Spack command per line (without
  the `spack` executable; `#` starts a comment). Each command is run as
  `spack -C spack_env/bootstrap <command>` before the environment is
  created.

For the Intel environment, this installs the oneAPI compilers inside the
install tree of the environment, so that they can be reused when the
environment is concretized. Note that this step actually compiles/installs
the compilers, so it can take a while.

## Dependencies provided by the chain

**Spack environment, `intel` compiler**

- `intel-oneapi-compilers@2025.3.2` (`icx`, `icpx`, `ifx`), built inside
  the environment;
- `intel-oneapi-mpi` (MPI) and `intel-oneapi-mkl` (BLAS, LAPACK,
  ScaLAPACK);
- `hdf5@1.14 +mpi +fortran +hl +szip`, `netcdf-c +mpi`,
  `netcdf-fortran`, `parallel-netcdf +fortran +shared`;
- `petsc@3.23 +mpi +fortran ~debug` with `hypre`, `mumps`, `scalapack`
  and `superlu-dist`;
- tools: `nco`, `cmake`, `coreutils`, `grep`, `ncftp`, `sshpass`,
  `pngquant`.

All the scientific libraries (HDF5, NetCDF, PnetCDF, PETSc and its
solvers) are compiled with the Intel compilers, since the Fortran modules
must match the compiler used for the model. Packages are linked with
`rpath`.

**Spack environment, `gcc` compiler**

- the system GCC (`gcc`, `g++`, `gfortran`), declared as an external;
- `openmpi@5` and `openblas`, `netlib-scalapack`;
- the same HDF5 / NetCDF / PnetCDF / PETSc stack, plus `nco` and `cmake`.

> **Note:** the `gcc` template currently declares an external
> `gcc@15.2.0` in `/usr`; adapt it to the compiler available on your
> machine.

**Python environment** (micromamba, from `conda-forge`)

`python`, `ipython`, `numpy`, `scipy`, `pandas`, `xarray`,
`scikit-learn`, `mpi4py`, `matplotlib`, `basemap` (with data),
`cartopy`, `cmocean`, `pillow`, `netcdf4`, `zarr`, `fsspec`, `gsw`,
`seawater`, `python-dateutil`, `latexcodec`, `copernicusmarine`, ...;
then, via pip, [`bit.sea`](https://github.com/inogs/bit.sea) and the CPU
version of PyTorch (`torch`, `torchvision`, `torchaudio`).

To change the software of the chain, edit the files in `environments/`;
no change to the Python code is needed.

## Workflow: installing a new chain

1. **Prepare the machine**: make sure the [prerequisites](#prerequisites)
   are installed and load your SSH keys:

   ```bash
   eval "$(ssh-agent)"   # if no agent is running
   ssh-add
   ```

2. **Install `opa-chain-builder`** and move to the root of this
   repository:

   ```bash
   poetry install
   eval "$(poetry env activate)"
   ```

3. **Select the configuration**: set `HPC_SYSTEM` to the name of one of
   the subdirectories of `configurations/` (or create a new one), or plan
   to pass `-c`. Check `spack.toml` and `chain.toml`.

4. **Install Spack** (only the first time on a given machine):

   ```bash
   opa-chain-builder install_spack
   ```

5. **Build the chain**, overriding what is needed from the command line:

   ```bash
   opa-chain-builder build_chain -n MyChain -o /path/to/MyChain
   ```

6. **Follow the instructions printed at the end**:

   ```bash
   # activate the chain (Spack, Python environment, OPA_* variables)
   source /path/to/MyChain/chain_env.sh

   # build all the compiled dependencies (this takes a long time:
   # consider running it inside a job or a screen/tmux session)
   spack -e /path/to/MyChain/HOST/<hostname>/spack_env install
   ```

   Then run the model builder in `/path/to/MyChain/HOST/<hostname>`, and
   finally compile and install the chain executables:

   ```bash
   cd /path/to/MyChain/bin/src
   make
   make install
   ```

From now on, `source /path/to/MyChain/chain_env.sh` is all you need to
work with the chain.

## Layout of an installed chain

```
<home>/                         # clone of the chain repository (OGS/v5c)
├── chain_env.sh                # activation script
├── bin/                        # added to the PATH by chain_env.sh
└── HOST/
    └── <hostname>/
        ├── python_env/         # micromamba environment
        ├── spack_env/          # Spack environment (spack.yaml, opt/, view)
        │   └── bootstrap/      # config used to install the compilers
        ├── model_builder/
        ├── bit.sea/
        ├── ogstm_preproc/
        └── ogstm_postproc/
```

`chain_env.sh`:

- refuses to be sourced if a *different* chain is already active in the
  shell (i.e. if `OPA_NAME` is set to another value), so open a new shell
  to switch chain;
- sources the `setup-env.sh` of Spack, unless `spack` is already
  available;
- exports all the `OPA_*` variables listed in [`chain.toml`](#chaintoml)
  and adds `<home>/bin` to the `PATH`;
- activates the Python environment, showing the name of the chain in the
  prompt.

## Development

```bash
poetry install
poetry run pytest
```

The code is linted with `ruff` (all rules enabled, see `pyproject.toml`)
through `pre-commit`:

```bash
poetry run pre-commit install
poetry run pre-commit run --all-files
```

The Python sources live in `src/opa_chain_builder/`:

- `__main__.py` — command-line interface;
- `config.py` — `SpackConfig` and `ChainConfig`, the models of the TOML
  files, and the logic to find the configuration directory;
- `actions/opa_build_chain.py` — the `build_chain` procedure;
- `tools/` — small wrappers around external tools (`git`, `spack`,
  `micromamba`, `ssh`, `slurm`).
