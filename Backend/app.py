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

def clean_amazon_title(title, word_limit=6):
    title = re.sub(r'\[.*?\]|\(.*?\)', '', title)

    title = re.sub(r'[|/,:]', '', title)
    title = re.sub(r'\s+', ' ', title)

    words = title.strip().split()
    short_title = ' '.join(words[:word_limit])
    return short_title

def extract_asin_from_url(url):
    """Extract ASIN from a standard Amazon URL."""
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

def store_in_firestore(products):
    for asin, product_info in products.items():
        try:
            product_ref = db.collection("products").document()
            product_ref.set(product_info)
            print(f"✅ Stored in Firestore: {product_info['full_name']} (ASIN: {asin})")
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

@app.route('/match-product', methods=['POST'])
def match_product():
    data = request.json
    incoming_name = data.get("product_name")

    if not incoming_name:
        return jsonify({"error": "Missing product name"}), 400

    try:
        cleaned_input = clean_amazon_title(incoming_name)

        products_ref = db.collection("products").stream()

        cleaned_to_doc = {}
        doc_id_to_data = {}

        for doc in products_ref:
            doc_data = doc.to_dict()
            name = doc_data.get("name")
            if name:
                cleaned_name = clean_amazon_title(name)
                cleaned_to_doc[cleaned_name] = doc.id
                doc_id_to_data[doc.id] = doc_data  

        best_match, score = process.extractOne(
            cleaned_input, cleaned_to_doc.keys(), scorer=fuzz.token_sort_ratio
        )

        matched_doc_id = cleaned_to_doc[best_match]
        matched_product = doc_id_to_data[matched_doc_id]

        matched_product_name = matched_product.get("name")
        matched_asin = matched_product.get("asin")

        trustified_ref = db.collection("trustified_data").list_documents()
        trustified_ids = [doc.id for doc in trustified_ref]

        best_trustified_id, trust_score = process.extractOne(
            matched_product_name, trustified_ids, scorer=fuzz.token_sort_ratio
        )

        if trust_score > 60:
            trust_doc = db.collection("trustified_data").document(best_trustified_id).get()
            trust_data = trust_doc.to_dict()

            return jsonify({
                "asin": matched_asin,
                "testing_status": trust_data.get("testing_status"),
                "tested_by": trust_data.get("tested_by"),
                "batch_no": trust_data.get("batch_no"),
                "published_date": trust_data.get("published_date"),
                "report_url": trust_data.get("report_url")
            })
        else:
            return jsonify({"message": "No sufficiently close match found"}), 404

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/trust-data', methods=['POST'])
def get_batch_trust_data():
    try:
        data = request.get_json()
        asin_list = data.get("asins", [])
        if not asin_list:
            return jsonify({}), 400

        trustified_ref = db.collection("trustified_data")
        result = {}

        for asin in asin_list:
            products_query = db.collection("products").where("asin", "==", asin).stream()
            product_doc = next(products_query, None)
            if product_doc:
                full_name = product_doc.to_dict().get("full_name", "")
                trust_match = trustified_ref.document(full_name).get()
                if trust_match.exists:
                    trust_data = trust_match.to_dict()
                    result[asin] = {
                        "testing_status": trust_data.get("testing_status"),
                        "tested_by": trust_data.get("tested_by"),
                        "batch_no": trust_data.get("batch_no"),
                        "published_date": trust_data.get("published_date"),
                        "report_url": trust_data.get("report_url")
                    }

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500



if __name__ == "__main__":
    app.run(debug=True, port=10000)




