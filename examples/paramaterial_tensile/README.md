# 三个公开拉伸试样：从 CSV 到可核对结果

简体中文 | [English](README.en.md)

本例处理 AA6061-T651 铝合金在 **20°C、A 批次**下的三个单轴拉伸试样。源码包已附带三条 CC BY 4.0 工程应力—应变曲线，共 1,889 行；不需要另外下载数据、训练模型或启动 Abaqus。

一次运行会按作者方法计算抗拉强度、弹性模量和 0.2% 规定塑性延伸强度，再通过已安装的公开流水线规范化为 HDF5、读回并重算，核对流转是否改变结果。

## 安装并运行

这个固定案例使用 **Python 3.12** 和独立环境。取得本项目 v0.3.1 源码后，在含 `pyproject.toml` 的目录执行：

```text
python -m venv .venv
```

Windows PowerShell：

```powershell
.\.venv\Scripts\python.exe -m pip install . -r examples/paramaterial_tensile/requirements.txt
.\.venv\Scripts\python.exe -B examples/paramaterial_tensile/workflow.py --run-dir runs/paramaterial-001
```

Linux/macOS 命令写法：

```bash
.venv/bin/python -m pip install . -r examples/paramaterial_tensile/requirements.txt
.venv/bin/python -B examples/paramaterial_tensile/workflow.py --run-dir runs/paramaterial-001
```

Windows/Linux 是本例的发布验收平台；macOS 未完成端到端验收。已安装 wheel 时也可直接使用源码包中的案例目录，入口不从仓库 `src/` 注入模块。`run.json` 记录实际加载的公开包版本及位置。

下一次改用新的 `--run-dir`。已有目录会被拒绝，原始 CSV 保持不变。运行依赖单列在 [requirements.txt](requirements.txt)，不增加主库的基础依赖。

## 看哪些文件

| 输出 | 内容 |
|---|---|
| `metrics.csv` | 三个试样的 UTS、E、Rp0.2 及处理窗口 |
| `metrics_comparison.csv` | 直接处理、流水线读回后处理和独立复算的对照 |
| `curves.png`、`proof_stress.png` | 完整原始/平移曲线和小应变 proof 计算图 |
| `curves/` | 保留原行号的逐行原始与修正曲线 |
| `normalized/` | 三个规范化 HDF5 样本与收据 |
| `verify_readback.json`、`run.json` | 新进程读回核对与运行状态 |

输出收据会记录使用者本机的文件位置；它们适合本地追溯，分享前应检查所含路径。

固定输入的参考计算值为：

| 试样 | 原始行数 | UTS / MPa | E / GPa | Rp0.2 / MPa |
|---|---:|---:|---:|---:|
| 055 | 614 | 277.081 | 63.703 | 251.966 |
| 056 | 645 | 277.834 | 54.345 | 252.887 |
| 057 | 630 | 280.209 | 65.257 | 254.024 |

这些是本项目独立重算的参考值，不是恢复出的作者逐试样真值；显示精度不代表实验测量精度。

公开安装包生成的[示例结果](results/README.md)随源码提供，可先查看再自行复跑：

![三试样的 proof 计算图](results/proof_stress.png)

## 处理口径

使用原版 Paramaterial **0.1.0**，并核对其处理模块的 SHA-256。先在完整曲线上求 UTS，再以**原始应变 `< 0.01`**取窗，按 36 MPa 预载与作者规则选择上下比例点，以两点割线求 E，沿应变轴修正零点，最后用原函数插值求 0.2% 偏移线交点。三个试样均沿用作者已保存的未剔除筛选记录。

HDF5 保存未经零点修正的输入，修正是后续派生操作。没有平滑、重排或转换为真实应力。图中的完整修正曲线应用同一平移量；E 和 proof 仍使用作者的小应变窗口。

本例验证文件流转和计算复现的一致性，不进行材料标定、跨材料预测或标准符合性认证。原数据论文的 20°C 参考表汇总多个批次，不是本例 A 批次三个试样的逐样本验收标准。

## 使用体验记录

一次先前的本地独立代理试用分别使用作者 Notebook 和复跑入口，两条路线都一次成功、九个指标相同。它说明已配置案例能够独立使用。该试用发生在本例公开移植之前，不是本发布版本的计时验收，也不能给出真人省时百分比。两条路线都允许一次启动；这里的便利是集中输出结果，并随运行自动保存来源、单位和读回检查。

## 来源与许可

[SOURCES.md](SOURCES.md) 保存数据记录、固定上游提交、试样对应、摘要、筛选依据和处理说明。数据与派生材料采用 CC BY 4.0；Paramaterial 及其示例的 MIT 文本位于 [licenses/](licenses/)。代码许可不替代数据许可。原论文全文、上游完整 Notebook、个人操作日志和本机环境不随本例分发。
