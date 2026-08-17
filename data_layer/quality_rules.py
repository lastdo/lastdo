"""Shadow quality rules for Taiwan stock screener results."""
from __future__ import annotations

import json
import re
from typing import Any

import pandas as pd
from groq import Groq


INDUSTRY_TRADITIONAL = "traditional"
INDUSTRY_NON_TRADITIONAL = "non_traditional"
INDUSTRY_AMBIGUOUS = "ambiguous"
INDUSTRY_UNKNOWN = "unknown"

TRADITIONAL_INDUSTRIES = {
    "水泥工業",
    "食品工業",
    "塑膠工業",
    "紡織纖維",
    "電機機械",
    "電器電纜",
    "玻璃陶瓷",
    "造紙工業",
    "鋼鐵工業",
    "橡膠工業",
    "汽車工業",
    "建材營造",
    "航運業",
    "觀光事業",
    "觀光餐旅",
    "貿易百貨",
    "化學工業",
    "油電燃氣業",
}

NON_TRADITIONAL_INDUSTRIES = {
    "半導體業",
    "生技醫療業",
    "光電業",
    "文化創意業",
    "金融保險",
    "金融業",
    "通信網路業",
    "資訊服務業",
    "電子工業",
    "電子商務業",
    "電子通路業",
    "電子零組件業",
    "電腦及週邊設備業",
    "其他電子業",
    "其他電子類",
    "數位雲端",
    "數位雲端類",
}

AMBIGUOUS_INDUSTRIES = {
    "其他",
    "化學生技醫療",
    "居家生活",
    "居家生活類",
    "農業科技業",
    "運動休閒",
    "運動休閒類",
    "綠能環保",
    "綠能環保類",
}

NET_INCOME_TYPES = (
    "ProfitLoss",
    "IncomeAfterTaxes",
    "ProfitLossAttributableToOwnersOfParent",
)


def classify_industry_category(industry_category: object) -> dict[str, Any]:
    category = (
        str(industry_category).strip()
        if industry_category is not None and not pd.isna(industry_category)
        else ""
    )
    if category in TRADITIONAL_INDUSTRIES:
        return {
            "industry_classification": INDUSTRY_TRADITIONAL,
            "industry_classification_source": "固定產業名單",
            "industry_classification_confidence": 1.0,
            "industry_reason": f"官方產業別「{category}」列入傳統產業名單。",
        }
    if category in NON_TRADITIONAL_INDUSTRIES:
        return {
            "industry_classification": INDUSTRY_NON_TRADITIONAL,
            "industry_classification_source": "固定產業名單",
            "industry_classification_confidence": 1.0,
            "industry_reason": f"官方產業別「{category}」列入非傳統產業名單。",
        }
    if category in AMBIGUOUS_INDUSTRIES:
        return {
            "industry_classification": INDUSTRY_AMBIGUOUS,
            "industry_classification_source": "待 Groq 補判",
            "industry_classification_confidence": pd.NA,
            "industry_reason": f"官方產業別「{category}」範圍較廣，需依主要業務補判。",
        }
    return {
        "industry_classification": INDUSTRY_UNKNOWN,
        "industry_classification_source": "資料不足",
        "industry_classification_confidence": pd.NA,
        "industry_reason": "沒有可用或已定義的官方產業分類。",
    }


def _extract_json_object(text: str) -> dict:
    clean = str(text or "").strip()
    try:
        payload = json.loads(clean)
        return payload if isinstance(payload, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", clean, flags=re.DOTALL)
        if not match:
            return {}
        try:
            payload = json.loads(match.group(0))
            return payload if isinstance(payload, dict) else {}
        except json.JSONDecodeError:
            return {}


def classify_ambiguous_industry_with_groq(
    stock_id: str,
    stock_name: str,
    industry_category: str,
    api_key: str,
    model: str = "qwen/qwen3.6-27b",
) -> dict[str, Any]:
    if not str(api_key).strip():
        return {
            "industry_classification": INDUSTRY_UNKNOWN,
            "industry_classification_source": "Groq 未執行",
            "industry_classification_confidence": pd.NA,
            "industry_reason": "未提供 Groq API Key，模糊產業保留為待確認。",
        }

    prompt = f"""
請判斷以下台灣上市櫃公司是否屬於傳統產業。

股票代號：{stock_id}
公司名稱：{stock_name}
官方產業別：{industry_category}

判定定義：
1. 傳統產業：主要營收來自成熟的實體製造、原物料、民生消費品、營建、運輸、觀光或傳統通路。
2. 非傳統產業：主要營收來自半導體、電子、軟體、雲端、資訊服務、生技醫療或其他創新科技；金融業也歸為非傳統產業。
3. 公司名稱或既有知識不足以確認主要業務時，必須回傳 unknown，不得猜測。

只能回傳單一 JSON 物件，不要 Markdown：
{{"classification":"traditional|non_traditional|unknown","confidence":0.0,"reason":"繁體中文簡短理由"}}
""".strip()

    try:
        client = Groq(api_key=str(api_key).strip())
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "你是保守的台灣股票產業分類器。資料不足時一定回傳 unknown。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_completion_tokens=220,
            reasoning_effort="none",
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or ""
        payload = _extract_json_object(content)
        classification = str(payload.get("classification", "unknown")).strip().lower()
        if classification not in {INDUSTRY_TRADITIONAL, INDUSTRY_NON_TRADITIONAL}:
            classification = INDUSTRY_UNKNOWN
        confidence = pd.to_numeric(payload.get("confidence"), errors="coerce")
        if pd.isna(confidence) or float(confidence) < 0.75:
            classification = INDUSTRY_UNKNOWN
        return {
            "industry_classification": classification,
            "industry_classification_source": "Groq 補判",
            "industry_classification_confidence": float(confidence) if pd.notna(confidence) else pd.NA,
            "industry_reason": str(payload.get("reason") or "Groq 未提供判定理由。").strip(),
        }
    except Exception as exc:
        return {
            "industry_classification": INDUSTRY_UNKNOWN,
            "industry_classification_source": "Groq 失敗",
            "industry_classification_confidence": pd.NA,
            "industry_reason": f"Groq 補判失敗：{type(exc).__name__}",
        }


def calculate_three_year_average_net_margin(financial_df: pd.DataFrame) -> dict[str, Any]:
    insufficient = {
        "net_margin_data_status": "insufficient",
        "net_margin_declining_3y": pd.NA,
        "net_margin_summary": "資料不足",
        "net_margin_years": "",
    }
    required = {"date", "type", "value"}
    if financial_df.empty or not required.issubset(financial_df.columns):
        return insufficient

    df = financial_df[list(required)].copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["date", "type", "value"])
    if df.empty:
        return insufficient

    revenue = (
        df[df["type"] == "Revenue"]
        .sort_values("date")
        .drop_duplicates("date", keep="last")
        .set_index("date")["value"]
    )
    income = df[df["type"].isin(NET_INCOME_TYPES)].copy()
    if revenue.empty or income.empty:
        return insufficient

    priority = {item: index for index, item in enumerate(NET_INCOME_TYPES)}
    income["_priority"] = income["type"].map(priority)
    income = (
        income.sort_values(["date", "_priority"])
        .drop_duplicates("date", keep="first")
        .set_index("date")["value"]
    )
    quarterly = pd.concat([revenue.rename("revenue"), income.rename("net_income")], axis=1).dropna()
    quarterly = quarterly[quarterly["revenue"] != 0].copy()
    if quarterly.empty:
        return insufficient

    quarterly["net_margin"] = quarterly["net_income"] / quarterly["revenue"] * 100
    quarterly["year"] = quarterly.index.year
    quarterly["quarter"] = quarterly.index.quarter

    complete_rows = []
    for year, group in quarterly.groupby("year"):
        group = group.drop_duplicates("quarter", keep="last")
        if set(group["quarter"].astype(int)) != {1, 2, 3, 4}:
            continue
        complete_rows.append({"year": int(year), "average_net_margin": float(group["net_margin"].mean())})

    annual = pd.DataFrame(complete_rows).sort_values("year") if complete_rows else pd.DataFrame()
    if len(annual) < 3:
        return insufficient

    latest_three = annual.tail(3).reset_index(drop=True)
    values = latest_three["average_net_margin"].tolist()
    declining = bool(values[0] > values[1] > values[2])
    summary = " → ".join(
        f"{int(row.year)}:{row.average_net_margin:.2f}%" for row in latest_three.itertuples(index=False)
    )
    return {
        "net_margin_data_status": "complete",
        "net_margin_declining_3y": declining,
        "net_margin_summary": summary,
        "net_margin_years": "/".join(latest_three["year"].astype(int).astype(str)),
    }


def apply_shadow_quality_rules(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    statuses = []
    excluded_flags = []
    reasons = []
    industry_labels = []
    margin_labels = []

    industry_label_map = {
        INDUSTRY_TRADITIONAL: "傳統產業",
        INDUSTRY_NON_TRADITIONAL: "非傳統產業",
        INDUSTRY_AMBIGUOUS: "模糊產業",
        INDUSTRY_UNKNOWN: "資料不足",
    }

    for row in result.to_dict("records"):
        row_reasons = []
        raw_classification = row.get("industry_classification")
        classification = (
            str(raw_classification).strip()
            if raw_classification is not None and not pd.isna(raw_classification)
            else INDUSTRY_UNKNOWN
        )
        if classification == INDUSTRY_TRADITIONAL:
            raw_category = row.get("industry_category")
            category = (
                str(raw_category).strip()
                if raw_category is not None and not pd.isna(raw_category)
                else "未知產業"
            )
            row_reasons.append(f"傳統產業（{category}）")

        declining = row.get("net_margin_declining_3y")
        declining_flag = False if declining is None or pd.isna(declining) else bool(declining)
        if declining_flag:
            raw_summary = row.get("net_margin_summary")
            summary = "" if raw_summary is None or pd.isna(raw_summary) else str(raw_summary)
            row_reasons.append(f"年平均淨利率連三年下滑（{summary}）")

        excluded = bool(row_reasons)
        industry_pending = classification in {INDUSTRY_AMBIGUOUS, INDUSTRY_UNKNOWN}
        raw_margin_status = row.get("net_margin_data_status")
        margin_status = (
            str(raw_margin_status).strip()
            if raw_margin_status is not None and not pd.isna(raw_margin_status)
            else "insufficient"
        )
        margin_pending = margin_status != "complete"
        if excluded:
            status = "新規則會排除"
        elif industry_pending or margin_pending:
            status = "待確認（暫不排除）"
        else:
            status = "新規則保留"

        statuses.append(status)
        excluded_flags.append(excluded)
        reasons.append("；".join(row_reasons) if row_reasons else "—")
        industry_labels.append(industry_label_map.get(classification, "資料不足"))
        if margin_pending:
            margin_labels.append("資料不足")
        elif declining_flag:
            margin_labels.append("連三年下滑")
        else:
            margin_labels.append("未連三年下滑")

    result["shadow_rule_status"] = statuses
    result["shadow_excluded"] = excluded_flags
    result["shadow_exclusion_reason"] = reasons
    result["industry_classification_label"] = industry_labels
    result["net_margin_trend_label"] = margin_labels
    return result
