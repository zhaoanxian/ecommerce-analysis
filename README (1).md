# 电商交易数据分析项目（Online Retail II）

> 基于英国电商 106 万条真实交易记录的完整经营分析：数据清洗 → SQL 验证 → 业务分析 → 可视化 → 交互看板 → 客户价值预测。
> 分析语言：Python (pandas) + SQL (SQLite)，双引擎互相验证；建模：BG/NBD + Gamma-Gamma。

## 项目成果一览

| 指标 | 数值 |
|---|---|
| 分析时间跨度 | 2009-12 ~ 2011-12（约 25 个月） |
| 有效交易行数 | 793,609（原始 1,067,371，清洗后保留 74.4%） |
| 营收总额 | £17,685,461 |
| 订单数 / 客户数 / SKU 数 | 36,969 / 5,878 / 4,631 |
| 客单价 AOV | £478.39 |
| 复购率 | 72.4% |
| 次月留存率（中位） | 20.5% |
| 头部 5% 客户营收贡献 | 52.1% |
| 80% 营收所需 SKU 占比 | 21.3% |
| CLV 模型验证（时间切分 373 天） | Pearson r = 0.83，MAE = 3.29 次 |
| 预测未来 12 个月 CLV | £10,527,199 |
| 头部 10% 客户占预测 CLV | 61.6% |

核心结论与业务建议见 [reports/analysis_report.md](reports/analysis_report.md)。

## 项目结构

```text
ecommerce-analysis/
├── data/
│   ├── raw/                    # 原始数据（需自行下载，见下文）
│   └── processed/              # 清洗后的 csv + SQLite 库
├── src/
│   ├── prepare_data.py         # 数据清洗（含清洗日志，每步剔除多少行都有记录）
│   ├── analysis.py             # 五大业务分析 + 7 张业务图表
│   ├── run_sql.py              # 导入 SQLite 并执行 SQL 查询
│   ├── dashboard.py            # Streamlit 交互式经营看板
│   └── clv_model.py            # BG/NBD + Gamma-Gamma 客户价值预测与验证
├── sql/
│   └── analysis_queries.sql    # 8 条业务 SQL（含窗口函数）
├── output/                     # 每个分析主题的结果 csv
│   ├── clv_customer.csv        # 逐客户 CLV 及预测参数
│   ├── clv_validation.csv      # 模型验证指标
│   └── sql_results/
├── reports/
│   ├── figures/                # 8 张图表（7 张业务图 + 1 张 CLV 验证图）
│   └── analysis_report.md      # 完整分析报告（结论 + 建议）
├── requirements.txt
└── README.md
```

## 快速开始

### 1. 环境准备

Python 3.10+，安装依赖：

```bash
pip install -r requirements.txt
```

### 2. 获取数据

本项目使用 UCI 公开数据集 [Online Retail II](https://archive.ics.uci.edu/dataset/502/online+retail+ii)（CC BY 4.0）。

- 官方下载：https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip
- 镜像下载（HuggingFace）：https://huggingface.co/datasets/michaelmallari/online-retail-ii

下载后将 `online_retail_ii.xlsx` 放入 `data/raw/` 目录。

### 3. 一键运行

脚本有先后依赖，请按顺序执行：

```bash
python src/prepare_data.py   # 数据清洗，生成 data/processed/clean_transactions.csv
python src/analysis.py       # 业务分析 + 图表，结果写入 output/ 和 reports/figures/
python src/run_sql.py        # SQL 双引擎验证，生成 data/processed/ecommerce.db
python src/clv_model.py      # CLV 建模与验证，生成 output/clv_*.csv 与 08_clv.png
```

### 4. 启动交互看板

```bash
streamlit run src/dashboard.py
```

浏览器自动打开 http://localhost:8501（需先完成第 3 步前两条命令，看板读取 `output/` 与 `data/processed/` 下的结果）。

## 数据字典

清洗后的明细表 `clean_transactions.csv`：

| 字段 | 类型 | 说明 |
|---|---|---|
| InvoiceNo | str | 订单号（取消单以 C 开头，已在清洗时剔除） |
| StockCode | str | 商品编码 |
| Description | str | 商品描述 |
| Quantity | int | 数量 |
| InvoiceDate | datetime | 下单时间 |
| UnitPrice | float | 单价（£） |
| CustomerID | int | 客户编号（缺失客户已剔除） |
| Country | str | 国家 |
| Revenue | float | 本行金额 = Quantity × UnitPrice（衍生） |
| Year / Month / DayOfWeek / Hour | - | 时间衍生字段 |
| IsOutlier | bool | 极端金额标记（3×IQR，保留未删除） |

## 分析方法

1. **数据清洗**（`prepare_data.py`）——合并两个年度 sheet → 去重 → 剔除取消单/负数量/负单价 → 剔除无客户 ID → IQR 异常打标 → 时间衍生字段。每一步的剔除行数写入 `cleaning_log.csv`，全程可追溯。
2. **业务分析**（`analysis.py`）——按「经营五问」组织：
   - Q1 大盘：月度营收/订单/客单价走势 + 同比
   - Q2 商品：帕累托分析（多少 SKU 贡献 80% 营收）
   - Q3 客户：RFM 五分位打分 + 7 类分层
   - Q4 留存：月度队列留存热力图（cohort analysis）+ 复购率
   - Q5 区域时段：国家分布 + 星期×小时营收热力图
3. **SQL 双引擎**（`run_sql.py`）——同样的分析用 SQL 再算一遍（含 `NTILE`、`LAG` 窗口函数），验证 pandas 结果正确性。
4. **交互看板**（`dashboard.py`）——Streamlit 构建，支持国家 × 时间双维筛选联动，与预计算结果联动展示。
5. **价值预测**（`clv_model.py`）——BG/NBD 预测未来购买次数，Gamma-Gamma 预测客单金额，相乘得 12 个月 CLV；用时间切分法验证排序能力。

## 交互式经营看板（Streamlit）

```bash
streamlit run src/dashboard.py
```

- **侧边栏筛选**：国家（含「全部国家」）+ 月份区间滑杆，选择后全页面图表联动
- **分页展示**：大盘趋势、商品帕累托、RFM 分层、地域与时段分布
- **数据口径**：趋势与分层读 `output/` 预计算结果，时段分布基于清洗后明细实时聚合
- **缓存策略**：`@st.cache_data` 缓存明细与汇总表，切换筛选不重复读盘

## 客户生命周期价值预测（BG/NBD + Gamma-Gamma）

```bash
python src/clv_model.py
```

**建模口径**

- 交易定义：同一客户同日多笔合并为一次交易（`freq="D"`）
- `frequency` = 重复购买次数（交易数 − 1），`recency` = 首末次购买间隔，`T` = 首次购买至观测截止天数
- 输入矩阵由本文件手动计算（`build_calibration` / `build_summary`），与 `lifetimes.utils` 逐客户一致性已验证（max|Δ| = 0），规避库与新版 pandas 的兼容问题
- 客户级价值 = 预测购买次数 × Gamma-Gamma 预期客单金额，折扣率按 12 个月窗口计算

**时间切分验证**（校准截止 2010-12-01，外推 373 天，2,758 名客户）

| 指标 | 数值 |
|---|---|
| MAE | 3.29 次 |
| RMSE | 4.52 次 |
| Pearson r | 0.83 |
| 实际均值 vs 预测均值 | 4.18 次 vs 6.12 次 |

**输出与结论**

- `output/clv_customer.csv`：逐客户 `clv_12m` 与 `clv_decile` 分层
- `output/clv_validation.csv`：验证指标
- `reports/figures/08_clv.png`：验证散点 + CLV 十分位贡献图
- 未来 12 个月预测总 CLV £10,527,199，其中头部 10%（587 人）占 61.6%

**已知局限**

- 模型对高频 B2B 客户存在系统性高估（预测均值 6.12 次 vs 实际 4.18 次，整体上偏约 46%），适合做客户**排序与分层**，不宜直接作为绝对金额预算
- 假设客户购买行为在观测期内稳定，无法刻画促销、断货等外部冲击
- 剔除无客户 ID 的交易（占原始 22.1%），故模型覆盖的是可识别客户群体，不含柜台散单

## 核心发现（速览）

1. **强季节性**：9-11 月营收陡增，11 月是全年峰值（£1.16M），为次年 2 月低谷（£0.45M）的 2.6 倍。
2. **商品长尾明显**：21.3% 的 SKU 贡献 80% 营收，爆款依赖度高。
3. **客户集中度极高**：头部 5% 客户贡献 52.1% 营收，RFM 分层中「重要价值客户」占营收 68.4%。
4. **复购健康但留存一般**：整体复购率 72.4%，但次月留存仅 20.5%，客户有「间隔性回流」特征（平均复购间隔 51.7 天）。
5. **地域高度集中**：英国本土 82.9%，海外增长空间大。
6. **时段规律清晰**：工作日 10:00-15:00 是下单高峰，周六几乎无交易（B2B 特征）。

## License

- 代码：MIT
- 数据：UCI Online Retail II（[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)），使用时请遵守原始许可
