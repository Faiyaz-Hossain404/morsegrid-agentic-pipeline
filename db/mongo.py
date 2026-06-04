import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

def get_db_client():
    """Initialize and returns a connection client to MongoDB Atlas."""
    uri = os.getenv("MONGODB_URI")
    if not uri:
        raise ValueError("MONGODB_URI missing from environment variables")
    try:
        client = MongoClient(uri, serverSelectioinTimeoutMS=10000)
        return client
    except Exception as e:
        print(f"Failed to parse MongoDB connection URI: {e}")
        return None