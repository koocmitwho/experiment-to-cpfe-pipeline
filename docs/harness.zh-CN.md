# 材料科研 harness：本地接入指南

v0.4.0 的 harness 支持固定 `paramaterial_tensile.v1`：三个 AA6061-T651 试样、1889 行公开工程曲线。它包装已有案例，不改变 Paramaterial 算法、参考值或 `1e-7` 数值容差。原有 `pipeline validate`、规范化、训练和求解入口仍独立可用。

任务服务提供 Python API、JSON CLI、可选 stdio MCP 和本地中文浏览器界面，均复用同一业务核心。Codex、Claude Code 与 Claude Desktop 的配置见 [MCP 中文指南](harness-mcp.zh-CN.md)，界面启动与使用见 [本地任务界面指南](harness-ui.zh-CN.md)。真实模型、Abaqus、训练、远程执行和检查点续算尚未在此 harness 中验证或开放。案例运行无外部 API；新环境安装依赖需要本地缓存或网络。

## 安装与工作区

按 [README](../README.md#安装)取得含示例的 v0.4.0 源码，使用 Python 3.12 建立独立环境，安装本项目和 `examples/paramaterial_tensile/requirements.txt`。wheel 包含库、CLI、harness 入口和界面静态资源，案例文件仍从对应源码包取得。以下命令从仓库根目录运行。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install . -r examples/paramaterial_tensile/requirements.txt
.\.venv\Scripts\python.exe -m experiment_to_cpfe.cli harness init --workspace runs/harness-demo --case-dir examples/paramaterial_tensile
.\.venv\Scripts\python.exe -m experiment_to_cpfe.cli harness tools list --json
```

`init` 是操作者命令，不在 agent 工具列表中。注册案例目录与计算工作区必须分离。现有工作区不能覆盖初始化。默认上限：CPU 1、并发 1、GPU/模型调用 0、活跃墙钟 600 秒、输出 1 GiB、重试一次；agent 可以降低所请求预算，不能提高授权上限。
其中“并发 1”是 worker 的固定实现（同一工作区同时只有一个 attempt 处于 running），`workspace.json` 的 `max_concurrency` 只是记录，修改它不会改变并发；CLI `init` 目前也不提供修改上限的参数。

## 人用 CLI

```powershell
'{"schema_version":"harness.v1","request_id":"plan-1","workspace_id":"local","workflow_id":"paramaterial_tensile.v1"}' | .\.venv\Scripts\python.exe -m experiment_to_cpfe.cli harness call task.plan --workspace runs/harness-demo --request-json -
'{"schema_version":"harness.v1","request_id":"create-1","workspace_id":"local","idempotency_key":"my-case-1","workflow_id":"paramaterial_tensile.v1"}' | .\.venv\Scripts\python.exe -m experiment_to_cpfe.cli harness call task.create --workspace runs/harness-demo --request-json -
```

从创建响应读取 `run_id` 和 `state_version`，按 `task.start` schema 构造请求。提交立即返回 `task_id/run_id/attempt_id`，随后用 `task.status`、`events.list`、`artifacts.list` 和 `reports.get` 读取状态。命令输出为 JSON；错误也有稳定外壳，不向工具调用者返回 traceback。

`runs.list` 按创建时间倒序列出工作区内的 run（分页，含状态、状态版本、attempt 数和已记录的验收状态），不探测 worker、不复核证据；判断结论仍以 `task.status` 和 `reports.get` 为准。`task.create` 的返回含 `deduplicated`：为 `true` 表示输入、代码、环境、预算、审核要求、协议与授权策略等冻结内容完全相同，返回的是已有冻结任务而非新建；需要第二次独立复现时使用 `replicate=true`。`inputs.register` 只登记文件引用，当前不影响计划、执行或验收。

工具的退出码只描述调用是否被接受。`queued` 不代表完成，`completed` 不代表科学指标通过。最终检查 `overall_acceptance` 和各层证据。

## 无模型自动客户端

Python 调用与 CLI 使用同一个业务核心，例如：

```python
from experiment_to_cpfe.harness import HarnessClient

client = HarnessClient('runs/harness-demo')
base = {'schema_version': 'harness.v1', 'workspace_id': 'local', 'request_id': 'example-1'}
created = client.call('task.create', {
    **base, 'idempotency_key': 'python-case-1', 'workflow_id': 'paramaterial_tensile.v1'
})
if not created['ok']:
    raise RuntimeError(created['error']['code'])
run = created['data']
if run['execution_status'] == 'ready':
    started = client.call('task.start', {
        **base, 'idempotency_key': 'python-case-1:start',
        'run_id': run['run_id'], 'expected_state_version': run['state_version']
    })
    print(started)
```

完整自动客户端会按返回状态继续查询，而不是把提交成功当成计算完成。

```powershell
.\.venv\Scripts\python.exe -B examples/harness/contract_client.py --workspace runs/harness-demo --idempotency-key automatic-case-1
```

该客户端先发现工具，再经公开工具完成预检、计划、创建、提交、状态轮询和报告读取。没有私有函数调用、数据库改状态或模型服务。输出 `client_kind=no_model_contract_client`；它只能证明接口可用，不是真实 agent 验收。

同一幂等键与相同请求返回原任务；同键不同请求被拒绝。等价任务即使用新键也会去重。要做第二次真实复现实验，明确添加 `--replicate`。客户端超时不会伪报计算已经失败，也不会自动重试科研计算。

## 状态与恢复

当前 worker 的进程树包含与崩溃恢复仅完成 Windows 实机验证；Linux/macOS
启动工具明确返回 unsupported。数据处理核心和原来的跨平台 CLI 不受此限制。

task 是逻辑目标，run 固定输入/代码/环境/协议/预算，stage 是阶段，attempt 是一次执行。每次重试分配新目录，旧失败目录保留。第一版案例内部三试样循环没有独立检查点。

- 暂停只支持阶段边界；运行中先 `pause_requested`，计算未停稳不会称为 paused。
- 取消针对本次拥有的进程树，确认停止后才称 cancelled。
- 普通本地 CLI 退出后的后台查询已验证。MCP 客户端关闭或重启可能通过 Windows Job 终止在途 worker；使用 MCP 时保持连接到任务终止，具体边界见 [MCP 指南](harness-mcp.zh-CN.md)。worker 消失后先查询状态，再显式调用 `task.reconcile` 核对，不凭心跳丢失补交。
- 整案中断没有检查点续算；明确返回 `CHECKPOINT_UNSUPPORTED`。允许重试时用新 attempt 整案重跑。
- 输入、源代码、依赖、协议或授权策略变化会阻止旧 run 继续使用；不要修改旧收据使其重新匹配。
- 上游产物篡改在读回/复用前拒绝；文件存在不是完整性证明。

预算按整个 run 累计，重试不会补充墙钟时间。存储为预留条件及轮询检查，不是文件系统硬配额；CPU 限制为继承 affinity/线程上限，不是 CPU 时间计费。无法支持的资源/平台保证必须视为未支持。

## 人工接管

创建时 `require_review=true` 可要求固定阶段边界的人工作业审核。计算停稳后产生 handoff，工具只能查询和提交证据；不能自行批准。操作者检查已登记产物，使用 `harness approve --handoff-id ... --evidence-id ... --reviewer ... --basis ...`，然后将返回的 `approval_id` 连同精确 attempt 与证据提交给 `handoffs.submit`。服务再次核验输入和产物后才继续。

这里是对固定结果的审核，不是修改材料参数的授权。材料、单位解释、划分或阈值的实质变化需另建任务修订；本版 agent 没有修改这些内容的工具。

## 产物与安全边界

ODB/HDF5 不直接放入模型上下文。产物使用 ID、摘要、大小、来源 attempt 和验收状态；HDF5 只允许已登记数值字段切片。每次最多 500 行和 256 KiB；JSON 文件解析另有 4 MiB 上限。拒绝目录穿越、链接逃逸、HDF5 外链/VDS/外部存储。

固定来源 CSV、案例算法及参考表只有读取操作。半成品不会登记为已验收结果。失败证据与原运行保留，不提供自动清理工具。

工具权限不是操作系统沙箱。操作者配置、数据库和批准命令必须不在 agent 任意 shell/文件写权限范围内；同一账户持有这些权限可以绕过任何 Python 接口。受控文本视图忠实返回已登记内容，文件中的本地路径可能保留；对外分享前应审阅。错误外壳不会回显原始异常或环境变量。

## 科研验收边界

工程执行、数据身份/单位/来源、数值一致性、科学主张分别报告。本案例的九指标与独立复算一致不等于作者实验真值、材料标定或跨材料泛化。

现有 `check-evaluation-protocol` 返回 0 表示报告完成，指标 `not_met` 与 holdout `not_verified` 仍可能存在。harness 的报告解释器保留实际判定；无阈值是 not_requested，不能默认达标。

后续训练默认选 external_test，测试真值与训练/模型选择隔离；现有训练功能不在首版 harness 注册表中。Abaqus 待真实软件、许可、输入及各阶段验收获准后单独接入。真实 Codex/Claude 调用也需另行批准模型与费用。

## 验证与依赖边界

旧基础测试仍用 `python -m pytest -q tests`，不引入 Paramaterial 依赖。
安装案例单列依赖后，在 Windows 运行 `python -m pytest -q examples/harness/tests`，
覆盖新工具、真实三试样、故障恢复、MCP 和 HTTP 适配。CI 配置在原有 Paramaterial Windows job 中显式执行该套件；
具体结果见 [v0.4.0 发布验证记录](verification/2026-10-13-harness-release.md)和对应提交的 CI。不能把 Linux 未执行 worker 验证描述成跨平台通过，HTTP/静态检查也不能替代真实浏览器或模型客户端验收。
