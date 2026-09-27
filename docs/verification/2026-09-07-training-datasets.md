# 通用训练数据层本地验证

2026-09-07，Windows、Python 3.12.10、PyTorch 2.8.0+cpu，使用项目 `.venv`。

本次新增配置驱动的训练集构建入口。表列和数组分量按显式身份对齐，保留来源、
单位和转换记录，然后交给原有标量回归 MLP。旧训练配置和四数组 NPZ 仍可使用。

## 验证结果

| 检查 | 结果 |
| --- | --- |
| 完整离线回归（复核修复后） | 535 passed，2 skipped，28.02 s |
| 候选 wheel 在源码目录外安装 | 1 passed，3.38 s |
| wheel 与 sdist 构建 | 通过，wheel 从本次 sdist 构建 |
| `twine check --strict` | 两个产物通过 |
| 项目环境 `pip check` | 无依赖冲突 |

全量测试中的两项跳过分别是 opt-in Abaqus 和需要候选 wheel 的安装测试。
后者已在构建完成后单独启用。安装检查使用新的目标目录，在 `python -I` 进程中
核对模块来自候选包，并完成 validate、提取脚本帮助与训练集构建。

新增行为按 TDD 实施。最初 34 项数据构建测试因入口缺失失败，之后补充命令、
数据内容与语义错配、配置类型、原生数组声明和现有 ODB 表的测试。
测试实际运行读取、对齐、转换、分组检查及 CPU 优化。

后续复核补充了 7 个回归用例，修复四处问题：同一来源有无摘要混用时漏检跨划分，
新包丢失格式标记后跳过语义校验，旧完整 NPZ 被误拒绝，以及更名表列无法显式绑定
原单位键。修复后的针对性测试为 73 passed，两条独立审查均确认原问题已解决。
表列既有单位和 ODB field 单位仍参与核对。

## 两套合成数据

`examples/synthetic_training/prepare.py` 生成两个独立集合。每个集合四个样本，
每个样本 31 行，按 2/1/1 个案例分为 train/validation/test。输入来自合成公式
`y = x * gain`，以 `input` 记录来源。

| 输入布局 | 特征 / 目标 | 测试 RMSE | 测试 NRMSE | 均值基线 RMSE |
| --- | --- | ---: | ---: | ---: |
| 规范化表 | extension、stiffness / force | 0.061595 N | 3.623% | 0.516613 N |
| `[channel, row]` 数组，目标倒序 | phase、gain / amplitude | 0.061595 V | 3.623% | 0.516613 V |

两套数据的数值关系相同，分别检查字段、单位换算和布局处理，因此误差相同。
表的 force 从 kN 转 N，数组通过身份把倒序目标重新对齐。训练设置为 CPU 单线程、
seed=17、最多 800 epoch、patience=300，使用既有的两层 32 单元 tanh MLP。
validation MSE 选择第 44 个 epoch 的 checkpoint。标准化训练损失从 1.00546 降至
最后记录的 0.000367，读回模型与保存预测的最大绝对差为 0。

## 兼容性与检查范围

构建测试覆盖同一集合混用布局、原生数组 entity 轴和分量单位、表上游换算单位、
现有 ODB 提取表的显式资产绑定，以及字段错配、重复身份、选行越界、缺失单位、
非有限值、同组跨划分和目标来源跨划分。

新训练包中的字段顺序、单位、数据或元数据变化会在训练前核对。数据记录沿用
SamplePackage 元数据和资产链，训练结果保存所用数据及配置的收据。

既有 CuSn8Ni2 训练包的 729 行、9 个训练/验证/测试案例、0–0.8% 应变范围及
H_08/H_16/H_18 分工通过只读检查。案例脚本、已有模型和求解结果未修改，也未重跑。

目标来源检查目前以根来源文件为单位。同一原始文件内的多个独立试样仍需放在
同一划分。插值、聚合和配准由上游处理并记录定义，训练构建器接收处理后的标量列。

`.github/workflows/tests.yml` 新增 Ubuntu CPU 训练 job，显式安装并检查 CPU torch，
执行数据构建、优化和 checkpoint 读回测试。本页记录本地结果，远端结果见对应提交的
[Actions 运行](https://github.com/17636365690/experiment-to-cpfe-pipeline/actions/workflows/tests.yml)。

## 本地记录

初次实现的输出放在忽略目录 `runs/training-data-20260907/`：`offline-tests.log`、
`build.log`、`installed-wheel.log`、`acceptance.json`，以及两个示例的输入、数据集和模型。
复核后的完整回归、构建与安装日志保存在该目录的 `review-1/`，原始审查意见和
修复复核结论见 `review-1/review.md`。上表使用复核后的验证结果，合成误差表引用
初次验收的模型记录。本轮没有改动优化过程。
本地构建保留当前项目版本号 0.1.0，产物仅用于安装验证，未替换已发布的 Release 附件。

使用配置和命令见[训练数据指南](../training-datasets.md)。


## Account-link note — 2026-09-27

The account links above use the historical repository owner name. The current repository is https://github.com/koocmitwho/experiment-to-cpfe-pipeline.
