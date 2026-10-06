# Sources and reuse notices

This example uses three real AA6061-T651 tensile specimens at 20 degrees Celsius from lot A. Its inputs are author-provided engineering stress-strain curves, already processed from experimental measurements; they are not raw DIC images or load-cell streams.

## Experimental data

Michael Shields, B.S. Aakash, and JohnPatrick Connors (2019). *Stress-strain data for aluminum 6061-T651 from 9 lots at 6 temperatures under uniaxial and plain strain tension*. Mendeley Data, version 2, published 4 July 2019. [DOI: 10.17632/rd6jm9tyb6.2](https://doi.org/10.17632/rd6jm9tyb6.2). [Dataset record](https://data.mendeley.com/datasets/rd6jm9tyb6/2).

The data are licensed under [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/); a copy is in [licenses/CC-BY-4.0.txt](licenses/CC-BY-4.0.txt). The data and derivatives are separately identified here; the surrounding repository's software license does not replace the data license.

The copies in `data/` were obtained from Dan Slater's Paramaterial examples repository at commit `77357000ebe4939fb540a0ef1e1071a14d3728e9`. The prepared filenames were assigned upstream. This example copies those CSV files byte for byte, preserving the original physical filename mapping below. The upstream backup and prepared copies were byte-identical when acquired. No byte-for-byte comparison against the Mendeley-hosted original files has been performed.

| Included filename | Original physical filename | Rows | SHA-256 |
|---|---|---:|---|
| `test_ID_055.csv` | `T_020_A_1_001_022_03.csv` | 614 | `35ed1f7b1e0406bba3ba903087e186097d60229f4a533b07188515845fb162b5` |
| `test_ID_056.csv` | `T_020_A_2_002_024_04.csv` | 645 | `4e381c1c478cb093788a5d7df9bf51d7d23a299b9fb2a7aa18351371f6ee24e1` |
| `test_ID_057.csv` | `T_020_A_3_003_025_05.csv` | 630 | `ab08b8e87472facdbb842b1dd7ed3567b50089269dc33655023944b495da50bb` |

`Strain` is dimensionless engineering strain and `Stress_MPa` is engineering stress in MPa. The metadata's `rate` field has no verified unit, so it is omitted from the calculation manifest and is not used in this example.

Reproduction outputs apply the author's strain-zero correction and compute UTS, endpoint-secant elastic modulus, and 0.2% proof stress. Corrected curves, numerical tables, and figures are derivatives produced by this example. No input CSV is overwritten, smoothed, sorted, or converted to true stress. Preserve the data attribution and identify these transformations when redistributing derived outputs.

## Fixed upstream metadata and method records

The following records establish the specimen mapping, selection, and algorithm. They are linked for inspection rather than bundled. SHA-256 values refer to the exact bytes acquired for the original case on 6 October 2026 (UTC).

- [metadata/00 backup info.xlsx](https://raw.githubusercontent.com/dan-slater/paramaterial-examples/77357000ebe4939fb540a0ef1e1071a14d3728e9/examples/dan-msc-basic-usage/info/00%20backup%20info.xlsx): Backup metadata: maps test IDs to original physical filenames.
  SHA-256: `b2bc0fed8600f40a2ec43e35737d47fedb5d014658bc4f623f247922b73608ed`.
- [metadata/01 prepared info.xlsx](https://raw.githubusercontent.com/dan-slater/paramaterial-examples/77357000ebe4939fb540a0ef1e1071a14d3728e9/examples/dan-msc-basic-usage/info/01%20prepared%20info.xlsx): Prepared metadata: tensile test type, 20 degrees Celsius, lot A, and specimen numbers 1-3.
  SHA-256: `49f4097cadcb34605bc3d79411f2c6e6ad1a21a8b72497bdc1173350fbf4106d`.
- [screening-marked.pdf](https://raw.githubusercontent.com/dan-slater/paramaterial-examples/77357000ebe4939fb540a0ef1e1071a14d3728e9/examples/dan-msc-basic-usage/info/screening-marked.pdf): Saved author screening: each selected specimen has reject field /Off and a blank comment. This records the author decision, not a new physical acceptance test.
  SHA-256: `df48554105ade7241295fab2788d0e5a7ebf34c3b79f5cf444342b9aacbabecc`.
- [author_notebook.ipynb](https://raw.githubusercontent.com/dan-slater/paramaterial-examples/77357000ebe4939fb540a0ef1e1071a14d3728e9/examples/dan-msc-basic-usage/dan-msc-basic-usage-0.1.0.ipynb): Author workflow and saved outputs for Paramaterial 0.1.0.
  SHA-256: `2444aa1c6ee2dd386e07b0f2c5a777c8a5c3c56d61970928dc87ad952f27fcec`.
- [metadata/aakash results.xlsx](https://raw.githubusercontent.com/dan-slater/paramaterial-examples/77357000ebe4939fb540a0ef1e1071a14d3728e9/examples/dan-msc-basic-usage/info/aakash%20results.xlsx): Temperature-level reference across lots; not a per-specimen ground truth for this three-specimen case.
  SHA-256: `856257043a78cc061fb6fe4f5d1801b9d9a0b067c1f379a5d76f57ffd21df866`.

The three screening widgets occur on pages 1, 2, and 3 for specimens 055, 056, and 057 respectively. The JSON manifest records the screening source URL and hash for each specimen. The complete spreadsheets, screening PDF, and original Notebook are not redistributed here.

## Paramaterial and author example code

- [Paramaterial](https://github.com/dan-slater/paramaterial), execution version **0.1.0 from PyPI**, is MIT licensed. The bundled notice is [licenses/Paramaterial-MIT.txt](licenses/Paramaterial-MIT.txt), copyright (c) 2022 dan-slater.
- [Paramaterial examples at the pinned commit](https://github.com/dan-slater/paramaterial-examples/tree/77357000ebe4939fb540a0ef1e1071a14d3728e9), including the adapted method sequence, are MIT licensed. The bundled notice is [licenses/Paramaterial-examples-MIT.txt](licenses/Paramaterial-examples-MIT.txt), copyright (c) 2023 dan-slater.
- The case calls the original package functions; it does not vendor the Paramaterial package or substitute a different elastic-fit algorithm. This example's orchestration, manifest, and verification are additions to the upstream method.

- [PyPI 0.1.0 wheel](https://files.pythonhosted.org/packages/35/e9/6975b177ff3c909a2251ac0694cc0f73bdc6d0e18e43de35d2da4346def9/paramaterial-0.1.0-py3-none-any.whl). SHA-256: `3bde2d5db7da47690fcb5fc3ab6ac8d71319e2f4f8a2fb9e5be9c77fc7f437e0`.
- Unmodified `paramaterial/processing.py` from that wheel has SHA-256 `5c991eebb20968e77d93522c4be50d4fa9812de8bf0d430471d46fadbd4e6d22`.

The method computes UTS on the full engineering curve; selects the original `Strain < 0.01` window; uses the author's 36 MPa preload and upper/lower-point selection; obtains E from the selected endpoint secant; shifts the strain zero; and locates the 0.002-offset intersection by piecewise linear interpolation. The 36 MPa setting belongs to this fixed reproduction and is not a general recommendation for new materials.

## Numerical reference and scope

[data/reference_metrics.json](data/reference_metrics.json) contains a separate NumPy-based numerical recalculation of the pinned algorithm, made on 6 October 2026 without importing Paramaterial. It preserves the full stored floating-point precision. These are newly computed reproduction checks, not recovered author per-specimen results, experimental ground truth, or claims of physical measurement accuracy. Tiny floating-point differences from the package implementation can occur; the verification tolerance is numerical only.

No saved textual, HTML, or JSON Notebook output was found containing the three IDs' author-result values. The author's 20 degrees Celsius summary pools 19 tensile specimens across multiple lots and must not be used as a tolerance for the selected three-specimen mean. The example does not perform material calibration, model training, solver execution, or generalization testing.

For experimental context, see Aakash, Connors, and Shields (2019), [Data in Brief, DOI 10.1016/j.dib.2019.104085](https://doi.org/10.1016/j.dib.2019.104085). The article is separately licensed CC BY-NC-ND 4.0. Its full text, XML, PDF, and figures are not redistributed in this example.
