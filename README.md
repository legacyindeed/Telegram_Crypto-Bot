# What-If Profit/Loss Bot

A Telegram bot that lets you explore crypto “what if” scenarios and track a simple manual portfolio.

## Features

- `/whatifdate SYMBOL USD_AMOUNT YYYY-MM-DD`  
  See how much you would have now if you invested `$USD_AMOUNT` in `SYMBOL` on a past date.

- `/addpos SYMBOL AMOUNT BUY_PRICE`  
  Add a manual position to your portfolio.

- `/portfolio`  
  Show all positions with current value and PnL.

- `/ath SYMBOL`  
  All-time-high price, date, current price, market cap and degen score.

- `/clear`  
  Clear your entire portfolio.

- `/remove SYMBOL`  
  Remove all saved positions for that token.

- `/gm`  
  Little degen good-morning message.

## Setup

1. Clone the repo and create a virtual env (optional but recommended).

2. Install dependencies:

   ```bash
   pip install -r requirements.txt


# PowerShell
$env:BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN_HERE"

# or bash
export BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN_HERE"




---

## 5. (Optional) `.env.example`

If you want to be extra clean, create a `.env.example`:

```text
BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN_HERE


