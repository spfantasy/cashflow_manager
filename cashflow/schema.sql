-- 现金流管理系统 数据库结构
--
-- 金额字段说明：SQLite 没有 DECIMAL 类型（NUMERIC 亲和性会把 '15.50' 转成 REAL
-- 从而丢精度），因此金额以「精确十进制字符串」保存在 TEXT 列里，聚合在 Python 侧
-- 用 decimal.Decimal 完成。

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- --------------------------------------------------------------------------
-- 卖家 / 用户配置（页面6）
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS seller (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_name       TEXT    NOT NULL UNIQUE,
    match_regex       TEXT    NOT NULL DEFAULT '',   -- 匹配 item 标题的正则，空=不参与匹配
    share_membership  INTEGER NOT NULL DEFAULT 0,    -- 1=参与会员费/发款费均摊
    sort_order        INTEGER NOT NULL DEFAULT 100,  -- 匹配优先级，小者先匹配
    created_at        TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at        TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

-- --------------------------------------------------------------------------
-- ebay_item：来源「报告 - 下载 - 所有订单」
-- 主键 item_id，已存在则跳过写入。
-- 除 guide 点名的字段外，额外保存 X（运费分配）所需的派生列，
-- 供交易报告导入时计算 Y（成交费-固定）使用。
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ebay_item (
    item_id            TEXT PRIMARY KEY,
    order_id           TEXT,
    record_id          TEXT,                          -- 销售记录编号
    buyer_username     TEXT,
    buyer_country      TEXT,
    item_name          TEXT,
    seller_name        TEXT NOT NULL DEFAULT 'Unknown',
    seller_manual      INTEGER NOT NULL DEFAULT 0,    -- 1=页面4人工调整过，重新匹配时跳过
    track_id           TEXT,
    lot                INTEGER NOT NULL DEFAULT 1,

    -- 以下为分配算法所需的扩展列
    item_price         TEXT,                          -- 物品小计（成交价）
    order_shipping     TEXT,                          -- 订单实收运费
    base_shipping      TEXT,                          -- 按追踪号判定的基础运费 9.99/35.99
    allocated_shipping TEXT,                          -- X：分摊到本 item 的运费收入
    shipping_reminder  TEXT,                          -- X 的计算说明
    payment_date       INTEGER,                       -- 付款日期 YYYYMMDD
    order_seq          INTEGER NOT NULL DEFAULT 0,    -- 订单内表格顺序，0=第一笔
    source_file        TEXT,
    created_at         TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE INDEX IF NOT EXISTS idx_ebay_item_order   ON ebay_item(order_id);
CREATE INDEX IF NOT EXISTS idx_ebay_item_seller  ON ebay_item(seller_name);

-- --------------------------------------------------------------------------
-- ebay_item_cashflow：现金流明细
-- 主键 cashflow_id，已存在则跳过写入。
-- order_id 冗余保存一份：交易报告里存在「订单明细未导入」的 item（跨月订单），
-- 这些现金流 join 不到 ebay_item，详情页仍需要能按订单号筛出来。
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ebay_item_cashflow (
    cashflow_id     TEXT PRIMARY KEY,
    item_id         TEXT NOT NULL,
    order_id        TEXT,
    cashflow_source TEXT NOT NULL,
    cashflow_type   TEXT NOT NULL,
    amount          TEXT NOT NULL,                    -- 精确十进制字符串
    cashflow_date   INTEGER NOT NULL DEFAULT 0,       -- YYYYMMDD
    reminder        TEXT NOT NULL DEFAULT '',
    source_file     TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE INDEX IF NOT EXISTS idx_cashflow_item  ON ebay_item_cashflow(item_id);
CREATE INDEX IF NOT EXISTS idx_cashflow_date  ON ebay_item_cashflow(cashflow_date);
CREATE INDEX IF NOT EXISTS idx_cashflow_order ON ebay_item_cashflow(order_id);

-- --------------------------------------------------------------------------
-- import_log：导入历史，便于追溯
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS import_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name    TEXT NOT NULL,
    file_kind    TEXT NOT NULL,
    inserted     INTEGER NOT NULL DEFAULT 0,
    skipped      INTEGER NOT NULL DEFAULT 0,
    failed       INTEGER NOT NULL DEFAULT 0,
    detail       TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
