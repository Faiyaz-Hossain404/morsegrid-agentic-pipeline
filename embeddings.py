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