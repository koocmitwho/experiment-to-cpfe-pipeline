# v0.2.0 数据基础层验证记录

本次公开数据导入、规范化、训练数据构建、任务声明和基础检查。新增演示使用自行生成的合成数据，不依赖外部实验文件、训练库或求解器。

## 本地验证

2026-09-26，在 Windows、Python 3.12 上检查发布候选：

| 环境与检查 | 结果 |
| --- | --- |
| 独立基础环境，全量测试；未安装 Torch | 686 passed，8 skipped |
| 含训练依赖的环境，全量测试 | 696 passed，2 skipped |
| 合成数据主流程 | 3 个样本、12 行；8 行 train、4 行 validation |
| 独立来源与输入可用时间 | 跨分组混用、预测时尚不可得输入均被拒绝 |
| 原有同文件多试样能力 | 来源行与试样分组回归通过 |

基础环境的跳过项来自可选训练依赖及显式启用的安装包/真实 Abaqus 检查。含训练依赖的全量测试跳过安装包检查与真实 Abaqus 检查；安装包检查另行执行。训练测试使用小型合成数据，仅检查既有标量模型行为。

全量命令为 `python -B -m pytest -q`。本次未执行真实 Abaqus 求解、材料标定或实验精度验证。

## 发布边界与审查修复

迁移按文件及其数据依赖组织。数据导入所需的原子 JSON 记录、来源摘要和 BAM 文件解析被提取为独立辅助模块；本次不增加任务编排或新的模型训练引擎。

审查期间补充并通过了以下回归：

- 数据构建允许 train/validation 两分区；现有标量训练器仍在创建输出和优化前要求 train/validation/test 三分区，避免生成不完整模型。
- BAM 合成文件按显式证据类型记录为 `input`，真实实验声明记录为 `measured`；资产、数据行与元数据来源一致。
- 缺失导入配置会留下失败记录，不能遗留一个误导性的 running 状态。
- 数据集构建保留公共版本已有的同文件多试样隔离规则。

待公开的源码、测试及示例经过来源与内容检查。此次新增内容不含课程派生网络、专用研究模型、原始实验数据、模型权重或本机运行报告。代码、文档和新增合成夹具沿用项目 Apache-2.0；既有第三方材料继续遵循各自声明。

## 复跑

```text
python -m pip install -e ".[dev]"
python -B -m pytest -q
python examples/data_foundation/workflow.py --run-dir runs/data-foundation-new
python -m build
python -m twine check --strict dist/*
```

设置 `EXP2CPFE_WHEEL_DIR=dist` 后，可单独运行 `tests/integration/test_installed_wheel.py`。该检查在仓库之外安装 wheel，使用 Python 隔离模式验证模块来源、默认校验资源、提取脚本帮助、数据集构建及新的完整合成流程。

分发文件还需通过成员清单检查，包含源码测试所需的小型夹具与脚本。具体发布提交的跨平台结果见仓库 [GitHub Actions](https://github.com/koocmitwho/experiment-to-cpfe-pipeline/actions)，发行文件见 [v0.2.0](https://github.com/koocmitwho/experiment-to-cpfe-pipeline/releases/tag/v0.2.0)。

这些检查证明所述软件行为，不证明实验真实性、统计独立性、材料物理有效性或泛化能力。
