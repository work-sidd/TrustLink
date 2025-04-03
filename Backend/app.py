from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
import firebase_admin
from firebase_admin import credentials, firestore
import os
import tempfile
import json

app = Flask(__name__)


firebase_credentials = json.loads(os.getenv("FIREBASE_CREDENTIALS"))

with tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".json") as temp_file:
    json.dump(firebase_credentials, temp_file)
    temp_file_path = temp_file.name  

cred = credentials.Certificate(temp_file_path)
firebase_admin.initialize_app(cred)
db = firestore.client()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
}

def scrape_amazon_search_results(search_url):
    """
    Scrapes Amazon search results page to extract product names.
    """
    response = requests.get(search_url, headers=HEADERS)
    if response.status_code != 200:
        return {"error": "Failed to fetch search results"}

    soup = BeautifulSoup(response.text, "html.parser")
    products = []

    for item in soup.select(".s-main-slot .s-result-item"):
        title_tag = item.select_one("h2 a.a-link-normal")
        if title_tag:
            product_name = title_tag.get_text(strip=True)
            products.append({"name": product_name})  

    return products

def scrape_amazon_product_page(product_url):
    """
    Scrapes an Amazon product page to extract the product name.
    """
    response = requests.get(product_url, headers=HEADERS)
    if response.status_code != 200:
        return {"error": "Failed to fetch product page"}

    soup = BeautifulSoup(response.text, "html.parser")
    product_name = soup.select_one("#productTitle")

    return {"name": product_name.get_text(strip=True)} if product_name else {"error": "Product title not found"}

def scrape_amazon(amazon_url):
    """
    Determines if the URL is a search results page or a product page
    and calls the appropriate scraping method.
    """
    if "/s?" in amazon_url:  # Identifies search results page
        return scrape_amazon_search_results(amazon_url)
    elif "/dp/" in amazon_url or "/gp/" in amazon_url:  # Identifies a product page
        return scrape_amazon_product_page(amazon_url)
    else:
        return {"error": "Invalid Amazon URL format"}

def store_in_firestore(products):
    """
    Stores the product(s) in Firebase Firestore.
    """
    if isinstance(products, dict): 
        products = [products] 
    for product in products:
        try:
            product_ref = db.collection("products").document()
            product_ref.set(product)
            print(f"✅ Stored in Firestore: {product['name']}")
        except Exception as e:
            print(f"❌ Firestore Error: {e}")

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
    product_data = scrape_amazon(amazon_url)

    print(f"🟢 Scraped Products: {product_data}")

    if "error" in product_data:
        return jsonify({"error": product_data["error"]}), 400

    # Store product details in Firestore
    try:
        store_in_firestore(product_data)
        return jsonify({"message": "✅ Product details saved successfully!"})
    except Exception as e:
        return jsonify({"error": f"Firestore Error: {e}"}), 500

if __name__ == "__main__":
    app.run(debug=True, port=10000)




