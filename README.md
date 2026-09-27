# Experiment-to-CPFE Pipeline

[English](README.en.md)

把实验与微结构数据整理成可追溯的样本包，再按需要准备 Abaqus 输入、提取求解结果和构建机器学习数据集。

项目在数据处理过程中保存单位、坐标、张量顺序、取向约定、样本身份和来源记录。模型配置记录材料参数、网格、加载条件和评价方案。

**v0.2.0 新增数据基础层**：导入实验文件及其上下文，保留未知字段，构建具名多目标数据集，检查输入可用时间、来源分组、评价协议和交接状态。这个流程使用基础 Python 安装即可运行。

**v0.2.1 修复与检查更新**：导出前校验合并后的 ODB 记录，绑定逐行来源和字段单位；补齐 CLI 摘要、策略传递及 CI skip 门禁，并执行 CPU PyG 导出测试。

## 从一个小例子开始

需要 Python 3.12 或更新版本。在仓库根目录执行：

```text
git clone https://github.com/koocmitwho/experiment-to-cpfe-pipeline.git
cd experiment-to-cpfe-pipeline
python -m venv .venv
```

Windows PowerShell 激活环境：

```powershell
.venv/Scripts/Activate.ps1
```

Linux/macOS 使用 `source .venv/bin/activate`。随后安装并运行：

```text
python -m pip install -e .
python examples/data_foundation/workflow.py --run-dir runs/data-foundation-001
```

示例生成 3 个合成样本、12 行数据，保留原始信息并读回 HDF5，再构建训练集、检查分组和评价声明。输出位于指定目录，其中：

- `dataset/dataset.npz` 保存特征、目标、样本身份和分区；本例为 8 行 train、4 行 validation。
- `dataset/dataset.json` 保存单位、来源链和任务检查结果。
- `protocol/evaluation-protocol.json` 与 `intake/intake-status.json` 保存协议和交接检查。
- `verification.json` 记录合成数据流程的执行情况和检查结果。

每次运行使用新的输出目录。[数据基础层指南](docs/data-foundation.md) 介绍逐步命令、配置和结果含义；[示例说明](examples/data_foundation/README.md) 提供最短复跑路径。

## 已实现的能力

| 环节 | 可以做什么 | 使用入口 |
| --- | --- | --- |
| 原始数据接入 | 读取已支持的表格、数组、网格、取向和图数据，保留源文件与转换记录 | [数据格式](docs/data-modalities.md)、[原生适配器](docs/native-adapters.md) |
| 实验信息整理 | 导入自描述 JSON 或指定 BAM LIS 配置，保存原始元数据、单位与已知/待确认信息 | `import-experiment-file` |
| 样本规范化 | 按显式数据配置生成并读回标准 HDF5 | `normalize-sample` |
| 训练数据构建 | 选择表列或数组分量，按行身份对齐，声明单位换算、目标顺序与样本分组 | `build-training-dataset` |
| 基础检查 | 检查未来输入、标签污染、分组重叠、评价声明及其证据；记录交接状态 | `check-evaluation-protocol`、`check-intake-status` |
| Abaqus 接入 | 检查受支持模型的输入条件，生成或暂存 INP，执行 datacheck/analysis，提取 ODB | [运行指南](docs/runbook.md) |
| 现有学习器 | 对标量目标运行分组 CPU MLP，使用训练集拟合归一化、验证集选择检查点 | [训练数据指南](docs/training-datasets.md) |

HDF5 是规范样本包。导出前会校验合并后的实验与仿真记录，并保存本阶段报告。NPZ/PyG 从已校验的 HDF5 导出，保留相关数据及来源元信息；PyG 使用显式图数组和特征声明。启用的格式由 `export.formats` 指定。具体格式和求解器条件见[能力与运行条件](docs/limitations.md)。

数据集构建支持 v1 标量目标和 v2 有序目标列表，并支持 train/validation 开发数据。`train-surrogate` 使用标量 CPU MLP，接收 v1 目标声明和 train/validation/test 三分区配置，完整操作见[训练数据指南](docs/training-datasets.md)。

## 已有公开案例

### KupferDigital：拉伸实验到有限元和代理模型

[CuSn8Ni2 拉伸案例](examples/kupfer_tensile/README.md) 包含公开实验数据的处理方式、材料标定、Abaqus 模型、ODB 提取、数据打包和标量 MLP。H_08 用于标定，H_16 用于模型检查，H_18 用于最终实验比较。

[既有验证记录](docs/verification/2026-09-06-public-tensile-surrogate.md) 对应 0–0.8% 工程应变内的均匀标距小应变模型，记录了 12 个有限元算例。其保留 FE 算例的 MLP RMSE 为 0.682 MPa；在实验试样 H_18 上，FE 和 MLP RMSE 分别为 4.428 MPa、4.477 MPa。记录中的日期、模型和试样划分给出了这些结果的具体条件。

[参考 INP](examples/kupfer_tensile/reference/base.inp) 与[结果摘要](docs/verification/assets/public-tensile-20260906/summary.json) 随案例提供。数据及指定处理材料遵循 CC BY 4.0，详见[第三方声明](THIRD_PARTY_NOTICES.md)。

### GH4169：超声参数到平均晶粒尺寸

[GH4169 案例](examples/gh4169_ultrasonic/README.md) 将公开数据中的 10 个试样接入 HDF5 和训练数据集，比较均值、线性、岭回归及 MLP 基线。它展示同一工作簿内不同实体试样的来源分组；该小样本记录中线性回归表现优于 MLP。

通过案例中的来源链接获取 CC BY-NC 3.0 原始数据，使用仓库脚本在本地生成规范化样本、模型和评价结果。

## 原有求解与导出流程

以下合成例子检查完整样本和求解条件，准备 INP，并导出数据：

```text
pipeline validate --config examples/synthetic_minimal/sample.yaml --run-dir runs/synthetic-001
pipeline build-inp --config examples/synthetic_minimal/sample.yaml --run-dir runs/synthetic-001
pipeline export --config examples/synthetic_minimal/sample.yaml --run-dir runs/synthetic-001 --format hdf5
pipeline export --config examples/synthetic_minimal/sample.yaml --run-dir runs/synthetic-001 --format npz
pipeline inspect --run-dir runs/synthetic-001
```

已实现的 Abaqus 配置使用直接定义节点和单元的三维实体网格、一个命名材料和一个静态位移加载步。材料可为各向同性弹性、各向同性塑性或显式 UMAT；取向可按声明映射到初始化的 STATEV。[能力与运行条件](docs/limitations.md)列出配置细节。安装并配置自己的 Abaqus 后，使用：

```text
pipeline run-abaqus --config sample.yaml --run-dir runs/sample-001 --stage datacheck
pipeline run-abaqus --config sample.yaml --run-dir runs/sample-001 --stage analysis
pipeline extract-odb --config sample.yaml --run-dir runs/sample-001
```

配置或输入改变后使用新的运行目录。datacheck 与 analysis 分别记录阶段产物。仅检查数据时可使用 `normalize-sample`；`validate` 同时检查求解条件。

## 可选依赖和开发

```text
python -m pip install -e ".[native]"
pipeline adapt --config examples/synthetic_native/imports.yaml --run-dir runs/native-example
```

`native` 增加 MAT5/XLSX 读取；`training` 增加现有 CPU MLP 所需依赖；`ml` 提供 PyTorch/PyG 导出依赖。按使用入口选择对应的附加依赖。

开发检查：

```text
python -m pip install -e ".[dev]"
python -m pytest -q -rs --strict-markers
python -m build
```

源码和发行文件通过 [GitHub Releases](https://github.com/koocmitwho/experiment-to-cpfe-pipeline/releases) 提供。版本内容见[更新记录](CHANGELOG.md)，修复与测试证据见[验证记录](docs/verification/2026-09-27-validation-ci-hardening.md)。各阶段命令会打印执行摘要；`pipeline --version` 显示工具版本。

## 文档与许可

[数据基础层](docs/data-foundation.md) · [Schema](docs/schema.md) · [数据格式](docs/data-modalities.md) · [原生适配器](docs/native-adapters.md) · [训练数据](docs/training-datasets.md) · [运行指南](docs/runbook.md) · [能力与运行条件](docs/limitations.md)

代码、文档和合成夹具使用 [Apache-2.0](LICENSE)。第三方数据和指定处理材料适用各自许可，见 [NOTICE](NOTICE)、[第三方声明](THIRD_PARTY_NOTICES.md) 和[许可说明](docs/licensing.md)。输入数据、模型权重和求解产物应连同其来源、许可和实验条件保存在自己的数据目录。
