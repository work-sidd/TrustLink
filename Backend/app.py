from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
import time
import random

app = Flask(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
}

def scrape_amazon_search(search_url):
    print(f"Scraping search page: {search_url}")
    response = requests.get(search_url, headers=HEADERS)
    soup = BeautifulSoup(response.text, "html.parser")
    
    products = []
    
    for item in soup.select(".s-main-slot .s-result-item"):
        title_tag = item.select_one("h2 a")
        price_tag = item.select_one(".a-price-whole")
        
        if title_tag:
            product_name = title_tag.get_text(strip=True)
            product_link = "https://www.amazon.in" + title_tag["href"]
            product_price = price_tag.get_text(strip=True) if price_tag else "N/A"
            
            products.append({
                "name": product_name,
                "link": product_link,
                "price": product_price
            })

    return products

@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.json
    search_url = data.get("url")

    if not search_url:
        return jsonify({"error": "No URL provided"}), 400

    products = scrape_amazon_search(search_url)
    return jsonify(products)

@app.route('/track-url', methods=['POST'])
def track_url():
    data = request.json
    amazon_url = data.get("url")

    if not amazon_url:
        return jsonify({"error": "No URL provided"}), 400

    print(f"Received URL: {amazon_url}")
    
    # Here, you can later add logic to store URLs in a database
    return jsonify({"message": "URL received successfully!"})


if __name__ == "__main__":
    app.run(debug=True, port=5000)



