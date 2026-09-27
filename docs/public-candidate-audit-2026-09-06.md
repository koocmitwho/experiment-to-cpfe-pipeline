# 公开候选文件审查：2026-09-06

> **Superseding note added 2026-09-27:** The repository now includes its
> Apache-2.0 `LICENSE`, current project `NOTICE` and `THIRD_PARTY_NOTICES.md`.
> This supersedes the historical statement below that the root lacked a
> project license. `pyproject.toml` includes all three license files for
> distribution. The original 2026-09-06 audit is retained as a dated snapshot;
> current capabilities and commands are documented in the v0.2.0 guides.

本记录覆盖上传候选文件和文档的审查，不是整个项目的最终发布结论。生产代码和测试
仍在并行修改；最后一次测试、构建、归档检查和候选文件扫描应由最终验收报告记录。

## 文档修订

- `README.md`：修正虚拟环境用法，区分资产登记、格式解析、离线测试和真实求解证据。
- `docs/data-modalities.md`：列出已实现接口和登记型扩展接口；记录显式 ANG/CTF 列映射、
  HDF5 dataset map、图特征契约和格式限制。
- `docs/schema.md`：说明父子哈希、转换记录、字段单位、描述元数据和容器版本标识。
- `docs/runbook.md`：补充输入绑定、原生 INCLUDE 暂存、提取单位、正式导出条件和默认
  校验策略的权威位置。根配置目录中的策略文件只是模板。
- `docs/limitations.md`：说明科学验证、适配器、内存处理和公开 CPFE 验证尚存的边界。
- `docs/release_checklist.md`：把最终验收、候选文件、构建归档和历史扫描分开列明。
- 原实现计划：删除绝对安装路径示例，移除审计对 `docs/superpowers/` 的排除，并要求
  同时检查非忽略新增文件。

没有改写以前的 `docs/verification/` 历史报告，没有更改 Git 历史或分配项目许可证。

## 实际只读检查

执行 `git ls-files --cached --others --exclude-standard` 取得候选清单，再使用
PowerShell 逐文件检查大小、扩展名、常见凭据模式和机器路径。报告只输出路径、类别
与行号，不输出可能的凭据值。检查机器路径前归一化重复转义的反斜杠，避免漏掉文档
代码块中的路径。

扫描快照包含 **107 个文件、467111 字节**（本记录创建前；并行改动后的最终候选
数量会变化）。该快照未命中：

- GitHub/AWS/OpenAI 常见令牌模式或私钥头；
- 原始 ODB/CAE、Fortran 源、检查点、HDF5/NPZ/NPY 等受限候选扩展名；
- 大于 2 MiB 的单文件；
- 机器安装路径或用户目录模式。

模式扫描不是穷尽的凭据检测，扩展名也不能独立判断数据来源和许可。小型合成样本、
测试夹具和公开来源 URL/哈希清单仍需结合内容解释。

执行 `git rev-list --all`，并通过 `git ls-tree -r --name-only` 与 `git show` 扫描
两个可达提交。没有凭据或受限文件类型命中。两个提交的原实现计划均含通用的绝对
Abaqus 安装路径示例和禁止路径规则；当前工作树已经清理这些文档字符串，但旧提交
仍保留。它们属于历史文档中的可移植性问题，未发现实际凭据。不能声称历史中已无
绝对路径，也不能用修改当前文件来表示历史内容已删除。

对本轮文档执行 `git diff --check`：通过。本轮文档审查不重新声称生产代码测试或
真实求解结果；相应证据由主验收流程记录。

## 许可、证据和下一步

根目录尚无项目级 `LICENSE`。这是所有者待定的许可选择；公开来源的 MIT/CC-BY 标签
不自动许可整个项目，也不阻止对源代码进行审查。没有擅自添加许可证。

上述文档审查没有新增 measured、inferred 或 simulated 科学数据，仅修改通用说明并读取
候选源文件。未使用本机实验案例、原始公开数据或 ODB，未启动仿真、训练、提交或推送。
假设是公开上传保留现有历史；若所有者要求连历史通用路径字符串也必须移除，需要
单独讨论历史处理方式。

最终验收需要重新扫描最后的候选清单和构建归档，运行完整离线测试与安装验证，并
在有授权和可用环境时记录小型真实求解闭环。此前审计中的发布阻塞项不能仅凭本文档
或本轮无命中扫描标为已解决。

## 后续：公开合成示例接入新契约

随后按主验收任务更新 `examples/synthetic_minimal/sample.yaml`。原配置预检得到
`ready=false`，明确报告重复元素分配、占位材料模型、非结构化边界和不支持的输出；
证明新门槛拒绝了原来的不完整例子。更新后的单元仅映射到晶粒 1，使用明确的
`isotropic_elastic`、`E=1 Pa`、`nu=0.3`，并提供约束刚体运动的初始边界以及 SMOKE
步骤内的顶部位移。输出为 S、LE、U、RF，分别声明 Pa、1、m、N，提取位置为 native。
原网格坐标与连接已一致，无需改动 `mesh.inp`。

公开示例中的所有生成值标记为 `input`，来源说明为 `synthetic`。保留的
`measured_observations` 是数据表布局名称，不将这些生成值变成实际测量。没有新增
真实 measured/inferred/simulated 证据。

使用项目虚拟环境实际执行以下命令，均返回 0；使用新目录，没有覆盖原运行：

```text
pipeline validate --config examples/synthetic_minimal/sample.yaml --run-dir runs/v1-public-example-20260906-02
pipeline build-inp --config examples/synthetic_minimal/sample.yaml --run-dir runs/v1-public-example-20260906-02
pipeline export --config examples/synthetic_minimal/sample.yaml --run-dir runs/v1-public-example-20260906-02 --format hdf5
pipeline export --config examples/synthetic_minimal/sample.yaml --run-dir runs/v1-public-example-20260906-02 --format npz
pipeline inspect --run-dir runs/v1-public-example-20260906-02
python -m pytest tests/integration/test_offline_pipeline.py tests/unit/test_pipeline.py -q
```

聚焦测试 **8 passed**。另外读取 HDF5 与 NPZ，核验 8 个资产、2 个数组、voxel
origin/spacing、原始资产到 normalized 子资产的父链接、全部 `input` 证据标签、
表记录/数组一致性和 NPZ 的 HDF5 来源哈希。没有 simulation_records。四个阶段均
completed，9 个登记产物重新计算 SHA-256 均匹配。

| 产物 | SHA-256 |
|---|---|
| run_manifest.json | `70e3929396d9418d4befcd65edfd684b36342b59f3227dd98637500fc29c1d40` |
| dataset/sample.h5 | `e4a852f30aa4bbdb25038134b00705008d704f727bcd48e4a4073c1a67316aa2` |
| dataset/sample.npz | `21834764ea65f8b454d9cf9c9d2185c2124d6ed8a84139e3273abcc89145f6ff` |

此追加步骤只使用仓库内小型合成样本，未启动求解器。它验证离线公共示例；真实
求解和完整发布审计仍由最终报告给出。本地运行目录含机器路径与运行 manifest，
通过 `runs/` 忽略规则保留在本地。

上述哈希对应当时的离线示例快照。后续真实求解发现，小应变模型应显式请求 E，
而非可能被 Abaqus 替换的 LE；完整单轴边界还应约束底面全部节点的 Z 自由度。
最终示例与真实求解报告据此修正，使用新的运行目录和 manifest。不能把这里保留的
早期快照哈希当成最终配置或最终求解证据。
