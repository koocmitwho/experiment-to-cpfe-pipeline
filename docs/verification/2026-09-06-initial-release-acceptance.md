# 初版发布验收：2026-09-06

初版的已声明支持范围通过本机验收：离线多模态输入、实际 INP 契约检查、单样本
Abaqus 求解、真实 ODB 提取、HDF5/NPZ 和可选 PyG 导出。这里的“初版”不意味着
所有厂商二进制、任意 Abaqus 模型或自动材料校准已经实现。具体边界见
[limitations](../limitations.md)。GitHub 目标沿用 CPData 的账户
`17636365690/experiment-to-cpfe-pipeline`，不另建账户或重复仓库。

## 1. 修改文件与实现范围

本次工作区基准为 `909fa2fca9f651c77176008341fd64abd34b38dc`。此前阶段报告保留原始
测试数和哈希；本报告给出收尾后的验收结果，不追改历史证据。

| 阶段 | 主要文件 | 初版验收内容 |
|---|---|---|
| 1 包与测试环境 | pyproject.toml、_resources、py.typed、tests、CI | 包内资源、离开源码目录的 wheel 安装；Windows/Linux CI |
| 2–3 Asset 与 SamplePackage | assets/models.py、registry.py、schema/io.py | 九种模态、四类证据、父资产、逻辑载荷与文件哈希区分 |
| 4 通用表格 | adapters/tabular.py、test_tabular_semantic_gates.py、test_tabular_lineage.py | CSV/TXT/JSON、逐字段单位、逐行来源、转换与损失记录 |
| 5 EBSD/HDF5 | adapters/ebsd.py、hdf5_layout.py | 显式 ANG/CTF/text 列映射、显式 HDF5 layout；不猜厂商布局 |
| 6–7 空间场与体素 | adapters/fields.py、voxel.py、vti.py | 点坐标、单位、origin/spacing/axis/dtype/shape；标量 ASCII VTI 子集 |
| 8–9 配准检查与 Readiness | schema/validation.py、solver_contract.py | ID、单位、坐标、时间、实际网格/材料/加载/输出语义；不完整则阻断 |
| 10–11 INP 与分阶段执行 | solvers/abaqus/inp.py、bundle.py、runner.py、provenance/binding.py | 模板/原生 INCLUDE、传递依赖哈希、ASCII 临时执行、产物归档、进程超时 |
| 12 ODB 提取 | _resources/abaqus_extract_odb.py、field_contract.py、solvers/abaqus/extraction.py | Abaqus Python、字段身份/分量/位置、缺失项、单位；无静默填零 |
| 13–14 标准与派生包 | datasets/hdf5.py、package.py | 标记化 HDF5、Unicode/空数组往返、NPZ、真实 PyG Data、哈希绑定 |
| 15–16 回归与集成 | tests/unit、tests/integration | 多模态离线、安装后资源、单 CPU 真实求解全链路 |
| 17 发布审计 | docs、.github/workflows/tests.yml | 当前文件/归档/历史分别审查；只上传通用代码和小型合成素材 |

`pipeline.py` 和 `cli.py` 集成上述阶段。README、schema、runbook、data-modalities、
limitations 与 release_checklist 区分原始格式登记、真正解析和可执行 solver profile。
旧 `minimal_abaqus.inp` 明确标为静态关键字检查夹具，不声称可求解。

## 2. 实际执行的验收命令

以下 `python` 均指项目 `.venv` 的 Python 3.12；CLI smoke 使用同一环境的
`pipeline` 可执行文件。各次运行使用新目录，未覆盖已有求解和报告。

```text
python -m pytest -q
python -m build --outdir runs/release-20260906/final-dist
python -m pip check
python -m pytest -q tests/integration/test_installed_wheel.py
python -m pytest -q tests/integration/test_abaqus_optional.py
git diff --check
git ls-files --cached --others --exclude-standard
git log --oneline
git remote -v
git config user.name
git config user.email
gh run list --limit 3 --json databaseId,headSha,conclusion,status,url
```

安装测试显式设置 `EXP2CPFE_WHEEL_DIR=runs/release-20260906/final-dist`。真实集成测试
显式设置 `EXP2CPFE_RUN_ABAQUS=1`，并指定本地 `real-elastic.json` 与全新
`real-elastic-run`；两者位于忽略的 `runs/release-20260906/`。配置以公开合成例子为
基础，只显式提供本机命令、ASCII scratch 和 180 秒阶段超时。Abaqus 环境命令覆盖
在此次测试中清除，由配置提供命令。没有批处理或多样本搜索。

实际离线 CLI 调用：

```text
pipeline validate --config examples/synthetic_minimal/sample.yaml --run-dir runs/release-20260906/offline-cli
pipeline build-inp --config examples/synthetic_minimal/sample.yaml --run-dir runs/release-20260906/offline-cli
pipeline export --config examples/synthetic_minimal/sample.yaml --run-dir runs/release-20260906/offline-cli --format hdf5
pipeline export --config examples/synthetic_minimal/sample.yaml --run-dir runs/release-20260906/offline-cli --format npz
pipeline inspect --run-dir runs/release-20260906/offline-cli
```

原生 UMAT 测试另执行 validate → stage-input-bundle → build-inp → datacheck →
analysis → extract-odb → HDF5 → NPZ。独立读取两个真实 HDF5，检查末帧解析解、
STATEV，并重新计算 manifest 登记的全部产物哈希。

## 3. 测试结果

- 最终全套：**371 passed，2 skipped，21.40 秒**。两个跳过项为需显式启用的安装
  wheel 和真实 Abaqus 测试；随后分别启用，两项均通过。PyG 可选依赖已安装，
  图导出测试实际执行，不是跳过后推断通过。
- 最终 wheel 安装测试：**1 passed，3.34 秒**。在源码目录之外安装并导入 wheel，
  检查默认 policy 和提取脚本均来自已安装包。
- 最终真实全链路测试：**1 passed，77.37 秒**；验证七个阶段收据、ODB 不被提取
  修改、字段与单位、HDF5/NPZ 一致性和全部产物哈希。
- 独立离线 CLI：五条命令均返回 0，inspect 显示四个完成阶段。
- 构建生成一个 wheel 和一个 sdist；`pip check` 无依赖冲突；`git diff --check`
  无空白错误。

修复先有失败测试：提取命令/超时和示例回归 7 项，发布 CI/元数据 2 项，模板失败
收据 2 项，表格单位/证据 13 项，表格转换 lineage 8 项，可选真实测试 harness
7 项，均经历 red → green。此前空间适配器、原生 bundle、场契约等测试见同目录
历史阶段记录及新测试文件。

## 4. 真实求解结果与产物

环境使用 Abaqus 2025、已验证的 Intel ifx/Visual Studio 工具链。命令与工具链路径
只留在本地配置，不写入核心代码或公开配置模板。

| 本地合成测试 | 网格/材料 | 已验证结果 |
|---|---|---|
| 最终弹性闭环 | 8 节点、1 个 C3D8，E=1 Pa、nu=0.3、边长 1 m，顶面 Z 位移 0.001 m | 1,008 条 S/E/U/RF 记录；末帧八积分点 S33 与 E33 均为 0.0010000000474974513 |
| 原生 INCLUDE + UMAT | 同尺寸，自编线弹性 UMAT，显式四元数 STATEV 1–4 | 1,232 条记录；编译/链接分别完成；S33/E33 同上，SDV1=1，SDV2–4=0 与初始输入逐项一致 |

解析解比较使用 `rtol=1e-7, atol=1e-12`。UMAT 是接口与状态变量传递测试，不是
晶体塑性本构实现或材料校准。STATEV 的零值来自真实 ODB 中的明确初始状态，
不是为缺失字段补零。

早期尝试请求小应变模型的 LE，Abaqus 在 DAT 中提示改为 E；提取正确报缺失 LE。
另一次只约束三个底角，解析均匀应变假设不成立。最终版本请求 E，并约束全部底面
节点的 Z 自由度。早期失败证据保留，未用最终结果覆盖。

## 5. Manifest 和 SHA-256

每个初始化运行均包含四个规定报告：run_manifest.json、validation.json、
solver_readiness.json、qa_report.md。以下只是可公开的合成结果指纹；完整本机
manifest、ODB、HDF5、NPZ 和 scratch 保留在被忽略的 runs 目录。

| 产物 | SHA-256 |
|---|---|
| 最终弹性 run_manifest.json | `435da87dbeb029a188539bca498f61ec95b6ab5f95485ec1e537149231cdaf1b` |
| 最终弹性 ODB | `02f46bd894b32f6f5c9f59930a9e929fc3fa46a2a765a8f0a7f8ef386015d06e` |
| 最终弹性 HDF5 | `bc13b6c64d7658954bc61627ec15b7aa6813124371791a2b6188c9c942ea9c7b` |
| 最终弹性 NPZ | `4783b714676299a5766414e27aa6475cd01d4f09e6acaa6ddfa66404d03e1cdb` |
| 原生 UMAT run_manifest.json | `cb8c006d43ef01b25127ea9f81653b36dca44b9f7858eddf396378921d3772d4` |
| 原生 UMAT ODB | `0b970fa523fb41a933679198e22cdb8bba11878568b3103c966c84bb9581a178` |
| 原生 UMAT HDF5 | `582596619f4da09f74e8bd97055116f4b473144b45bfbd74ae22b1b234d080df` |
| 原生 UMAT NPZ | `868f85ad011663ff4698f2e604b7fbe857e1c49df904d3dc978ed551fb0ff244` |
| experiment_to_cpfe-0.1.0-py3-none-any.whl | `2eca6f3ba32eeaba7ec165dcc6056eaf3c0305526961a9fcf4de2d4d15fa3008` |
| experiment_to_cpfe-0.1.0.tar.gz | `8b425986206530b5aafa6328d847323d0893c699fc791a51cd119e5f81f47cf9` |

wheel 为 74,215 字节、47 个文件；sdist 为 60,730 字节、52 个文件。归档已检查
field_contract、solver_contract、VTI、py.typed、policy 和提取脚本的实际存在，
没有把过时 dist 中的早期构建当作发布产物。

## 6. 仍存在的限制

当前严格检查的是平面命名空间下的三维实体网格、单材料、单静态位移加载步，
以及显式 UMAT STATEV 取向初始化。PBC/equations、assembly、更多本构和加载
语义、自动空间/时间配准、网格生成、图像相关、完整厂商二进制解析、任意 DAMASK
结果语义仍需专门适配器；不支持的求解 profile 会阻断。不会用实验曲线补齐这些输入。

提取覆盖所请求的场输出，不自动生成全部 history/homogenization 结果。容器、图
导出和若干适配器为内存式；大规模数据、分布式调度、训练不属于本初版。

## 7. measured / inferred / input / simulated

公开生成的曲线、微结构、DIC、voxel、网格及边界/材料参数均为 `input`，不是
`measured`。两个真实 ODB 与提取结果为 `simulated`。本轮没有新增真实测量或由
测量推断的材料参数。测试目录中的 fake_solver 和模拟字段 fixture 只是明确标记的
测试替身，不计入真实求解证据。转换保持来源类别，不因导出到 /simulation 而改变证据。

## 8. 本地案例与公开数据

本轮求解只使用小型新构造的合成输入；本机历史私人实验/材料案例未作为核心代码
依赖。公开 NTNU 的 URL、固定版本、哈希和来源说明保留为可选测试入口，其下载
文件不上传。NTNU 的物理单位尚未全部确认，且周期方程超出当前 profile，仍不能
宣称完成了该公开晶体塑性基准。未将其他公开实验材料曲线与它混合充当验证标签。

## 9. 假设与公共仓库审计

物理参数、取向状态、单位和边界均是本合成测试的显式声明；没有从未说明的文件
猜测。初版采用当前已授权的现有 GitHub 账户与远程，保留配置好的 Git 作者身份。

最终源码候选和两个构建归档扫描未发现原始实验、ODB/CAE、UMAT 源、检查点、
常见凭据或本机安装路径。唯一宽泛绝对路径命中是故意测试路径拒绝的
`tests/unit/test_input_bundle.py`，已人工核验。CSV/INP/JSON 候选分别确认是微型
合成输入、模板或公开来源说明。完整候选逐文件哈希记录在本地 public-audit.json。

可达的两个旧提交另行检查，无凭据；旧计划中存在通用安装路径示例，当前文档已
去除，但没有重写历史，也不声称历史字符串已被删除。机器运行配置与私有 manifest
一直排除在候选之外。审查发现和修复见 [双轴审查记录](2026-09-06-final-code-review.md)。

项目许可证未由所有者指定，因此不添加 LICENSE、不套用外部数据源的 MIT 标签，
也不宣称已授予整个项目的开源许可。源码可以按本次授权上传；PyPI 发布、标签和
GitHub Release 不属于本次操作。

## 10. 交付与下一阶段

本报告记录上传前验收；最终 Git 提交及该提交的远程 Windows/Linux CI 结果在
交付消息中单独给出。CI 每次 push/PR 重跑离线测试、构建和 wheel 安装验证。

下一轮应先为一个物理单位与许可完整的公开 CPFE 输入增加其专用 profile，再做
有独立实验目标的验证；不要把接口 smoke test 升格为材料科学验证。当前无需继续
扩展这些未声明的能力即可交付已验证的初版代码。


## Account-link note — 2026-09-27

The account links above use the historical repository owner name. The current repository is https://github.com/koocmitwho/experiment-to-cpfe-pipeline.
