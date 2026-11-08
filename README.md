# Groww Trading Terminal & Algorithmic Trading Environment

A complete Python + Flask trading system environment built for algorithmic trading and portfolio tracking using the official **Groww Trade API**.

---

## 🚀 Features

- **Automated Authentication**: Connects using Groww API Key and API Secret approval flow, with support for 2FA TOTP code verification (`pyotp`).
- **Session Caching**: Session tokens are automatically cached until the daily 6:00 AM IST expiration, avoiding unnecessary re-authentications.
- **Interactive Web Terminal**: Modern, dark-mode financial dashboard powered by Tailwind CSS, Lucide icons, and Chart.js.
  - **Account Profile**: Unique Client Code (UCC), Vendor ID, NSE/BSE permissions, and active segments (CASH, FNO, COMMODITY).
  - **Funds & Margins**: Live Clear Cash, Net Margin Used, Collaterals, and detailed breakdowns across Equity and F&O.
  - **Demat Holdings**: Live holdings table with quantities, average buy prices, total invested amounts, exchange badges, and asset allocation pie chart.
  - **Positions & Orders**: Day/Net positions, unrealized P&L, and order book.
  - **Algo Code Starter**: Pre-built examples for automated order execution.
  - **API Configuration**: Easily view, test, or update credentials directly from the web interface.

---

## 📁 Project Structure

```
Groww-Trading-Project/
├── app.py                  # Flask web server & REST API endpoints
├── config.py               # Credentials loader & app configuration
├── groww_service.py        # Groww API service wrapper with session caching
├── example_strategy.py     # Standalone Python script for algorithmic trading
├── keys.txt                # API Key and Secret configuration file
├── requirements.txt        # Python package dependencies
├── run.bat                 # One-click Windows batch runner
├── run.ps1                 # PowerShell runner script
├── static/
│   ├── css/custom.css      # Custom scrollbars and transition animations
│   └── js/dashboard.js     # Responsive async dashboard controller
└── templates/
    └── index.html          # Main web terminal dashboard interface
```

---

## 🔑 Credentials Setup (`keys.txt`)

Your credentials are read from `keys.txt` in the project root:

```ini
api_key = <your_groww_api_key_jwt>
api_secret = <your_groww_api_secret>
```

*(Optional)* If you have a TOTP secret seed for generating 6-digit TOTP codes automatically:
```ini
totp_secret = <your_base32_totp_seed>
```

---

## ⚡ Quick Start

### 1. Launch with One-Click
Double click **`run.bat`** (or execute `./run.ps1` in PowerShell).

### 2. Manual Command Line
```powershell
# Activate the virtual environment
.\venv\Scripts\Activate.ps1

# Run the Flask terminal
python app.py
```

### 3. Open in Browser
Visit **`http://127.0.0.1:5000`** to view your live Groww trading terminal.

---

## 🛠️ Development Tools Included

- **`growwapi`**: Official Python client library for Groww Trade API.
- **`pyotp`**: RFC 6238 Time-Based One-Time Password library for automated 2FA.
- **`flask`**: Lightweight, fast Python web framework.
- **`python-dotenv`**: Secure environment variable loader.
- **`requests`**: HTTP request library.
- **`pandas`**: High-performance data analysis toolkit for backtesting and analytics.
