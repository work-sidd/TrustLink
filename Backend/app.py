from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
import firebase_admin
from firebase_admin import credentials, firestore
import os
import tempfile
import json
import re

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
    response = requests.get(search_url, headers=HEADERS)
    if response.status_code != 200:
        return {"error": "Failed to fetch search results"}

    soup = BeautifulSoup(response.text, "html.parser")
    product_data = {}

    for link_tag in soup.select("a.a-link-normal.s-line-clamp-3.s-link-style.a-text-normal"):
        title_tag = link_tag.find("h2", class_="a-size-base-plus a-spacing-none a-color-base a-text-normal")
        if title_tag:
            product_name = title_tag.get_text(strip=True)
            product_url = "https://www.amazon.in" + link_tag["href"]
            product_data[product_name] = product_url

    return product_data

def scrape_amazon_product_page(product_url):
    """
    Scrapes an Amazon product page to extract the product name and return it as a dictionary.
    """
    response = requests.get(product_url, headers=HEADERS)
    if response.status_code != 200:
        return {"error": "Failed to fetch product page"}

    soup = BeautifulSoup(response.text, "html.parser")
    product_name_tag = soup.select_one("#productTitle")

    if not product_name_tag:
        return {"error": "Product title not found"}

    product_name = product_name_tag.get_text(strip=True)
    return {product_name: product_url}

def scrape_amazon(amazon_url):
    """
    Determines if the URL is a search results page or a product page
    and calls the appropriate scraping method.
    """
    if "/s?" in amazon_url:  
        return scrape_amazon_search_results(amazon_url)
    elif "/dp/" in amazon_url or "/gp/" in amazon_url:  
        return scrape_amazon_product_page(amazon_url)
    else:
        return {"error": "Invalid Amazon URL format"}
    
def clean_amazon_title(title, word_limit=6):
    title = re.sub(r'\[.*?\]|\(.*?\)', '', title)

    title = re.sub(r'[|/,:]', '', title)
    title = re.sub(r'\s+', ' ', title)

    words = title.strip().split()
    short_title = ' '.join(words[:word_limit])
    return short_title

def store_in_firestore(products):
    """
    Stores the product(s) in Firebase Firestore.
    """
    for product_name, product_url in products.items():  
        try:
            product_ref = db.collection("products").document()
            cleaned_name = clean_amazon_title(product_name)
            product_data = {
                "name": cleaned_name,
                "full_name": product_name,
                "url": product_url 
            }
            product_ref.set(product_data)
            print(f"✅ Stored in Firestore: {product_name}")
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

    product_data = scrape_amazon(amazon_url)

    if "error" in product_data:
        return jsonify({"error": product_data["error"]}), 400

    try:
        store_in_firestore(product_data)
        return jsonify({"message": "✅ Product details saved successfully!"})
    except Exception as e:
        return jsonify({"error": f"Firestore Error: {e}"}), 500

if __name__ == "__main__":
    app.run(debug=True, port=10000)




