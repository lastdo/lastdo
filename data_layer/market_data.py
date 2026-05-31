import pandas as pd

from data_layer.contracts import (
    INSTITUTIONAL_NET_BUY_CONTRACT,
    PRICE_SNAPSHOT_CONTRACT,
    PUBLIC_PE_CONTRACT,
    RECENT_REVENUE_METRICS_CONTRACT,
    REVENUE_SNAPSHOT_CONTRACT,
    empty_contract_frame,
    ensure_dataframe_contract,
    select_contract_columns,
)


PUBLIC_PE_TWSE_COLUMNS = {
    "Code": "stock_id",
    "PEratio": "pe_ratio_public",
}
PUBLIC_PE_TPEX_COLUMNS = {
    "SecuritiesCompanyCode": "stock_id",
    "PriceEarningRatio": "pe_ratio_public",
}
PUBLIC_PE_TPEX_FALLBACK_COLUMNS = {
    "股票代號": "stock_id",
    "本益比": "pe_ratio_public",
}


PRICE_TWSE_COLUMNS = {
    "Code": "stock_id",
    "Name": "stock_name",
    "ClosingPrice": "close",
    "TradeVolume": "vol_shares",
}
PRICE_TPEX_COLUMNS = {
    "SecuritiesCompanyCode": "stock_id",
    "CompanyName": "stock_name",
    "Close": "close",
    "TradingShares": "vol_shares",
}
REVENUE_COLUMNS = {
    "公司代號": "stock_id",
    "資料年月": "rev_ym",
    "營業收入-當月營收": "rev_cur",
    "營業收入-去年當月營收": "rev_ly",
    "營業收入-去年同月增減(%)": "rev_yoy",
}


def clean_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("--", "", regex=False)
        .str.strip(),
        errors="coerce",
    )


def _select_columns(raw_data: list, column_map: dict[str, str]) -> pd.DataFrame:
    df = pd.DataFrame(raw_data)
    if df.empty or not set(column_map).issubset(df.columns):
        return pd.DataFrame(columns=list(column_map.values()))
    return df[list(column_map)].rename(columns=column_map)


def build_price_snapshot(raw_twse_price: list, raw_tpex_price: list) -> pd.DataFrame:
    frames = []

    df_twse = _select_columns(raw_twse_price, PRICE_TWSE_COLUMNS)
    if not df_twse.empty:
        df_twse["market"] = "TWSE"
        frames.append(df_twse)

    df_tpex = _select_columns(raw_tpex_price, PRICE_TPEX_COLUMNS)
    if not df_tpex.empty:
        df_tpex["market"] = "TPEX"
        frames.append(df_tpex)

    if not frames:
        return empty_contract_frame(PRICE_SNAPSHOT_CONTRACT)

    df_price = pd.concat(frames, ignore_index=True)
    df_price["stock_id"] = df_price["stock_id"].astype(str).str.strip()
    df_price["stock_name"] = df_price["stock_name"].astype(str).str.strip()
    df_price["close"] = clean_numeric(df_price["close"])
    df_price["vol_shares"] = clean_numeric(df_price["vol_shares"])
    df_price["vol_lot"] = df_price["vol_shares"] / 1000
    df_price = df_price.dropna(subset=list(PRICE_SNAPSHOT_CONTRACT.required))
    return select_contract_columns(df_price, PRICE_SNAPSHOT_CONTRACT)


def build_revenue_snapshot(raw_twse_rev: list, raw_tpex_rev: list) -> pd.DataFrame:
    frames = []

    df_twse = _select_columns(raw_twse_rev, REVENUE_COLUMNS)
    if not df_twse.empty:
        frames.append(df_twse)

    df_tpex = _select_columns(raw_tpex_rev, REVENUE_COLUMNS)
    if not df_tpex.empty:
        frames.append(df_tpex)

    if not frames:
        return empty_contract_frame(REVENUE_SNAPSHOT_CONTRACT)

    df_rev = pd.concat(frames, ignore_index=True)
    df_rev["stock_id"] = df_rev["stock_id"].astype(str).str.strip()
    df_rev["rev_ym"] = df_rev["rev_ym"].astype(str).str.strip().str.replace("/", "", regex=False)
    df_rev["rev_yoy"] = clean_numeric(df_rev["rev_yoy"])
    df_rev["rev_cur"] = clean_numeric(df_rev["rev_cur"])
    df_rev["rev_ly"] = clean_numeric(df_rev["rev_ly"])
    df_rev = df_rev.dropna(subset=["rev_yoy"])
    return select_contract_columns(df_rev, REVENUE_SNAPSHOT_CONTRACT)


def build_public_pe_snapshot(raw_twse_pe: list, raw_tpex_pe: list) -> pd.DataFrame:
    frames = []

    df_twse = pd.DataFrame(raw_twse_pe)
    if set(PUBLIC_PE_TWSE_COLUMNS).issubset(df_twse.columns):
        frames.append(
            df_twse[list(PUBLIC_PE_TWSE_COLUMNS)].rename(columns=PUBLIC_PE_TWSE_COLUMNS)
        )

    df_tpex = pd.DataFrame(raw_tpex_pe)
    if set(PUBLIC_PE_TPEX_COLUMNS).issubset(df_tpex.columns):
        frames.append(
            df_tpex[list(PUBLIC_PE_TPEX_COLUMNS)].rename(columns=PUBLIC_PE_TPEX_COLUMNS)
        )
    elif set(PUBLIC_PE_TPEX_FALLBACK_COLUMNS).issubset(df_tpex.columns):
        frames.append(
            df_tpex[list(PUBLIC_PE_TPEX_FALLBACK_COLUMNS)].rename(
                columns=PUBLIC_PE_TPEX_FALLBACK_COLUMNS
            )
        )

    if not frames:
        return empty_contract_frame(PUBLIC_PE_CONTRACT)

    df = pd.concat(frames, ignore_index=True)
    df["stock_id"] = df["stock_id"].astype(str).str.strip()
    df["pe_ratio_public"] = clean_numeric(df["pe_ratio_public"])
    df.loc[df["pe_ratio_public"] <= 0, "pe_ratio_public"] = pd.NA
    df = df.drop_duplicates("stock_id")
    return select_contract_columns(df, PUBLIC_PE_CONTRACT)


def build_institutional_net_buy_frame(
    stock_ids,
    primary_net_shares,
    secondary_net_shares=None,
) -> pd.DataFrame:
    net = clean_numeric(pd.Series(primary_net_shares)).fillna(0)
    if secondary_net_shares is not None:
        net = net + clean_numeric(pd.Series(secondary_net_shares)).fillna(0)

    df = pd.DataFrame(
        {
            "stock_id": pd.Series(stock_ids).astype(str).str.strip(),
            "foreign_net_shares": net,
        }
    )
    return select_contract_columns(df, INSTITUTIONAL_NET_BUY_CONTRACT)


def prev_roc_month(ym_str: str) -> str:
    try:
        s = str(ym_str).strip().replace("/", "")
        if len(s) == 5:
            roc_year, month = int(s[:3]), int(s[3:])
        elif len(s) == 6:
            roc_year, month = int(s[:4]) - 1911, int(s[4:])
        else:
            return ""
        month -= 1
        if month == 0:
            month = 12
            roc_year -= 1
        return f"{roc_year}{month:02d}"
    except Exception:
        return ""


def latest_revenue_month(df_rev: pd.DataFrame) -> str:
    if df_rev.empty or "rev_ym" not in df_rev.columns:
        return ""
    counts = df_rev["rev_ym"].dropna().astype(str).value_counts()
    if counts.empty:
        return ""
    return str(counts.index[0]).strip()


def build_latest_revenue_view(df_rev: pd.DataFrame) -> pd.DataFrame:
    ensure_dataframe_contract(df_rev, REVENUE_SNAPSHOT_CONTRACT)
    if df_rev.empty:
        return empty_contract_frame(REVENUE_SNAPSHOT_CONTRACT)
    return (
        df_rev.sort_values(["stock_id", "rev_ym"], ascending=[True, False])
        .groupby("stock_id", as_index=False)
        .first()
    )


def build_recent_revenue_metrics(df_rev: pd.DataFrame, months: int = 2) -> pd.DataFrame:
    ensure_dataframe_contract(df_rev, REVENUE_SNAPSHOT_CONTRACT)
    if df_rev.empty:
        return empty_contract_frame(RECENT_REVENUE_METRICS_CONTRACT)

    df_sorted = df_rev.sort_values(["stock_id", "rev_ym"], ascending=[True, False])
    df_top = df_sorted.groupby("stock_id").head(months)

    df_avg = df_top.groupby("stock_id", as_index=False).agg(
        avg_rev_yoy=("rev_yoy", "mean"),
        rev_months=("rev_ym", lambda x: "/".join(sorted(x.tolist(), reverse=True))),
    )
    df_latest = df_sorted.groupby("stock_id", as_index=False).first()
    df_recent = (
        df_top.groupby("stock_id")
        .agg(
            latest_rev_yoy=("rev_yoy", "first"),
            prev_rev_yoy=("rev_yoy", lambda x: x.iloc[1] if len(x) > 1 else pd.NA),
        )
        .reset_index()
    )

    merged = df_latest.merge(df_avg, on="stock_id", how="left")
    merged = merged.merge(df_recent, on="stock_id", how="left")
    return select_contract_columns(merged, RECENT_REVENUE_METRICS_CONTRACT)
