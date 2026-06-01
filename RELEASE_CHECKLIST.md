# Release Checklist

每次推送到 Streamlit Cloud 前，先跑這份檢查。目標不是商用品管，而是保護家庭投資工具每天可用。

## 必跑指令

- `python -m py_compile Inventory.py pages/1_app_tw.py pages/2_analysis_history.py pages/3_growth_screener.py pages/4_chip_screener.py pages/5_bottom_screener.py render_layer/style.py render_layer/watchlist.py render_layer/diagnostics.py`
- `python -m pytest`

## 手機版快速檢查

- 首頁 / 庫存頁能正常載入，文字在淺色主內容與深色側欄都看得到。
- 三個選股頁的側欄「資料來源」可讀，不被深色文字蓋掉。
- 選股進度列不會讓畫面變成幾乎全白或全黑。
- 加入自選股區塊即使走勢圖暫時抓不到，也不能讓整頁白屏。

## AI 分析報告

- 報告章節維持固定順序：決策摘要、趨勢分析、基本面分析、籌碼面分析、基期風險評估、技術分析。
- 不要輸出「追蹤條件」或「資料來源與時間戳」作為新章節。
- 當 EPS、月營收、毛利率、外資持股或新聞資料不足時，報告要明確說資料不足，不要假裝完整。
- 下載與儲存 Markdown 後，內容仍可回看同一份 AI 分析。

## 資料與 FinMind

- 若遇到 FinMind 402 / 403 / 429 / ip banned / rate limit，畫面要提示資料不完整，不能當成零結果。
- 選股頁要先用 TWSE/TPEX 免費資料過濾，再呼叫 FinMind。
- 成長股與底部選股的 FinMind 進度提示要能看出目前查詢階段。

## 推送前

- `git status --short` 只應包含本次要送出的檔案。
- 檢查 diff 沒有意外改到中文欄位名稱、API 欄位 matcher、CSV 欄位或 Streamlit 顯示文字。
- 推送後等 Streamlit Cloud 完成部署，再用手機開一次主要流程。
