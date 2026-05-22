import pandas as pd


CSV_ENCODING = "utf-8-sig"


def dataframe_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False, encoding=CSV_ENCODING).encode(CSV_ENCODING)
