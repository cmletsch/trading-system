# Trading System — One-Time Setup Guide
## Takes about 20 minutes. You do this once. After that, everything runs automatically forever.

---

## WHAT YOU'RE SETTING UP

- **GitHub** — free website that stores your scripts and hosts your dashboards
- **Google Sheets** — replaces your Excel file, stores all your trading data online
- **GitHub Actions** — free automation that runs your analysis at 8pm ET every trading day

Your two dashboards will live at permanent URLs you can bookmark and check from any device.

---

## STEP 1 — Create a Free GitHub Account

1. Go to **https://github.com**
2. Click **Sign up**
3. Use your email, create a username and password
4. Verify your email when prompted
5. Choose the **Free** plan

---

## STEP 2 — Create Your Repository (Your "Project Folder" Online)

1. Once logged in to GitHub, click the **+** icon in the top right corner
2. Click **New repository**
3. Name it: `trading-system`
4. Set it to **Private**
5. Check the box: **Add a README file**
6. Click **Create repository**

---

## STEP 3 — Enable GitHub Pages (Your Dashboard URLs)

1. In your new repository, click **Settings** (top menu)
2. Scroll down to **Pages** in the left sidebar
3. Under **Source**, select **Deploy from a branch**
4. Under **Branch**, select `main` and folder `/docs`
5. Click **Save**
6. Your dashboard URLs will be:
   - `https://YOUR-USERNAME.github.io/trading-system/fge.html`
   - `https://YOUR-USERNAME.github.io/trading-system/mdr.html`

---

## STEP 4 — Set Up Google Cloud (For Google Sheets Access)

Your scripts need permission to read/write your Google Sheet. This is done through a "service account" — basically a robot email address that has access.

1. Go to **https://console.cloud.google.com**
2. Click **Select a project** at the top → **New Project**
3. Name it `trading-system` → click **Create**
4. In the search bar at the top, search for **Google Sheets API**
5. Click on it → click **Enable**
6. In the search bar, search for **Google Drive API**
7. Click on it → click **Enable**
8. In the left sidebar, go to **IAM & Admin → Service Accounts**
9. Click **Create Service Account**
10. Name it `trading-bot` → click **Create and Continue** → click **Done**
11. Click on the service account you just created
12. Go to the **Keys** tab → **Add Key** → **Create new key** → **JSON**
13. A file downloads to your computer — this is your credentials file
    - **Keep this file safe — it's your key to your data**
    - Rename it to `credentials.json`

---

## STEP 5 — Create Your Google Sheet

1. Go to **https://sheets.google.com**
2. Click **Blank spreadsheet**
3. Name it: `Trading Data 2026`
4. Create these tabs (click the + at the bottom to add tabs):
   - `TOP Gainers Data`
   - `MDR TRACKING`
   - `SCAN LOG`
5. Copy the URL of your sheet — you need the ID in the middle:
   - URL looks like: `https://docs.google.com/spreadsheets/d/XXXXXXXXX/edit`
   - The **XXXXXXXXX** part is your Sheet ID — copy it

---

## STEP 6 — Share Your Sheet With the Service Account

1. Open your `credentials.json` file in any text editor (Notepad, TextEdit)
2. Find the line that says `"client_email"` — copy that email address
   - It looks like: `trading-bot@trading-system-XXXXX.iam.gserviceaccount.com`
3. In your Google Sheet, click **Share** (top right)
4. Paste that email address
5. Set permission to **Editor**
6. Click **Send**

---

## STEP 7 — Import Your Existing Excel Data

1. In your Google Sheet, click **File → Import**
2. Upload your `Chevelle 2026 Stock Trades.xlsx` file
3. Choose **Replace spreadsheet**
4. Your existing data is now in Google Sheets

---

## STEP 8 — Add Your Credentials to GitHub (Secrets)

This is how your scripts authenticate to Google Sheets securely — GitHub encrypts this and never shows it.

1. In your GitHub repository, click **Settings**
2. In the left sidebar, click **Secrets and variables → Actions**
3. Click **New repository secret**
4. Name: `GOOGLE_CREDENTIALS`
5. Value: Open your `credentials.json` file, select ALL the text, paste it in
6. Click **Add secret**

Add a second secret:
7. Click **New repository secret**
8. Name: `SPREADSHEET_ID`
9. Value: Paste your Sheet ID from Step 5
10. Click **Add secret**

---

## STEP 9 — Upload the Scripts

1. In your GitHub repository, click **Add file → Upload files**
2. Upload all the files from this package (the scripts, workflows, etc.)
3. Click **Commit changes**

That's it. The system will run automatically at 8pm ET every trading day.

---

## ACCESSING YOUR DASHBOARDS

Bookmark these two URLs (replace YOUR-USERNAME with your GitHub username):
- **FGE Top Gainers:** `https://YOUR-USERNAME.github.io/trading-system/fge.html`
- **MDR Dashboard:** `https://YOUR-USERNAME.github.io/trading-system/mdr.html`

---

## WINTER TIME ADJUSTMENT (November)

When clocks fall back in November, you'll need to update one line in `.github/workflows/eod.yml`:
- Change `0 0 * * 2-6` to `0 1 * * 2-6`
This keeps the run time at exactly 8pm EST.

---

## DOWNLOAD / BACKUP

Both dashboards have a **Download Backup** button. Click it anytime to download `trading_data_YYYY-MM-DD.xlsx` with all your data.
