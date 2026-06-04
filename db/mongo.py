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
    

def test_connection():
    """Verifies connection status to the cluster."""
    print("Connecting to MongoDB Atlas...")
    client = get_db_client()
    if client:
        try:
            client.admin.command('ping')
            print("Successfully connected to MongoDB Atlas.")

            db = client['morsegrid_outfitters']
            print(f"Database context targeted: '{db.name}'")
        except Exception as e:
            print(f"Connection error: Could not reach Atlas cluster.\n{e}")
        finally:
            client.close()