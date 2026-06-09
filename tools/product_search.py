import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from embeddings import get_vertex_embedding
from db.mongo import get_db_client

PRODUCTS_INDEX = "products_vector_index"


def find_similar_products(query_text: str, limit: int = 5) -> list:
    """
    Find motorcycle gear products most semantically similar to the query.
    Uses Atlas Vector Search on the product catalog.

    Args:
        query_text: A natural-language description of what the customer is interested in.
                    E.g. "vintage cafe racer leather jacket" or "adventure touring helmet".
        limit: Maximum number of products to return (default 5, max 10).

    Returns:
        A list of dicts, each with: product_id, title, category, price, description.
        Returns an error dict if the search fails.
    """
    try:
        limit = min(int(limit), 10)
        vec = get_vertex_embedding(query_text)
        client = get_db_client()
        db = client["morsegrid_outfitters"]
        pipeline = [
            {
                "$vectorSearch": {
                    "index": PRODUCTS_INDEX,
                    "path": "desc_vector",
                    "queryVector": vec,
                    "numCandidates": 100,
                    "limit": limit + 5,  # over-fetch to absorb out-of-stock filter
                }
            },
            {"$match": {"in_stock": True}},
            {"$limit": limit},
            {
                "$project": {
                    "product_id": 1,
                    "title": 1,
                    "category": 1,
                    "price": 1,
                    "description": 1,
                    "score": {"$meta": "vectorSearchScore"},
                    "_id": 0,
                }
            },
        ]
        results = list(db.products.aggregate(pipeline))
        return results if results else [{"info": "No matching in-stock products found."}]
    except Exception as exc:
        return [{"error": str(exc)}]
