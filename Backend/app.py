from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
import firebase_admin
from firebase_admin import credentials, firestore
import os
import tempfile
import json
import re
from rapidfuzz import fuzz, process

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
trustified_cache = []

def normalize_name(text):
    text = text.lower()
    text = re.sub(r"[^a-z0-9]", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")

def load_trustified_data():
    global trustified_cache
    trustified_cache = []

    docs = db.collection("trustified_data").stream()
    for doc in docs:
        data = doc.to_dict()
        trustified_cache.append({
            "doc_id": doc.id,
            "brand_name": data.get("brand_name", ""),
            "product_name": data.get("product_name", ""),
            "normalized": normalize_name(f"{data.get('brand_name', '')} {data.get('product_name', '')}"),
            "testing_status": data.get("testing_status"),
            "tested_by": data.get("tested_by"),
            "batch_no": data.get("batch_no"),
            "published_date": data.get("published_date"),
            "report_url": data.get("report_url")
        })

load_trustified_data()

def clean_amazon_title(title, word_limit=6):
    title = re.sub(r'\[.*?\]|\(.*?\)', '', title)
    title = re.sub(r'[|/,:]', '', title)
    title = re.sub(r'\s+', ' ', title)
    words = title.strip().split()
    short_title = ' '.join(words[:word_limit])
    return short_title

def extract_asin_from_url(url):
    match = re.search(r"/dp/([A-Z0-9]{10})|/gp/product/([A-Z0-9]{10})", url)
    if match:
        return match.group(1) or match.group(2)
    return None

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
            asin = extract_asin_from_url(product_url)
            if asin:
                product_data[asin] = {
                    "full_name": product_name,
                    "name": clean_amazon_title(product_name),
                    "asin": asin
                }

    return product_data

def scrape_amazon_product_page(product_url):
    response = requests.get(product_url, headers=HEADERS)
    if response.status_code != 200:
        return {"error": "Failed to fetch product page"}

    soup = BeautifulSoup(response.text, "html.parser")
    product_name_tag = soup.select_one("#productTitle")
    if not product_name_tag:
        return {"error": "Product title not found"}

    product_name = product_name_tag.get_text(strip=True)
    asin = extract_asin_from_url(product_url)
    if not asin:
        return {"error": "ASIN not found in URL"}

    return {
        asin: {
            "full_name": product_name,
            "name": clean_amazon_title(product_name),
            "asin": asin
        }
    }

def scrape_amazon(amazon_url):
    if "/s?" in amazon_url:
        return scrape_amazon_search_results(amazon_url)
    elif "/dp/" in amazon_url or "/gp/" in amazon_url:
        return scrape_amazon_product_page(amazon_url)
    else:
        return {"error": "Invalid Amazon URL format"}


def match_trustified_data(product_name):
    cleaned_input = clean_amazon_title(product_name)
    normalized_input = normalize_name(cleaned_input)

    choices = [entry["normalized"] for entry in trustified_cache]
    match_result = process.extractOne(normalized_input, choices, scorer=fuzz.token_sort_ratio)

    if not match_result:
        return None

    best_match_norm, trust_score = match_result[0], match_result[1]

    if trust_score > 60:
        return next((entry for entry in trustified_cache if entry["normalized"] == best_match_norm), None)

    return None

def store_in_firestore(products):
    for asin, product_info in products.items():
        try:
            trustified_match = match_trustified_data(product_info["name"])  

            if trustified_match:  
                product_info.update({
                    "testing_status": trustified_match.get("testing_status"),
                    "tested_by": trustified_match.get("tested_by"),
                    "batch_no": trustified_match.get("batch_no"),
                    "published_date": trustified_match.get("published_date"),
                    "report_url": trustified_match.get("report_url")
                })

                product_ref = db.collection("matched_results").document(asin)  
                product_ref.set(product_info)

                print(f"✅ Stored {product_info['name']} (ASIN: {asin})")
            else:
                print(f"⚠️ No trustified match for {product_info['name']} (ASIN: {asin}) — Skipped storing.")

        except Exception as e:
            print(f"❌ Firestore Error: {e}")


@app.route('/track-url', methods=['POST'])
def track_url():
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
        return jsonify({"message": "✅ Products scraped and matched successfully!"})
    except Exception as e:
        return jsonify({"error": f"Firestore Error: {e}"}), 500

if __name__ == "__main__":
    app.run(debug=True, port=10000)





