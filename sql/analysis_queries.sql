-- ============================================================
-- SQL 分析查询集（SQLite 语法）
-- 用法：
--   python3 src/run_sql.py        # 自动建库并运行所有查询
-- 或手动:
--   sqlite3 ecommerce.db < sql/analysis_queries.sql
-- ============================================================

-- 1. 月度营收趋势
SELECT
    strftime('%Y-%m', InvoiceDate) AS month,
    ROUND(SUM(Revenue), 2)          AS revenue,
    COUNT(DISTINCT InvoiceNo)       AS orders,
    COUNT(DISTINCT CustomerID)      AS customers
FROM clean_transactions
GROUP BY month
ORDER BY month;

-- 2. 营收 TOP 20 商品
SELECT
    StockCode,
    MAX(Description)                AS description,
    ROUND(SUM(Revenue), 2)          AS revenue,
    SUM(Quantity)                   AS total_qty,
    COUNT(DISTINCT InvoiceNo)       AS orders
FROM clean_transactions
GROUP BY StockCode
ORDER BY revenue DESC
LIMIT 20;

-- 3. 客户 RFM（简化版：R=最近购买距今天数, F=订单数, M=累计消费）
WITH cust AS (
    SELECT
        CustomerID,
        CAST(JULIANDAY('2011-12-10') - JULIANDAY(MAX(InvoiceDate)) AS INTEGER) AS recency,
        COUNT(DISTINCT InvoiceNo)  AS frequency,
        ROUND(SUM(Revenue), 2)     AS monetary
    FROM clean_transactions
    GROUP BY CustomerID
)
SELECT * FROM cust ORDER BY monetary DESC LIMIT 30;

-- 4. 复购率
SELECT
    COUNT(*)                                                   AS total_customers,
    SUM(CASE WHEN order_cnt > 1 THEN 1 ELSE 0 END)             AS repeat_customers,
    ROUND(1.0 * SUM(CASE WHEN order_cnt > 1 THEN 1 ELSE 0 END) / COUNT(*), 4) AS repeat_rate
FROM (
    SELECT CustomerID, COUNT(DISTINCT InvoiceNo) AS order_cnt
    FROM clean_transactions
    GROUP BY CustomerID
);

-- 5. 各国营收与占比
WITH c AS (
    SELECT Country,
           ROUND(SUM(Revenue), 2) AS revenue
    FROM clean_transactions
    GROUP BY Country
)
SELECT
    Country,
    revenue,
    ROUND(100.0 * revenue / (SELECT SUM(revenue) FROM c), 2) AS revenue_pct
FROM c
ORDER BY revenue DESC
LIMIT 15;

-- 6. 一周中各天 + 各时段的营收矩阵
SELECT
    CASE CAST(strftime('%w', InvoiceDate) AS INTEGER)
        WHEN 0 THEN '周日' WHEN 1 THEN '周一' WHEN 2 THEN '周二' WHEN 3 THEN '周三'
        WHEN 4 THEN '周四' WHEN 5 THEN '周五' WHEN 6 THEN '周六'
    END                                          AS day_of_week,
    strftime('%H', InvoiceDate)                  AS hour,
    ROUND(SUM(Revenue), 2)                       AS revenue
FROM clean_transactions
GROUP BY day_of_week, hour
ORDER BY day_of_week, hour;

-- 7. 高价值客户（累计消费 TOP 5%）贡献的营收占比
WITH cust_rev AS (
    SELECT CustomerID, SUM(Revenue) AS revenue
    FROM clean_transactions
    GROUP BY CustomerID
),
ranked AS (
    SELECT CustomerID, revenue,
           NTILE(100) OVER (ORDER BY revenue DESC) AS percentile
    FROM cust_rev
)
SELECT
    MAX(CASE WHEN percentile <= 5 THEN revenue ELSE 0 END) AS top5_revenue,
    ROUND(SUM(revenue), 2)                                 AS total_revenue,
    ROUND(100.0 * SUM(CASE WHEN percentile <= 5 THEN revenue ELSE 0 END) / SUM(revenue), 2)
        AS top5_pct
FROM ranked;

-- 8. 平均订单间隔（客户连续两次购买间隔天数）
WITH order_dates AS (
    SELECT CustomerID, InvoiceNo, MIN(InvoiceDate) AS order_date
    FROM clean_transactions
    GROUP BY CustomerID, InvoiceNo
),
gaps AS (
    SELECT
        CustomerID,
        JULIANDAY(order_date) - JULIANDAY(
            LAG(order_date) OVER (PARTITION BY CustomerID ORDER BY order_date)
        ) AS gap_days
    FROM order_dates
)
SELECT
    ROUND(AVG(gap_days), 1)  AS avg_gap_days,
    ROUND(MIN(gap_days), 1)  AS min_gap,
    ROUND(MAX(gap_days), 1)  AS max_gap
FROM gaps
WHERE gap_days IS NOT NULL;
