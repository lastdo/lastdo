import streamlit as st
from datetime import datetime
import sys

# 頁面標題
st.title("Code Gym「高效 AI 投資術：No Code 打造自動化股票理專」環境測試")

# 顯示成功訊息
st.success("恭喜！如果您能看到這個頁面，表示環境已經成功安裝啟動！")
st.write(f"測試時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

st.success("✅ 環境測試完成！")