"""
CLV 客户生命周期价值建模
------------------------
模型：BG/NBD（预测未来购买次数）+ Gamma-Gamma（预测客单价值）
验证：时间切分法 —— 用 2010-12-01 前的数据训练，
      预测其后 12 个月的购买次数，与真实值对比（MAE / 相关系数）。

兼容性说明：RFM 输入矩阵为手动计算（本文件 build_calibration /
build_summary 函数），与 lifetimes.utils 的输出逐客户一致
（已验证 max|Δ| = 0），但不受 lifetimes 库与新版 pandas 的
兼容性问题影响。

业务口径（BG/NBD 标准输入）：
 交易 = 客户在某一天的全部购买合并为一次（freq="D"）
  frequency = 重复购买次数 = 交易数 - 1
  recency   = 首次与最后一次购买的间隔天数
  T         = 首次购买距观测截止（或校准截止）的天数
  monetary  = 重复交易的人均金额（Gamma-Gamma 用）

输出：
  output/clv_customer.csv    每个客户的 CLV 及预测参数
  output/clv_validation.csv  模型验证指标
  reports/figures/08_clv.png 模型验证图 + CLV 分布图
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from lifetimes import BetaGeoFitter, GammaGammaFitter

plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "Noto Sans CJK JP",
                                   "Noto Serif CJK SC", "Noto Serif CJK JP",
                                   "WenQuanYi Zen Hei", "SimHei", "Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed" / "clean_transactions.csv"
OUTPUT = ROOT / "output"
FIGURES = ROOT / "reports" / "figures"

CALIB_END = pd.Timestamp("2010-12-01")  # 校准期/验证期切分点
PREDICT_MONTHS = 12                      # CLV 预测窗口


def load() -> pd.DataFrame:
    df = pd.read_csv(PROCESSED, parse_dates=["InvoiceDate"])
    df["day"] = df["InvoiceDate"].dt.normalize()
    return df


# ---------------------------------------------------------------- RFM 输入
def build_transactions(df: pd.DataFrame) -> pd.DataFrame:
    """按 (客户, 天) 合并交易，返回客户×天的交易表。"""
    return (
        df.groupby(["CustomerID", "day"])
        .agg(value=("Revenue", "sum"))
        .reset_index()
    )


def build_calibration(tx: pd.DataFrame, obs_end: pd.Timestamp) -> pd.DataFrame:
    """校准期(切分点前)输入 + 验证期真实购买次数。"""
    cal_tx = tx[tx["day"] < CALIB_END]
    g = cal_tx.groupby("CustomerID")["day"]
    cal = pd.DataFrame({"n": g.size(), "first": g.min(), "last": g.max()})
    cal["frequency"] = cal["n"] - 1
    cal["recency"] = (cal["last"] - cal["first"]).dt.days
    cal["T"] = (CALIB_END - cal["first"]).dt.days
    cal = cal[cal["frequency"] > 0]

    fh = tx[tx["day"] >= CALIB_END].groupby("CustomerID").size()
    cal["frequency_holdout"] = fh.reindex(cal.index).fillna(0)
    cal["duration_holdout"] = (obs_end - CALIB_END).days
    return cal


def build_summary(tx: pd.DataFrame, obs_end: pd.Timestamp) -> pd.DataFrame:
    """全量观测期的 BG/NBD + Gamma-Gamma 输入矩阵。"""
    g = tx.groupby("CustomerID")
    s = pd.DataFrame({
        "n": g.size(),
        "first": g["day"].min(),
        "last": g["day"].max(),
        "total_value": g["value"].sum(),
    })
    s["frequency"] = s["n"] - 1
    s["recency"] = (s["last"] - s["first"]).dt.days
    s["T"] = (obs_end - s["first"]).dt.days

    # monetary = 重复交易（去掉第一次）的人均金额；无重复购买则为 0
    first_value = tx.sort_values("day").groupby("CustomerID")["value"].first()
    repeat_value = s["total_value"] - first_value
    s["monetary_value"] = np.where(
        s["frequency"] > 0, repeat_value / s["frequency"].replace(0, 1), 0.0
    )
    s.loc[s["frequency"] == 0, "monetary_value"] = 0.0
    return s.reset_index()


# ---------------------------------------------------------------- 建模
def fit_and_validate(tx: pd.DataFrame, obs_end: pd.Timestamp):
    cal = build_calibration(tx, obs_end)

    bgf = BetaGeoFitter(penalizer_coef=0.01)
    bgf.fit(cal["frequency"], cal["recency"], cal["T"])

    cal["pred_holdout"] = bgf.predict(
        cal["duration_holdout"], cal["frequency"], cal["recency"], cal["T"]
    )
    actual = cal["frequency_holdout"]
    pred = cal["pred_holdout"]
    metrics = {
        "calibration_end": CALIB_END.date().isoformat(),
        "holdout_days": int(cal["duration_holdout"].iloc[0]),
        "n_customers": int(len(cal)),
        "mae": float(np.abs(actual - pred).mean()),
        "rmse": float(np.sqrt(((actual - pred) ** 2).mean())),
        "pearson_r": float(np.corrcoef(actual, pred)[0, 1]),
        "actual_mean": float(actual.mean()),
        "pred_mean": float(pred.mean()),
    }
    return bgf, metrics, cal


def compute_clv(tx: pd.DataFrame, obs_end: pd.Timestamp, bgf: BetaGeoFitter):
    summary = build_summary(tx, obs_end)

    repeat = summary[(summary["frequency"] > 0) & (summary["monetary_value"] > 0)]
    ggf = GammaGammaFitter(penalizer_coef=0.01)
    ggf.fit(repeat["frequency"], repeat["monetary_value"])

    summary["expected_avg_value"] = ggf.conditional_expected_average_profit(
        summary["frequency"], summary["monetary_value"]
    )
    t_days = PREDICT_MONTHS * 30.44
    summary["predicted_purchases_12m"] = bgf.predict(
        t_days, summary["frequency"], summary["recency"], summary["T"]
    )
    summary["clv_12m"] = (
        summary["predicted_purchases_12m"] * summary["expected_avg_value"]
    )

    valid = summary.dropna(subset=["clv_12m"])
    summary["clv_decile"] = pd.NA
    summary.loc[valid.index, "clv_decile"] = pd.qcut(
        valid["clv_12m"].rank(method="first"), 10, labels=range(10, 0, -1)
    ).astype(int)
    return summary, ggf


def make_figures(metrics: dict, cal: pd.DataFrame, clv: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(15, 6))

    ax = axes[0]
    grp = cal.groupby(cal["frequency_holdout"].clip(upper=6))["pred_holdout"].mean()
    act = cal.groupby(cal["frequency_holdout"].clip(upper=6)).size()
    ax.bar(grp.index - 0.18, grp.index, width=0.36,
           color="#4A9B7F", alpha=0.85, label="实际购买次数")
    ax.bar(grp.index + 0.18, grp.values, width=0.36,
           color="#2E5C8A", alpha=0.85, label="模型预测均值")
    for x in grp.index:
        ax.text(x, act.loc[x] / 5, f"n={act.loc[x]}", ha="center",
                fontsize=9, color="grey")
    ax.set_xlabel("验证期实际购买次数（>6 截断）")
    ax.set_ylabel("次数")
    ax.set_title(
        f"BG/NBD 模型验证（{metrics['holdout_days']} 天）\n"
        f"MAE={metrics['mae']:.2f}  Pearson r={metrics['pearson_r']:.2f}",
        fontsize=14, weight="bold",
    )
    ax.legend()

    ax = axes[1]
    dec = clv.dropna(subset=["clv_decile"]).groupby("clv_decile").agg(
        clv=("clv_12m", "sum"))
    dec["clv_pct"] = dec["clv"] / dec["clv"].sum()
    ax.barh([f"第{d}档" for d in dec.index][::-1], dec["clv_pct"][::-1] * 100,
            color=["#C1554A" if d == dec.index.min() else "#7B6BA8"
                   for d in dec.index[::-1]], alpha=0.88)
    for i, (_, row) in enumerate(dec[::-1].iterrows()):
        ax.text(row["clv_pct"] * 100, i, f"  {row['clv_pct']:.1%}",
                va="center", fontsize=11, weight="bold")
    ax.set_xlabel("未来 12 个月预测 CLV 占比 (%)")
    ax.set_title("CLV 十分位分布：头部 10% 客户的预测价值占比",
                 fontsize=14, weight="bold")

    fig.tight_layout()
    fig.savefig(FIGURES / "08_clv.png")
    plt.close(fig)


def main() -> None:
    df = load()
    obs_end = df["day"].max()
    tx = build_transactions(df)
    print(f"数据 {len(df):,} 行 / {df['CustomerID'].nunique():,} 客户 / "
          f"{len(tx):,} 客户×天交易")

    print("① 时间切分验证 BG/NBD ...")
    bgf, metrics, cal = fit_and_validate(tx, obs_end)
    print(f"   模型参数: r={bgf.params_['r']:.3f}, alpha={bgf.params_['alpha']:.2f}, "
          f"a={bgf.params_['a']:.3f}, b={bgf.params_['b']:.3f}")
    print(f"   验证期 {metrics['holdout_days']} 天 / {metrics['n_customers']} 客户")
    print(f"   MAE={metrics['mae']:.3f}  RMSE={metrics['rmse']:.3f}  "
          f"Pearson r={metrics['pearson_r']:.3f}")
    print(f"   实际均值 {metrics['actual_mean']:.3f} vs 预测均值 {metrics['pred_mean']:.3f}")

    print("② Gamma-Gamma + CLV 计算 ...")
    clv, ggf = compute_clv(tx, obs_end, bgf)
    print(f"   GG 参数: p={ggf.params_['p']:.3f}, q={ggf.params_['q']:.3f}, "
          f"v={ggf.params_['v']:.2f}")

    top10_pct = clv.sort_values("clv_12m", ascending=False).head(
        max(1, len(clv) // 10))["clv_12m"].sum() / clv["clv_12m"].sum()
    print(f"   未来 {PREDICT_MONTHS} 个月总预测 CLV: £{clv['clv_12m'].sum():,.0f}")
    print(f"   头部 10% 客户占预测 CLV: {top10_pct:.1%}")

    make_figures(metrics, cal, clv)

    clv_out = clv.rename(columns={
        "frequency": "repeat_purchases", "recency": "recency_days",
        "T": "tenure_days", "monetary_value": "avg_order_value_hist",
    })
    clv_out.to_csv(OUTPUT / "clv_customer.csv", index=False)
    pd.DataFrame([metrics]).to_csv(OUTPUT / "clv_validation.csv", index=False)
    print("\n输出: output/clv_customer.csv, clv_validation.csv, reports/figures/08_clv.png")


if __name__ == "__main__":
    main()
