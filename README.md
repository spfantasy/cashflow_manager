# cashflow_manager · 订单-现金流管理系统

在 eBay 和物流系统之间做交易的多用户共用账户场景下，导入 eBay 导出的报表，
按**订单 / 刊登 / 用户**查询现金流并计算收益。

技术栈：**Flask + SQLite + openpyxl**，开发环境 `python run.py --debug` 启动，
发布用 **PyInstaller** 打包成 Windows 单文件 exe（GitHub Actions 自动构建）。

> 需求原文与实现细节对照见 **[docs/guide.md](docs/guide.md)**：
> 原文一字未改，文末「补充说明」记录了实测报表结构与所有需要拍板的口径。

---

## 快速开始

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

python run.py --debug            # 打开 http://127.0.0.1:5000
python -m pytest                 # 运行测试
```

常用参数：

| 参数 | 说明 |
| --- | --- |
| `--debug` | 调试模式（自动重载） |
| `--host` / `--port` | 监听地址与端口，默认 `127.0.0.1:5000` |
| `--init-db` | 只初始化数据库后退出 |
| `--no-browser` | 启动后不自动打开浏览器 |

环境变量：`CASHFLOW_DB`（数据库文件路径，默认 `<程序目录>/data/cashflow.db`）、
`CASHFLOW_UPLOAD_DIR`、`CASHFLOW_HOST`、`CASHFLOW_PORT`、`CASHFLOW_SECRET_KEY`。

打包：

```bash
pyinstaller --noconfirm --clean cashflow_manager.spec   # 产物 dist/CashflowManager.exe
```

推送/合并到 `main` 后 GitHub Actions 会跑测试并上传 Windows exe 产物。

---

## 页面

| 页面 | 路径 | 功能 |
| --- | --- | --- |
| 页面1 流水 | `/` | 按日期范围 + 用户筛选，顶部显示 amount 合计，左连接 ebay_item，支持导出 Excel |
| 页面2 详情 | `/details` | 按 item_id / order_id（**或**关系）筛选，列出每笔现金流，支持导出 Excel 与勾选删除（带二次确认） |
| 页面3 导入数据 | `/imports` | 三个拖入框分别对应三类文件，一次可拖多个，导入后展示统计；有需人工处理的记录会弹对话框 |
| 页面4 刊登调整 | `/listings` | 输入 item_id 与用户名，调整该物品的 seller_name |
| 页面5 手工帐 | `/manual` | 手工创建现金流 |
| 页面6 配置 | `/settings` | 维护 seller 列表、匹配标题的正则、是否参与会员费均摊；可一键重新匹配全部物品 |

「页面1 流水」的用户筛选同时匹配两类数据：item 的 `seller_name`，以及账户级现金流的
`item_id = ebay账户-{用户名}`。

---

## 数据模型

- `ebay_item`：主键 `item_id`，来源「报告 - 下载 - 所有订单」。除 guide 点名的字段外，
  另存 X（运费分摊）所需的派生列，供交易报告导入时计算 Y。
- `ebay_item_cashflow`：主键 `cashflow_id`，所有现金流明细。
  额外冗余一列 `order_id`：交易报告里存在「订单明细未导入」的跨月订单 item
  （实测 512 个），这些现金流 join 不到 `ebay_item`，但详情页仍要能按订单号筛出来。
- `seller`：用户配置（`match_regex`、`share_membership`）。
- `import_log`：导入历史。

两个业务表都是「主键已存在则跳过写入」，重复导入同一份文件不会产生重复数据。

**关于金额**：SQLite 没有 DECIMAL 类型（NUMERIC 亲和性会把 `'15.50'` 转成 REAL 而丢精度），
因此金额一律以**精确十进制字符串**保存在 TEXT 列，聚合在 Python 侧用 `decimal.Decimal`
完成，全程不经过 float。

---

## 导入规则

### 1. 报告 - 下载 - 所有订单（→ `ebay_item` + 成交价/运费）

多物品订单的结构是「一行订单级汇总行 + 每物品一行」：

```
[订单级] 物品编号=<空>  数量=9  成交价=US $13.41  运费与处理费=US $15.50  付款日期=Jan-17-26
[物品行] 168058590540  数量=1  成交价=US $1.00   运费与处理费=<空>        付款日期=<空>  追踪号码=ES1003...
```

单物品订单则一行同时带订单级与物品级数据。因此：**实收运费与付款日期取自订单级行**
（多物品订单的物品行上是空的），缺失时依次回退到出售日期。

每个 item 派生出两笔现金流：

| cashflow_id | 来源 | 类型 | 金额 | 日期 | reminder |
| --- | --- | --- | --- | --- | --- |
| `EBAY-TRADE-{item_id}` | ebay费用 | 成交价 | 物品小计 | 付款日期 | 空 |
| `EBAY-TRANSPORT-{item_id}` | ebay费用 | 运费 | X（见下） | 付款日期 | X 的算式 |

### 2. 付款 - 交易报告（→ 税费 / 刊登费 / 发款费 / 退款）

`类型=订单`（物品编号非空的行）：

| cashflow_id | 类型 | 金额 |
| --- | --- | --- |
| `EBAY-TAX-TRADE-{item_id}` | 成交费 | 成交费 — 因品类而异 |
| `EBAY-TAX-INTER-{item_id}` | 跨国交易费 | 跨国交易费用 |
| `EBAY-TAX-TRADEFIX-{item_id}` | 成交费 — 固定 | Y（按收入分摊订单级合计） |

日期取**发款日期**。eBay 收取的税费是代收买家的、最终全额被 eBay 取走，按 guide 不记现金流。
物品编号为 `--` 的订单级汇总行跳过（实测 26 行）。

`类型=其他费用`：只处理描述为 `Insertion Fee` 的行，日期取**发款日期**；
负数记 `EBAY-TAX-PUB-{item_id}`，正数（返还）记 `EBAY-TAX-PUBRETURN-{item_id}`，
两者 `cashflow_type` 都是「刊登费」。
**Store 订阅费在此跳过**——它在税费账单里以会员费形式导入，两边都记就重复了。

`类型=发放款项`：从描述「已扣除发款费 $5.91」解析金额，日期取**交易创建日期**，
按人头均摊给参与会员费均摊的用户，每人一行
`EBAY-TRANSACTIONFEE-{日期}-{用户}`，`item_id = ebay账户-{用户}`。

`类型=退款`：见下文「退款」。`类型=收费`（信用卡扣费）忽略。

### 3. 付款 - 税费账单（→ 会员费）

只取 `費用組別=訂用服務及一次性費用`（实测 1 行）。账单里费用是正数（21.95），
现金流记 `-21.95`，按人头均摊，每人一行 `EBAY-MEMBERSHIP-{日期}-{用户}`，
`item_id = ebay账户-{用户}`，日期取账单日期，reminder 为账单备注 + 分摊算式。

账单里的 `刊登費/成交費/跨國交易費` 与交易报告重复；`銀行提現費`（22 行）与交易报告的
「发放款项」按發款編號逐条一一对应，因此整类忽略，发款费统一从交易报告取。

---

## 费用分摊规则

三条规则都遵循同一约定：参与方 N>1 时，**前 N-1 个四舍五入到 0.01，最后一个取残值**，
保证分摊结果之和与原始总额严格相等。

### X · 按 lot 分配订单运费

1. 基础运费由追踪号码判定：`ES` 开头 28 位 → 9.99；`XX123456789XX`（2 字母+9 数字+2 字母）
   → 9.99；其余（含缺失）→ 35.99。
2. 应收运费：表格顺序上的**第一笔 = 基础运费 / N**，其余每笔 = 基础运费 / N + 合单附加运费；
   附加运费由该 item 的 lot 决定：`0<lot<=5 → 1`，`5<lot<=10 → 2`，`lot>10 → 3`。
   lot 从标题正则 `Lot(3)` / `Lot3` 解析，匹配失败记 1。
3. 系数 = 订单实收运费 / 应收运费之和，X = 应收运费 × 系数。

> 实测订单 27-14089-26755（9 个 item、lot 均为 1、实收 15.50）：
> 应收 9.99 + 8 = 17.99，系数 15.5/17.99 = 0.862，
> 第一笔 reminder `(9.99 / 9) * 0.862` → 0.96，其余 `(9.99 / 9 + 1) * 0.862` → 1.82，
> 最后一笔取残值 1.80，合计恰好 15.50。

### Y · 按收入分配订单级固定成交费

权重 = 物品小计 + 该 item 的 X；把订单下所有 `成交费 — 固定`（实测每单 -0.4，只写在
其中一行上）按权重占比摊到各 item。

> reminder 形如 `(1+0.96)/(13.41+15.50) * 0.4`。

订单明细不在 `ebay_item` 里（跨月订单）时，退回使用交易报告自身同一订单的行
（物品小计 + 该行运费与处理费）作为权重。
唯一需要 X 参与的分摊就是 Y；成交费、跨国交易费都是逐行直读。

### W · 按人头均摊

发款费与会员费在「参与会员费均摊 = 是」的用户之间等分。

> reminder 形如 `银行参考编号 MZBIL0TEWF5T66I  5.91 / 3`、
> `01 月 01 日 - 01 月 31 日  21.95 / 3`。

### 退款

退款行没有物品编号，需要按订单号反查 `ebay_item`：

- 查不到该订单的物品明细 → **导入失败**，提示录入手工账；
- 订单下物品涉及**多个卖家或多个买家** → 无法确定分摊逻辑，**导入失败**，提示录入手工账；
- 否则按 Y 的权重（物品小计 + X）分摊净额，reminder 记为 `退款编号 xxxxx`，日期取发款日期。
  单个 item 的 cashflow_id 用 `EBAY-REFUND-{退款编号}`；多个 item 时追加 `-{item_id}` 以保证主键唯一。

所有失败项都不会写入数据库，导入结束后页面会**弹出对话框**逐条列出，交由人工在页面5 补录。

---

## 边界情况

- **订单表缺失也能导入后两类文件**：只导入交易报告/税费账单时数据正常入库，
  只是页面查询时 join 不到标题等信息（Y 会退回交易报告自带的运费与处理费）。
- 退款查不到订单明细时导入失败（无法分摊）。
- 订单表里订单编号为空的历史行，按「销售记录编号」区分成不同订单分组。
- 文件尾部的统计行（如「62 笔已下载记录」「卖家用户名 : lcy-228」）会被自动跳过。
- 支持 `.csv`（自动尝试 utf-8-sig / utf-8 / gb18030 / big5 / cp1252）与 `.xlsx`。

---

## 目录结构

```
run.py                       启动入口
cashflow_manager.spec        PyInstaller 打包配置
cashflow/
  __init__.py                应用工厂
  config.py  db.py  schema.sql  repository.py  money.py  resources.py
  allocations.py             三条分摊算法（X / Y / W）
  exporters.py               Excel 导出
  importer/                  orders.py / transactions.py / invoice.py
  blueprints/                flows / details / imports / listings / manual / settings
  templates/  static/
tests/                       pytest（含用真实样例校验 guide 数字的用例）
.github/workflows/build.yml  测试 + Windows 打包
```

`description/` 为本地样例数据目录，未纳入版本控制；依赖它的测试会自动跳过。

---

## 与 guide 的差异 / 补充说明

1. **guide 说「订单表每一行可以理解为一个物品」**，实测多物品订单还有一行订单级汇总行，
   订单级字段（实收运费、付款日期）只写在那一行上，已按此解析。
2. **guide 说样例是 Excel**，实际给的是 CSV；两者都支持。
3. **guide 未给出退款分摊算法**，按确认结论：沿用 Y 的权重，且只在订单下物品同属一个卖家
   （且同一个买家）时执行，否则跳过并提示人工录入手工账。
4. **多 item 退款的 cashflow_id** 追加 `-{item_id}` 后缀以保证主键唯一（guide 的示例
   `EBAY-REFUND-5180906651` 就是单 item 场景，已保持一致）。
5. **金额单位**：guide 要求 BigDecimal 不用 float。SQLite 无对应类型，改为「精确十进制字符串 +
   Decimal 运算」，导出 xlsx 时受 Excel 本身限制写为 2 位小数数字。
6. **新增「重新匹配」按钮**：配置好正则后，已入库的 item 不会因为重新导入而更新
   seller_name（主键已存在会跳过），因此页面6 提供按当前配置重新匹配的功能；
   页面4 手工调整过的物品会被标记并跳过，不会被覆盖。
