# AI 台股分析系統 規格說明書

> **用途說明**: 本規格說明書作為AI提示語使用，將此完整內容提交給AI，AI將根據規格生成完整的應用程式碼。

## 📋 系統概述

### 系統名稱
【Code Gym】AI 台股趨勢分析系統

### 核心功能描述
建立一個基於網頁的台灣股票技術分析工具，能夠：
1. 獲取指定台股的歷史價格數據和技術指標（**完全免費，無需付費API**）
2. 繪製專業的K線圖、移動平均線，以及三大法人買賣超圖表
3. 使用AI進行深度技術面與籌碼面分析和趨勢解讀
4. 提供客觀的歷史數據分析和教育性技術指標說明

### 技術架構要求
- **界面框架**: 使用 Streamlit 框架
- **數據來源**: FinMind（免費版，需免費註冊取得 Token）
- **AI 模型**: Groq + Llama 3.3 70B（**完全免費，無需信用卡**）
- **視覺化工具**: 互動式圖表（使用 Plotly Graph Objects）
- **數據處理**: Pandas
- **日期處理**: datetime
- **HTTP 請求**: requests
- **部署方式**: 可直接在瀏覽器中運行
- **費用**: 完全免費（FinMind 免費額度 + Groq 免費額度）

## 🎯 功能需求規格

### F-001: 用戶界面設計
**基本要求**:
- 頁面設定：`st.set_page_config(page_title="AI 台股趨勢分析系統", page_icon="📈", layout="wide")`
- 頁面標題: "📈 AI 台股趨勢分析系統"，緊接一條分隔線
- **自動載入環境變數**：程式啟動時執行 `load_dotenv()`，從 `.env` 檔案自動讀取 `FINMIND_TOKEN` 和 `GROQ_API_KEY`（需安裝 `python-dotenv`）
- 左側控制區包含：
  - 標頭 "📊 分析設定"，緊接一條分隔線
  - 台股代碼輸入：用戶輸入台灣股票代碼（純數字，預設值: "2330"）
  - FinMind Token：`value=os.getenv("FINMIND_TOKEN", "")`，type="password"
  - Groq API Key：`value=os.getenv("GROQ_API_KEY", "")`，type="password"
  - 起始日期選擇：用戶選擇分析起始日期（預設為90天前）
  - 結束日期選擇：用戶選擇分析結束日期（預設為今天）
- 主要執行按鈕: "🔍 分析"（`use_container_width=True, type="primary"`）

**台股代碼格式說明**:
- 使用者只需輸入純數字代碼，例如：2330（台積電）、2317（鴻海）、0050（元大台灣50）
- FinMind 直接接受純數字代碼，**無需加任何後綴**

### F-002: 數據獲取功能
**功能目標**: 自動從 FinMind 免費 API 取得台股歷史價格數據與三大法人資料
**數據來源與說明**:
- FinMind REST API，端點：`https://api.finmindtrade.com/api/v4/data`
- 免費版每日限 600 次請求，免費註冊取得 Token：https://finmindtrade.com
- FinMind 使用純數字台股代碼（無需後綴），支援上市及上櫃股票

**FinMind API 通用請求函式**: `_finmind_get(dataset, data_id, start_date, end_date, token)`
```python
import requests, pandas as pd
FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"

def _finmind_get(dataset, data_id, start_date, end_date, token=""):
    params = {
        "dataset":    dataset,
        "data_id":    data_id,
        "start_date": str(start_date),
        "end_date":   str(end_date),
    }
    if token:
        params["token"] = token
    resp = requests.get(FINMIND_URL, params=params, timeout=30)
    resp.raise_for_status()
    result = resp.json()
    if result.get("status") != 200 or not result.get("data"):
        return pd.DataFrame()
    return pd.DataFrame(result["data"])
```

**股價資料** (dataset: `TaiwanStockPrice`):
- FinMind 欄位對應：`max` → `high`、`min` → `low`、`Trading_Volume` → `volume`
- 統一欄位：date, open, high, low, close, volume
- date 欄位轉為 `pd.Timestamp`，按日期升序排列

**股票名稱** (dataset: `TaiwanStockInfo`):
- 從 `stock_name` 欄位取得中文名稱，失敗時回傳純數字代碼

**常用台股代碼範例**:
| 代碼 | 名稱 | 市場 |
|------|------|------|
| 2330 | 台積電 | 上市 |
| 2317 | 鴻海 | 上市 |
| 2454 | 聯發科 | 上市 |
| 2412 | 中華電 | 上市 |
| 0050 | 元大台灣50 | 上市 |
| 0056 | 元大高股息 | 上市 |
| 2603 | 長榮 | 上市 |
| 2881 | 富邦金 | 上市 |
| 6547 | 力旺 | 上櫃 |
| 8299 | 群聯 | 上櫃 |

**數據範圍**:
- 價格數據：包含開盤價(open)、最高價(high)、最低價(low)、收盤價(close)
- 成交量數據：每日交易量(volume)，單位為「股」（顯示時 ÷1000 換算為「張」）
- 時間範圍：根據用戶選擇的起始和結束日期

**額外 FinMind 資料集（分析時自動取得近兩年資料）**:
- **月營收** (`TaiwanStockMonthRevenue`)：取近兩年，計算月營收年增率（pct_change(12)×100）
  - 自訂函式：`get_monthly_revenue(symbol, token)` → 回傳 `date, revenue, yoy`
- **季EPS / 年EPS** (`TaiwanStockFinancialStatements`，type=="EPS")：
  - 季EPS：原始資料（每季報告）
  - 年EPS：以日曆年度加總季EPS
  - 自訂函式：`get_eps_data(symbol, token)` → 回傳 `(quarterly_df, annual_df)`，欄位均為 `date, eps`
- **季毛利率** (`TaiwanStockFinancialStatements`，type in ["GrossProfit","Revenue"])：
  - pivot 後計算 gross_margin = GrossProfit / Revenue × 100
  - 自訂函式：`get_gross_margin(symbol, token)` → 回傳 `date, gross_profit, revenue, gross_margin`
- **外資持股比例** (`TaiwanStockShareholding`)：取近三個月
  - 自訂函式：`get_foreign_holding(symbol, token)` → 回傳 `date, foreign_hold_ratio`
**處理要求**:
- 自動檢查資料是否為空（代碼錯誤或 Token 錯誤時資料為空）
- 提供友善的錯誤提示，說明可能原因與解決方式
- 從 `TaiwanStockInfo` 取得股票中文名稱顯示在圖表標題

### F-003: 數據處理與計算
**處理目標**: 將原始價格數據轉換為技術分析用的指標數據
**計算項目**:
- MA5: 5日移動平均線，計算最近5個交易日收盤價的平均值
- MA10: 10日移動平均線，計算最近10個交易日收盤價的平均值
- MA20: 20日移動平均線，計算最近20個交易日收盤價的平均值
- MA60: 60日移動平均線，計算最近60個交易日收盤價的平均值
**通用品質要求**:
- 使用 Pandas 的 rolling 函數計算移動平均
- 按日期升序排列，確保時間序列一致性
- 使用 min_periods=1 避免初期資料不足造成的缺值

### F-004: 主要顯示區域設計
**雙 Tab 分頁設計**：使用 `st.tabs(["📊 技術面總覽", "🤖 AI 綜合分析"])` 分為兩頁。

#### Tab 1：📊 技術面總覽
依序包含：
1. **K線圖 + 均線**（550px，高度）
2. **三大法人每日買賣超分組長條圖**（350px）
3. **三大法人累積折線圖**（300px）
4. **三大法人摘要**：`st.columns(3)` + `st.metric()` 顯示外資/投信/自營商整月累積（張）
5. **基本統計**：`st.columns(3)` 顯示起始價/結束價/期間漲跌幅
6. **月營收 + 年增率雙軸圖**（380px）：左Y軸=月營收（千元）的柱狀圖，右Y軸=年增率(%)折線圖
7. **季EPS / 年EPS 雙欄**：`st.columns(2)`，各320px 柱狀圖（含 0 基準線）
8. **最近10筆交易日資料**：`st.dataframe()`，成交量欄位顯示為「成交量(張)」（已 ÷1000）

#### Tab 2：🤖 AI 綜合分析
- 點擊分析後在此 Tab 顯示 Groq AI 分析報告（`st.markdown()`）
- 使用 `st.spinner("🤖 AI 正在分析台股數據，請稍候（約 15-30 秒）...")` 顯示進度

#### 股價K線圖與技術指標詳細內容：
- 主要指標：K線圖(開高低收)、MA5、MA10、MA20、MA60移動平均線
- 主要圖表：使用 Plotly Graph Objects 繪製 Candlestick K線圖
- K線顏色：漲紅（`#EF5350`）、跌綠（`#26A69A`）符合台股習慣
- 圖表標題：顯示股票代碼、股票名稱和分析期間
- caption 標示「資料來源：FinMind（免費版）」
- 軸標籤：X軸為日期，Y軸為「價格（新台幣 NT$）」
- 圖例設置：水平排列在圖表上方；關閉 `xaxis_rangeslider_visible`
- 圖表樣式：`template="plotly_dark"`，高度 550px

#### 三大法人買賣超詳細內容：
- **每日買賣超長條圖**（grouped bar chart）：
  - 外資及陸資（藍色 `#2196F3`）、投信（綠色 `#4CAF50`）、自營商（橘色 `#FF9800`）
  - 單位：張（FinMind 原始為股，已 ÷ 1000 換算）
  - 高度 350px
- **累積買賣超折線圖**（line chart）：
  - 同色系，顯示外資累積、投信累積、自營商累積
  - 高度 300px
- **摘要指標**：使用 `st.columns(3)` + `st.metric()` 顯示三方累積買賣超（張）
- 無法取得資料時（未輸入 Token 或日期無資料）顯示 `st.info()`

#### 月營收 + 年增率雙軸圖：
- 使用 `make_subplots(specs=[[{"secondary_y": True}]])` 建立雙Y軸
- 左Y軸：月營收（千元）柱狀圖，顏色 `#42A5F5`
- 右Y軸：年增率(%)折線圖，顏色 `#FF7043`，加 0 基準水平線（`#666666`，dash）
- 高度 380px，`template="plotly_dark"`

#### 季EPS / 年EPS 圖：
- `st.columns(2)`，左欄顯示季EPS、右欄顯示年EPS
- 均為柱狀圖，加 0 基準水平線，高度 320px，`template="plotly_dark"`

### F-005: 基本資訊展示
**展示方式**: 使用 st.columns(3) 展示重要的價格統計資訊
**展示內容**:
- 第一欄: 起始價格 - 分析期間第一個交易日的收盤價（NT$格式，含 help 顯示日期）
- 第二欄: 結束價格 - 分析期間最後一個交易日的收盤價（NT$格式，含 help 顯示日期）
- 第三欄: 期間價格變化 - 顯示期間漲跌幅百分比（value）和絕對變化（delta，NT$格式）
**數值處理**:
- 價格使用新台幣符號 NT$ 和適當的小數位數（.2f格式）
- 百分比以 `{pct_change:+.2f}%` 格式顯示
- 使用 `st.metric()` 展示關鍵指標，`delta_color="normal"`

### F-006: AI分析功能
**分析目標**: 使用 Groq + Llama 3.3 70B 對台股技術數據、基本面、籌碼面進行券商研究員水準的深度分析
**AI服務**: Groq Cloud API，完全免費，無需信用卡
**免費申請網址**: https://console.groq.com
**模型**: `llama-3.3-70b-versatile`
**參數**: `max_tokens=8192`，`temperature=0.4`
**Python套件**: `groq`

**函式簽名**:
```python
def generate_ai_insights(
    full_symbol, stock_name, stock_data, ii_data, groq_api_key,
    rev_data=None, eps_y=None, gross_margin_data=None, foreign_holding_data=None
) -> str:
```

**數據準備**:
- 取最後60筆股價+均線資料，轉 JSON；**volume 在送入 AI 前 ÷1000 換算為張**
- 三大法人取近 30 日，轉 JSON
- 從 `eps_y` 計算真實年EPS與本益比（`pe_ratio = end_price / latest_annual_eps`）
- 從 `rev_data` 取近12個月月營收年增率（dropna 後取 tail(12)）
- 從 `gross_margin_data` 取近8季毛利率
- 從 `foreign_holding_data` 取近6筆外資持股比例

**System Message**（最高優先規則）:
```
你是一位資深台股研究分析師，分析品質必須達到券商研究員水準。

【數字禁造規則】：prompt 中沒有以「提供數據」標注的財務數字（EPS、營收金額、
毛利率百分比、法人張數等），不可自行捏造。但此規則僅限於財務數字，不適用於
公司名稱、事件名稱、政策名稱、客戶名稱等質性資訊。

【強制使用訓練知識】：對於以下類型的內容，必須主動從訓練知識中提取具體資訊，
禁止以「無法提供」「時效有限」為由略過：
- 利多/利空事件：必須給出具體事件名稱、發生時間
- 主要客戶：必須列出已知的具體客戶公司名稱（如 HP、Dell、Apple 等）
- 法人目標價：必須列出記得的具體券商名稱與目標價
- 季節性規律、展覽效應：必須給出具體歷史年份案例
- 政策影響：必須引用具體政策名稱（如：美國晶片法案、IRA補貼）
若真的完全不知道某筆訓練知識，才可寫「訓練資料中無此資訊」（例外非常態）。

所有來自訓練資料（非 prompt 提供數據）的內容，結尾加注 (訓練資料，時效有限)。
技術面指標（RSI、MACD數值）：只根據 prompt 提供的股價數據推算，不可憑空給數值。
使用繁體中文，格式清晰，關鍵數字加粗，所有分析僅供研究參考，非投資建議。
```

**Prompt 結構（5節，無勝率分析）**:

**1. 趨勢分析** — 從提供數據計算：整月漲跌幅/高低點、近5日走向與量能（volume單位=張，數字大=量大）、具體支撐/阻力元數、均線排列判斷

**2. 基本面分析** — 包含以下注入的【提供數據】欄位：
  - 年EPS + 本益比（`pe_section`，真實計算）
  - 近期季毛利率（`gm_section`，FinMind 財務報表）
  - 近12個月營收年增率（`rev_section`，FinMind 月營收）
  - 法人目標價：主動搜尋訓練知識，必須給具體券商+數字+時間
  - 利基利空：格式「[時間] [事件全名]：[影響說明]」，禁止只寫事件類別
  - 產業定位：具體客戶名稱（禁說「無法提供」）、角色、競爭優勢
  - 總經互動：具體政策全名、匯率影響機制、利率影響程度

**3. 籌碼面分析** — 注入三大法人整月累積（外資/投信/自營商各自），近5日各別計算（禁止加總為單一數字），外資持股比例（`fh_section`），籌碼結構判斷，法人買賣與新聞一致性（引用具體事件）

**4. 基期風險評估** — 本益比對比近三年(2023-2025)PE區間（禁用更久歷史），近60筆股價區間分位，季節性規律（具體歷史年份+月份+漲跌幅），未來3個月內事件（法說會/展覽/財報），下行支撐位+景氣下行情境估算

**5. 技術分析** — 日/週/月線型態，RSI/MACD（從提供數據推算），具體操作觀察點（積極買點/保守買點/停損/第一目標/第二目標，全部給具體元數）
- 使用「歷史數據顯示」、「技術指標反映」、「過去走勢呈現」等客觀描述
- 避免「可能性」、「預期」、「建議」、「關注」等暗示性用詞
- 禁用「如果...則...」的假設句型，改用「歷史上當...時，曾出現...現象」
- 不提供具體價位的操作參考點，僅描述技術位階的歷史表現
- 強調「歷史表現不代表未來結果」
- 避免任何可能被解讀為操作指引的表達

免責聲明：所提供的分析內容純粹基於歷史數據的技術解讀，僅供教育和研究參考，不構成任何投資建議或未來走勢預測。歷史表現不代表未來結果。

---

請基於以下台股歷史數據進行深度技術分析：

### 基本資訊
- 股票代號：{full_symbol}（{stock_name}）
- 分析期間：{first_date} 至 {last_date}
- 期間價格變化：{price_change:.2f}%（從 NT${start_price:.2f} 變化到 NT${end_price:.2f}）

### 完整交易數據（價格單位：新台幣，最近60筆）
{data_json}

### 三大法人買賣超資料（近30日，單位：張）
{ii_json}

分析期間合計：
- 外資及陸資累積：{total_foreign:,} 張（正值=累積買超，負值=累積賣超）
- 投信累積：{total_trust:,} 張
- 自營商累積：{total_dealer:,} 張

### 分析架構：技術面與籌碼面完整分析

#### 1. 趨勢分析
- 整體趨勢方向（上升、下降、盤整）
- 關鍵支撐位和阻力位識別
- 趨勢強度評估，要包括整月的趨勢(較長)以及五天內(較短)的趨勢

#### 2. 基本面分析
- 依照常用基本面指標分析
- 法人對於基本面看法
- 有沒有新的利基利空，包刮產業轉型/技術提升/廠商角色轉換/新產品/競爭對手
  /成本上升/技術被超越等
- 與總體經濟可能的互動為何

### F-007: 輔助功能
**進度顯示**:
- `st.spinner(f"正在從 FinMind 取得 {symbol_input} 的歷史股價資料...")` 顯示資料獲取進度
- `st.spinner("正在取得股票基本資訊...")` 顯示名稱查詢進度
- `st.spinner("正在從 FinMind 取得三大法人買賣超資料...")` 顯示籌碼資料進度
- `st.spinner("正在從 FinMind 取得月營收與EPS資料...")` 顯示月營收/EPS獲取
- `st.spinner("正在從 FinMind 取得毛利率與外資持股資料...")` 顯示財務資料獲取
- `st.spinner("🤖 AI 正在分析台股數據，請稍候（約 15-30 秒）...")` 顯示 AI 分析進度
**數據表格展示**:
- 使用 `st.dataframe()` 顯示最近10筆交易數據
- 按日期降序排列，最新數據在前
- **成交量欄位顯示名稱為「成交量(張)」**（volume ÷1000 換算），其餘：日期、開盤價、最高價、最低價、收盤價、MA5、MA10、MA20、MA60
**狀態反饋標準**:
- `st.success()` 用於資料獲取成功，顯示股票名稱和筆數
- `st.error()` 用於代碼錯誤、API錯誤等，提供具體解決建議
- `st.warning()` 用於資料量過大或日期範圍無資料
- `st.info()` 用於三大法人資料無法取得時說明原因

### F-008: 錯誤處理與用戶體驗
**輸入驗證**:
- 檢查股票代碼是否為空
- 驗證股票代碼是否為純數字（台股代碼為數字）
- 驗證起始日期必須早於結束日期（`start_date >= end_date` 時報錯）
- 檢查 Groq API Key 是否已輸入（FinMind Token 為選填，無 Token 仍可取得股價，但三大法人資料可能受限）
- 提供台股代碼輸入範例：2330（台積電）、2317（鴻海）、0050（元大台灣50）
**錯誤處理**:
- FinMind 取不到資料（代碼錯誤或 Token 錯誤）要有清楚說明，含申請 Token 的連結
- Groq API Key 無效（HTTP 401）時提供申請連結
- Groq 請求頻率過高（HTTP 429）時提示「請等1分鐘後再試」
- 所有例外都用 try-except 處理，錯誤時以 `st.error()` 顯示

### F-009: 免責聲明與安全
**免責聲明位置**: 在側邊欄底部
**免責聲明內容**:
```markdown
### 📢 免責聲明
本系統僅供學術研究與教育用途，AI 提供的數據與分析結果僅供參考，
**不構成投資建議或財務建議**。
請使用者自行判斷投資決策，並承擔相關風險。
本系統作者不對任何投資行為負責，亦不承擔任何損失責任。
```
**安全要求**:
- FinMind Token 與 Groq API Key 均使用 `type="password"` 安全輸入
- 不在程式碼中寫入任何憑證資訊
- 驗證輸入格式（台股代碼應為純數字）

## 🛠️ 安裝需求

### 必要套件 (requirements.txt)
```
streamlit
requests
pandas
plotly
groq
python-dotenv
```

### 安裝指令
```bash
pip install streamlit requests pandas plotly groq python-dotenv
```

### 免費資源申請說明
1. **FinMind Token** - 免費申請（每日 600 次請求）：
   - 前往 https://finmindtrade.com
   - 登入或註冊帳號
   - 於個人頁面取得 Token
   - 不填 Token 仍可使用，但部分資料（如三大法人）可能受限
2. **Groq API Key** - 完全免費（無需信用卡）：
   - 前往 https://console.groq.com
   - 登入或註冊帳號
   - 點選「API Keys」→「Create API Key」
   - 免費方案限制：每分鐘 6,000 tokens（llama-3.3-70b-versatile）

## 🎨 界面設計與體驗標準

### 整體風格要求
- **專業感**: 符合台灣股票分析工具標準
- **易用性**: 針對台股用戶習慣設計，代碼輸入簡單直觀
- **台股特色**: 顯示股票中文名稱，幣別使用新台幣（NT$），K線顏色符合台股習慣（漲紅跌綠）
- **免費標示**: 側邊欄 caption 標示「📡 資料來源：FinMind（免費版，需註冊取得 Token）」和「🤖 AI：Groq + Llama 3.3 70B（完全免費）」

### 操作流程設計標準
1. **進入系統**: 看到清晰的台股分析工具標題（📈 AI 台股趨勢分析系統）
2. **輸入階段**: 輸入台股代碼 → 輸入 FinMind Token（選填）→ 輸入 Groq API Key → 設定日期
3. **執行階段**: 點擊「🔍 分析」按鈕，依序顯示進度（股價資料 → 股票名稱 → 三大法人 → 計算 MA → AI 分析）
4. **結果展示**: K線圖 → 三大法人買賣超圖 → 基本統計（NT$）→ AI分析（繁體中文）→ 數據表格

## 📊 品質標準

### 台股特有處理
- FinMind `TaiwanStockPrice` 欄位對應：`max` → `high`、`min` → `low`、`Trading_Volume` → `volume`
- 台股成交量單位為「股」；三大法人買賣超由股換算為張（÷ 1000）
- 股票名稱從 `TaiwanStockInfo` 資料集的 `stock_name` 欄位取得
- FinMind 直接使用純數字代碼，無需任何後綴

### 效能品質標準
- FinMind API 回應時間約 3-10 秒，需顯示進度
- 三大法人資料額外需 3-10 秒
- AI 分析（Groq + Llama 3.3 70B）回應時間約 10-20 秒

## AI實作指令

**請根據以上完整規格說明書，生成一個完整可運行的 Streamlit 網頁應用程式（台股版）。**

### 必要實現要求
1. **完全實現所有功能需求** (F-001 到 F-009)
2. **使用免費工具**: FinMind（需免費 Token）+ Groq（完全免費，無需信用卡）
3. **台股格式**: 直接使用純數字代碼，幣別顯示 NT$
4. **繁體中文分析**: AI 回答必須使用繁體中文

### 主要函數需求
1. `_finmind_get(dataset, data_id, start_date, end_date, token)` - FinMind REST API 通用請求函式
2. `get_taiwan_stock_data(symbol, start_date, end_date, token)` - 用 FinMind 獲取台股歷史價格，回傳 (DataFrame, symbol)
3. `get_stock_name(symbol, token)` - 從 `TaiwanStockInfo` 取得股票中文名稱
4. `get_institutional_investors(symbol, start_date, end_date, token)` - 取得三大法人買賣超資料（÷1000 換算為張），含累積欄位
5. `get_monthly_revenue(symbol, token)` - 取近兩年月營收，計算年增率(pct_change(12))，回傳 `date, revenue, yoy`
6. `get_eps_data(symbol, token)` - 取近兩年EPS，回傳 `(quarterly_df, annual_df)`，欄位均為 `date, eps`；年EPS為同年季EPS加總
7. `get_gross_margin(symbol, token)` - 取近兩年季毛利率，回傳 `date, gross_profit, revenue, gross_margin`
8. `get_foreign_holding(symbol, token)` - 取近三個月外資持股比例，回傳 `date, foreign_hold_ratio`
9. `get_moving_averages(df)` - 計算 MA5, MA10, MA20, MA60
10. `generate_ai_insights(full_symbol, stock_name, stock_data, ii_data, groq_api_key, rev_data=None, eps_y=None, gross_margin_data=None, foreign_holding_data=None)` - 使用 Groq + Llama 3.3 70B 進行五節深度分析

### 交付物要求
- 一個完整的 Python 程式檔案 `app_tw.py`
- 所有必要的 import 語句（`logging`, `streamlit`, `requests`, `pandas`, `plotly.graph_objects`, `groq`, `json`, `datetime`）
- 完整的函數實現
- 主程式邏輯
- 適當的中文註釋
- 可直接用 `streamlit run app_tw.py` 執行
