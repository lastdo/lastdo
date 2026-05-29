# Google Sheets Portfolio Setup

## 1. Create the worksheet

Create a Google Sheet and add a worksheet named `holdings`.

The app will create these headers automatically if the sheet is empty:

- `row_id`
- `family_id`
- `stock_id`
- `stock_name`
- `avg_cost`
- `shares`
- `note`
- `created_at`
- `updated_at`
- `is_deleted`

## 2. Create a Google service account

1. Open Google Cloud Console.
2. Enable Google Sheets API and Google Drive API.
3. Create a service account.
4. Generate a JSON key.
5. Share the Google Sheet with the service account email as an editor.

## 3. Add Streamlit secrets

In Streamlit Community Cloud, add these secrets:

```toml
# Optional API keys used by pages
FINMIND_TOKEN = "your_finmind_token"
GROQ_API_KEY = "your_groq_api_key"

# Portfolio storage settings
PORTFOLIO_USE_GOOGLE_SHEETS = true
PORTFOLIO_DEFAULT_FAMILY_ID = "lwh38009"
GOOGLE_SHEETS_PORTFOLIO_SPREADSHEET_ID = "your_google_sheet_id"
GOOGLE_SHEETS_PORTFOLIO_WORKSHEET = "holdings"
# Optional: if you want the in-app edit link to open a specific tab
# GOOGLE_SHEETS_PORTFOLIO_WORKSHEET_GID = "0"

[GOOGLE_SERVICE_ACCOUNT]
type = "service_account"
project_id = "your-project-id"
private_key_id = "your-private-key-id"
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "your-service-account@your-project.iam.gserviceaccount.com"
client_id = "1234567890"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "https://www.googleapis.com/robot/v1/metadata/x509/your-service-account"
universe_domain = "googleapis.com"
```

## 3.1 Open web Google Sheet for family editing

1. Open your Google Sheet in a browser:
   - `https://docs.google.com/spreadsheets/d/<your_google_sheet_id>/edit`
2. Click **Share** and add your family members as **Editor**.
3. Ask your family to edit the `holdings` worksheet directly.
4. Keep `family_id` consistent with the app sidebar value (default `lwh38009`) if multiple households share one sheet.

## 4. Migration behavior

- The app keeps `portfolio.json` as a fallback.
- On the first successful Google Sheets connection, if the worksheet is empty, local `portfolio.json` data will be copied into Google Sheets under the active `family_id`.
- The backup file `portfolio.json(20260524)` is not touched by the app.
