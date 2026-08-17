import pandas as pd
from types import SimpleNamespace
from unittest.mock import Mock, patch

from data_layer.quality_rules import (
    INDUSTRY_AMBIGUOUS,
    INDUSTRY_NON_TRADITIONAL,
    INDUSTRY_TRADITIONAL,
    apply_shadow_quality_rules,
    calculate_three_year_average_net_margin,
    classify_ambiguous_industry_with_groq,
    classify_industry_category,
)


def _financial_rows(year_margins: dict[int, float]) -> pd.DataFrame:
    rows = []
    for year, margin in year_margins.items():
        for quarter, month in enumerate((3, 6, 9, 12), start=1):
            date = f"{year}-{month:02d}-{31 if month in (3, 12) else 30}"
            rows.extend(
                [
                    {"date": date, "type": "Revenue", "value": 100.0},
                    {"date": date, "type": "IncomeAfterTaxes", "value": margin},
                ]
            )
    return pd.DataFrame(rows)


def test_classify_industry_category_uses_fixed_and_ambiguous_lists():
    assert classify_industry_category("鋼鐵工業")["industry_classification"] == INDUSTRY_TRADITIONAL
    assert classify_industry_category("半導體業")["industry_classification"] == INDUSTRY_NON_TRADITIONAL
    assert classify_industry_category("其他")["industry_classification"] == INDUSTRY_AMBIGUOUS


def test_groq_ambiguous_classification_requires_structured_high_confidence_result():
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content='{"classification":"traditional","confidence":0.91,"reason":"主要業務為自行車製造"}'
                )
            )
        ]
    )
    client = Mock()
    client.chat.completions.create.return_value = response

    with patch("data_layer.quality_rules.Groq", return_value=client):
        result = classify_ambiguous_industry_with_groq("9914", "美利達", "其他", "test-key")

    assert result["industry_classification"] == INDUSTRY_TRADITIONAL
    assert result["industry_classification_source"] == "Groq 補判"
    assert result["industry_classification_confidence"] == 0.91


def test_calculate_three_year_average_net_margin_detects_strict_decline():
    result = calculate_three_year_average_net_margin(
        _financial_rows({2022: 40.0, 2023: 30.0, 2024: 20.0, 2025: 10.0})
    )

    assert result["net_margin_data_status"] == "complete"
    assert result["net_margin_declining_3y"] is True
    assert result["net_margin_years"] == "2023/2024/2025"
    assert result["net_margin_summary"] == "2023:30.00% → 2024:20.00% → 2025:10.00%"


def test_calculate_three_year_average_net_margin_requires_four_quarters_each_year():
    df = _financial_rows({2023: 30.0, 2024: 20.0, 2025: 10.0})
    df = df[~((pd.to_datetime(df["date"]).dt.year == 2025) & (pd.to_datetime(df["date"]).dt.quarter == 4))]

    result = calculate_three_year_average_net_margin(df)

    assert result["net_margin_data_status"] == "insufficient"
    assert pd.isna(result["net_margin_declining_3y"])


def test_shadow_rules_keep_original_rows_and_mark_exclusion_reasons():
    original = pd.DataFrame(
        [
            {
                "stock_id": "1301",
                "industry_category": "塑膠工業",
                "industry_classification": INDUSTRY_TRADITIONAL,
                "net_margin_data_status": "complete",
                "net_margin_declining_3y": False,
                "net_margin_summary": "2023:10.00% → 2024:11.00% → 2025:12.00%",
            },
            {
                "stock_id": "2330",
                "industry_category": "半導體業",
                "industry_classification": INDUSTRY_NON_TRADITIONAL,
                "net_margin_data_status": "complete",
                "net_margin_declining_3y": True,
                "net_margin_summary": "2023:50.00% → 2024:45.00% → 2025:40.00%",
            },
            {
                "stock_id": "9999",
                "industry_category": "其他",
                "industry_classification": INDUSTRY_AMBIGUOUS,
                "net_margin_data_status": "insufficient",
                "net_margin_declining_3y": pd.NA,
                "net_margin_summary": "資料不足",
            },
        ]
    )

    result = apply_shadow_quality_rules(original)

    assert len(result) == len(original)
    assert result.loc[result["stock_id"] == "1301", "shadow_excluded"].item() is True
    assert "傳統產業" in result.loc[result["stock_id"] == "1301", "shadow_exclusion_reason"].item()
    assert result.loc[result["stock_id"] == "2330", "shadow_excluded"].item() is True
    assert "連三年下滑" in result.loc[result["stock_id"] == "2330", "shadow_exclusion_reason"].item()
    assert result.loc[result["stock_id"] == "9999", "shadow_excluded"].item() is False
    assert result.loc[result["stock_id"] == "9999", "shadow_rule_status"].item() == "待確認（暫不排除）"
