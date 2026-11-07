"""
Streamlit 交互式经营看板
------------------------
运行方式（在项目根目录）:
    streamlit run src/dashboard.py
浏览器会自动打开 http://localhost:8501
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
PROCESSED = ROOT / "data" / "processed" / "clean_transactions.csv"

st.set_page_config(page_title="电商经营看板", page_icon="📊", layout="wide")


@st.cache_data
def load_transactions() -> pd.DataFrame:
    return pd.read_csv(PROCESSED, parse_dates=["InvoiceDate"])


@st.cache_data
def load_monthly() -> pd.DataFrame:
    return pd.read_csv(OUTPUT / "monthly_trend.csv")


@st.cache_data
def load_segments() -> pd.DataFrame:
    return pd.read_csv(OUTPUT / "rfm_segments.csv")


@st.cache_data
def load_country() -> pd.DataFrame:
    return pd.read_csv(OUTPUT / "country_revenue.csv")


df = load_transactions()
monthly = load_monthly()
segments = load_segments()
country = load_country()

# ---------------- 侧边栏筛选 ----------------
st.sidebar.title("📊 电商经营看板")
st.sidebar.caption("数据：UCI Online Retail II（2009-12 ~ 2011-12）")

country_options = ["全部国家"] + sorted(country["Country"].unique().tolist())
sel_country = st.sidebar.selectbox("国家筛选", country_options, index=0)

month_range = st.sidebar.slider(
    "月份范围",
    min_value=0,
    max_value=len(monthly) - 1,
    value=(0, len(monthly) - 1),
    format="",
)
sel_months = monthly.iloc[month_range[0]:month_range[1] + 1]["Month"].tolist()

st.sidebar.divider()
st.sidebar.markdown(
    "**数据口径**\n\n清洗后有效交易，已剔除取消单/退货/"
    "缺失客户ID记录。看板数据来自 `output/` 预计算结果。"
)

# ---------------- 数据按筛选条件裁剪 ----------------
view = df[df["Country"] == sel_country] if sel_country != "全部国家" else df
view = view[view["Month"].isin(sel_months)]

if view.empty:
    st.warning("当前筛选条件下没有数据，请调整侧边栏选项。")
    st.stop()

# ---------------- 顶部 KPI 卡片 ----------------
total_rev = view["Revenue"].sum()
n_orders = view["InvoiceNo"].nunique()
n_customers = view["CustomerID"].nunique()
aov = total_rev / n_orders if n_orders else 0

c1, c2, c3, c4 = st.columns(4)
c1.metric("营收总额", f"£{total_rev:,.0f}")
c2.metric("订单数", f"{n_orders:,}")
c3.metric("客户数", f"{n_customers:,}")
c4.metric("客单价 AOV", f"£{aov:,.2f}")

st.divider()

# ---------------- Tab 布局 ----------------
tab_trend, tab_product, tab_customer, tab_retention, tab_geo = st.tabs(
    ["📈 大盘走势", "🛒 商品分析", "👤 客户分层", "🔁 留存复购", "🌍 区域时段"]
)

with tab_trend:
    m = monthly[monthly["Month"].isin(sel_months)]
    st.subheader("月度营收 / 订单数走势")
    st.line_chart(m.set_index("Month")[["revenue", "orders"]], height=380)
    st.subheader("客单价走势")
    st.area_chart(m.set_index("Month")["aov"], height=260)
    with st.expander("查看明细数据"):
        st.dataframe(m, width='stretch')

with tab_product:
    st.subheader("营收 TOP 20 商品")
    if sel_country == "全部国家":
        top = (
            view.groupby(["StockCode", "Description"])["Revenue"].sum()
            .sort_values(ascending=False).head(20).reset_index()
        )
        top.index = top.index + 1
        top.index.name = "排名"
        st.dataframe(top, width='stretch')
    else:
        st.caption("单国家视图下直接从明细聚合")
        top = (
            view.groupby("Description")["Revenue"].sum()
            .sort_values(ascending=False).head(20).reset_index()
        )
        st.bar_chart(top.set_index("Description")["Revenue"], height=420)

    st.subheader("商品集中度（帕累托）")
    pareto = (
        view.groupby("StockCode")["Revenue"].sum().sort_values(ascending=False)
    )
    cum = pareto.cumsum() / pareto.sum()
    n80 = int((cum < 0.8).sum() + 1)
    sku_pct = n80 / len(pareto) if len(pareto) else 0
    k1, k2 = st.columns(2)
    k1.metric("SKU 总数", f"{len(pareto):,}")
    k2.metric("贡献 80% 营收的 SKU 占比", f"{sku_pct:.1%}")
    st.line_chart(cum.reset_index(drop=True), height=300)

with tab_customer:
    st.subheader("RFM 客户分层（基于全量数据）")
    seg = segments.copy()
    seg_show = seg[["segment", "customers", "customer_pct", "revenue",
                    "revenue_pct", "avg_recency", "avg_freq", "avg_monetary"]]
    seg_show.columns = ["分层", "人数", "人数占比", "营收", "营收占比",
                        "平均最近购买(天)", "平均频次", "人均消费"]
    styled = seg_show.style.format({
        "人数占比": "{:.1%}", "营收占比": "{:.1%}",
        "营收": "£{:,.0f}", "人均消费": "£{:,.0f}",
    })
    st.dataframe(styled, width='stretch', hide_index=True)

    c_a, c_b = st.columns(2)
    with c_a:
        st.caption("各分层营收占比")
        st.bar_chart(seg.set_index("segment")["revenue_pct"], height=320)
    with c_b:
        st.caption("各分层人数占比")
        st.bar_chart(seg.set_index("segment")["customer_pct"], height=320)

    st.info(
        f"💡 头部洞察：**{seg.iloc[0]['segment']}** 人数占 "
        f"{seg.iloc[0]['customer_pct']:.1%}，贡献营收 {seg.iloc[0]['revenue_pct']:.1%}。",
        icon="✅",
    )

with tab_retention:
    st.subheader("月度队列留存（Cohort Retention）")
    ret_path = OUTPUT / "cohort_retention.csv"
    ret = pd.read_csv(ret_path, index_col=0)
    ret.columns = [f"第{c}月" for c in ret.columns]
    ret.index.name = "首购月份"
    styled = ret.style.format("{:.0f}", na_rep="-").background_gradient(
        cmap="Blues", axis=1, vmin=0, vmax=60
    )
    st.dataframe(styled, width='stretch', height=560)
    st.caption("数值 = 该队列客户在第 N 月仍有购买的比例（%）。首列为全量基准。")

    st.subheader("复购核心指标")
    rep = pd.read_csv(OUTPUT / "repurchase_stats.csv")
    r = rep.set_index("metric")["value"]
    k1, k2, k3 = st.columns(3)
    k1.metric("复购率", f"{r['复购率']:.1%}")
    k2.metric("人均订单数", f"{r['人均订单数']:.2f}")
    k3.metric("单次客户占比", f"{r['单次客户占比']:.1%}")
    st.warning(
        "⚠️ 复购率 72.4% 但次月留存仅约 20.5%：客户呈「间隔性回流」"
        "（平均复购间隔 51.7 天），应在第 35-40 天设置召回触点。",
        icon="💡",
    )

with tab_geo:
    st.subheader("各国营收")
    co = country.copy()
    co_show = co[["Country", "revenue", "orders", "customers", "revenue_pct"]]
    co_show.columns = ["国家", "营收", "订单数", "客户数", "营收占比"]
    st.dataframe(
        co_show.style.format({"营收": "£{:,.0f}", "营收占比": "{:.2%}"}),
        width='stretch', hide_index=True,
    )
    c_a, c_b = st.columns(2)
    with c_a:
        st.caption("TOP 10 国家营收")
        top_c = co.head(10).set_index("Country")["revenue"]
        st.bar_chart(top_c, height=340)
    with c_b:
        st.caption("时段分布（按下单小时，全量数据）")
        by_hour = view.groupby("Hour")["Revenue"].sum()
        st.bar_chart(by_hour, height=340)

# ---------------- 底部说明 ----------------
st.divider()
st.caption(
    "分析口径与结论详见 reports/analysis_report.md ｜ "
    "预计算结果来自 src/analysis.py，交互筛选基于清洗后明细。"
)
