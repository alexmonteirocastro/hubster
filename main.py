import argparse

from db import (
    backfill_job_title_company_metadata,
    create_collection,
    get_qdrant_client,
    get_settings,
    query_jobs_in_qdrant,
    seed_dev_qdrant_db,
    seed_qdrant_db,
    sync_qdrant_db,
)


def main(mode: str = "sync"):
    settings = get_settings()
    client = get_qdrant_client()

    if mode == "seed-dev":
        if settings.qdrant_dev_collection_name == settings.qdrant_collection_name:
            raise ValueError(
                "QDRANT_DEV_COLLECTION_NAME must differ from QDRANT_COLLECTION_NAME."
            )
        print(
            f"Seeding dev retrieval collection '{settings.qdrant_dev_collection_name}'..."
        )
        seed_dev_qdrant_db(client, settings.qdrant_dev_collection_name)
        collection_name = settings.qdrant_dev_collection_name
    elif mode == "backfill":
        print(
            f"Backfilling job_title/company on '{settings.qdrant_collection_name}'..."
        )
        backfill_job_title_company_metadata(client, settings.qdrant_collection_name)
        return
    elif mode == "backfill-dev":
        if settings.qdrant_dev_collection_name == settings.qdrant_collection_name:
            raise ValueError(
                "QDRANT_DEV_COLLECTION_NAME must differ from QDRANT_COLLECTION_NAME."
            )
        print(
            f"Backfilling job_title/company on '{settings.qdrant_dev_collection_name}'..."
        )
        backfill_job_title_company_metadata(
            client, settings.qdrant_dev_collection_name
        )
        return
    else:
        create_collection(client, settings.qdrant_collection_name)
        collection_name = settings.qdrant_collection_name

        if mode == "seed":
            print("Running full seed (bootstrap)...")
            seed_qdrant_db(client, settings.qdrant_collection_name)
        elif mode == "sync":
            print("Running incremental sync...")
            sync_qdrant_db(client, settings.qdrant_collection_name)
        else:
            raise ValueError(
                f"Unknown mode: {mode}. Use 'sync', 'seed', 'seed-dev', "
                "'backfill', or 'backfill-dev'."
            )

    print("\n--- Testing Search ---")

    response = query_jobs_in_qdrant(
        db_client=client,
        collection_name=collection_name,
        query_text="Looking for a Python developer in Denmark",
    )

    for hit in response.points:
        print(f"Score: {hit.score:.4f} | Job: {hit.payload.get('job_role')}")


def _run_main():
    parser = argparse.ArgumentParser(description="Ingest Hub jobs into Qdrant")
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Full bootstrap seed (first run). Default is incremental sync.",
    )
    parser.add_argument(
        "--seed-dev",
        action="store_true",
        help="Seed the dev retrieval collection with a small country sample.",
    )
    parser.add_argument(
        "--backfill",
        action="store_true",
        help=(
            "One-time migration: add job_title/company payload fields to "
            "already-indexed points. Required after deploying ALE-81."
        ),
    )
    parser.add_argument(
        "--backfill-dev",
        action="store_true",
        help="Same as --backfill, but targets QDRANT_DEV_COLLECTION_NAME.",
    )
    args = parser.parse_args()

    selected_modes = [
        name
        for name, enabled in (
            ("seed", args.seed),
            ("seed-dev", args.seed_dev),
            ("backfill", args.backfill),
            ("backfill-dev", args.backfill_dev),
        )
        if enabled
    ]
    if len(selected_modes) > 1:
        parser.error(
            "Use only one of --seed, --seed-dev, --backfill, or --backfill-dev."
        )

    if args.seed_dev:
        mode = "seed-dev"
    elif args.seed:
        mode = "seed"
    elif args.backfill_dev:
        mode = "backfill-dev"
    elif args.backfill:
        mode = "backfill"
    else:
        mode = "sync"

    main(mode=mode)


if __name__ == "__main__":
    _run_main()
