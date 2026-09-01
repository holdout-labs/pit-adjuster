# pit-adjuster

![PyPI version](https://img.shields.io/pypi/v/pit-adjuster.svg)
![PyPI downloads](https://img.shields.io/pypi/dm/pit-adjuster.svg)
![CI](https://github.com/holdout-labs/pit-adjuster/actions/workflows/ci.yml/badge.svg)
![License](https://img.shields.io/badge/license-MIT-blue)

## 中文说明

`pit-adjuster` 面向 A 股等股票市场的历史行情复权和公司行为数据处理。
它根据带时间点的公司行为档案重建固定基准价格，检查复权因子链是否连续，
并识别数据供应商悄悄切换复权口径的情况。工具只处理和验证历史数据，
不预测价格、不提供交易建议；公司行为的发生日、公告时间和数据覆盖范围
必须由使用者提供并核验。

面向日线价格历史的带时间点固定基准后复权引擎（point-in-time fixed-basis
back-adjustment engine）：重建价格，使**任意一天读到的正是那一天当时
所能知道的信息**——外加针对悄悄切换复权口径的数据供应商的漂移检测
（drift detection）。要求 Python 3.11+，**零依赖**，支持
Windows / Linux / macOS。

**简单来说：** 数据供应商会悄悄切换复权口径——你今天看到的 2019 年价格，
可能已经不是昨天看到的那些；而 CSV 中的数据形态没有任何变化。
`pit-adjuster` 会检测这种变化，并基于带时间点的公司行为档案
（point-in-time corporate-action archive）重建历史数据，从而让你的回测
不会因为底层数据的含义悄然改变而无声无息地失效。

![adjustment chain](https://img.shields.io/badge/deps-0-brightgreen)
![python](https://img.shields.io/badge/python-3.11%2B-blue)

**状态：** v0.1.1 alpha，已发布到 PyPI。复权计算逻辑已在生产研究管线中
经过实战检验，但这个独立包尚属全新：在 v1.0 之前，CLI 和 schema 预计
会有所调整。

## 为什么需要这个工具

数据供应商提供的 A 股（以及大多数股票市场）历史数据，都是**当前口径
（current-vintage）**的复权形式。存在两个隐蔽的危险：

1. **复权口径本身不是带时间点的。** 你今天看到的价格，内嵌了历史上
   发生过的每一次复权事件——包括在某个历史日期*之后*才公告的事件。
   使用这些价格做回测，等于在读取未来。
2. **供应商会悄悄切换复权口径。** 某一天起，你的数据源开始提供前复权
   （forward-adjusted，qfq）价格，而昨天它提供的还是后复权
   （back-adjusted，hfq）价格。CSV 中的数据形态没有任何变化；每一个
   历史信号的值却在悄然改变。

`pit-adjuster` 用两种原料重建历史数据——当前口径的前复权（qfq）K 线，
加上一份**带时间点的公司行为档案（point-in-time corporate-action
archive）**——重建为固定基准的后复权（hfq）链，其中每一天的价格只
取决于除权除息日（ex-date）不晚于当天的公司行为事件。然后它会*校验*：
重建是否正确地反转了供应商的复权链？供应商的复权链是否仍然与今天的
实时原始价格一致？

## 设计理念

价格历史必须可逆。一个无法证明其价格在过去是可获知的研究管线，做的
不是回测——而是在想当然。`pit-adjuster` 把**无前视（look-ahead
freedom）当作一种可验证的性质**，而非风格偏好：

- **PIT 原则**——每一个价格、因子和校准，都只依赖于该历史时点可得的
  信息。参见 [Kelly et al., "Scaling Point-in-Time Language Models"](https://www.nber.org/papers/w35247)
  （NBER w35247）和 [Look-Ahead-Bench](https://ar5iv.labs.arxiv.org/html/2601.13770)
  （arXiv:2601.13770），了解为什么整个行业都在向这一点靠拢。
- **前视偏差（look-ahead bias）是可度量的**——Daniel、Sornette 和
  Wohrmann（2008）在 ["Look-Ahead Benchmark Bias in Portfolio Performance Evaluation"](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1289222)
  （arXiv:0810.1922）中量化了事后基准（ex-post benchmark）的构建如何
  虚增业绩。供应商悄悄调换复权口径，做的正是这件事——就在你的价格列
  内部。
- **形式化依据**——Fonseca（2026）在
  ["Look-Ahead-Freedom as Temporal Non-Interference"](https://econpapers.repec.org/paper/arxpapers/2607.04958.htm)
  （arXiv:2607.04958）中证明，无前视在一般情况下是*不可判定*的（当信息
  可得性依赖于数据取值时为 Pi-0-1-困难），但在**与取值无关的片段
  （value-independent fragment）上**存在**线性时间可判定的类型-效应
  系统（type-effect system）**——包括窗口（windowing）、重采样
  （resampling）、连接（joins）、PIT 读取和 vintage 读取。

**诚实的边界：** 本包只对问题中与取值无关的片段实现可验证的校验（复权
因子链、除权除息日顺序、快照等价性、复权链反转）。对于一般的取值相关
情形，我们退而使用启发式防护（heuristic guards），并明确说明这一点——
只有在理论上允许的地方，我们才声称可验证。

## 快速开始

```bash
# install the published package from PyPI
pip install pit-adjuster

# or run without installing anything:
#   PYTHONPATH=src python -m pit_adjuster --help

# try it on synthetic data (builds a fake qfq history + action archive,
# rebuilds to hfq, runs invert-check and drift-check)
python examples/demo.py
```

重建你自己的历史数据：

```bash
padj rebuild \
  --bars bars.json --actions actions.json \
  --as-of 2026-08-11 --code 600000 --out hfq.json

padj invert-check --bars hfq.json --actions actions.json --as-of 2026-08-11
padj drift-check --bars hfq.json --actions actions.json \
  --as-of 2026-08-11 --live live_closes.json
```

`padj rebuild` 是主力命令：它先把供应商的 qfq 复权链反转回原始价格，
然后只重新应用除权除息日不晚于各 K 线日期的公司行为事件（以档案覆盖
起始日为固定基准）。原始开盘价/收盘价（raw open/close）会与复权价格
一并保留，以便执行层面的工作可以映射回名义价格（nominal prices）。

## 命令

| 命令 | 功能 |
| --- | --- |
| `rebuild` | 将 K 线重建为固定基准的 hfq：`open/high/low/close` 为复权价，`raw_open/raw_close` 为名义价，`adj_factor` 为累计复权因子，成交量归一化为股数 |
| `invert-check` | 除权除息日连续性健全性检查：是否满足 `raw_{ex-1} × factor_e ≥ raw_ex`？仅供参考——真实的除权除息日会包含隔夜收益，因此违规可能是误报 |
| `drift-check` | **静态前复权检测。** 将反转后的原始收盘价与实时原始收盘价对比；超出容差的分歧具有权威性——说明供应商的复权链已不再与档案一致 |
| `snapshot-equivalence` | 在容差范围内逐日比较两次重建的输出（例如新旧管线版本）——即"有没有变化？"的门槛检查 |
| `version` | 打印版本号 |

全局标志：每个子命令都支持 `--help`；支持的地方可通过 `--out` 输出
JSON；其余情况打印人类可读的摘要。

## 数据模型

**Bars（K 线）**——日线 K 线的 JSON 列表，每条至少包含 `date`（ISO
格式）和 `close`；`open/high/low/volume/amount/turnover` 会在重建过程
中原样保留：

```json
{"date": "2026-06-12", "open": 95.0, "high": 96.0, "low": 94.5, "close": 95.5, "volume": 1234500}
```

**Actions（公司行为）**——带时间点的公司行为档案，每个事件一条记录，
包含 `ex_date`、`adjustment_factor` 和 `available_at`：

```json
{"ex_date": "2026-06-15", "adjustment_factor": 0.95, "available_at": "2026-06-14T18:00:00", "action_type": "cash_dividend_stock_distribution"}
```

无效记录（缺少除权除息日、复权因子为非正数或非有限值）会被丢弃；只有
`ex_date <= as_of_date` 的事件才会参与计算。schema 位于
[schema/corporate-action.schema.json](https://github.com/holdout-labs/pit-adjuster/blob/main/schema/corporate-action.schema.json)。

## 复权计算

标准的 A 股复权因子计算（依据交易所参考价规则）：

```
factor_e = (prior_close - cash) / (prior_close * (1 + bonus + transfer))
qfq_t    = raw_t * prod_{e: ex_date_e > t} factor_e
hfq_t    = raw_t * prod_{e: ex_date_e <= t} (1 / factor_e)
```

`rebuild` 先把供应商的 qfq 复权链反转回原始价格，再以档案覆盖起始日为
固定基准应用 hfq 复权链。**关键性质（测试中）：** 对于相同的复权因子链，
hfq 与 qfq 会得到完全一致的复权*收益率*，同时 hfq 额外保证了 `t` 时刻
的价格不会受到除权除息日晚于 `t` 的事件影响。

成交量归一化遵循 A 股惯例：大多数代码的成交量以手（lot）为单位（×100
换算为股）；科创板（STAR Market）代码（688/689 开头）直接以股为单位。
两者均可参数化——参见 `rebuild_bars` 中的 `--volume-to-shares` 与
`native_share_prefixes` 参数。

## 验证模型

`pit-adjuster` 从不信任其输入：

- `invert-check`——除权除息日处的复权因子连续性（健全性检查，容忍误报）
- `drift-check`——反转后的原始价格对比实时原始价格（权威性的分歧检测；
  这就是"静态前复权检测器"——如果供应商调换复权口径，它会触发告警）
- `snapshot-equivalence`——两次重建的前后等价性，是管线迁移的可复现性
  门槛

所有校验均为只读操作。这里没有任何交易、定价或决策功能。

## 开发

```bash
python -m pip install -e . pytest
python -m pytest
```

CI 会在 Ubuntu、Windows 和 macOS 上以 Python 3.11 和 3.12 运行完整测试
套件。问题（issue）在周末处理；欢迎提交 pull request。

## 相关工作

- [Daniel, Sornette & Wohrmann (2008)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1289222) ——量化了前视基准偏差（look-ahead benchmark bias）
- [Fonseca (2026)](https://econpapers.repec.org/paper/arxpapers/2607.04958.htm) ——无前视作为时间非干涉（temporal non-interference）（可验证性的边界）
- [Point-in-Time Backtesting of Momentum-Trend Equity Strategies: A Formal Bias Taxonomy, ATR Trailing Stop Analysis, and Investor-Experience Metrics](https://www.mdpi.com/2227-7390/14/12/2182)（Mathematics 2026, 14(12):2182）
- [Kelly et al., Scaling Point-in-Time Language Models](https://www.nber.org/papers/w35247)（NBER w35247）
- [Look-Ahead-Bench](https://ar5iv.labs.arxiv.org/html/2601.13770)（arXiv:2601.13770）——用于度量 PIT LLM 中的前视偏差

## 项目家族

隶属于 [Holdout](https://github.com/holdout-labs)——一个对抗量化研究中
自欺行为的工具链：

- [pit-adjuster](https://github.com/holdout-labs/pit-adjuster) ——带静态前复权漂移检测的 PIT 后复权
- [falsification-ledger](https://github.com/holdout-labs/falsification-ledger) ——预注册与证伪台账（pre-registration and falsification ledger）
- [factor-qc](https://github.com/holdout-labs/factor-qc) ——默认拒绝（fail-closed）的回测质量闸门
- [lesson-book](https://github.com/holdout-labs/lesson-book) ——交易者的学费记忆（tuition memory）
- [lookahead-free](https://github.com/holdout-labs/lookahead-free) ——可验证的无前视（look-ahead-freedom）校验
- [ashare-data-immunity](https://github.com/holdout-labs/ashare-data-immunity) ——A 股日线 K 线的数据免疫

姊妹组织：[Metabolism Tools](https://github.com/metabolism-tools)——
[`workspace-metabolism`](https://github.com/metabolism-tools/workspace-metabolism)，
面向智能体工作区（agentic workspaces）的、由策略驱动的文件生命周期管理。

## 许可证

MIT
