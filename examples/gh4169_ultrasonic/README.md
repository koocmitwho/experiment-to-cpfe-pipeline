# GH4169 超声参数预测平均晶粒尺寸

本例把作者公开的试样级超声参数接入 SamplePackage、HDF5 和配置驱动的训练 NPZ，
再用现有 CPU MLP 与均值、线性及岭回归基线进行评估。数据共有十个 GH4169 试样。
当前结果中线性回归比 MLP 更准确，适合作为这份小样本数据的参考方法。

## 数据与任务

唯一数据源为 Xi Chen、Guanhua Wu、Zhenggan Zhou、chen hao 的
[Mendeley Data v1](https://data.mendeley.com/datasets/v487vwmd7r/1)，
DOI 10.17632/v487vwmd7r.1，2019-05-27 发布。
[原论文公开页面](https://www.sciencedirect.com/science/article/abs/pii/S0963869518304225)
说明试样来自 GH4169 轧制棒材，并描述十个试样。

DATA.xlsx 的有效数据在 Sheet1；Sheet2 和 Sheet3 为空。Sheet1 有 224 个非空单元格，
没有公式，按公式模式与缓存值模式读取的数值一致。A4:A11 是 NO.1–NO.8，
A12:A13 是 T1/T2。每个试样一行汇总参数，作者结果表 A48:A49 再次将 T1/T2
标为测试样本。六张 JPG 是附带金相图；模型输入采用下表中的试样汇总参数。

| 角色 | 原始位置 | 含义 | 单位 |
| --- | --- | --- | --- |
| 试样身份 | A4:A13 | 原始试样编号 | 标签 |
| 条件记录 | B4:B13 | 热处理原文 | 复合文本，不解析为数值 |
| 目标 | C4:C13 | 金相平均晶粒直径 | μm（配置记作 um） |
| 输入一 | D4:D13 | 平均衰减系数 ᾱ | dB/mm |
| 输入二 | F4:F13 | 平均纵波声速 c̄L | m/s |

D3/F3 的符号是嵌入 PNG，分别为工作簿 `xl/media/image1.png` 和 `image3.png`；
单纯读取单元格文本只能得到单位。本次已提取并目视检查这些表头。
所选 D/F 列保留作者汇总参数的原始量纲。两列输入按物理定义和单位固定，
每件试样的目标来自 C4:C13。

原表的其余列、表头和热处理文字保存在工作簿审查记录中。B9/B10 原文为
`11000℃/1h/WC`、`11300℃/1h/WC`，按原样保存。热处理字符串作为标签登记单位 `1`，
其中的温度与时间信息保留原始文本表示。

## 规范化与来源分组

`prepare.py` 核对 `source.json` 固定的文件版本，再调用现有 XLSX block 适配器。
每个试样输出一个 HDF5 和对应的 `*.ingest.json`，包含原表列映射、工作表/行、
试样身份、单位、许可和转换记录。`workbook-audit.json` 保存全部工作表的非空值、
公式/缓存信息和处理选择。原始热处理字符串保留在表行及来源记录中。

十个 HDF5 的根来源仍是同一个 DATA.xlsx。生成的 `build.json` 用
`target_specimen: {column: specimen, evidence: ...}` 声明 A 列的实体试样身份，
按同一试样的全部测量分组。构建器核对源行和身份，保留整份工作簿的来源链。
表坐标使用记录轴，张量和取向采用标量回归对应的适用性声明。

## 小样本评估

T1/T2 始终保留为作者测试样本。开发集固定四对：NO.1/NO.5、NO.2/NO.6、
NO.3/NO.7、NO.4/NO.8；按原编号固定划分。

开发集外层每次留出一对。其余六个试样再轮流取一对验证，得到三个 4/2/2
训练/验证/外层测试配置。各模型按内层验证 MSE 选择 checkpoint，等权平均后
预测外层两件试样。外层试样的目标在对应模型的训练和检查点选择完成后用于评价。
内层验证误差用于选择检查点，最终报告开发集外层和作者测试集的误差。

最终四个 MLP 分别按 6/2/2 使用开发集和 T1/T2，四个验证选定的模型等权平均。
固定单隐藏层四单元 tanh、seed=17、学习率 0.003、最多 1500 epoch、patience=200。
输入和目标的均值/尺度仅在各模型训练子集拟合。该网络有 17 个参数，训练样本很少。

均值与 OLS 在外层六个、最终八个开发试样上拟合。岭回归的 alpha 候选为
0.01/0.1/1/10/100；在相应内层验证选择后，用全部可用开发试样重新拟合。
因此各 MLP 成员使用的拟合试样数少于这些重新拟合的基线，结果按这套流程比较。
评价单位为原始工作簿中的实体试样。

2026-09-07 本地运行，误差单位均为 μm：

| 方法 | 开发集外层 MAE（n=8） | 开发集外层 RMSE | 作者测试 MAE（n=2） | 作者测试 RMSE |
| --- | ---: | ---: | ---: | ---: |
| 均值 | 45.00 | 51.84 | 20.62 | 27.22 |
| OLS | 9.18 | 10.00 | 5.54 | 5.71 |
| 岭回归 | 10.31 | 11.41 | 5.96 | 5.96 |
| MLP 集成 | 19.92 | 26.56 | 9.38 | 9.38 |

16 个 MLP checkpoint 已逐一读回，预测与训练保存值的最大绝对差为 0。
最终岭回归 alpha 为 0.01。部分内层 MLP 的最佳 epoch 为 1，另一些达到 1500；
这些检查点选择记录了不同小样本组成下的优化结果。开发集外层与最终作者测试
使用各自规定的训练规模，本表按这两套评估流程分别报告误差。

这份公开数据用于检查接入、分组、训练和预测流程。评价采用回顾性设置，
保留上述开发试样与 T1/T2 的计算分工。
训练完成后的描述性检查显示，八个开发试样的两列特征相关系数为 −0.9822。
该值描述两个输入在这八件试样中的相关程度；输入列、超参数和划分采用上述固定设置。

## 本地复跑

在仓库根目录，使用项目 `.venv`；安装基础、native 和 training 依赖，绘图另需
matplotlib。每次选择新的输出目录。通过数据页的正常下载链接取得原始文件，
下载后由 `prepare.py` 核对文件版本和工作簿内容。

```powershell
.\.venv\Scripts\python.exe -X utf8 examples/gh4169_ultrasonic/prepare.py --source runs/public-data-screening/gh4169-20260907/raw/DATA.xlsx --output-dir runs/gh4169-rerun/normalized
.\.venv\Scripts\python.exe -X utf8 examples/gh4169_ultrasonic/evaluate.py --normalized-dir runs/gh4169-rerun/normalized --output-dir runs/gh4169-rerun/evaluation
.\.venv\Scripts\python.exe -X utf8 examples/gh4169_ultrasonic/plot.py --evaluation runs/gh4169-rerun/evaluation/evaluation.json
```

若只想构建默认的第一组 6/2/2 NPZ，可在规范化后单独运行：

```powershell
.\.venv\Scripts\pipeline.exe build-training-dataset --config runs/gh4169-rerun/normalized/build.json --run-dir runs/gh4169-rerun/dataset
```

`evaluate.py` 会为全部 16 个拟合写出独立的 `build.json`、dataset.npz、dataset.json、
训练配置、数据收据、model.pt 和训练历史；复跑单个拟合可用保存的 `fit.json`
执行 `pipeline train-surrogate --config <fit.json> --run-dir <new-model-directory>`。
最终集成由 `final-0` 到 `final-3` 的四个 checkpoint 通过 `predict_mlp` 预测后取均值，
模型按 `[attenuation_mean, longitudinal_velocity_mean]` 顺序接收两列输入。

`evaluation.json` 和 `predictions.csv` 保存每件试样、每种模型的预测、带符号误差、
绝对误差及汇总指标。`specimen-errors.png/svg` 为同一数据的静态图。
本轮完整结果在 `runs/gh4169-ultrasonic-20260907/`；
测试和下载证据也保存在该目录及原筛选目录的 `refresh/` 中。

原始文件、规范化数据、模型、逐试样结果及图均留在忽略目录，并保留
[CC BY-NC 3.0](https://creativecommons.org/licenses/by-nc/3.0/) 署名与非商业条件。
本例脚本和合成测试夹具使用项目代码许可，原数据许可不随之改变。
