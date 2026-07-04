import os

from dotenv import load_dotenv

from db import client, create_collection, drop_db, query_jobs_in_qdrant, seed_qdrant_db

load_dotenv()

collection_name = os.getenv("QDRANT_COLLECTION_NAME", "")
embedding_model = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")


def main(reset_db: bool = False):
    if reset_db:
        drop_db(client, collection_name)

    create_collection(client, collection_name)
    seed_qdrant_db(client, collection_name)

    # 4. Try a quick search to see if it works
    print("\n--- Testing Search ---")

    response = query_jobs_in_qdrant(
        db_client=client,
        collection_name=collection_name,
        query_text="Looking for a Python developer in Denmark",
    )

    # Accessing the results
    for hit in response.points:
        print(f"Score: {hit.score:.4f} | Job: {hit.payload.get('job_role')}")


if __name__ == "__main__":
    main(reset_db=True)
