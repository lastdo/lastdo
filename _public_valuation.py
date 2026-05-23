import pandas as pd

from _market_api import fetch_json_tpex, fetch_json_twse


URL_TWSE_PE = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"
URL_TPEX_PE = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis"
PUBLIC_PE_LABEL = "官方上市櫃API（近四季EPS反推）"


def fetch_public_pe_ratios() -> pd.DataFrame:
    """Fetch official TWSE/TPEX PE ratios and normalize to a single schema."""
    frames = []

    try:
        raw_twse = fetch_json_twse(URL_TWSE_PE)
        df_twse = pd.DataFrame(raw_twse)
        if {"Code", "PEratio"}.issubset(df_twse.columns):
            frames.append(
                df_twse[["Code", "PEratio"]].rename(
                    columns={"Code": "stock_id", "PEratio": "pe_ratio_public"}
                )
            )
    except Exception:
        pass

    try:
        raw_tpex = fetch_json_tpex(URL_TPEX_PE)
        df_tpex = pd.DataFrame(raw_tpex)
        if {"SecuritiesCompanyCode", "PriceEarningRatio"}.issubset(df_tpex.columns):
            frames.append(
                df_tpex[["SecuritiesCompanyCode", "PriceEarningRatio"]].rename(
                    columns={
                        "SecuritiesCompanyCode": "stock_id",
                        "PriceEarningRatio": "pe_ratio_public",
                    }
                )
            )
        elif {"股票代號", "本益比"}.issubset(df_tpex.columns):
            frames.append(
                df_tpex[["股票代號", "本益比"]].rename(
                    columns={"股票代號": "stock_id", "本益比": "pe_ratio_public"}
                )
            )
    except Exception:
        pass

    if not frames:
        return pd.DataFrame(columns=["stock_id", "pe_ratio_public"])

    df = pd.concat(frames, ignore_index=True)
    df["stock_id"] = df["stock_id"].astype(str).str.strip()
    df["pe_ratio_public"] = (
        df["pe_ratio_public"].astype(str).str.replace(",", "", regex=False).str.strip()
    )
    df["pe_ratio_public"] = pd.to_numeric(df["pe_ratio_public"], errors="coerce")
    df.loc[df["pe_ratio_public"] <= 0, "pe_ratio_public"] = pd.NA
    return df.drop_duplicates("stock_id")


def attach_public_valuation(
    df: pd.DataFrame,
    df_public_pe: pd.DataFrame,
    price_col: str = "close",
) -> pd.DataFrame:
    """Attach official PE and reverse-computed trailing-4Q EPS to a stock dataframe."""
    merged = df.merge(df_public_pe, on="stock_id", how="left")
    merged["pe_ratio"] = pd.to_numeric(merged["pe_ratio_public"], errors="coerce")
    merged["ttm_eps"] = pd.NA

    valid_mask = merged["pe_ratio"].notna() & (merged["pe_ratio"] > 0)
    merged.loc[valid_mask, "ttm_eps"] = (
        pd.to_numeric(merged.loc[valid_mask, price_col], errors="coerce")
        / merged.loc[valid_mask, "pe_ratio"]
    )
    merged["ttm_eps"] = pd.to_numeric(merged["ttm_eps"], errors="coerce")
    merged.loc[merged["ttm_eps"] <= 0, "ttm_eps"] = pd.NA

    merged["pe_label"] = pd.NA
    merged.loc[valid_mask, "pe_label"] = PUBLIC_PE_LABEL
    return merged
