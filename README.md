# Experiment-to-CPFE Pipeline

简体中文 | [English](README.en.md)

当前公开版本：**v0.3.1**。[下载与安装包](https://github.com/koocmitwho/experiment-to-cpfe-pipeline/releases/tag/v0.3.1) · [版本变化](CHANGELOG.md)

**把实验与微结构数据整理成可追溯的样本，再按需要建集、训练、独立预测和评价。**

这是一个 Python 库和命令行工具。它把分散的表格、数组、试样信息与来源记录整理为统一 HDF5 样本，检查单位、行身份和数据划分，并为标量回归或受支持的 Abaqus 工作流准备输入。

例如，一份拉伸文件中的应变以百分数保存，应力以 MPa 保存；同一试样有多行测量。项目可以记录百分数到无量纲的换算，把整个试样放在同一数据分区，只用训练记录拟合归一化，再用冻结模型预测另一试样，最后对齐真值并输出 CSV 和误差指标。

> 数据检查和测试通过说明软件按所声明的规则运行。材料模型是否正确、实验是否足够独立、预测精度是否达到研究要求，需要另外设计和验证。

## 适合谁，能解决什么问题

适合需要整理材料实验数据、准备有限元输入或建立小型回归基线的研究者与工程开发者，尤其是希望保留原文件、试样身份、单位换算和训练划分的人。

主要用途包括：

- **整理多种数据。** 按明确配置读取表格、数值数组、网格、取向和图数据，保留来源与处理关系。
- **保留实验上下文。** 记录材料、几何、加载与测量信息，保留原始元数据和未知字段，区分已确认和缺失的信息。
- **构建可检查的数据集。** 按行身份对齐特征和目标，记录单位换算，按试样或显式分组划分 train、validation、test。
- **运行标量回归。** 使用 CPU OLS（普通最小二乘线性回归）或 MLP（多层感知机），只用训练记录拟合预处理和模型，用验证记录选模型。
- **分开预测与评价。** 用冻结检查点和输入数据生成预测，再用单独的真值数据评价，交付可读 CSV、中文摘要和机器可读记录。
- **衔接受支持的求解流程。** 检查和准备 Abaqus INP，记录 datacheck、analysis 与 ODB 提取阶段，导出 HDF5/NPZ，或按显式图声明导出 PyG。

项目不会自动解释任意仪器格式、推断缺失的物理事实，或从任意实验自动建立晶体塑性本构模型。图像和厂商专有文件可能需要先由其他工具转成这里支持的数值格式。Abaqus 执行需要使用者自己的软件、模型和必要的编译工具链。

## 安装

需要 **Python 3.12 或更新版本**。基础依赖为 NumPy、pandas、h5py、Pydantic 和 PyYAML；pip 会按 [pyproject.toml](pyproject.toml) 安装。

公开源码与包可以独立使用，不需要私有代码、私有材料卡、训练权重或研究数据。基础示例不需要 PyTorch、PyG、GPU 或 Abaqus。大部分真实案例的数据需要另外下载；Paramaterial 小案例附带三条已获再分发许可的工程应力—应变曲线。

### 推荐：获取带示例的固定版本源码

以下命令在你选择的工作目录执行；如果目标目录已存在，先检查其中的版本和本地修改。

```text
git clone --branch v0.3.1 --depth 1 https://github.com/koocmitwho/experiment-to-cpfe-pipeline.git
cd experiment-to-cpfe-pipeline
python -m venv .venv
```

Windows PowerShell：

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m experiment_to_cpfe.cli --version
```

Linux/macOS shell：

```bash
.venv/bin/python -m pip install -e .
.venv/bin/python -m experiment_to_cpfe.cli --version
```

应显示 `pipeline 0.3.1`。这里直接使用虚拟环境中的解释器，不要求修改 PowerShell 执行策略。后续命令从仓库根目录运行，默认给出 Windows 写法；Linux/macOS 将 `.\.venv\Scripts\python.exe` 换成 `.venv/bin/python`。

没有 Git 时，也可下载 [Release 的源码包](https://github.com/koocmitwho/experiment-to-cpfe-pipeline/releases/download/v0.3.1/experiment_to_cpfe-0.3.1.tar.gz)，解压后在含 `pyproject.toml` 的目录安装。

### 只需要库和 CLI：安装 wheel

在新建或已有的独立虚拟环境中安装，例如 Windows：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install "https://github.com/koocmitwho/experiment-to-cpfe-pipeline/releases/download/v0.3.1/experiment_to_cpfe-0.3.1-py3-none-any.whl"
.\.venv\Scripts\python.exe -m experiment_to_cpfe.cli --help
```

wheel 提供库和 CLI；示例脚本、配置和固定案例清单位于源码仓库及源码包。安装 wheel 后想运行下文示例，还需取得对应 v0.3.1 源码中的 `examples/`。本版本通过 GitHub 分发，没有发布到 PyPI。

### 按用途添加依赖

以下命令用于已取得的源码目录；基础流程不需要一次装齐所有附加依赖。

| 用途 | 附加依赖 | 说明 |
|---|---|---|
| MAT5/XLSX 原生读取 | `.[native]` | SciPy、openpyxl |
| 标量训练与模型推理 | `.[training]` | PyTorch、SciPy；公开训练器使用 CPU |
| PyG 图导出 | `.[ml]` | PyTorch、torch-geometric；仍需正确的图声明 |
| 开发与打包 | `.[dev]` | pytest、build、twine 等 |

例如安装原生读取依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[native]"
```

Windows/Linux 训练示例建议先安装 CPU PyTorch，再安装训练与原生读取依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install "torch>=2.6" --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -e ".[training,native]"
```

PyTorch 的平台选择见 [官方安装页面](https://pytorch.org/get-started/locally/)。Linux/Windows 已有发布 CI；macOS 的完整流程尚未验证。

## 第一次运行：不下载数据，不启动求解器

先完成源码基础安装，然后执行：

```powershell
.\.venv\Scripts\python.exe -X utf8 examples/data_foundation/workflow.py --run-dir runs/data-foundation-001
```

脚本生成 3 个合成试样、12 行数据，完成实验文件导入、CSV 规范化、HDF5 读回、数据集构建，以及评价协议和交接状态检查。两件试样的 8 行归 train，另一件试样的 4 行归 validation。

主要结果位于 `runs/data-foundation-001/`：

| 文件 | 内容 |
|---|---|
| `imports/<specimen>/sample.h5` | 三个规范样本及其实验上下文 |
| `normalized/sample.h5` | 单独演示 CSV 规范化的样本 |
| `dataset/dataset.npz`、`dataset/dataset.json` | 特征、目标、行身份、分组、单位与来源 |
| `protocol/evaluation-protocol.json` | 评价协议与已声明证据的检查结果 |
| `intake/intake-status.json` | 交接检查结果 |
| `verification.json` | 合成流程的软件检查摘要 |

**这一步不训练模型。** 它演示 v2 目标列表与两分区建集；生成的配置不能直接交给当前标量训练器。要验证训练入口，使用下一节的 v1 示例。

每次选择尚不存在的输出目录，例如下一次用 `runs/data-foundation-002`。修改配置后保留原结果，另开目录。逐步命令和字段见 [数据基础层指南](docs/data-foundation.md) 与 [示例说明](examples/data_foundation/README.md)。

## 小型真实案例：三个拉伸试样的处理与读回

[Paramaterial 三试样案例](examples/paramaterial_tensile/README.md) 使用附带的 AA6061-T651、20°C、A 批次公开曲线，共 1,889 行。它按作者方法计算 UTS、E 和 0.2% proof，再经公开包 HDF5 规范化、读回和独立核对，输出曲线及指标对照表。案例使用单列的 Python 3.12 依赖，不需要训练或求解器。

```powershell
.\.venv\Scripts\python.exe -m pip install -r examples/paramaterial_tensile/requirements.txt
.\.venv\Scripts\python.exe -B examples/paramaterial_tensile/workflow.py --run-dir runs/paramaterial-001
```

输入为作者公开的工程应力—应变曲线，数据采用 CC BY 4.0；[来源与处理口径](examples/paramaterial_tensile/SOURCES.md)随例保留。这一小任务检验处理与流转一致性，不代表材料标定或跨材料预测。

## 接着运行：合成数据上的标量训练

安装上面的 CPU 训练依赖后，运行表布局示例：

```powershell
.\.venv\Scripts\python.exe examples/synthetic_training/prepare.py --output-dir runs/training-inputs-001
.\.venv\Scripts\python.exe -m experiment_to_cpfe.cli build-training-dataset --config runs/training-inputs-001/table/build.yaml --run-dir runs/table-dataset-001
.\.venv\Scripts\python.exe -m experiment_to_cpfe.cli train-surrogate --config runs/table-dataset-001/training-config.json --run-dir runs/table-model-001
```

输入由 `y = x * gain` 生成：四个合成样本，每个 31 行，固定为 2 个训练样本、1 个验证样本、1 个测试样本。示例展示 kN 到 N 的单位换算，以及按样本隔离的标量回归。

打开 `runs/table-model-001/training.json` 查看实际训练设置、归一化、分区误差和训练均值基线；`model.pt` 是冻结检查点，`predictions.npz` 保存该训练流程的分区预测。这些是合成软件示例，不证明真实材料预测精度。数组布局、参数调整和完整说明见 [合成训练示例](examples/synthetic_training/README.md)。

### 数据划分和版本边界

| 操作 | v0.3.1 支持范围 |
|---|---|
| `build-training-dataset` | v1 单个 `target`；v2 有序 `targets` 列表；必须有 train、validation，test 可选 |
| `train-surrogate` 默认模式 | v1 标量目标；要求 train、validation、test |
| `train-surrogate` 的 `evaluation_mode: external_test` | v1 标量目标；只允许 train、validation，测试数据留在外部 |
| `infer-surrogate` / `evaluate-surrogate` | 当前公开标量 OLS/MLP 检查点与对应输入/真值；不支持 v2 多目标训练或推理 |

不要把同一原始试样的测量行随机拆到训练和测试中。可以按 `sample_id`、`experiment_id` 或显式 `group_id` 分组；共享工作簿中的不同试样需声明原始身份列和对应来源。程序检查声明与来源是否跨分区冲突，但独立性仍需实验设计支持，改文件名或分组标签不会创造独立试样。

归一化和 OLS 系数只拟合训练记录；MLP 检查点由验证误差选择。输入是否在实际预测时可获得、是否含有目标派生信息，也需要明确配置。规则与配置示例见 [训练数据指南](docs/training-datasets.md)。

## 真实公开案例：接入到独立预测与评价

[DOPAMICS 完整中文教程](docs/real-case-workflow.md) 展示公开棕榈小叶拉伸数据的接入、规范化、标量建集、CPU OLS/MLP、独立预测和测试评价，不需要 PyG、GPU 或 Abaqus。

完成源码与 CPU 训练依赖安装后，从 [Zenodo 15343816](https://zenodo.org/records/15343816) **仅下载** `2025-04-08_Mechanical_data_tensile_test_laser_ALES.zip`（约 622 KB），保存到仓库外的 `../cpfe-data/dopamics/`，然后执行：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 examples/external_cases/workflow.py --case dopamics --source-root ../cpfe-data/dopamics --run-dir ../cpfe-results/dopamics-001
```

脚本核对固定文件摘要、原始试样身份、表头和单位；不会下载或运行上游脚本。输入是已测得的激光应变，目标是仪器报告应力。固定划分为 3 个训练试样（424 行）、1 个验证试样（181 行）和 1 个外部测试试样（182 行）；同一试样保持同一角色。它只在验证集上选择 OLS/MLP，再评价测试试样。

先读输出目录中的 `REPORT.md`，然后看：

- `inference/predictions.csv`：逐行预测、身份、来源与单位，不含真值。
- `evaluation/evaluation.csv` 和 `evaluation/SUMMARY.md`：对齐后的真值、残差、指标和中文说明。
- `baseline-comparison.csv`、`model-selection.json`：训练均值、OLS 和所选模型的比较及验证选模依据。
- `configs/`、`commands/`、`verification.json`：实际配置、阶段命令和结果记录。

需要单独预测时，准备冻结的 `model.pt`、输入专用 HDF5 和推理配置，调用 `infer-surrogate --config ... --run-dir ...`。评价使用 `evaluate-surrogate --config ... --run-dir ...`，需要预测产物及其完成记录、真值专用 HDF5，不需要重新打开模型或原训练文件。教程给出生成配置后的可执行命令；`template-config` 可从建集配置生成待填写草稿。

推理与评价核对名称、单位、试样和行身份。HDF5 完整性检查会读取整个列明包，因此要把封存真值放在单独文件中；仅在混合文件里不选择目标列不等于隔离。

### 怎样理解案例结果

v0.3.0 固定案例在一个测试试样上得到：

| 方法 | RMSE（MPa） | MAE（MPa） | R² |
|---|---:|---:|---:|
| 训练均值基线 | 2.245313 | 1.810683 | -1.090530 |
| OLS | 3.140684 | 2.839127 | -3.090262 |
| 验证集所选 MLP | 2.071353 | 1.923316 | -0.779143 |

MLP 的 RMSE 较均值基线低，但 MAE 更高，不能称为全面优于基线。负 R² 表示其平方误差超过以测试真值均值定义的方差参照；该测试均值只是统计参照，并非可部署的训练基线。182 行不是 182 个独立试样。

这里没有预设科学精度门槛，也没有材料标定、晶体塑性或跨材料验证结论。数据来源检查读过公开测试响应，案例是回顾性条件回归，不是新的盲测。任务和科学有效性仍未完成评定。指标定义和源数据约定见 [完整教程](docs/real-case-workflow.md)。

## 其他示例

| 示例 | 展示内容 | 条件与边界 |
|---|---|---|
| [FAIR Train / PCL](examples/external_cases/README.md) | FAIR 原始工作簿通道导入；PCL 十二通道和预热等记录的数值建集 | 公开源数据另行下载；这两个固定案例不训练模型 |
| [GH4169 超声](examples/gh4169_ultrasonic/README.md) | 十个试样的平均晶粒尺寸标量回归，比较均值、线性、岭回归和 MLP | 原始数据为 CC BY-NC 3.0；小样本结果中线性回归优于 MLP |
| [KupferDigital 拉伸](examples/kupfer_tensile/README.md) | CuSn8Ni2 小应变均匀标距模型、标定、有限元与代理模型比较 | 完整求解需要自己的 Abaqus；历史结果限定在 0–0.8% 工程应变与所述试样/模型 |
| [合成原生导入配置](examples/synthetic_native/imports.yaml) | 明确声明的原生数值导入 | 使用 `native` 依赖；不执行真实求解 |

历史 KupferDigital 记录包含 12 个有限元案例：保留 FE 案例上的 MLP RMSE 为 0.682 MPa；H_18 实验比较中 FE/MLP RMSE 为 4.428/4.477 MPa。这些仅属于 [对应模型和历史验证条件](docs/verification/2026-09-06-public-tensile-surrogate.md)，不能代表任意晶体塑性实验，也不能当作 v0.3.0 的真实 Abaqus 重验结果。

## 输入、输出与求解器入口

数据输入由 JSON/YAML 配置明确声明：文件路径、样本/试样身份、表列或数组分量、原单位与换算、坐标与取向约定、分组及必要的来源信息。配置示例是起点，不能把自己的原始数据只改文件名后直接套用。

| 阶段 | 主要输入 | 主要输出 |
|---|---|---|
| 实验文件导入 / 规范化 | 自描述 JSON、配置的 BAM LIS 信息或受支持的数值文件及映射 | `sample.h5`、原始上下文、来源与处理记录 |
| 训练建集 | 规范 HDF5、特征/目标选择、行对齐与分组配置 | `dataset.npz`、`dataset.json`、`training-config.json` |
| 标量训练 | v1 训练包和训练参数 | `model.pt`、`training.json`、分区预测与均值基线 |
| 独立推理 | 冻结检查点、输入专用 HDF5、推理配置 | `predictions.npz`、`predictions.csv`、`inference.json`、中文摘要 |
| 独立评价 | 预测 NPZ 与完成记录、真值专用 HDF5、评价配置 | `evaluation.npz`、`evaluation.csv`、`evaluation.json`、中文摘要 |
| 求解 / 提取 / 导出 | 受支持的 INP、材料与加载配置、求解器和 ODB | 阶段记录、提取字段、HDF5/NPZ，以及满足图声明时的 PyG |

HDF5 是规范样本格式。普通样本 NPZ 保留样本数据；训练 NPZ 保存被明确选出的特征、目标和划分，两者不能混用。图导出使用已声明的节点、图数组和特征，不会从任意图像自动生成图。格式与选择器见 [数据格式](docs/data-modalities.md) 和 [原生适配器](docs/native-adapters.md)。

基础安装可以先运行不启动 Abaqus 的校验、INP 准备和导出：

```powershell
.\.venv\Scripts\python.exe -m experiment_to_cpfe.cli validate --config examples/synthetic_minimal/sample.yaml --run-dir runs/synthetic-001
.\.venv\Scripts\python.exe -m experiment_to_cpfe.cli build-inp --config examples/synthetic_minimal/sample.yaml --run-dir runs/synthetic-001
.\.venv\Scripts\python.exe -m experiment_to_cpfe.cli export --config examples/synthetic_minimal/sample.yaml --run-dir runs/synthetic-001 --format hdf5
.\.venv\Scripts\python.exe -m experiment_to_cpfe.cli export --config examples/synthetic_minimal/sample.yaml --run-dir runs/synthetic-001 --format npz
.\.venv\Scripts\python.exe -m experiment_to_cpfe.cli inspect --run-dir runs/synthetic-001
```

这组命令是同一次运行的连续阶段，按顺序共用目录。新的一次运行应更换目录。训练、独立预测、评价和完整示例各自使用新输出目录；不要通过删除原结果来让重跑覆盖它。

当前 Abaqus 检查范围是受支持的三维实体单元、单材料和单静态位移加载步，可声明各向同性弹性、各向同性塑性或显式 UMAT。用户子程序、材料参数、编译链和真实运行均由使用者提供。取向可按已声明映射写入初始 STATEV；这不自动补全或验证晶体塑性模型。实际执行需先按 [运行指南](docs/runbook.md) 准备配置，再使用 `run-abaqus --stage datacheck`、`run-abaqus --stage analysis` 和 `extract-odb`。

## 当前验证范围与局限

v0.3.1 新增 Paramaterial 小案例；其依赖、测试与运行结果按[案例说明](examples/paramaterial_tensile/README.md)单列。以下 v0.3.0 数字保留为历史发布证据。

v0.3.0 发布审核验证了公开包的独立安装、源码示例、CPU 训练/推理/评价和包内容。Windows 隔离环境最终复核为 **831 通过、1 跳过**，唯一跳过项为未启用的真实 Abaqus。标签 [CI](https://github.com/koocmitwho/experiment-to-cpfe-pipeline/actions/runs/36811952722) 的 Ubuntu/Windows 基础流程、CPU training、CPU ML 四项均通过；基础流程还检查了 wheel 安装，CPU ML 包含实际 PyG 序列化读回。

这些结果没有覆盖或证明：

- 真实 Abaqus、GPU、可选绘图、macOS 完整流程或所有依赖版本组合。
- 任意厂商格式、任意晶体塑性实验、本构准确度、数值收敛和跨材料泛化。
- v0.3.0 审核中的 FAIR/PCL 实数据重跑；此次覆盖其公开合成回归。
- 历史 Windows 原生崩溃的根因；限定 CPU 运行未复现不能解释原故障。

进一步的功能条件见 [能力与运行条件](docs/limitations.md)。[发布审核快照](docs/verification/2026-09-30-public-usability.md) 和 [Release](https://github.com/koocmitwho/experiment-to-cpfe-pipeline/releases/tag/v0.3.0) 保留具体安装、命令、指标与分发证据。

## 项目结构和文档入口

```text
src/experiment_to_cpfe/  Python 库、CLI、适配器、建集、训练与求解器接口
configs/                 示例配置、策略及 INP 模板
examples/                合成示例与公开案例脚本/固定来源清单
docs/                    格式、训练、运行和案例指南
tests/                   公开单元测试与集成测试
scripts/                 ODB 提取与运行产物校验工具
```

按需求查阅：

- 初次接入与字段声明：[数据基础层](docs/data-foundation.md)、[Schema](docs/schema.md)。
- 原始文件读取：[数据格式](docs/data-modalities.md)、[原生适配器](docs/native-adapters.md)。
- 训练与分组：[训练数据](docs/training-datasets.md)、[合成训练示例](examples/synthetic_training/README.md)。
- 从真实数据到独立预测：[DOPAMICS 中文教程](docs/real-case-workflow.md)。
- 求解器与导出：[运行指南](docs/runbook.md)、[能力边界](docs/limitations.md)。

部分详细技术文档使用英文；中文 README 与真实案例教程提供主要入门路径。

## 测试与贡献

在未安装 PyTorch 的基础环境中，安装开发依赖后可运行基础测试和打包：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q -rs --strict-markers
.\.venv\Scripts\python.exe -m build
```

默认 `offline` 测试模式允许缺少 PyTorch 的已登记测试，以及未启用的真实 Abaqus/wheel 安装检查被跳过；其他意外跳过会失败。如果此前已安装训练用 PyTorch，完整套件还会检查 PyG，只有 `.[training]` 并不够。先按上文安装 CPU PyTorch，再补齐 ML 开发依赖并运行：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,ml]"
$env:EXP2CPFE_TEST_PROFILE = "ml"
.\.venv\Scripts\python.exe -m pytest -q -rs --strict-markers
```

Linux 用 `export EXP2CPFE_TEST_PROFILE=ml` 设置该模式。wheel 安装检查需先构建包，再按 [发布检查表](docs/release_checklist.md) 设置 `EXP2CPFE_WHEEL_DIR`。不同依赖和 opt-in 设置的测试数不能直接等同。

欢迎通过 [Issues](https://github.com/koocmitwho/experiment-to-cpfe-pipeline/issues) 描述问题或提交 Pull Request。报告错误时附版本、相关命令、最小可复现配置和脱敏后的诊断；贡献格式适配或功能时说明适用范围并补充相应验证。请使用可公开的小型合成样本或有明确再分发许可的输入，不上传私人实验、凭据、模型权重或本机配置。

## 许可证与数据来源

项目代码、文档和合成夹具使用 [Apache-2.0](LICENSE)。数据与来源派生材料遵循各自许可证：

- KupferDigital 指定案例材料，以及 DOPAMICS、FAIR Train、PCL 来源派生清单：CC BY 4.0。
- Paramaterial 三条公开工程曲线、来源派生清单与参考计算：CC BY 4.0；上游方法与示例保留 MIT 声明。
- 另外获取的 GH4169 原始数据：CC BY-NC 3.0；项目代码的许可证不改变其非商业条款。
- 其他可选来源按各自清单和上游条件使用。

作者、原始记录、修改说明和适用范围见 [NOTICE](NOTICE)、[第三方声明](THIRD_PARTY_NOTICES.md) 与 [许可记录](docs/licensing.md)。源码包附带三条已明确归属的 Paramaterial 案例曲线；其他原始档案、训练权重和求解结果由使用者保存在本地工作目录。
