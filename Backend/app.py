from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
import firebase_admin
from firebase_admin import credentials, firestore
import os
import json

app = Flask(__name__)
firebase_credentials = json.loads(os.getenv("FIREBASE_CREDENTIALS"))

cred = credentials.Certificate(firebase_credentials)
firebase_admin.initialize_app(cred)
db = firestore.client()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
}

def scrape_amazon_search(search_url):
    """
    Scrapes Amazon search results page and extracts product names & links.
    """
    print(f"Scraping search page: {search_url}")
    response = requests.get(search_url, headers=HEADERS)

    if response.status_code != 200:
        return {"error": "Failed to fetch search results"}

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

def store_in_firestore(products):
    """
    Stores the list of products in Firebase Firestore.
    """
    for product in products:
        product_ref = db.collection("products").document()
        product_ref.set(product)
        print(f"Stored in Firestore: {product['name']}")

@app.route('/track-url', methods=['POST'])
def track_url():
    """
    Receives an Amazon URL, scrapes product details, and stores them in Firestore.
    """
    data = request.json
    amazon_url = data.get("url")

    if not amazon_url:
        return jsonify({"error": "No URL provided"}), 400

    print(f"Received URL: {amazon_url}")
    
    # Scrape the product details
    product_data = scrape_amazon_search(amazon_url)
    
    if "error" in product_data:
        return jsonify({"error": product_data["error"]}), 400

    # Store product details in Firestore
    store_in_firestore(product_data)
    
    return jsonify({"message": "Product details saved successfully!"})

if __name__ == "__main__":
    app.run(debug=True, port=10000)




