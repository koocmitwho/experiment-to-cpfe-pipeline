# 固定版本的真实外部案例

完整步骤、CPU 安装、分组、指标解释和失败处理见 [使用指南](../../docs/real-case-workflow.md) / [English](../../docs/real-case-workflow.en.md)。来源、许可和处理说明见 [第三方声明](../../THIRD_PARTY_NOTICES.md)。

源码只保存项目驱动和经审清单，不包含原始数据、训练权重或第三方脚本。输入和输出放在仓库外；每次使用新输出目录。

|案例|官方记录|源目录中的文件|实际执行|
|---|---|---|---|
|dopamics|[15343816](https://zenodo.org/records/15343816)|2025-04-08_Mechanical_data_tensile_test_laser_ALES.zip|接入→v1 建集→CPU OLS/MLP→独立预测→评价|
|fair-train|[19007867](https://zenodo.org/records/19007867)|TensileTestProject.zip|三份原始 XLSX 全通道接入，保留 Sheet2 原行；不训练|
|pcl|[10995304](https://zenodo.org/records/10995304)|TensileTestAtTdef_PCLSG10_1.csv、_2.csv、_3.csv|十二通道接入、包含预热的完整记录建集；不训练|

```text
python examples/external_cases/workflow.py --case dopamics --source-root ../cpfe-data/dopamics --run-dir ../cpfe-results/dopamics-001
python examples/external_cases/workflow.py --case fair-train --source-root ../cpfe-data/fair-train --run-dir ../cpfe-results/fair-001
python examples/external_cases/workflow.py --case pcl --source-root ../cpfe-data/pcl --run-dir ../cpfe-results/pcl-001
```

三个官方记录均为 CC BY 4.0；清单摘要不一致时停止。不能把任意新的文件重命名成上述名称来代替固定数据。

DOPAMICS 用已测激光应变回归仪器报告应力。应变 `%` 显式乘 0.01，目标 MPa；固定原始试样 3/1/1，验证选模和训练归一化。生物个体/批次独立性与应力物理约定仍未建立，任务为 `legacy_unassessed`。

FAIR 不把上游派生 JSON 的固定日期或材料解析当原始事实；负值原样保留，不调零或转应力。PCL 的三次 replicate 身份不证明批次独立；全部记录不称为恒温 95°C 曲线。不得将仪器派生力/应力/位移关系当材料规律发现。
