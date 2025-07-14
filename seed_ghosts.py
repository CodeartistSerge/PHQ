"""
seed_ghostnames.py – one-off loader for the GhostNames kind
Run against the Datastore emulator or a real project.
"""
import os
import uuid
import itertools
import json
from google.cloud import ndb
from models import GhostNames
from dotenv import load_dotenv
load_dotenv()

PROJECT_ID = os.getenv("GOOGLE_AUTH_PROJECT_ID", "")
JSON_PATH  = os.getenv("DATA_GHOSTS_FILE", "")

if not PROJECT_ID or not JSON_PATH or not os.path.exists(JSON_PATH):
    raise ValueError((
        "Please set GOOGLE_AUTH_PROJECT_ID and "
        "DATA_GHOSTS_FILE environment variables correctly."
    ))

client = ndb.Client(project=PROJECT_ID)

def chunks(iterable, size=500):
    """Yield successive `size`-long chunks from iterable."""
    it = iter(iterable)
    return iter(lambda: list(itertools.islice(it, size)), [])

with client.context():
    data = json.load(open(JSON_PATH, encoding="utf-8"))
    entities = [
        GhostNames(
            ghost_unique_hash=str(uuid.uuid4()),
            ghost_name=item["name"],
            ghost_description=item.get("description", ""),
            first_name="",
            last_name="",
            email="",
            reserved_by_email=""
        )
        for item in data
    ]

    for batch in chunks(entities):
        ndb.put_multi(batch)
    print(f"Imported {len(entities)} ghost names.")
