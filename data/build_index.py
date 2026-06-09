import os
import sys
import time
from dotenv import load_dotenv

# Ensure the root folder is in the python path so we can import db + embeddings
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.mongo import get_db_client
from embeddings import get_vertex_embedding

from pymongo.operations import SearchIndexModel

load_dotenv()

DB_NAME = "morsegrid_outfitters"
EMBED_DIM = 768  # text-embedding-004
PRODUCTS_INDEX = "products_vector_index"
CUSTOMERS_INDEX = "customers_vector_index"


def embed_products(db):
    """Embed each product (title + description + category + tags) into desc_vector."""
    prods = list(db.products.find({}))
    done = 0
    for p in prods:
        text = (f"{p['title']}. {p['description']} "
                f"Category: {p['category']}. Tags: {', '.join(p.get('tags', []))}.")
        vec = get_vertex_embedding(text)
        if vec:
            db.products.update_one({"_id": p["_id"]}, {"$set": {"desc_vector": vec}})
            done += 1
    print(f"OK - embedded {done}/{len(prods)} products")


def embed_customers(db):
    """Embed each customer's behavior_summary into behavior_vector."""
    custs = list(db.customers.find({}))
    done = 0
    for c in custs:
        text = c.get("behavior_summary") or c.get("name", "")
        vec = get_vertex_embedding(text)
        if vec:
            db.customers.update_one({"_id": c["_id"]}, {"$set": {"behavior_vector": vec}})
            done += 1
    print(f"OK - embedded {done}/{len(custs)} customers")


def ensure_vector_index(coll, name, path):
    existing = [ix["name"] for ix in coll.list_search_indexes()]
    if name in existing:
        print(f"OK - index '{name}' already exists")
        return
    model = SearchIndexModel(
        definition={"fields": [{
            "type": "vector",
            "path": path,
            "numDimensions": EMBED_DIM,
            "similarity": "cosine",
        }]},
        name=name,
        type="vectorSearch",
    )
    coll.create_search_index(model=model)
    print(f"OK - created index '{name}' (building...)")


def wait_until_ready(coll, name, timeout=300):
    start = time.time()
    while time.time() - start < timeout:
        for ix in coll.list_search_indexes():
            if ix["name"] == name and ix.get("queryable"):
                print(f"OK - index '{name}' is queryable")
                return True
        time.sleep(5)
    print(f"WARN - index '{name}' not queryable after {timeout}s")
    return False


def test_search(db, query="vintage cafe racer leather jacket"):
    print(f"\nTest vector search: '{query}'")
    qvec = get_vertex_embedding(query)
    if not qvec:
        print("ERROR - could not embed test query")
        return
    pipeline = [
        {"$vectorSearch": {
            "index": PRODUCTS_INDEX,
            "path": "desc_vector",
            "queryVector": qvec,
            "numCandidates": 100,
            "limit": 5,
        }},
        {"$project": {"_id": 0, "title": 1, "category": 1,
                      "score": {"$meta": "vectorSearchScore"}}},
    ]
    results = list(db.products.aggregate(pipeline))
    for r in results:
        print(f"  {r['score']:.3f}  {r['title']} ({r['category']})")
    if results:
        print(f"DONE - vector search returned {len(results)} hits  <-- DAY 1 PASS GATE")
    else:
        print("WARN - vector search returned 0 hits (index may still be building)")


def main():
    client = get_db_client()
    if not client:
        print("ERROR - no DB connection")
        return
    db = client[DB_NAME]

    print("Embedding documents with Vertex text-embedding-004 ...")
    embed_products(db)
    embed_customers(db)

    print("\nCreating Atlas Vector Search indexes ...")
    ensure_vector_index(db.products, PRODUCTS_INDEX, "desc_vector")
    ensure_vector_index(db.customers, CUSTOMERS_INDEX, "behavior_vector")

    print("\nWaiting for indexes to build (can take 1-3 min on Atlas M0) ...")
    wait_until_ready(db.products, PRODUCTS_INDEX)
    wait_until_ready(db.customers, CUSTOMERS_INDEX)

    test_search(db)
    client.close()


if __name__ == "__main__":
    main()
