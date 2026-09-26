# 数据基础层：从文件到可检查的数据集

本指南对应 v0.2.0 的数据导入、样本规范化、训练数据构建与基础检查。运行下述例子只需要基础安装，不需要 Torch、Abaqus 或外部数据下载。

## 一次运行整个例子

在仓库根目录、已激活的 Python 3.12+ 环境中执行：

```text
python -m pip install -e .
python examples/data_foundation/workflow.py --run-dir runs/data-foundation-001
```

脚本生成三个合成试样，每个四行。力由 `force = 2 * command + 0.1 * specimen_index` 计算，单位为 N，两个试样进入 train，一个进入 validation。它还单独生成一份 CSV，演示普通声明式规范化。

最后打印并保存到 `verification.json` 的摘要为：

```json
{
  "status": "completed",
  "evidence_scope": "synthetic_mechanism_only",
  "specimens": 3,
  "rows": 12,
  "training_executed": false,
  "solver_executed": false,
  "checks": {
    "future_input_rejected": true,
    "group_overlap_rejected": true
  },
  "scientific_validity": "not_established_by_software_checks"
}
```

这些检查证明本例的文件处理、身份对齐与拒绝规则能够执行。数值来自合成公式，没有测量误差、材料标定或数值收敛结论。`ready`、`declared_ready` 等状态表示已声明条件的检查结果。

## 到哪里看结果

下表中的路径都相对本次 `--run-dir`：

| 路径 | 内容 |
| --- | --- |
| `inputs/` | 本例生成的原始 JSON 和 CSV |
| `configs/` | 导入、规范化、数据构建、协议和交接配置 |
| `imports/specimen-a/sample.h5` | 首个合成试样的规范化样本；另外两个试样使用同样目录结构 |
| `imports/specimen-a/experiment-context.json` | 已声明信息、缺失/待确认字段、原始元数据与脚本记录 |
| `imports/specimen-a/experiment-file.json` | 导入状态、源文件哈希和产物记录 |
| `normalized/sample.h5`、`normalized/normalization.json` | CSV 规范化结果与检查记录 |
| `dataset/dataset.npz` | 特征、目标、分组、分区、样本身份和行身份 |
| `dataset/dataset.json` | 单位、列选择、来源、任务合同及检查结果 |
| `dataset/training-config.json` | 数据集位置、哈希与特征/目标声明 |
| `dataset/build-manifest.json` | 构建配置、输入和产物的来源记录 |
| `protocol/evaluation-protocol.json`、`protocol/REPORT.md` | 评价协议的机器可读结果与文字报告 |
| `intake/intake-status.json`、`intake/REPORT.md` | 交接状态及证据记录 |
| `verification.json` | 本例最终检查摘要 |

本例的特征和目标形状均为 `(12, 1)`，分区是 8 行 train、4 行 validation；统计组有 3 个。行数不等于独立试样数。原始 JSON 的 `unknown_header` 保留在实验上下文的 `raw_metadata` 中，未赋予推测的含义。

## 单独运行各阶段

先运行完整例子，以生成下面引用的真实配置和合成源文件。随后可以使用新的输出目录重跑单独阶段：

```text
pipeline import-experiment-file --config runs/data-foundation-001/configs/specimen-a.json --run-dir runs/data-foundation-import-002
pipeline normalize-sample --config runs/data-foundation-001/configs/normalize.json --run-dir runs/data-foundation-normalize-002
pipeline build-training-dataset --config runs/data-foundation-001/configs/build.json --run-dir runs/data-foundation-dataset-002
pipeline check-evaluation-protocol --config runs/data-foundation-001/configs/protocol.json --run-dir runs/data-foundation-protocol-002
pipeline check-intake-status --config runs/data-foundation-001/configs/intake.json --run-dir runs/data-foundation-intake-002
```

每行独立读取原示例的配置；重跑数据构建仍然引用 `data-foundation-001/imports/` 中的三个样本。若要改用另一批导入产物，需要显式修改构建配置的 `inputs`。保留示例生成时的目录位置；搬迁后应更新配置中的路径并重新构建。

配置或输入改变后，换一个新的输出目录。导入和规范化失败时应读取对应状态文件与错误信息，修正配置后在新目录重试。

## 数据导入保留哪些信息

`import-experiment-file` 支持 `self_describing_json_v1` 和 `bam_lis_context_v1` 两个显式配置。前者读取声明了样本、单位、观测行及上下文的 JSON；后者通过另行提供的 BAM 任务配置解释相应 LIS 文件。它不自动推断任意仪器格式。

导入配置用 `source.path` 和 `source.sha256` 绑定文件，另需说明用途、许可及 `evidence_scope`。合成示例使用 `synthetic_mechanism_only`。真实文件的声明应来自其采集记录。

实验上下文逐项区分 `confirmed`、`unconfirmed`、`unavailable` 与 `not_applicable`，覆盖身份、材料、几何、加载、温度、预载、归零、测量时序和预处理等字段。未知字段原样保留；确认的采集时间须包含时区。`confirmed` 指已有提交的依据，软件不会自动核实实验事实。

可选 `scripts` 记录采集/处理脚本的位置、哈希、声明版本和用途。导入时只核对并登记这些文件，不执行它们，也不控制仪器。

`normalize-sample` 面向已能明确描述的表格、资产和原生导入配置。每个映射字段须声明单位；它生成 HDF5 并核对读回，同时保存配置和输入的哈希。求解器准备检查属于后续 `validate` 流程。

## 训练数据声明与任务合同

构建器从标准 HDF5 中显式选取表列或数组分量，使用行身份对齐。源单位与目标单位不同时，配置必须提供带原因的仿射换算。输出保留使用了哪些源行、哪些资产以及各分区所属的组。

- **v1：**使用 `target` 描述一个标量目标。
- **v2：**使用有序 `targets` 列表，支持一个或多个目标；列表顺序就是输出数组的列顺序。
- **分组：**选择 `sample_id`、`experiment_id` 或显式 `group_id`；同一个组不得跨分区，train 和 validation 必须存在，test 可省略。
- **同文件多试样：**已有 `target_specimen` 机制核对原始表中的试样列、源行及分组，保留整份文件的来源链，详见 [GH4169 示例](../examples/gh4169_ultrasonic/README.md)。

示例 `configs/build.json` 中的任务合同还声明：预测时刻、哪些输入在该时刻已经可用、目标的物理量和单位、空间/时间范围、需要哪些上下文以及独立分组采用什么身份。已知的未来输入、标签/目标派生输入、目标字段改名充当特征、跨角色的来源重用以及用验证/测试记录拟合预处理会受到检查。缺少合同的旧配置仍可构建，任务状态标为 `legacy_unassessed`。

`declared_ready` 表示所选声明满足该任务合同；待确认输入或缺失上下文会得到 `conditional`。来源分组与角色检查不会替代实验设计对独立性的论证。

**数据构建与现有训练器的范围不同。**本例使用 v2 目标列表和 train/validation 两分区，生成的 `training-config.json` 不能直接用于现有 `train-surrogate`。公开的现有训练器仍支持原有 v1 标量目标、train/validation/test 三分区的 CPU MLP。需要复跑原有训练流程时，使用 [v1 训练数据指南](training-datasets.md) 或[原有合成训练示例](../examples/synthetic_training/README.md)。

## 协议与交接检查如何解释

`check-evaluation-protocol` 按声明的条件身份、统计组和记录数去重计数，检查角色重叠和留出轴。可选指标证据须绑定已保存文件、哈希、数值位置和单位；它不会执行模型或读取证据文件里嵌入链接所指向的模型/真实响应。本例仅检查三个合成条件和批次声明，报告中的科学主张状态为 `not_established_by_metadata`。

`check-intake-status` 保存指定检查点的评审人、依据、条件、阻碍项和证据。状态可以是 `ready`、`conditional`、`awaiting_information` 或 `not_applicable`。本例的评审人标为自动合成演示，不代表人工实验审查。报告保留 `scientific_validity: not_assessed` 和 `downstream_execution: not_started`，未选择的检查点也不会自动视为完成。

返回[项目首页](../README.md)；数据结构详见 [Schema](schema.md)，原有求解流程详见[运行指南](runbook.md)。
