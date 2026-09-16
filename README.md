# Google Maps Reviews Scraper API

An API that extracts reviews from any place on Google Maps. Returns structured data: author, rating, text, and date.

## ✨ Features

*   **Structured Data**: Get clean JSON output ready for your application.
*   **Pay-Per-Call**: Only $0.10 per request, paid in USDC on the Base network.
*   **No Login Required**: Works with any public place on Google Maps.

## 🚀 How It Works

1.  **Send a POST request** to our API endpoint with the place you want to scrape.
2.  **Pay $0.10 in USDC** on the Base network (the API will return a `402 Payment Required` response with payment details).
3.  **Receive your data** instantly in a clean JSON format.

## 💻 Usage Example

Here's a simple `curl` command to get you started:

```bash
curl -X POST https://gmaps-api-service.relaxdev.ru/scrape \
  -H "Content-Type: application/json" \
  -d '{"queries": ["Eiffel Tower"], "max_reviews": 10}'
