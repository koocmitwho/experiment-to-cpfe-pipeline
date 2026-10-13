# Harness MCP：Codex 与 Claude 本地接入

v0.4.0 为 harness 提供可选 stdio MCP 适配层。Python API、JSON CLI、MCP 和本地中文界面均调用同一个
`HarnessClient`，沿用 `harness.v1` 请求、响应、预算、幂等性、证据检查和人工审核规则。
计算工作流仍只有 `paramaterial_tensile.v1`；MCP 不增加训练、Abaqus、远程执行或模型服务。

本地协议测试可以完全不调用模型。将服务器配置到 Codex / Claude 与实际让模型调用工具是两步，
后者使用客户端自己的账户和模型服务。本指南给出手动配置示例，不自动修改客户端配置；本地协议检查不代表真实模型会话已通过验收。

## 1. 准备独立环境和新工作区

以下命令在 Windows PowerShell 中运行。先按 [README](../README.md#安装)取得 v0.4.0 源码。本文统一使用通用示例目录
`C:\work\experiment-to-cpfe-pipeline`；请替换为实际源码目录，并同步替换下面命令、TOML 和 JSON 中的所有绝对路径。
使用 Python 3.12 或更新的受支持版本。`mcp` 是可选依赖，不接入 MCP 时无需安装；当前约束为
`mcp>=2.3,<3`，早期本地协议验证使用 `2.3.0`。安装依赖需要本地缓存或网络，但不调用模型 API。

```powershell
Set-Location 'C:\work\experiment-to-cpfe-pipeline'
python -m venv .venv-mcp
.\.venv-mcp\Scripts\python.exe -m pip install '.[mcp]' -r examples/paramaterial_tensile/requirements.txt
.\.venv-mcp\Scripts\python.exe -I -B -m experiment_to_cpfe.cli harness init --workspace 'C:\work\experiment-to-cpfe-pipeline\runs\harness-mcp-demo' --case-dir 'C:\work\experiment-to-cpfe-pipeline\examples\paramaterial_tensile'
```

已有同名虚拟环境时可复用其解释器安装本次代码，无需重新建立环境。工作区必须选择一个尚不存在的目录；
重复演示时改用 `harness-mcp-demo-002` 等新名称。案例原件目录与计算工作区保持分离。

旧 run 冻结了输入、代码和环境身份。新增 MCP 模块或重新安装代码后，旧 run 的继续执行可能返回
`ENVIRONMENT_CHANGED`。保留旧 run 和收据，在新工作区建立新任务；不要修改旧收据或覆盖旧运行来消除差异。

`init` 是操作者命令。MCP 启动只连接一个已经初始化的工作区，不执行初始化，也不创建人工批准记录。

## 2. 服务启动方式

统一入口为：

```powershell
& 'C:\work\experiment-to-cpfe-pipeline\.venv-mcp\Scripts\python.exe' -I -B -m experiment_to_cpfe.harness.mcp --workspace 'C:\work\experiment-to-cpfe-pipeline\runs\harness-mcp-demo'
```

也可使用安装生成的 `pipeline-harness-mcp --workspace <绝对路径>`。客户端配置优先使用上面的绝对
`python.exe` 路径和模块入口，避免选中另一个环境。`-I` 使用隔离导入方式，因此必须先把项目安装到该解释器中；
仅设置 `PYTHONPATH=src` 不满足此配置。

该命令通过标准输入输出等待 MCP 消息，直接在终端启动后没有普通提示符是正常现象。交互式检查启动方式后可用
Ctrl+C 结束；正常使用时由客户端启动并管理服务器，无需额外开启终端。协议消息使用 stdout，诊断使用 stderr。
MCP 适配层仅提供 stdio，无监听端口、HTTP MCP 服务、远程连接或 MCP sampling 功能。另一个入口提供 [本地浏览器界面](harness-ui.zh-CN.md)，其 loopback HTTP 接口不是远程 MCP 端点。

## 3. Codex 配置

OpenAI 官方文档支持通过 `codex mcp add` 或 `[mcp_servers.<name>]` TOML 配置 stdio 服务。
配置形式在早期开发中依据 `codex-cli 0.146.0` 的 `mcp --help` 和 `mcp add --help` 核对；客户端升级后以所用版本的帮助与官方文档为准。
[官方 MCP 配置说明](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)

下面命令会写入 Codex 配置，供操作者决定接入时执行：

```powershell
codex mcp add cpfe-harness -- 'C:\work\experiment-to-cpfe-pipeline\.venv-mcp\Scripts\python.exe' -I -B -m experiment_to_cpfe.harness.mcp --workspace 'C:\work\experiment-to-cpfe-pipeline\runs\harness-mcp-demo'
codex mcp get cpfe-harness
```

也可将以下片段合并到用户 `~/.codex/config.toml`，或受信任项目的 `.codex/config.toml`。
两种方式选一种，保留已有配置，不重复定义同名表。TOML 单引号字符串保留 Windows 反斜杠。

```toml
[mcp_servers.cpfe-harness]
command = 'C:\work\experiment-to-cpfe-pipeline\.venv-mcp\Scripts\python.exe'
args = ['-I', '-B', '-m', 'experiment_to_cpfe.harness.mcp', '--workspace', 'C:\work\experiment-to-cpfe-pipeline\runs\harness-mcp-demo']
startup_timeout_sec = 30
tool_timeout_sec = 60
```

在新会话中用 `/mcp` 检查服务器和工具是否可见。配置记录可读并不等于握手和工具调用成功；最终还需客户端连接状态。
本项目没有提供会自动安装服务器或自动改变工具批准策略的脚本。

## 4. Claude Code 配置

Claude Code 支持本地 stdio 子进程，`--` 之后的参数传给服务器；`local` scope 仅关联当前项目。
配置形式在早期开发中依据 Claude Code `2.1.228` 的 `mcp add --help` 核对；客户端升级后以所用版本的帮助与官方文档为准。
[Claude Code 官方 MCP 文档](https://code.claude.com/docs/en/mcp)

在目标项目目录运行以下配置命令：

```powershell
Set-Location 'C:\work\experiment-to-cpfe-pipeline'
claude mcp add --transport stdio --scope local cpfe-harness -- 'C:\work\experiment-to-cpfe-pipeline\.venv-mcp\Scripts\python.exe' -I -B -m experiment_to_cpfe.harness.mcp --workspace 'C:\work\experiment-to-cpfe-pipeline\runs\harness-mcp-demo'
claude mcp get cpfe-harness
```

在 Claude Code 内用 `/mcp` 查看连接状态。若团队后续需要项目配置，可将服务写入项目根 `.mcp.json` 的
`mcpServers` 对象，并增加 `"type": "stdio"`；交互式会话可能要求确认项目信任及该服务器。
上述示例需要操作者自行执行；项目安装不会创建 `.mcp.json` 或修改用户的 `~/.claude.json`。

## 5. Claude Desktop 配置

Claude Desktop 的本地开发配置使用 `%APPDATA%\Claude\claude_desktop_config.json`。
从桌面应用的开发者设置进入 Edit Config，将下面的服务项合并进现有 `mcpServers`；保留其他服务器和设置。
JSON 中的 Windows 反斜杠必须写成 `\\`。
[MCP 官方本地连接教程](https://modelcontextprotocol.io/docs/2026-07-28/develop/connect-local-servers)

```json
{
  "mcpServers": {
    "cpfe-harness": {
      "command": "C:\\work\\experiment-to-cpfe-pipeline\\.venv-mcp\\Scripts\\python.exe",
      "args": [
        "-I", "-B", "-m", "experiment_to_cpfe.harness.mcp",
        "--workspace",
        "C:\\work\\experiment-to-cpfe-pipeline\\runs\\harness-mcp-demo"
      ]
    }
  }
}
```

保存后完全退出并重新启动 Claude Desktop，查看开发者设置中的连接状态。连接问题可检查
`%APPDATA%\Claude\logs\mcp.log` 和 `mcp-server-cpfe-harness.log`。此配置示例不构成 Desktop 实机接入验收。

这里的本地 JSON 机制不能直接用于 claude.ai 或 Cowork。Anthropic 的远程自定义连接器属于另一种连接方式，
本服务没有提供其所需的公网 HTTP 端点。组织策略也可能禁用本地 MCP；需按实际客户端状态判断可用性。
[Anthropic 连接方式说明](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp)

## 6. 工具调用与结果判读

MCP 名称采用 `harness_` 前缀，并把原工具名中的点替换为下划线。完整清单由 `tools/list` 返回；
输入字段直接沿用原 schema，不包在 `request` 子对象中，也不省略版本、请求或工作区标识。

| MCP 名称示例 | 同一业务核心工具 | 用途 |
|---|---|---|
| `harness_capabilities_get` | `capabilities.get` | 读取已注册工作流和支持范围 |
| `harness_inputs_validate` | `inputs.validate` | 核对固定案例的来源、单位与哈希 |
| `harness_task_plan` | `task.plan` | 只读计划，无 worker 启动 |
| `harness_task_create` / `harness_task_start` | `task.create` / `task.start` | 冻结任务、异步提交 |
| `harness_task_status` / `harness_reports_get` | `task.status` / `reports.get` | 查看状态与分层验收 |
| `harness_runs_list` | `runs.list` | 列出工作区内的任务（不探测 worker、不复核证据） |

例如，调用 `harness_task_plan` 的 arguments 为：

```json
{
  "schema_version": "harness.v1",
  "request_id": "mcp-plan-1",
  "workspace_id": "local",
  "workflow_id": "paramaterial_tensile.v1"
}
```

`workspace_id` 是固定的逻辑标识 `local`，不是一个允许模型更换目录的路径参数。实际工作区由服务启动参数绑定。
适配层公开原有工具；`init` 和操作者 `approve` 均不在工具清单内。`handoffs.submit` 仍要求已经存在的
精确人工批准记录，不能自己批准科研结果。

工具调用返回完整 `harness.v1` 外壳：`schema_version`、`request_id`、`ok`、`data`、`error`。
MCP `structuredContent` 和文本内容承载同一响应，`isError` 随 `ok=false` 置为真；业务错误保留原稳定错误码。
MCP 输出 schema 在原响应 schema 根节点补充 `type: object`，保留原 `$defs` 和 `oneOf` 分支。

收到 `task.start` 成功响应只表示调用被接受。继续查询 `task.status`，再读取 `reports.get`：
`queued` 不等于已完成，`completed` 不等于科学指标通过。检查 `overall_acceptance` 及工程、数据、数值和科学层的实际结论。
幂等键与 `expected_state_version` 规则没有改变；出现冲突时先读取状态，不用新键盲目补交计算。

MCP 请求取消与业务任务取消是不同操作；需要主动取消计算时，仍须调用 `task.control` 的 `cancel`。
但关闭、重启或崩溃退出 MCP 客户端可能终止仍在运行的 worker，不能据此假设计算会在后台继续。
早期 Windows 本地测试中，MCP SDK 2.3 stdio 客户端会把服务器及其后代放入带 `KILL_ON_CLOSE` 的
Windows Job；客户端关闭该 Job 时，即使服务器自身正常退出，在途 worker 也会被终止。
其他宿主的进程管理行为需分别验证。本实现尊重宿主 Job 的生命周期约束，不尝试从中脱离。

因此，从 `task.start` 提交后应保持 MCP 连接，直到任务进入 `completed`、`failed`、`cancelled` 或
`interrupted` 等终止状态；暂停和等待人工审核应按相应控制流程处理。若连接意外关闭，重新连接同一工作区后先调用
`task.status` 读取状态，再显式调用 `task.reconcile` 保守核对原任务。保留旧 attempt 和故障证据，
不能把 `interrupted` 当作 `accepted`，也不能自动补交或重算不确定的任务。

让 worker 完全独立于客户端生命周期需要额外的常驻任务服务（broker），不在 v0.4.0 的轻量 stdio 适配范围内。

## 7. 无模型验证与常见问题

开发验证需在同一虚拟环境安装 `dev`、`mcp` 两组可选依赖及固定案例依赖，随后运行本地测试：

```powershell
.\.venv-mcp\Scripts\python.exe -m pip install '.[dev,mcp]' -r examples/paramaterial_tensile/requirements.txt
.\.venv-mcp\Scripts\python.exe -B -m pytest -q examples/harness/tests
.\.venv-mcp\Scripts\python.exe -B -m pytest -q tests
```

独立 MCP 端到端验收脚本还会将请求、响应和案例证据写入指定的新目录。该命令使用已经安装的包，
输出目录必须为尚不存在的绝对路径，每次复验换用新目录，不覆盖旧证据：

```powershell
.\.venv-mcp\Scripts\python.exe -I -B examples/harness/tests/test_harness_mcp_e2e.py --output-dir 'C:\work\experiment-to-cpfe-pipeline\runs\harness-mcp-e2e-001'
```

本地 MCP 验证使用协议客户端直接启动服务器、发现 schema、调用工具并检查响应，不需要模型账户或 API key。
本地协议往返、真实 Paramaterial 案例、Codex/Claude 内的实际模型调用是不同证据，不能相互替代。
当前发布的执行结果与验证范围见 [v0.4.0 发布验证记录](verification/2026-10-13-harness-release.md)；本指南不将配置示例视为客户端已接入。

| 现象 | 检查方法 |
|---|---|
| 缺少 `mcp` 包 | 用配置中的同一个 `python.exe` 安装 `.[mcp]`；基本库安装不自动引入它。 |
| `No module named experiment_to_cpfe` | 确认项目已安装到该解释器；`-I` 不采用当前目录或 `PYTHONPATH` 作为源码导入补丁。 |
| 工作区无法打开 | 确认 `--workspace` 为绝对路径，且已经由操作者 `harness init` 初始化；勿指向案例原件目录。 |
| 启动后终端无输出 | stdio 服务在等协议输入；使用客户端连接，不把人用 JSON CLI 请求直接当作 MCP 消息发送。 |
| `ENVIRONMENT_CHANGED` | 保留旧运行，使用当前环境初始化新的工作区，不篡改已有身份记录。 |
| 客户端关闭后任务中断 | 重连同一工作区，先 `task.status`，再显式 `task.reconcile`；保留 `interrupted` 和旧证据，不自动重算。后续提交保持连接到任务终止。 |
| 请求被拒绝 | 按 `tools/list` 的 schema 提交原字段，查看 `error.code` 与 `required_action`，不降低科学阈值或改原始文件。 |
| Desktop 工具不可见 | 检查 JSON 语法、绝对路径、重新启动后的连接日志及组织策略。 |

原有固定案例、资源预算、Windows worker、受控产物和科学验收限制见
[harness 本地接入指南](harness.zh-CN.md)。MCP 是调用入口，不能替代操作系统权限隔离；拥有同一账户任意 shell 或
文件写权限的客户端仍可绕开接口约束。harness 不提供自动清理、提交、推送、发布或修改科学参数的工具。
