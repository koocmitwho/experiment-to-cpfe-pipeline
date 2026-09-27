# License review: v0.1.0 historical snapshot and current distribution

The dependency table and source review below record the 2026-09-06 v0.1.0
snapshot. Current v0.2.1 distribution metadata names `koocmitwho` and the project
contributors in `NOTICE`; the repository URL matches `pyproject.toml`.

Project code, documentation and synthetic fixtures use Apache-2.0, with
the public tensile materials listed in
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) under CC-BY-4.0.

Apache-2.0 permits reuse, modification and redistribution, including commercial
use, and provides an explicit contributor patent grant. These terms suit reuse
in research and engineering software. See the [license text](../LICENSE) for
attribution and redistribution requirements.

## Source and dependency review

The four commits preceding v0.1.0 use the repository's configured author.
The reviewed source tree contains project implementations, tests, small
synthetic inputs and source references.

The installed direct dependency metadata was reviewed on 2026-09-06:

| Use | Packages | Upstream license metadata |
|---|---|---|
| Core | h5py 3.16.0, pandas 3.0.5 | BSD-3-Clause / BSD |
| Core | NumPy 2.5.2 | BSD-3-Clause, 0BSD, MIT, Zlib, CC0-1.0 |
| Core | pydantic 2.13.5, PyYAML 6.0.3 | MIT |
| Native/training | SciPy 1.18.1, openpyxl 3.1.5 | BSD / MIT |
| Training/graph | torch 2.8.0+cpu, torch-geometric 2.7.0 | BSD-3-Clause / MIT |
| Example plotting | matplotlib 3.11.1 | Matplotlib license, PSF-based |
| Development/build | pytest 9.1.1, build 1.6.0, setuptools 78.1.0 | MIT |
| Release metadata check | twine 7.0.0 | Apache-2.0 |

The table records the review environment. Installation requirements are in
`pyproject.toml`. Each dependency retains its own license and ships with its
upstream notices.

## Public experimental materials

The [Zenodo source record](https://zenodo.org/records/10820299) confirms
KupferDigital version 2, its seven creators and CC-BY-4.0. The third-party
notice provides full attribution, links and the changes made to the data.
The project's processed figures, result summary and reference INP use
CC-BY-4.0 as listed there; the preparation and training scripts use Apache-2.0.
The original archive and raw experimental files remain in local source storage.

The NTNU manifest references an MIT-licensed input bundle. Other datasets in
the adapter reports are obtained from their publishers for local reading tests.

## Distribution metadata

The Python wheel and sdist declare `License-Expression: Apache-2.0` and ship
`LICENSE`, `NOTICE` and `THIRD_PARTY_NOTICES.md`. The case files listed under
CC-BY-4.0 are distributed through the GitHub source tree and its source archives.
The README links to those files and their terms.

References: [Apache licensing FAQ](https://www.apache.org/foundation/license-faq),
[Apache-2.0 terms](https://www.apache.org/licenses/LICENSE-2.0),
[CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/),
[setuptools license metadata](https://setuptools.pypa.io/en/stable/userguide/license_migration.html).
