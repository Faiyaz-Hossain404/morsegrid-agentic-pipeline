import os
from google import genai
from google.genai.types import EmbedContentConfig
from dotenv import load_dotenv

load_dotenv()

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(
            vertexai=True,
            project=os.getenv("PROJECT_ID"),
            location=os.getenv("LOCATION", "us-central1"),
        )
    return _client


def get_vertex_embedding(text: str):
    """Generate a 768-dim embedding using text-embedding-004 (google-genai SDK)."""
    try:
        response = _get_client().models.embed_content(
            model="text-embedding-004",
            contents=text,
            config=EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
        )
        return response.embeddings[0].values
    except Exception as e:
        print(f"\n Error generating embedding: {e}")
        return None


if __name__ == "__main__":
    test_text = "Yo Yo Test This Shyt"
    print("Testing Vertex AI Embeddings...")
    vector = get_vertex_embedding(test_text)

    if vector:
        print("SUCCESS")
        print(f"Generated Vector Dimensions: {len(vector)}")
        print(f"First numbers of the vector: {vector[0:5]}")
