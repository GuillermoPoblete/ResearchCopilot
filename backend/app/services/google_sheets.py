import re
from collections import Counter
from urllib.parse import unquote

import pandas as pd
import requests
from fastapi import HTTPException

GOOGLE_SHEETS_API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"
SPREADSHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")


def extract_spreadsheet_id(sheet_url: str) -> str | None:
    if not sheet_url:
        return None
    match = SPREADSHEET_ID_RE.search(sheet_url)
    if not match:
        return None
    return unquote(match.group(1))


def _normalize_headers(raw_headers: list[str], col_count: int) -> list[str]:
    headers = list(raw_headers[:col_count])
    while len(headers) < col_count:
        headers.append("")

    filled = []
    for idx, header in enumerate(headers):
        name = (header or "").strip()
        if not name:
            name = f"column_{idx + 1}"
        filled.append(name)

    counts = Counter()
    deduped = []
    for name in filled:
        counts[name] += 1
        if counts[name] == 1:
            deduped.append(name)
        else:
            deduped.append(f"{name}_{counts[name]}")
    return deduped


def _coerce_dataframe_types(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.columns:
        as_num = pd.to_numeric(df[col], errors="coerce")
        num_ratio = float(as_num.notna().mean()) if len(df) else 0.0
        if num_ratio >= 0.9:
            df[col] = as_num
            continue

        as_bool = df[col].astype(str).str.lower().map(
            {"true": True, "false": False, "1": True, "0": False}
        )
        bool_ratio = float(as_bool.notna().mean()) if len(df) else 0.0
        if bool_ratio >= 0.95:
            df[col] = as_bool
            continue

        as_dt = pd.to_datetime(df[col], errors="coerce", utc=True)
        dt_ratio = float(as_dt.notna().mean()) if len(df) else 0.0
        if dt_ratio >= 0.9:
            df[col] = as_dt
    return df


def load_first_sheet_dataframe(sheet_url: str, access_token: str) -> tuple[pd.DataFrame, dict]:
    spreadsheet_id = extract_spreadsheet_id(sheet_url)
    if not spreadsheet_id:
        raise HTTPException(status_code=400, detail="Invalid Google Sheet URL")
    if not access_token:
        raise HTTPException(status_code=400, detail="google_access_token is required")

    headers = {"Authorization": f"Bearer {access_token}"}

    meta_resp = requests.get(
        f"{GOOGLE_SHEETS_API_BASE}/{spreadsheet_id}",
        headers=headers,
        params={"fields": "sheets(properties(title,sheetId))"},
        timeout=20,
    )
    if meta_resp.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"Could not read spreadsheet metadata ({meta_resp.status_code})",
        )

    meta = meta_resp.json()
    sheets = meta.get("sheets", [])
    if not sheets:
        raise HTTPException(status_code=400, detail="Spreadsheet has no sheets")

    first_title = sheets[0]["properties"]["title"]
    values_resp = requests.get(
        f"{GOOGLE_SHEETS_API_BASE}/{spreadsheet_id}/values/{first_title}!A:ZZ",
        headers=headers,
        timeout=20,
    )
    if values_resp.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"Could not read sheet values ({values_resp.status_code})",
        )

    values = values_resp.json().get("values", [])
    if not values:
        raise HTTPException(status_code=400, detail="Sheet has no data")

    col_count = max(len(row) for row in values)
    row_count = max(len(values) - 1, 0)
    header_row = values[0] if values else []
    headers_row = _normalize_headers(header_row, col_count)

    rows = []
    for row in values[1:]:
        filled = list(row[:col_count])
        while len(filled) < col_count:
            filled.append(None)
        if all((cell is None or str(cell).strip() == "") for cell in filled):
            continue
        rows.append(filled)

    df = pd.DataFrame(rows, columns=headers_row)
    df = _coerce_dataframe_types(df)

    context = {
        "sheet_url": sheet_url,
        "spreadsheet_id": spreadsheet_id,
        "sheet_name": first_title,
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "columns": [str(c) for c in df.columns],
        "dtypes": {str(c): str(df[c].dtype) for c in df.columns},
        "null_counts": {str(c): int(df[c].isna().sum()) for c in df.columns},
        "sample_rows": (
            df.head(5)
            .astype(object)
            .where(pd.notnull(df.head(5)), None)
            .to_dict(orient="records")
        ),
        "raw_input_row_count": row_count,
    }
    return df, context
