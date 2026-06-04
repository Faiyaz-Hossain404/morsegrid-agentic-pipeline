import os
from google.cloud import aiplatform
from vertexai.language_models import TextEmbeddingModel, TextEmbeddingInput
from dotenv import load_dotenv

load_dotenv()

aiplatform.init(
    project=os.getenv("PROJECT_ID"),
    location=os.getenv("LOCATION")
)

def get_vertex_embedding(text: str):
    """Generates vector embedding using structured inputs."""
    try:
        model = TextEmbeddingModel.from_pretrained("text-embedding-004")
        text_input = TextEmbeddingInput(text=text, task_type="RETRIEVAL_DOCUMENT")
        embeddings = model.get_embeddings([text_input])
        return embeddings[0].values
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