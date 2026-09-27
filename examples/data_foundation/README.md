# 数据基础层示例

本例生成 3 个合成试样、12 行数据，依次运行实验文件导入、普通 CSV 规范化、训练数据构建、评价协议检查和交接状态检查，使用基础 Python 安装即可运行。

在仓库根目录、Python 3.12+ 环境中执行：

```text
python -m pip install -e .
python examples/data_foundation/workflow.py --run-dir runs/data-foundation-001
```

每次选择新的输出目录；脚本拒绝复用已有结果目录。

主要输出：

- `imports/<specimen>/sample.h5`：三个规范化样本及对应的实验上下文。
- `normalized/sample.h5`：单独演示 CSV 规范化的样本。
- `dataset/dataset.npz`、`dataset/dataset.json`、`dataset/training-config.json`：具名目标数组、来源与配置。
- `protocol/evaluation-protocol.json`、`intake/intake-status.json`：协议和交接报告。
- `verification.json`：最终软件检查摘要。

特征与目标均为 `(12, 1)`。前两个试样的 8 行属于 train，第三个试样的 4 行属于 validation。本例检查未知表头保留、HDF5 读回，以及未来输入和跨分区分组被拒绝。力由公开在脚本中的代数公式生成，结果属于软件行为演示。

本例使用 v2 目标列表和 train/validation 两分区，输出的 `training-config.json` 记录数据声明。标量 MLP 训练使用 v1 目标声明和 train/validation/test 三分区配置，见[合成训练示例](../synthetic_training/README.md)。

逐步 CLI 命令、输出目录和字段解释见[数据基础层指南](../../docs/data-foundation.md)。源代码见 [workflow.py](workflow.py)。代码与合成数据使用 [Apache-2.0](../../LICENSE)。
