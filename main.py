import argparse
import os

from dotenv import load_dotenv

from db import client, create_collection, query_jobs_in_qdrant, seed_qdrant_db, sync_qdrant_db

load_dotenv()

collection_name = os.getenv("QDRANT_COLLECTION_NAME", "")


def main(mode: str = "sync"):
    create_collection(client, collection_name)

    if mode == "seed":
        print("Running full seed (bootstrap)...")
        seed_qdrant_db(client, collection_name)
    elif mode == "sync":
        print("Running incremental sync...")
        sync_qdrant_db(client, collection_name)
    else:
        raise ValueError(f"Unknown mode: {mode}. Use 'sync' or 'seed'.")

    print("\n--- Testing Search ---")

    response = query_jobs_in_qdrant(
        db_client=client,
        collection_name=collection_name,
        query_text="Looking for a Python developer in Denmark",
    )

    for hit in response.points:
        print(f"Score: {hit.score:.4f} | Job: {hit.payload.get('job_role')}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest Hub jobs into Qdrant")
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Full bootstrap seed (first run). Default is incremental sync.",
    )
    args = parser.parse_args()
    main(mode="seed" if args.seed else "sync")
