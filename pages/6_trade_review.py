import logging
import os
from datetime import datetime, time
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from groq import Groq


class _IgnoreBareMode(logging.Filter):
    def filter(self, record):
        return "missing ScriptRunContext" not in record.getMessage()


logging.getLogger(
    "streamlit.runtime.scriptrunner_utils.script_run_context"
).addFilter(_IgnoreBareMode())

load_dotenv()

st.set_page_config(
    page_title="AI 進出場分析",
    page_icon="AI",
    layout="wide",
)

import sys
from pathlib import Path as _Path

sys.path.insert(0, str(_Path(__file__).parent.parent))
from _style import apply_style, page_header, render_global_navigation

apply_style()
page_header(
    "AI",
    "AI 進出場分析",
    "檢查每筆交易是否符合原始策略，分開評估交易品質與交易結果。",
)

ANALYSIS_DIR = Path(__file__).parent.parent / "analysis"
ANALYSIS_DIR.mkdir(exist_ok=True)

DEFAULT_STRATEGY_RULES = """1. 本益比需合理或偏低。
2. 股價不得離重要均線太遠。
3. 月營收成長是重要觀察條件。
4. EPS 或獲利表現需支持買進邏輯。
5. 若基本面或技術面條件被破壞，應考慮出場。
6. 不因短線震盪任意賣出。
7. 達到合理獲利區間時，可分批停利。"""


def combine_datetime(date_value, time_value) -> datetime:
    if time_value is None:
        time_value = time(0, 0)
    return datetime.combine(date_value, time_value)


def format_price_diff(price_diff: float) -> str:
    sign = "+" if price_diff > 0 else ""
    return f"{sign}{price_diff:.2f} 元"


def format_return_rate(return_rate: float) -> str:
    sign = "+" if return_rate > 0 else ""
    return f"{sign}{return_rate:.2f}%"


def build_trade_review_prompt(
    stock_id: str,
    stock_name: str,
    strategy_rule_text: str,
    entry_datetime: datetime,
    entry_price: float,
    exit_datetime: datetime,
    exit_price: float,
    holding_days: int,
    price_diff_text: str,
    return_rate_text: str,
    buy_plan_text: str,
    sell_reason_text: str,
) -> str:
    return f"""你是一位嚴格的台股交易風控審查員。

你的任務不是鼓勵交易，也不是替使用者合理化決策。
你的任務是找出這筆交易中的邏輯漏洞、資料不足、策略不一致、風險控管問題與情緒化交易跡象。

重要限制：
1. 只能根據使用者提供的資料分析。
2. 不得自行假設財報、法人籌碼、技術線型、新聞或產業前景。
3. 如果資料不足，必須明確寫「資料不足，無法判斷」。
4. 請先提出反方觀點，再做合理性分析。
5. 不得因為交易賺錢就判定為成功交易。
6. 不得因為交易虧錢就判定為失敗交易。
7. 請將「策略執行品質」與「交易結果」分開評估。
8. 如果交易虧錢，但使用者有遵守原始策略、執行停損、避免更大損失，應視為紀律成功交易。
9. 如果交易賺錢，但進出場理由混亂、沒有風控、違反原本策略，應視為僥倖獲利交易。
10. 若缺少停損條件，必須扣分。
11. 若缺少預期價格或目標區間，必須扣分。
12. 若買進理由主要是主觀判斷且缺少數據，必須扣分。
13. 若出場理由與原始策略不一致，必須扣分。

交易成功定義：
成功交易不等於賺錢交易，失敗交易也不等於虧錢交易。
成功交易 = 有遵守策略 + 風險受控 + 進出場理由一致 + 決策品質良好。

總評分公式：
總評分 = 策略執行分數 x 70% + 結果績效分數 x 30%

分數門檻：
90 分以上：策略模板交易，不管賺賠都值得未來參考。
85 到 89 分：高品質成功交易，值得保留作為好案例。
80 到 84 分：成功交易，整體決策品質良好。
70 到 79 分：可接受交易，但需要檢討。
60 到 69 分：高風險交易，可能有明顯紀律問題。
60 分以下：不合格交易，不建議複製。

請根據以下資料分析：

股票代號：{stock_id}
股票名稱：{stock_name}

原始策略規則：
{strategy_rule_text}

入場時間：{entry_datetime.strftime("%Y-%m-%d %H:%M")}
入場價格：{entry_price:.2f}

出場時間：{exit_datetime.strftime("%Y-%m-%d %H:%M")}
出場價格：{exit_price:.2f}

持有天數：{holding_days}
價差：{price_diff_text}
報酬率：{return_rate_text}

買進理由 / 預期價格：
{buy_plan_text}

出場理由：
{sell_reason_text}

請用繁體中文回答，並使用以下格式：

一、已提供的客觀事實

二、主觀假設與資料不足

三、反方檢查

四、是否符合原始策略
請逐條檢查原始策略規則，標示：
- 符合
- 不符合
- 資料不足，無法判斷

五、入場合理性分析

六、出場合理性分析

七、策略執行分數
請給 0 到 100 分，並說明原因。

八、結果績效分數
請給 0 到 100 分，並說明原因。

九、總評分
請使用：
總評分 = 策略執行分數 x 70% + 結果績效分數 x 30%

十、交易分類
請從以下四類選一個：
- 高品質成功交易
- 紀律成功交易
- 僥倖獲利交易
- 策略失敗交易

十一、主要問題
請列出 3 到 5 點。

十二、下次優化策略
請提出具體可執行的改善方式。"""


def generate_trade_review(prompt: str, groq_api_key: str) -> str:
    client = Groq(api_key=groq_api_key)
    chat_completion = client.chat.completions.create(
        messages=[
            {
                "role": "system",
                "content": (
                    "你是一位嚴格、保守、重視紀律的台股交易風控審查員。"
                    "你只能根據使用者提供的資料分析；資料不足時必須明確說資料不足，無法判斷。"
                    "你必須先找問題，再評估合理性，且不得用賺賠結果取代交易品質判斷。"
                ),
            },
            {"role": "user", "content": prompt},
        ],
        model="llama-3.3-70b-versatile",
        max_tokens=8192,
        temperature=0.2,
    )
    return chat_completion.choices[0].message.content


with st.sidebar:
    render_global_navigation("trade_review")
    st.markdown("---")
    st.header("AI 設定")
    st.divider()
    groq_api_key = st.text_input(
        "Groq API Key",
        value=os.getenv("GROQ_API_KEY", ""),
        type="password",
        help="用於產生嚴格交易審查報告。",
    ).strip()
    save_report = st.toggle("分析後保存到 analysis 資料夾", value=True)
    st.markdown("---")
    st.caption("這一頁只檢查你提供的交易紀錄與策略文字，不會自行補財報、籌碼、新聞或線型。")

with st.expander("交易品質判斷標準", expanded=False):
    st.markdown(
        """
成功交易不等於賺錢交易。真正要評估的是：是否遵守策略、風險是否受控、進出場理由是否一致、決策品質是否良好。

總評分採用：策略執行分數 x 70% + 結果績效分數 x 30%。80 分以上可視為成功交易，85 分以上為高品質交易，90 分以上才適合作為策略模板。
"""
    )

with st.form("trade_review_form"):
    st.subheader("基本資料")
    c1, c2 = st.columns([1, 2])
    with c1:
        stock_id = st.text_input("股票代號", placeholder="例如：2330").strip()
    with c2:
        stock_name = st.text_input("股票名稱", placeholder="例如：台積電").strip()

    st.subheader("進出場資料")
    e1, e2, e3 = st.columns(3)
    with e1:
        entry_date = st.date_input("入場日期")
    with e2:
        entry_time = st.time_input("入場時間", value=time(9, 0), step=300)
    with e3:
        entry_price = st.number_input("入場價格", min_value=0.0, value=0.0, step=0.1, format="%.2f")

    x1, x2, x3 = st.columns(3)
    with x1:
        exit_date = st.date_input("出場日期")
    with x2:
        exit_time = st.time_input("出場時間", value=time(13, 30), step=300)
    with x3:
        exit_price = st.number_input("出場價格", min_value=0.0, value=0.0, step=0.1, format="%.2f")

    st.subheader("交易邏輯")
    buy_plan_text = st.text_area(
        "買進理由 / 預期價格",
        height=160,
        placeholder="請寫入買進條件、預期價格或目標區間、停損條件、風險假設。",
    ).strip()
    sell_reason_text = st.text_area(
        "出場理由",
        height=140,
        placeholder="請寫入出場原因：停利、停損、策略條件破壞、資金配置或其他理由。",
    ).strip()
    strategy_rule_text = st.text_area(
        "原始策略規則",
        value=DEFAULT_STRATEGY_RULES,
        height=190,
    ).strip()

    submitted = st.form_submit_button("產生 AI 進出場分析", type="primary", use_container_width=True)

entry_datetime = combine_datetime(entry_date, entry_time)
exit_datetime = combine_datetime(exit_date, exit_time)
holding_days = max((exit_datetime.date() - entry_datetime.date()).days, 0)
price_diff = exit_price - entry_price
return_rate = (price_diff / entry_price * 100) if entry_price > 0 else 0.0
price_diff_text = format_price_diff(price_diff)
return_rate_text = format_return_rate(return_rate)

m1, m2, m3 = st.columns(3)
m1.metric("持有天數", f"{holding_days} 天")
m2.metric("價差", price_diff_text)
m3.metric("報酬率", return_rate_text)

prompt = build_trade_review_prompt(
    stock_id=stock_id or "未提供",
    stock_name=stock_name or "未提供",
    strategy_rule_text=strategy_rule_text or "未提供",
    entry_datetime=entry_datetime,
    entry_price=entry_price,
    exit_datetime=exit_datetime,
    exit_price=exit_price,
    holding_days=holding_days,
    price_diff_text=price_diff_text,
    return_rate_text=return_rate_text,
    buy_plan_text=buy_plan_text or "未提供",
    sell_reason_text=sell_reason_text or "未提供",
)

with st.expander("檢視本次送出的完整 Prompt", expanded=False):
    st.text_area("Prompt", value=prompt, height=420)

if submitted:
    missing = []
    if not groq_api_key:
        missing.append("Groq API Key")
    if not stock_id:
        missing.append("股票代號")
    if entry_price <= 0:
        missing.append("入場價格")
    if exit_price <= 0:
        missing.append("出場價格")
    if exit_datetime < entry_datetime:
        missing.append("出場時間不可早於入場時間")
    if not buy_plan_text:
        missing.append("買進理由 / 預期價格")
    if not sell_reason_text:
        missing.append("出場理由")
    if not strategy_rule_text:
        missing.append("原始策略規則")

    if missing:
        st.error("請先補齊：" + "、".join(missing))
        st.stop()

    with st.spinner("AI 正在用嚴格風控角度檢查這筆交易..."):
        try:
            report = generate_trade_review(prompt, groq_api_key)
        except Exception as exc:
            st.error(f"AI 分析失敗：{exc}")
            st.stop()

    st.session_state["trade_review_report"] = report
    st.session_state["trade_review_prompt"] = prompt

    if save_report:
        safe_stock_name = stock_name or "未命名"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        filename = f"{stock_id}_{safe_stock_name}_進出場分析_{timestamp}.md"
        report_path = ANALYSIS_DIR / filename
        report_path.write_text(
            f"# {stock_id} {safe_stock_name} AI 進出場分析\n\n{report}\n\n---\n\n## Prompt\n\n```text\n{prompt}\n```\n",
            encoding="utf-8",
        )
        st.success(f"已保存報告：analysis/{filename}")

if st.session_state.get("trade_review_report"):
    report = st.session_state["trade_review_report"]
    st.subheader("AI 進出場分析報告")
    st.markdown(report)
    st.download_button(
        "下載 Markdown 報告",
        data=report,
        file_name=f"{stock_id or 'trade'}_ai_trade_review.md",
        mime="text/markdown",
        use_container_width=True,
    )
