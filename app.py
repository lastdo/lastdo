import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
import anthropic
import json
from datetime import datetime, timedelta

# ─────────────────────────────────────────────
# 頁面基本設定
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="AI 股票趨勢分析系統",
    page_icon="📈",
    layout="wide",
)

st.title("📈 AI 股票趨勢分析系統")
st.divider()   # rainbow divider (Streamlit 預設)


# ─────────────────────────────────────────────
# F-001 側邊欄控制區
# ─────────────────────────────────────────────
with st.sidebar:
    st.header("📊 分析設定")
    st.divider()

    symbol = st.text_input(
        "股票代碼 (美股)",
        value="AAPL",
        help="請輸入美股股票代碼，例如：AAPL, MSFT, GOOGL",
    ).strip().upper()

    fmp_api_key = st.text_input(
        "FMP API Key",
        type="password",
        help="請至 https://financialmodelingprep.com 申請免費 API Key",
    ).strip()

    claude_api_key = st.text_input(
        "Claude (Anthropic) API Key",
        type="password",
        help="請至 https://console.anthropic.com 申請 API Key",
    ).strip()

    default_start = datetime.today() - timedelta(days=90)
    default_end   = datetime.today()

    start_date = st.date_input("起始日期", value=default_start)
    end_date   = st.date_input("結束日期",  value=default_end)

    analyze_btn = st.button("🔍 分析", use_container_width=True, type="primary")

    # F-009 免責聲明
    st.markdown("---")
    st.markdown(
        """
        ### 📢 免責聲明
        本系統僅供學術研究與教育用途，AI 提供的數據與分析結果僅供參考，
        **不構成投資建議或財務建議**。
        請使用者自行判斷投資決策，並承擔相關風險。
        本系統作者不對任何投資行為負責，亦不承擔任何損失責任。
        """
    )


# ─────────────────────────────────────────────
# F-002 從 FMP API 獲取股票歷史數據
# ─────────────────────────────────────────────
def get_stock_data(symbol: str, api_key: str) -> pd.DataFrame:
    """向 Financial Modeling Prep API 取得完整歷史價格資料。"""
    url = (
        f"https://financialmodelingprep.com/stable/historical-price-eod/full"
        f"?symbol={symbol}&apikey={api_key}"
    )
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.Timeout:
        st.error("❌ API 請求逾時，請稍後再試。")
        return pd.DataFrame()
    except requests.exceptions.ConnectionError:
        st.error("❌ 無法連線至 FMP API，請檢查網路連線。")
        return pd.DataFrame()
    except requests.exceptions.HTTPError as e:
        st.error(f"❌ API 回應錯誤：{e}")
        return pd.DataFrame()
    except ValueError:
        st.error("❌ API 回傳資料格式異常，請確認 API Key 是否正確。")
        return pd.DataFrame()

    if not data or not isinstance(data, list):
        st.error(f"❌ 找不到股票代碼「{symbol}」，請確認輸入是否正確（範例：AAPL、MSFT、GOOGL）。")
        return pd.DataFrame()

    df = pd.DataFrame(data)
    # 確保欄位存在
    required_cols = {"date", "open", "high", "low", "close", "volume"}
    if not required_cols.issubset(df.columns):
        st.error("❌ API 回傳資料缺少必要欄位，請稍後再試。")
        return pd.DataFrame()

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df


# ─────────────────────────────────────────────
# F-003 依日期範圍過濾資料
# ─────────────────────────────────────────────
def filter_by_date_range(
    df: pd.DataFrame,
    start_date,
    end_date,
) -> pd.DataFrame:
    """根據使用者選擇的起迄日期過濾資料。"""
    mask = (df["date"] >= pd.Timestamp(start_date)) & (
        df["date"] <= pd.Timestamp(end_date)
    )
    return df.loc[mask].reset_index(drop=True)


# ─────────────────────────────────────────────
# F-003 計算移動平均線
# ─────────────────────────────────────────────
def get_moving_averages(df: pd.DataFrame) -> pd.DataFrame:
    """計算 MA5、MA10、MA20、MA60 移動平均線。"""
    df = df.copy()
    for window in [5, 10, 20, 60]:
        df[f"MA{window}"] = df["close"].rolling(window=window, min_periods=1).mean()
    return df


# ─────────────────────────────────────────────
# F-006 呼叫 Claude 進行技術分析
# ─────────────────────────────────────────────
def generate_ai_insights(
    symbol: str,
    stock_data: pd.DataFrame,
    claude_api_key: str,
) -> str:
    """使用 Claude Sonnet 4.6 對股票歷史數據進行深度技術分析。"""

    first_date   = stock_data["date"].iloc[0].strftime("%Y-%m-%d")
    last_date    = stock_data["date"].iloc[-1].strftime("%Y-%m-%d")
    start_price  = float(stock_data["close"].iloc[0])
    end_price    = float(stock_data["close"].iloc[-1])
    price_change = (end_price - start_price) / start_price * 100

    # 準備送給 AI 的精簡版資料（最多 60 筆，避免 token 過多）
    cols = ["date", "open", "high", "low", "close", "volume",
            "MA5", "MA10", "MA20", "MA60"]
    sample_df = stock_data[cols].tail(60).copy()
    sample_df["date"] = sample_df["date"].dt.strftime("%Y-%m-%d")
    data_json = sample_df.to_json(orient="records", force_ascii=False)

    system_message = """你是一位專業的技術分析師，專精於股票技術分析和歷史數據解讀。你的職責包括：

1. 客觀描述股票價格的歷史走勢和技術指標狀態
2. 解讀歷史市場數據和交易量變化模式
3. 識別技術面的歷史支撐阻力位
4. 提供純教育性的技術分析知識

重要原則：
- 僅提供歷史數據分析和技術指標解讀，絕不提供任何投資建議或預測
- 保持完全客觀中立的分析態度
- 使用專業術語但保持易懂
- 所有分析僅供教育和研究目的
- 強調技術分析的局限性和不確定性
- 使用繁體中文回答

嚴格的表達方式要求：
- 使用「歷史數據顯示」、「技術指標反映」、「過去走勢呈現」等客觀描述
- 避免「可能性」、「預期」、「建議」、「關注」等暗示性用詞
- 禁用「如果...則...」的假設句型，改用「歷史上當...時，曾出現...現象」
- 不提供具體價位的操作參考點，僅描述技術位階的歷史表現
- 強調「歷史表現不代表未來結果」
- 避免任何可能被解讀為操作指引的表達

免責聲明：所提供的分析內容純粹基於歷史數據的技術解讀，僅供教育和研究參考，不構成任何投資建議或未來走勢預測。歷史表現不代表未來結果。"""

    user_prompt = f"""請基於以下股票歷史數據進行深度技術分析：

### 基本資訊
- 股票代號：{symbol}
- 分析期間：{first_date} 至 {last_date}
- 期間價格變化：{price_change:.2f}% (從 ${start_price:.2f} 變化到 ${end_price:.2f})

### 完整交易數據
以下是該期間的完整交易數據，包含日期、開盤價、最高價、最低價、收盤價、成交量和移動平均線：
{data_json}

### 分析架構：技術面完整分析

#### 1. 趨勢分析
- 整體趨勢方向（上升、下降、盤整）
- 關鍵支撐位和阻力位識別
- 趨勢強度評估

#### 2. 技術指標分析
- 移動平均線分析（短期與長期MA的關係）
- 價格與移動平均線的相對位置
- 成交量與價格變動的關聯性

#### 3. 價格行為分析
- 重要的價格突破點
- 波動性評估
- 關鍵的轉折點識別

#### 4. 風險評估
- 當前價位的風險等級
- 潛在的支撐和阻力區間
- 市場情緒指標

#### 5. 市場觀察
- 短期技術面觀察（1-2週）
- 中期技術面觀察（1-3個月）
- 關鍵價位觀察點
- 技術面風險因子

### 綜合評估要求
#### 輸出格式要求
- 條理清晰，分段論述
- 提供具體的數據支撐
- 避免過於絕對的預測，強調分析的局限性
- 在適當位置使用表格或重點標記

分析目標：{symbol}"""

    try:
        client = anthropic.Anthropic(api_key=claude_api_key)
        message = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=4096,
            system=system_message,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return message.content[0].text
    except anthropic.AuthenticationError:
        st.error("❌ Claude API Key 無效，請確認金鑰是否正確。")
        return ""
    except anthropic.RateLimitError:
        st.error("❌ Claude API 請求頻率過高，請稍後再試。")
        return ""
    except anthropic.APIConnectionError:
        st.error("❌ 無法連線至 Claude API，請檢查網路連線。")
        return ""
    except Exception as e:
        st.error(f"❌ AI 分析失敗：{e}")
        return ""


# ─────────────────────────────────────────────
# 主程式邏輯
# ─────────────────────────────────────────────
if analyze_btn:

    # ── F-008 輸入驗證 ──────────────────────────
    if not symbol:
        st.error("❌ 請輸入股票代碼（例如：AAPL、MSFT、GOOGL）。")
        st.stop()
    if not fmp_api_key:
        st.error("❌ 請輸入 FMP API Key。申請網址：https://financialmodelingprep.com")
        st.stop()
    if not claude_api_key:
        st.error("❌ 請輸入 Claude API Key。申請網址：https://console.anthropic.com")
        st.stop()
    if start_date >= end_date:
        st.error("❌ 起始日期必須早於結束日期，請重新選擇。")
        st.stop()

    # ── F-002 獲取數據 ───────────────────────────
    with st.spinner(f"正在獲取 {symbol} 的歷史股價資料..."):
        raw_df = get_stock_data(symbol, fmp_api_key)

    if raw_df.empty:
        st.stop()

    # ── F-003 過濾日期 & 計算 MA ─────────────────
    st.info("📊 正在計算技術指標...")
    filtered_df = filter_by_date_range(raw_df, start_date, end_date)

    if filtered_df.empty:
        st.warning("⚠️ 所選日期範圍內沒有交易數據，請調整日期範圍後重試。")
        st.stop()

    if len(filtered_df) > 500:
        st.warning("⚠️ 資料量較大（超過 500 筆），圖表載入可能稍慢，請耐心等候。")

    stock_data = get_moving_averages(filtered_df)
    st.success(f"✅ 成功獲取 {symbol} 共 {len(stock_data)} 筆交易資料")

    # ── F-004 K 線圖與技術指標 ───────────────────
    st.subheader(f"📊 {symbol} 股價K線圖與技術指標")
    st.caption(f"分析期間：{start_date} ～ {end_date}")

    fig = go.Figure()

    # K 線圖
    fig.add_trace(
        go.Candlestick(
            x=stock_data["date"],
            open=stock_data["open"],
            high=stock_data["high"],
            low=stock_data["low"],
            close=stock_data["close"],
            name="K線",
            increasing_line_color="#EF5350",
            decreasing_line_color="#26A69A",
        )
    )

    # 移動平均線
    ma_colors = {
        "MA5":  "#FF9800",
        "MA10": "#2196F3",
        "MA20": "#9C27B0",
        "MA60": "#F44336",
    }
    for ma, color in ma_colors.items():
        fig.add_trace(
            go.Scatter(
                x=stock_data["date"],
                y=stock_data[ma],
                mode="lines",
                name=ma,
                line=dict(color=color, width=1.5),
            )
        )

    fig.update_layout(
        title=f"{symbol} 股價走勢圖（{start_date} ～ {end_date}）",
        xaxis_title="日期",
        yaxis_title="價格 (USD)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        xaxis_rangeslider_visible=False,
        template="plotly_dark",
        height=550,
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── F-005 基本統計資訊 ───────────────────────
    st.subheader("📋 基本統計資訊")

    start_price  = float(stock_data["close"].iloc[0])
    end_price    = float(stock_data["close"].iloc[-1])
    abs_change   = end_price - start_price
    pct_change   = abs_change / start_price * 100

    col1, col2, col3 = st.columns(3)
    col1.metric(
        label="起始價格",
        value=f"${start_price:.2f}",
        help=f"分析期間第一個交易日（{stock_data['date'].iloc[0].strftime('%Y-%m-%d')}）收盤價",
    )
    col2.metric(
        label="結束價格",
        value=f"${end_price:.2f}",
        help=f"分析期間最後一個交易日（{stock_data['date'].iloc[-1].strftime('%Y-%m-%d')}）收盤價",
    )
    col3.metric(
        label="期間價格變化",
        value=f"{pct_change:+.2f}%",
        delta=f"${abs_change:+.2f}",
        delta_color="normal",
    )

    # ── F-006 AI 技術分析 ────────────────────────
    st.subheader("🤖 AI 技術分析")
    with st.spinner("AI 正在分析中，請稍候（約 20-40 秒）..."):
        ai_report = generate_ai_insights(symbol, stock_data, claude_api_key)

    if ai_report:
        st.markdown(ai_report)

    # ── F-007 歷史數據表格 ───────────────────────
    st.subheader("📅 最近 10 筆交易日資料")

    display_df = stock_data.copy()
    display_df["date"] = display_df["date"].dt.strftime("%Y-%m-%d")
    display_df = display_df.rename(columns={
        "date":   "日期",
        "open":   "開盤價",
        "high":   "最高價",
        "low":    "最低價",
        "close":  "收盤價",
        "volume": "成交量",
    })

    # 按日期降序，取最近 10 筆
    show_cols = ["日期", "開盤價", "最高價", "最低價", "收盤價", "成交量",
                 "MA5", "MA10", "MA20", "MA60"]
    # 保留存在的欄位
    show_cols = [c for c in show_cols if c in display_df.columns]
    st.dataframe(
        display_df[show_cols].iloc[::-1].head(10).reset_index(drop=True),
        use_container_width=True,
    )

else:
    # 尚未點擊分析時顯示引導訊息
    st.info(
        "👈 請在左側側邊欄輸入股票代碼、API Key 及日期範圍，然後點擊「🔍 分析」開始分析。\n\n"
        "**支援的股票代碼範例**：AAPL（蘋果）、MSFT（微軟）、GOOGL（Alphabet）、AMZN（亞馬遜）、TSLA（特斯拉）"
    )
