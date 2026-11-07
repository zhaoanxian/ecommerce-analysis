"""
把清洗后的数据导入 SQLite，并执行 sql/analysis_queries.sql 里的查询。
展示「同一套分析，既可以用 pandas 也可以用 SQL 完成」——面试常问。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "processed" / "ecommerce.db"
CLEAN_CSV = ROOT / "data" / "processed" / "clean_transactions.csv"
SQL_FILE = ROOT / "sql" / "analysis_queries.sql"


def build_database() -> sqlite3.Connection:
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_csv(CLEAN_CSV, parse_dates=["InvoiceDate"])
    # 只导入分析需要的列，减小库体积
    df[["InvoiceNo", "StockCode", "Description", "Quantity", "InvoiceDate",
        "UnitPrice", "CustomerID", "Country", "Revenue"]].to_sql(
        "clean_transactions", conn, if_exists="replace", index=False)
    conn.execute(
        "CREATE INDEX idx_invdate ON clean_transactions(InvoiceDate)")
    conn.execute(
        "CREATE INDEX idx_customer ON clean_transactions(CustomerID)")
    conn.commit()
    return conn


def run_queries(conn: sqlite3.Connection) -> list[tuple[str, pd.DataFrame]]:
    sql_text = SQL_FILE.read_text(encoding="utf-8")
    # 按分号切分语句，过滤掉纯注释块
    statements = [s.strip() for s in sql_text.split(";") if s.strip()]
    results = []
    for stmt in statements:
        if all(line.strip().startswith("--") or not line.strip() for line in stmt.splitlines()):
            continue
        try:
            results.append((stmt, pd.read_sql(stmt, conn)))
        except Exception as e:  # noqa: BLE001
            print(f"[跳过] {e}", file=sys.stderr)
    return results


def main() -> None:
    print("建库 ...")
    conn = build_database()
    print(f"  {DB_PATH}")
    size_mb = DB_PATH.stat().st_size / 1048576
    print(f"  库大小 {size_mb:.1f} MB")

    results = run_queries(conn)
    out_dir = ROOT / "output" / "sql_results"
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, (stmt, res) in enumerate(results, 1):
        first_sql_line = next(
            l.strip().lstrip('-').strip() for l in stmt.splitlines() if l.strip() and not l.strip().startswith('--'))
        print(f"\n--- 查询 {i}: {first_sql_line[:60]} ---")
        print(res.head(8).to_string(index=False))
        res.to_csv(out_dir / f"query_{i}.csv", index=False)

    conn.close()
    print(f"\n共 {len(results)} 条查询，结果已存至 {out_dir}")


if __name__ == "__main__":
    main()
