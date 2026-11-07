"""
业务分析模块
------------
输入: data/processed/clean_transactions.csv
输出:
  - output/*.csv        每张分析表的明细结果
  - reports/figures/*.png 图表

分析框架：按「电商经营五问」组织
  Q1 整体经营大盘   —— 营收走势如何？增长来自哪里？
  Q2 商品结构        —— 哪些商品撑起营收？长尾有多长？
  Q3 客户价值        —— 客户贡献是否集中？RFM 分层结果如何？
  Q4 留存与复购      —— 客户会回来吗？留存曲线长什么样？
  Q5 区域与时段      —— 什么时间/地区该重点投放？
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed" / "clean_transactions.csv"
OUTPUT = ROOT / "output"
FIGURES = ROOT / "reports" / "figures"

# 中文字体：优先用系统里的 Noto/文泉驿，找不到就退回英文
def setup_style() -> None:
    sns.set_theme(style="whitegrid", context="talk")
    plt.rcParams["figure.dpi"] = 130
    plt.rcParams["savefig.bbox"] = "tight"
    plt.rcParams["axes.unicode_minus"] = False
    candidates = [
        "Noto Sans CJK SC", "Noto Sans SC", "Noto Sans CJK JP",
        "Noto Serif CJK SC", "Noto Serif CJK JP", "WenQuanYi Zen Hei",
        "Source Han Sans SC", "SimHei", "Microsoft YaHei", "PingFang SC",
        "Heiti SC", "Arial Unicode MS",
    ]
    from matplotlib import font_manager
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in candidates:
        if name in available:
            plt.rcParams["font.family"] = "sans-serif"
            plt.rcParams["font.sans-serif"] = [name] + plt.rcParams["font.sans-serif"]
            return
    plt.rcParams["font.family"] = "DejaVu Sans"


PALETTE = ["#2E5C8A", "#E8833A", "#4A9B7F", "#C1554A", "#7B6BA8", "#B8935A"]


# ---------------------------------------------------------------- Q1 大盘
def overall_trend(df: pd.DataFrame) -> pd.DataFrame:
    """月度营收 / 订单数 / 客单价 走势。"""
    monthly = (
        df.groupby("Month")
        .agg(
            revenue=("Revenue", "sum"),
            orders=("InvoiceNo", "nunique"),
            customers=("CustomerID", "nunique"),
            items=("Quantity", "sum"),
        )
        .reset_index()
    )
    monthly["aov"] = monthly["revenue"] / monthly["orders"]  # 客单价
    monthly["arpu"] = monthly["revenue"] / monthly["customers"]  # 人均消费

    fig, axes = plt.subplots(2, 1, figsize=(14, 9), sharex=True)
    ax = axes[0]
    ax.plot(monthly["Month"], monthly["revenue"] / 1000,
            color=PALETTE[0], lw=2.5, marker="o", ms=4)
    ax.fill_between(range(len(monthly)), monthly["revenue"] / 1000,
                    color=PALETTE[0], alpha=0.12)
    ax.set_ylabel("月营收（千英镑）")
    ax.set_title("月度营收走势：明显的年终旺季 + 年初回落", fontsize=15, weight="bold")
    ax.set_xticks(range(len(monthly)))
    ax.set_xticklabels(monthly["Month"], rotation=90, fontsize=9)

    ax2 = axes[1]
    ax2.bar(monthly["Month"], monthly["orders"], color=PALETTE[1], alpha=0.85, label="订单数")
    ax2.set_ylabel("订单数", color=PALETTE[1])
    ax2.tick_params(axis="y", labelcolor=PALETTE[1])
    ax2.set_xticks(range(len(monthly)))
    ax2.set_xticklabels(monthly["Month"], rotation=90, fontsize=9)

    ax3 = ax2.twinx()
    ax3.plot(monthly["Month"], monthly["aov"], color=PALETTE[3], lw=2, marker="s", ms=3, label="客单价")
    ax3.set_ylabel("客单价（£）", color=PALETTE[3])
    ax3.tick_params(axis="y", labelcolor=PALETTE[3])
    ax3.grid(False)
    ax2.set_title("订单量与客单价：旺季靠订单量拉动，客单价基本平稳", fontsize=15, weight="bold")

    fig.tight_layout()
    fig.savefig(FIGURES / "01_monthly_trend.png")
    plt.close(fig)

    monthly.to_csv(OUTPUT / "monthly_trend.csv", index=False)
    return monthly


# ---------------------------------------------------------------- Q1b 同比
def yoy_growth(monthly: pd.DataFrame) -> pd.DataFrame:
    """计算同比：用同月份对比上一年。注意 2009 只有 12 月，2011 只到 12 月初。"""
    m = monthly.copy()
    m["year"] = m["Month"].str[:4].astype(int)
    m["mon"] = m["Month"].str[5:7].astype(int)

    piv = m.pivot_table(index="mon", columns="year", values="revenue", aggfunc="sum")
    yoy = pd.DataFrame(index=piv.index)
    yoy["2010"] = piv.get(2010)
    yoy["2011"] = piv.get(2011)
    yoy["yoy_2011_vs_2010"] = (piv.get(2011) / piv.get(2010) - 1).round(4)
    yoy.index.name = "month"
    yoy.to_csv(OUTPUT / "yoy_growth.csv")
    return yoy


# ---------------------------------------------------------------- Q2 商品
def product_analysis(df: pd.DataFrame, top_n: int = 15) -> tuple[pd.DataFrame, pd.DataFrame]:
    """商品结构：帕累托 + 长尾 + TOP 商品。"""
    prod = (
        df.groupby(["StockCode", "Description"])
        .agg(revenue=("Revenue", "sum"), qty=("Quantity", "sum"),
             orders=("InvoiceNo", "nunique"))
        .reset_index()
        .sort_values("revenue", ascending=False)
    )
    prod["revenue_pct"] = prod["revenue"] / prod["revenue"].sum()
    prod["cum_pct"] = prod["revenue_pct"].cumsum()
    prod["rank"] = np.arange(1, len(prod) + 1)

    # 帕累托：多少 SKU 贡献 80% 营收
    n_80 = int((prod["cum_pct"] < 0.80).sum() + 1)
    sku_80_pct = n_80 / len(prod)

    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    ax = axes[0]
    ax.plot(prod["rank"], prod["cum_pct"] * 100, color=PALETTE[0], lw=2.5)
    ax.axhline(80, ls="--", color=PALETTE[3], lw=1.5)
    ax.axvline(n_80, ls="--", color=PALETTE[3], lw=1.5)
    ax.annotate(
        f"{n_80:,} 个 SKU（{sku_80_pct:.1%}）\n贡献 80% 营收",
        xy=(n_80, 80), xytext=(n_80 * 2.2, 55),
        fontsize=12, color=PALETTE[3],
        arrowprops=dict(arrowstyle="->", color=PALETTE[3], lw=1.5),
    )
    ax.set_xscale("log")
    ax.set_xlabel("商品排名（对数刻度）")
    ax.set_ylabel("累计营收占比 (%)")
    ax.set_title("营收高度集中：少数爆款撑起大盘", fontsize=15, weight="bold")

    ax = axes[1]
    top = prod.head(top_n).iloc[::-1]
    labels = [f"{r.Description[:28]}" for r in top.itertuples()]
    ax.barh(labels, top["revenue"] / 1000, color=PALETTE[2], alpha=0.85)
    ax.set_xlabel("营收（千英镑）")
    ax.set_title(f"营收 TOP {top_n} 商品", fontsize=15, weight="bold")
    ax.tick_params(axis="y", labelsize=9)

    fig.tight_layout()
    fig.savefig(FIGURES / "02_product_pareto.png")
    plt.close(fig)

    prod.head(100).to_csv(OUTPUT / "top_products.csv", index=False)
    return prod, pd.DataFrame([{"n_sku": len(prod), "sku_for_80pct": n_80,
                                "sku_pct_for_80pct": round(sku_80_pct, 4)}])


# ---------------------------------------------------------------- Q3 RFM
def rfm_analysis(df: pd.DataFrame, snapshot_days: int = 1) -> pd.DataFrame:
    """RFM 客户分层。R=最近购买间隔, F=购买频次, M=消费金额。"""
    snapshot = df["InvoiceDate"].max() + pd.Timedelta(days=snapshot_days)
    rfm = (
        df.groupby("CustomerID")
        .agg(
            recency=("InvoiceDate", lambda s: (snapshot - s.max()).days),
            frequency=("InvoiceNo", "nunique"),
            monetary=("Revenue", "sum"),
        )
        .reset_index()
    )

    # 五分位打分（1-5 分，5 最好）。R 越小越好，所以用反向标签
    rfm["R"] = pd.qcut(rfm["recency"], 5, labels=[5, 4, 3, 2, 1]).astype(int)
    # F/M 有大量重复值，qcut 会报边界重复错误，改用 rank 分位
    rfm["F"] = pd.qcut(rfm["frequency"].rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(int)
    rfm["M"] = pd.qcut(rfm["monetary"].rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(int)
    rfm["rfm_score"] = rfm["R"] * 100 + rfm["F"] * 10 + rfm["M"]

    def segment(row) -> str:
        r, f, m = row["R"], row["F"], row["M"]
        if r >= 4 and f >= 4 and m >= 4:
            return "重要价值客户"
        if r >= 3 and m >= 4:
            return "重要发展客户"
        if r <= 2 and f >= 4 and m >= 4:
            return "重要挽留客户"
        if r <= 2 and f <= 2 and m <= 2:
            return "流失客户"
        if r <= 3 and f <= 3:
            return "一般流失客户"
        if r >= 4:
            return "新客户"
        return "一般客户"

    rfm["segment"] = rfm.apply(segment, axis=1)

    seg = (
        rfm.groupby("segment")
        .agg(customers=("CustomerID", "count"),
             revenue=("monetary", "sum"),
             avg_recency=("recency", "mean"),
             avg_freq=("frequency", "mean"),
             avg_monetary=("monetary", "mean"))
        .reset_index()
        .sort_values("revenue", ascending=False)
    )
    seg["customer_pct"] = seg["customers"] / seg["customers"].sum()
    seg["revenue_pct"] = seg["revenue"] / seg["revenue"].sum()

    fig, axes = plt.subplots(1, 2, figsize=(16, 6.5))
    order = seg["segment"].tolist()
    ax = axes[0]
    color_map = dict(zip(order, PALETTE * 3))
    sns.barplot(data=seg, y="segment", x="revenue_pct", order=order,
                hue="segment", palette=color_map, legend=False, ax=ax)
    for i, row in enumerate(seg.itertuples()):
        ax.text(row.revenue_pct, i, f"  {row.revenue_pct:.1%}",
                va="center", fontsize=11, weight="bold")
    ax.set_xlabel("营收占比")
    ax.set_ylabel("")
    ax.set_title("各客户分层的营收贡献", fontsize=15, weight="bold")
    ax.set_xlim(0, seg["revenue_pct"].max() * 1.25)

    ax = axes[1]
    sns.scatterplot(data=rfm, x="frequency", y="monetary", size="recency",
                    hue="segment", palette=color_map, sizes=(15, 200),
                    alpha=0.65, ax=ax, legend="brief")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("购买频次（对数）")
    ax.set_ylabel("消费金额（对数）")
    ax.set_title("客户分布在频次-金额平面上的结构", fontsize=15, weight="bold")
    ax.legend(fontsize=8, loc="lower right", ncol=2, framealpha=0.9)

    fig.tight_layout()
    fig.savefig(FIGURES / "03_rfm_segments.png")
    plt.close(fig)

    rfm.to_csv(OUTPUT / "rfm_customer.csv", index=False)
    seg.to_csv(OUTPUT / "rfm_segments.csv", index=False)

    # 首次购买月份维度：新客还是老客在贡献
    return rfm


# ---------------------------------------------------------------- Q4 留存
def cohort_retention(df: pd.DataFrame) -> pd.DataFrame:
    """按月首购队列的留存热力图（cohort analysis）。"""
    first = df.groupby("CustomerID")["InvoiceDate"].min().dt.to_period("M").rename("cohort")
    d = df[["CustomerID", "InvoiceDate"]].copy()
    d["order_month"] = d["InvoiceDate"].dt.to_period("M")
    d = d.join(first, on="CustomerID")
    d["period"] = (d["order_month"] - d["cohort"]).apply(lambda x: x.n)

    cohort_data = d.groupby(["cohort", "period"])["CustomerID"].nunique().reset_index()
    pivot = cohort_data.pivot(index="cohort", columns="period", values="CustomerID")
    sizes = pivot[0]
    retention = pivot.div(sizes, axis=0) * 100

    # 只画前 12 个 cohort 的前 12 期，避免图太密
    plot_data = retention.iloc[:24, :12]
    fig, ax = plt.subplots(figsize=(14, 9))
    sns.heatmap(plot_data, annot=True, fmt=".0f", cmap="Blues",
                cbar_kws={"label": "留存率 (%)"}, ax=ax,
                annot_kws={"size": 8}, linewidths=0.5, linecolor="white")
    ax.set_xlabel("首购后第 N 个月")
    ax.set_ylabel("首购月份（cohort）")
    ax.set_title("月度队列留存：次月留存普遍 20-30%，之后趋稳", fontsize=15, weight="bold")
    fig.tight_layout()
    fig.savefig(FIGURES / "04_cohort_retention.png")
    plt.close(fig)

    retention.round(2).to_csv(OUTPUT / "cohort_retention.csv")
    return retention


def repurchase_stats(df: pd.DataFrame) -> pd.DataFrame:
    """复购率 & 购买间隔。"""
    per_cust = df.groupby("CustomerID").agg(
        orders=("InvoiceNo", "nunique"),
        first=("InvoiceDate", "min"),
        last=("InvoiceDate", "max"),
        revenue=("Revenue", "sum"),
    )
    per_cust["repeat"] = per_cust["orders"] > 1
    per_cust["tenure_days"] = (per_cust["last"] - per_cust["first"]).dt.days

    repeat_rate = per_cust["repeat"].mean()
    stats = pd.DataFrame([
        {"metric": "客户总数", "value": len(per_cust)},
        {"metric": "复购客户数", "value": int(per_cust["repeat"].sum())},
        {"metric": "复购率", "value": round(repeat_rate, 4)},
        {"metric": "人均订单数", "value": round(per_cust["orders"].mean(), 2)},
        {"metric": "单次客户占比", "value": round(1 - repeat_rate, 4)},
        {"metric": "下单≥5次客户占比", "value": round((per_cust["orders"] >= 5).mean(), 4)},
    ])
    per_cust.reset_index().to_csv(OUTPUT / "customer_summary.csv", index=False)
    stats.to_csv(OUTPUT / "repurchase_stats.csv", index=False)
    return stats


# ---------------------------------------------------------------- Q5 区域时段
def geo_time_analysis(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    country = (
        df.groupby("Country")
        .agg(revenue=("Revenue", "sum"), orders=("InvoiceNo", "nunique"),
             customers=("CustomerID", "nunique"))
        .reset_index()
        .sort_values("revenue", ascending=False)
    )
    country["revenue_pct"] = country["revenue"] / country["revenue"].sum()

    dow_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    dow_cn = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    by_dow = df.groupby("DayOfWeek")["Revenue"].sum().reindex(dow_order).fillna(0)
    by_hour = df.groupby("Hour")["Revenue"].sum().reindex(range(7, 21)).fillna(0)

    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    ax = axes[0]
    top_c = country.head(10).iloc[::-1]
    ax.barh(top_c["Country"], top_c["revenue"] / 1000, color=PALETTE[0], alpha=0.85)
    ax.set_xlabel("营收（千英镑）")
    ax.set_title("营收 TOP 10 国家（英国本土占比极高）", fontsize=15, weight="bold")

    ax = axes[1]
    ax.plot(by_hour.index, by_hour.values / 1000, color=PALETTE[1], lw=2.5, marker="o")
    ax.fill_between(by_hour.index, by_hour.values / 1000, color=PALETTE[1], alpha=0.15)
    ax.set_xlabel("下单小时")
    ax.set_ylabel("营收（千英镑）")
    ax.set_title("下单时段分布：集中在 10-14 点", fontsize=15, weight="bold")
    ax.set_xticks(list(by_hour.index))
    fig.tight_layout()
    fig.savefig(FIGURES / "05_geo_time.png")
    plt.close(fig)

    # 星期 + 小时热力图
    grid = df.pivot_table(index="DayOfWeek", columns="Hour", values="Revenue",
                          aggfunc="sum").reindex(dow_order)
    fig, ax = plt.subplots(figsize=(13, 5))
    sns.heatmap(grid / 1000, cmap="YlOrRd", ax=ax,
                cbar_kws={"label": "营收（千英镑）"},
                xticklabels=[f"{h}:00" for h in grid.columns], yticklabels=dow_cn)
    ax.set_title("营收热力图：周四中午是全年最强时段", fontsize=15, weight="bold")
    ax.set_xlabel("")
    ax.set_ylabel("")
    fig.tight_layout()
    fig.savefig(FIGURES / "06_heatmap_dow_hour.png")
    plt.close(fig)

    country.to_csv(OUTPUT / "country_revenue.csv", index=False)
    pd.DataFrame({"day_of_week": by_dow.index, "revenue": by_dow.values}).to_csv(
        OUTPUT / "revenue_by_dow.csv", index=False)
    return country, pd.DataFrame({"hour": by_hour.index, "revenue": by_hour.values})


# ---------------------------------------------------------------- 客单结构
def order_value_analysis(df: pd.DataFrame) -> pd.DataFrame:
    """订单金额分布 & 单笔订单商品件数分布。"""
    orders = df.groupby("InvoiceNo").agg(
        revenue=("Revenue", "sum"), items=("Quantity", "sum"),
        skus=("StockCode", "nunique"), customer=("CustomerID", "first"),
    ).reset_index()

    fig, axes = plt.subplots(1, 2, figsize=(15, 5.5))
    ax = axes[0]
    ax.hist(np.log1p(orders["revenue"]), bins=60, color=PALETTE[0], alpha=0.85)
    ax.set_xlabel("订单金额 log(1+£)")
    ax.set_ylabel("订单数")
    ax.set_title(f"订单金额分布（右偏），中位数 £{orders['revenue'].median():.0f}",
                 fontsize=14, weight="bold")
    ax.axvline(np.log1p(orders["revenue"].median()), color=PALETTE[3], ls="--", lw=2)

    ax = axes[1]
    ax.hist(np.log1p(orders["items"]), bins=60, color=PALETTE[2], alpha=0.85)
    ax.set_xlabel("订单件数 log(1+n)")
    ax.set_ylabel("订单数")
    ax.set_title(f"订单件数分布，中位数 {orders['items'].median():.0f} 件",
                 fontsize=14, weight="bold")
    ax.axvline(np.log1p(orders["items"].median()), color=PALETTE[3], ls="--", lw=2)
    fig.tight_layout()
    fig.savefig(FIGURES / "07_order_distribution.png")
    plt.close(fig)

    orders.to_csv(OUTPUT / "orders.csv", index=False)
    return orders


def main() -> None:
    setup_style()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    FIGURES.mkdir(parents=True, exist_ok=True)

    print("读取清洗后数据 ...")
    df = pd.read_csv(PROCESSED, parse_dates=["InvoiceDate"])
    print(f"  {len(df):,} 行 / {df['CustomerID'].nunique():,} 客户")

    print("Q1 大盘走势 ...")
    monthly = overall_trend(df)
    yoy = yoy_growth(monthly)

    print("Q2 商品结构 ...")
    prod, pareto = product_analysis(df)

    print("Q3 RFM 客户分层 ...")
    rfm = rfm_analysis(df)

    print("Q4 留存与复购 ...")
    retention = cohort_retention(df)
    rep = repurchase_stats(df)

    print("Q5 区域与时段 ...")
    country, hours = geo_time_analysis(df)

    print("客单结构 ...")
    orders = order_value_analysis(df)

    # ---- 汇总关键指标，供报告引用 ----
    total_rev = df["Revenue"].sum()
    df_rev = df[~df["IsOutlier"]]["Revenue"].sum()
    summary = pd.DataFrame([
        {"指标": "分析时间范围", "值": f"{df['InvoiceDate'].min():%Y-%m-%d} ~ {df['InvoiceDate'].max():%Y-%m-%d}"},
        {"指标": "有效交易行数", "值": f"{len(df):,}"},
        {"指标": "订单数", "值": f"{df['InvoiceNo'].nunique():,}"},
        {"指标": "客户数", "值": f"{df['CustomerID'].nunique():,}"},
        {"指标": "SKU 数", "值": f"{df['StockCode'].nunique():,}"},
        {"指标": "营收总额", "值": f"£{total_rev:,.0f}"},
        {"指标": "剔除极端值后营收", "值": f"£{df_rev:,.0f}"},
        {"指标": "客单价 AOV", "值": f"£{total_rev / df['InvoiceNo'].nunique():,.2f}"},
        {"指标": "人均消费 ARPU", "值": f"£{total_rev / df['CustomerID'].nunique():,.2f}"},
        {"指标": "复购率", "值": f"{rep.loc[rep.metric == '复购率', 'value'].iloc[0]:.1%}"},
        {"指标": "80% 营收来自 SKU 占比", "值": f"{pareto['sku_pct_for_80pct'].iloc[0]:.1%}"},
        {"指标": "英国本土营收占比", "值": f"{country.iloc[0]['revenue_pct']:.1%}"},
        {"指标": "次月留存率（中位）", "值": f"{retention[1].median():.1f}%"},
    ])
    summary.to_csv(OUTPUT / "kpi_summary.csv", index=False)

    print("\n=== 核心指标 ===")
    print(summary.to_string(index=False))
    print(f"\n图表输出: {FIGURES}")


if __name__ == "__main__":
    main()
