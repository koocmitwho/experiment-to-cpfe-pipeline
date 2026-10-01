# 用真实案例完成接入、训练、预测和评价

[English](real-case-workflow.en.md)

本指南对应 v0.3.0 源码；v0.2.2 不包含这些独立预测/评价入口。按下列步骤安装 v0.3.0 源码后操作。

使用标记源码（`git clone --branch v0.3.0 https://github.com/koocmitwho/experiment-to-cpfe-pipeline.git`）或 [v0.3.0 Release](https://github.com/koocmitwho/experiment-to-cpfe-pipeline/releases/tag/v0.3.0) 的源码包。wheel 提供库和 CLI；示例脚本与固定清单位于源码包。发布状态见[验证记录](verification/2026-09-30-public-usability.md)。

## 安装

需要 Python 3.12 或更新版本。原案例记录使用 Python 3.12.10 和已有 CPU PyTorch，未升级环境；发布审核另行验证了全新联网安装的 CPU 环境。在 v0.3.0 仓库根目录用 PowerShell 执行：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv\Scripts\python.exe -m pip install -e ".[training,native]"
$pythonPath = (Resolve-Path '.venv\Scripts\python.exe').Path
```

使用显式 Python 路径即可，无需改变 PowerShell 执行策略。Linux 可改用 `.venv/bin/python`。CPU 版本选择见 [PyTorch 官方安装页面](https://pytorch.org/get-started/locally/)；DOPAMICS 不需要 PyG、GPU 或 Abaqus。FAIR 的 XLSX 读取需要 `native` 中的 openpyxl，PCL 不需要训练依赖。可选图依赖缺失时仍交付 CSV 和指标。

## 获取 DOPAMICS 原始文件

打开 [Zenodo 15343816](https://zenodo.org/records/15343816)，仅下载 **2025-04-08_Mechanical_data_tensile_test_laser_ALES.zip**，约 622 KB。保存到仓库外的 `../cpfe-data/dopamics/`。不需要下载该记录中的大型 DIC 档案，不要运行其中的代码。

来源为 Paul Cathelineau 等记录的 DOPAMICS 激光拉伸数据，许可为 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)。出处、作者、变换和派生文件许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。固定版本 ZIP 的 SHA256 是：

```text
210c2474278ad4c05aae85958e3e1eb4ef339b02ebed91d1b72a3b292042ad61
```

入口会核对整个 ZIP、五份原生 TXT、原始试样元数据和仪器表头/单位。摘要不符即拒绝，不自动修改清单来接受另一版本。

## 运行整个案例

```powershell
& $pythonPath -B -X utf8 examples/external_cases/workflow.py --case dopamics --source-root ../cpfe-data/dopamics --run-dir ../cpfe-results/dopamics-001
```

每次选择一个尚不存在的输出目录。入口只读原文件，提取需要的成员到新运行目录，执行接入、建集、训练、独立预测和评价。CPU 单线程；OLS 有 2 个参数，MLP 的两个隐藏层各 16 个单元，共 321 个参数。MLP 最多 300 轮、patience 60、学习率 0.003、种子 17；预计数秒到数分钟、内存约 1 GB 以内，取决于首次依赖加载与磁盘速度。

固定划分如下；同一个原始试样的所有记录保持同一角色：

|角色|原始试样 ID|原生 trial|记录行数|
|---|---|---|---:|
|训练|MC87_0370、MC87_1016、MC87_1044|1、3、4|120＋101＋203＝424|
|验证|MC87_1013|10|181|
|独立预测/测试评价|MC87_1081|11|182|

原元数据 CSV 的物理第 55、59、62、58、63 行分别核对这些身份和 trial；收据为 `specimen-identity-checks.json`。每份 TXT 的数据从物理第 9 行开始。

本例输入为已测得的激光应变：原始 `%` 乘以 0.01 转成无量纲；目标是仪器报告应力，单位 MPa。保留全部记录，不调零、不按响应裁剪、选峰或筛行。训练/验证每试样预算上限为等距 256 行，本固定版本均未触发删行。

归一化只用 424 个训练记录拟合，验证记录只用于 MLP 检查点与 OLS/MLP 选择；OLS 系数由训练记录闭式求解。选模收据先于测试推理写入，规则为验证 RMSE 最小，并列选 OLS。测试只在选模后执行，不参与拟合或本次参数调整。

## 从哪里读结果

先打开 `REPORT.md`，再看以下文件：

|文件|用途|
|---|---|
|`inference/predictions.csv`|逐行预测、样本/组/原始行、目标和单位、原文件与成员、来源摘要、检查点及配置摘要；没有真值|
|`evaluation/evaluation.csv`|同一身份对齐的真值、预测、残差和冻结训练均值|
|`evaluation/SUMMARY.md`|中文指标、各项基线比较和任务状态|
|`baseline-comparison.csv`|训练均值、OLS 和验证集所选模型的测试比较|
|`model-selection.json`|仅基于验证集的候选误差、选中模型及时间|
|`models/*/training.json`|实际参数、逐轮记录、归一化、训练/验证指标|
|`configs/`、`commands/`|实际运行配置、命令参数、退出码与阶段耗时|
|`source-hashes-before.json`、`source-hashes-after.json`|原输入保持核对|
|`verification.json`|整体完成、数值读回、原始身份与独立进程读回结果|

`row_id` 是 JSON 复合身份；例如 `[9]` 对应该原始文件的第 9 行。不同试样都出现第 9 行正常，身份必须和 `sample_id` 一起使用。文本 CSV 单元格必要时加一条反斜杠，防止电子表格把原始身份当公式；JSON 与收据保留原值。数值列不作这种转义。

## 逐步运行与独立交付

完整案例会生成所有配置。需要交给另一用户独立预测时，复制冻结检查点、对应输入 HDF5 和推理配置，修正其中的文件路径，并使用新的输出目录：

```powershell
& $pythonPath -m experiment_to_cpfe.cli infer-surrogate --config ../cpfe-results/dopamics-001/configs/infer.json --run-dir ../cpfe-results/prediction-002
```

本命令只打开列明的输入 HDF5 和冻结模型。真值在独立 HDF5 中。HDF5 的完整性读取会检查整个列明包，所以把标签放在同一混合文件里不算隔离。

评价配置的 `predictions` 要指向本次预测 NPZ，`inputs` 指向真值 HDF5；目标、单位、试样和行身份必须一致。评价不需要模型或原训练文件：

```powershell
& $pythonPath -m experiment_to_cpfe.cli evaluate-surrogate --config ../cpfe-results/dopamics-001/configs/evaluate.json --run-dir ../cpfe-results/evaluation-002
```

该原始配置指向首次案例预测；若评价第二次预测，先修改 `predictions` 路径。泛用模板入口如下，生成后必须填写新输入、原始身份和模型路径：

```powershell
& $pythonPath -m experiment_to_cpfe.cli template-config --kind infer-surrogate --from-config ../cpfe-results/dopamics-001/configs/build.json --output ../cpfe-results/infer-draft.json
```

模板原样传递严格 `task_contract` 与一致的 `target_specimen`，拒绝部分或冲突声明。模板不推断新的试样或物理事实。

## 指标如何解释

本轮固定案例中，验证集选择 MLP；其最优轮为 13，完成 73 轮后早停。测试结果为：

|方法|RMSE (MPa)|MAE (MPa)|R²|bias (MPa)|
|---|---:|---:|---:|---:|
|训练均值 7.11323 MPa|2.245313|1.810683|-1.090530|1.621689|
|OLS 线性|3.140684|2.839127|-3.090262|2.839127|
|所选 MLP|2.071353|1.923316|-0.779143|1.923316|

RMSE 对大误差更敏感；MAE 表示平均绝对误差。这里 MLP 的 RMSE 较训练均值低，MAE 较高，不能合写成“全面优于基线”。残差定义为预测减真值；正 bias 表示平均高估。

R² 用本测试真值均值定义方差参照，因此可以为负：本模型的平方误差超过该统计参照。测试均值不是可部署的训练基线。NRMSE 为 RMSE 除以本次评价真值的 `max(abs(reference))`；不同真值尺度下不能直接据此排名。全零真值时 NRMSE 无定义，JSON 保存 null；非零常数真值的 NRMSE 仍有定义。任何常数真值的 R² 均无定义，JSON 保存 null。

这里只有一个测试试样，182 行不是 182 个独立试样。没有预设科学误差门槛，摘要给出 `not_assessed`。分组检查证明所声明身份和来源未跨角色混用；它不证明生物个体、批次或材料统计独立。

## 案例的适用范围

这是棕榈小叶原始激光拉伸数据上的回顾性条件回归。已测应变是输入，仪器报告应力是目标；工程/真实应力约定未独立确认。来源检查会读取公开测试响应，因此这不是新的盲测。任务保留 `legacy_unassessed`；没有晶体塑性求解、材料标定或跨材料验证结论。

把力、仪器应力、位移和同仪器派生通道任意互相预测可能产生代数关系泄漏；本例只选择激光应变，仍需承认同步测量和回顾性用途。若要未来加载预测、批次外泛化或本构验证，应另定输入时机、实验条件和独立试样方案。

FAIR Train 仅核对三个铜合金工作簿原始通道和源工作表/行；同牌号、批次、热处理、温度和规定速率不充分。PCL 保留全部十二通道及预热/平衡/加载记录并建集；时间/温度到应力只用于数值打包，不训练。其原数据要求和命令见 [外部案例目录](../examples/external_cases/README.md)。

## 失败后处理

文件版本、标题、单位、重复来源、非有限值或身份错配都会报错。已有输出目录不会覆盖。输入检查失败可能尚未创建目录；执行期失败保留 `failure.json` 或阶段失败收据，没有整体 `verification.json`。修改配置后选择新的运行目录，保留失败证据；不要改原始测量来使检查通过。

标量训练器默认要求 train/validation/test。此案例显式设置 `evaluation_mode: external_test`，只允许 train/validation。v2 多目标/具名目标列表被明确拒绝，不能直接传给该训练器；先在建集配置中用 v1 `target` 声明单个标量。
