import os
from google.cloud import aiplatform
from vertexai.language_models import TextEmbeddingModel
from dotenv import load_dotenv

load_dotenv()

aiplatform.init(
    project=os.getenv("PROJECT_ID"),
    location=os.getenv("LOCATION")
)

def get_vertex_embedding(text: str):
    """Generates vector embedding using Google's text-embedding-004 model."""
    try:
        model = TextEmbeddingModel.from_pretrained("text-embedding-004")
        embeddings = model.get_embeddings([text])
        return embeddings[0].values
    except Exception as e:
        print(f"Error generating embedding: {e}")
        return None
    

if __name__ == "__main__":
    test_text = "Classic Leather Cafe Racer Jacket - Premium Quality"
    print("Testing Vertex AI Embeddings...")
    vector = get_vertex_embedding(test_text)
    
    if vector:
        print(f"Success! Generated a vector of length: {len(vector)}")
        print(f"First few numbers of the vector: {vector[:5]}")