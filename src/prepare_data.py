"""
数据清洗模块
------------
输入: data/raw/ 下的原始 Excel（UCI Online Retail II，两个 sheet：2009-2010、2010-2011）
输出: data/processed/clean_transactions.csv（清洗后的明细表，含衍生字段）

清洗规则（每条规则都对应一个真实业务问题，可在 README / 报告中说明）:
1. 合并两个年度的 sheet，统一列名
2. 去掉完全重复的行（同一订单同一商品重复录入）
3. 剔除取消订单（InvoiceNo 以 'C' 开头）——退款单不代表销售收入
4. 剔除数量 <= 0 的记录（退货/库存调整）
5. 剔除单价 <= 0 的记录（赠品、坏账调整）
6. 剔除缺少 Customer ID 的记录（无法归因到用户，做用户分析时必须排除）
7. 按 IQR 法标记异常大额订单，不直接删除，只打标（供后续敏感性分析）
8. 新增衍生字段: Revenue, InvoiceDate, Year, Month, DayOfWeek, Hour
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"

# 列名标准化映射（原始数据列名大小写/空格不统一）
COLUMN_MAP = {
    "Invoice": "InvoiceNo",
    "InvoiceNo": "InvoiceNo",
    "StockCode": "StockCode",
    "Description": "Description",
    "Quantity": "Quantity",
    "InvoiceDate": "InvoiceDate",
    "Price": "UnitPrice",
    "UnitPrice": "UnitPrice",
    "Customer ID": "CustomerID",
    "CustomerID": "CustomerID",
    "Country": "Country",
}


def load_raw() -> pd.DataFrame:
    """读取 data/raw 下所有 csv / xlsx，合并成一张长表。"""
    frames: list[pd.DataFrame] = []

    csv_files = sorted(RAW_DIR.glob("*.csv"))
    for f in csv_files:
        # UCI 原始 csv 是 latin-1 编码，直接 utf-8 会报错
        for enc in ("utf-8", "latin-1"):
            try:
                df = pd.read_csv(f, encoding=enc, dtype={"Customer ID": "float"})
                break
            except UnicodeDecodeError:
                continue
        df["_source"] = f.name
        frames.append(df)

    xlsx_files = sorted([p for p in RAW_DIR.glob("*.xlsx") if not p.name.startswith("~$")])
    for f in xlsx_files:
        # 所有 sheet 都读，Online Retail II 的两年数据分两个 sheet
        sheets = pd.read_excel(f, sheet_name=None)
        for sheet_name, df in sheets.items():
            df["_source"] = f"{f.name}::{sheet_name}"
            frames.append(df)

    if not frames:
        raise FileNotFoundError(
            f"未在 {RAW_DIR} 找到数据文件。请先按 README 的『获取数据』一节下载原始数据。"
        )

    raw = pd.concat(frames, ignore_index=True)
    raw = raw.rename(columns={c: COLUMN_MAP.get(c.strip(), c.strip()) for c in raw.columns})
    return raw


def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """执行清洗，返回 (清洗后数据, 清洗日志)。"""
    log: list[dict] = []

    def record(step: str, before: int, after: int, note: str = "") -> None:
        log.append(
            {
                "step": step,
                "rows_before": before,
                "rows_after": after,
                "rows_removed": before - after,
                "note": note,
            }
        )

    n0 = len(df)
    record("原始数据", n0, n0, "合并全部 sheet")

    # --- 1. 去重 ---
    n = len(df)
    df = df.drop_duplicates()
    record("去除完全重复行", n, len(df))

    # --- 2. 类型转换 ---
    df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"], errors="coerce")
    n = len(df)
    df = df.dropna(subset=["InvoiceDate"])
    record("剔除日期无法解析的行", n, len(df))

    df["InvoiceNo"] = df["InvoiceNo"].astype(str).str.strip()
    df["StockCode"] = df["StockCode"].astype(str).str.strip()

    # --- 3. 取消订单 ---
    n = len(df)
    is_cancel = df["InvoiceNo"].str.upper().str.startswith("C")
    df = df[~is_cancel]
    record("剔除取消订单(C开头)", n, len(df), "退款单不计入销售收入")

    # --- 4. 数量 <= 0 ---
    n = len(df)
    df = df[df["Quantity"] > 0]
    record("剔除数量<=0", n, len(df), "退货/库存调整记录")

    # --- 5. 单价 <= 0 ---
    n = len(df)
    df = df[df["UnitPrice"] > 0]
    record("剔除单价<=0", n, len(df), "赠品/坏账调整记录")

    # --- 6. 缺失 CustomerID ---
    n = len(df)
    df = df[df["CustomerID"].notna()]
    record("剔除缺失CustomerID", n, len(df), "无法归因到用户")

    # --- 7. 异常值打标（不删除）---
    df = df.copy()
    df["Revenue"] = df["Quantity"] * df["UnitPrice"]

    q1, q3 = df["Revenue"].quantile([0.25, 0.75])
    iqr = q3 - q1
    upper = q3 + 3 * iqr  # 用 3 倍 IQR 放宽阈值，只抓极端值
    df["IsOutlier"] = df["Revenue"] > upper
    df["CustomerID"] = df["CustomerID"].astype(int)
    df["Description"] = (
        df["Description"].fillna("UNKNOWN").astype(str).str.strip().str.upper()
    )

    # --- 8. 衍生字段 ---
    df["Year"] = df["InvoiceDate"].dt.year
    df["Month"] = df["InvoiceDate"].dt.to_period("M").astype(str)
    df["DayOfWeek"] = df["InvoiceDate"].dt.day_name()
    df["Hour"] = df["InvoiceDate"].dt.hour

    df = df.sort_values("InvoiceDate").reset_index(drop=True)
    record("最终可用数据", n0, len(df), f"总计剔除 {n0 - len(df):,} 行 ({1 - len(df)/n0:.1%})")

    return df, pd.DataFrame(log)


def main() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    raw = load_raw()
    clean_df, log_df = clean(raw)

    clean_df.to_csv(PROCESSED_DIR / "clean_transactions.csv", index=False)
    log_df.to_csv(PROCESSED_DIR / "cleaning_log.csv", index=False)

    print(f"原始记录: {len(raw):,}")
    print(f"清洗后  : {len(clean_df):,}")
    print(f"保留比例: {len(clean_df) / len(raw):.1%}")
    print(f"时间范围: {clean_df['InvoiceDate'].min()} ~ {clean_df['InvoiceDate'].max()}")
    print(f"客户数  : {clean_df['CustomerID'].nunique():,}")
    print(f"订单数  : {clean_df['InvoiceNo'].nunique():,}")
    print(f"营收总额: £{clean_df['Revenue'].sum():,.0f}")
    print("\n清洗日志:")
    print(log_df.to_string(index=False))


if __name__ == "__main__":
    main()
