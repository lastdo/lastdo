# V4 Roadmap：雙龍吐珠策略回測

## 程式邊界

V4 回測邏輯不要混進既有 `data_layer` 或 `render_layer`。
即時選股頁和歷史回測頁的維護節奏不同，先隔離比過早共用更重要。

回測專用程式固定放在：

- `backtest_common`
  - 放策略常數、point-in-time 規則、日期視窗規則、稽核欄位規則
- `backtest_data_layer`
  - 放 FinMind / MOPS / 歷史價格查詢，以及任意基準日資料池重建用 dataframe builder
- `backtest_render_layer`
  - 放回測頁專用表格、CSV、診斷區塊、KPI 顯示

只有很穩定、且已經證明即時篩選與回測都需要的工具，未來才考慮移到真正共用層。
第一階段不做這件事。

## 核心原則

V4 第一件事不是完整績效回測，而是：

`給定任意 as_of_date，能重建雙龍吐珠在該基準日當下會選出哪些股票。`

`2026-03-18` 只是第一個驗證案例，不是程式假設。
之後可能會跑 `2026-06-18` 的半年前、任意日期、任意回看月數，都必須走同一套 `as_of_date` 管線。

如果基準日資料池做不準，後面的報酬比較、KPI、圖表、Supabase 都是空談。

## 第一階段目標

先做出一個可以回答下面問題的工具：

- 使用者指定 `as_of_date`
- 系統只使用 `as_of_date` 當下可取得的資料
- 先算出共用條件池
- 再分出 `龍騰升空` 與 `潛龍在淵`
- 輸出每檔股票入選或落選原因

第一個人工驗證日期先用 `2026-03-18`。
但程式、資料表、函式、UI 都不得硬寫 `2026-03-18`。

## 第一階段不做的事

- 不先做多期滾動回測
- 不先做勝率、Sharpe Ratio、最大回撤
- 不先做完整 Supabase schema
- 不先做複雜 benchmark
- 不先把回測 helper 抽進既有共用層

第一階段完成標準是：

`任意基準日可以重建資料池，且能解釋每檔股票卡在哪個條件。`

## Point-In-Time 規則

所有資料都以 `as_of_date` 為中心：

- 股價：
  - 只能使用 `<= as_of_date` 的歷史價格
- 季線：
  - 只能由 `as_of_date` 以前 60 個交易日計算
- 六個月低點：
  - 只能看 `as_of_date` 以前約 6 個月交易資料
- 月營收：
  - 只能使用 `as_of_date` 當天保守視為已公布的月份
  - 近兩月平均要排除二月；若最近兩個月包含二月，就往前補一個非二月月份
- EPS：
  - 以 FinMind `TaiwanStockFinancialStatements` 查到 `<= as_of_date` 的 EPS
  - 取最近四季加總為 `ttm_eps`
- PE：
  - 用 `as_of_date` 收盤價 / `ttm_eps`
  - 不使用今天的官方 PE 回推歷史 EPS

遇到缺資料，不要默默當成不符合策略。
要輸出 `fail_reason` 或資料診斷，讓使用者知道是條件不合，還是資料沒拿到。

## 第一階段資料流程

1. 使用者輸入 `as_of_date`
2. 取得股票清單
3. 對候選股票抓 `as_of_date` 前的歷史股價
4. 從歷史股價計算 `close`、`vol_lot`、`ma60`、`six_month_low`
5. 取得 `as_of_date` 可用的月營收，計算排除二月後的近兩月 YoY 平均
6. 以 FinMind 三線程查 EPS，取 `<= as_of_date` 最近四季加總
7. 用 `close / ttm_eps` 算 PE
8. 套用共用條件
9. 套用 `龍騰升空`
10. 套用 `潛龍在淵`
11. 輸出完整明細與 CSV

## 可稽核輸出欄位

第一版明細表至少要有：

- `as_of_date`
- `stock_id`
- `stock_name`
- `market`
- `price_date`
- `close`
- `vol_lot`
- `avg_rev_yoy`
- `rev_months`
- `ttm_eps`
- `eps_quarters`
- `pe_ratio`
- `ma60`
- `six_month_low`
- `six_month_low_date`
- `is_common_pass`
- `is_dragon_rise_pass`
- `is_dragon_hidden_pass`
- `fail_reason`

這張表比 KPI 更重要，因為它能驗證策略是否真的在指定日期成立。

## 第一個驗證案例

第一個 fixture 使用：

`as_of_date = 2026-03-18`

目標不是把日期寫死，而是用它驗證流程：

- 共用池數量是否合理
- `龍騰升空` 名單是否可解釋
- `潛龍在淵` 名單是否可解釋
- 目標股票是否能追到具體入選或落選原因

未來要能直接換成：

- `2026-06-18` 的半年前
- 使用者任意指定日期
- 多個基準日批次重建

## 第二階段才做的事

等任意基準日資料池可信後，再做：

- 存入 Supabase
- 建立比較日價格快照
- 計算個股報酬
- 計算大盤報酬
- 計算超額報酬
- 顯示 KPI 與圖表

第二階段的重點是：

`從可信的歷史名單，延伸到績效比較。`

## 第三階段才做的事

- 多個基準日批次重建
- 每月或每季滾動回測
- 等權重組合績效
- 勝率
- 最大回撤
- 年化報酬
- Sharpe Ratio

這些都建立在第一階段先站穩。

## 當前成功標準

V4 第一個 milestone 寫成：

`任意 as_of_date 可重建雙龍吐珠資料池，且第一個驗證案例 2026-03-18 能解釋每檔股票入選與落選原因。`

這才是 V4 的地基。
