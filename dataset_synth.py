"""
dataset_synth.py — Protocol Dataset Synth (Local Data Generator).

Generates large structured mock datasets locally — no API calls per row,
so "hundreds of thousands of entries" is actually fast. The LLM is used
once, up front, to turn a natural-language request into a field schema;
the bulk row generation itself is done with Faker + random, which is
what makes it scale to huge row counts.

Output: CSV (or JSON) written to audio_cache/, so results are usable in
Excel/pandas/whatever the user's testing/interview-prep needs.
"""

import json
import csv
import os
import random
import ollama
from faker import Faker
import model_router

fake = Faker()
OUTPUT_DIR = "audio_cache"

# Field-type keywords -> a Faker (or random) generator. The schema parser
# below maps whatever the LLM extracts onto the closest of these.
FIELD_GENERATORS = {
    "name": fake.name,
    "first_name": fake.first_name,
    "last_name": fake.last_name,
    "email": fake.email,
    "phone": fake.phone_number,
    "address": fake.address,
    "city": fake.city,
    "country": fake.country,
    "company": fake.company,
    "job_title": fake.job,
    "date": lambda: fake.date_between(start_date="-3y", end_date="today").isoformat(),
    "datetime": lambda: fake.date_time_between(start_date="-3y", end_date="now").isoformat(),
    "id": lambda: fake.uuid4(),
    "boolean": lambda: random.choice([True, False]),
    "integer": lambda: random.randint(1, 10000),
    "price": lambda: round(random.uniform(1, 5000), 2),
    "percentage": lambda: round(random.uniform(0, 100), 2),
    "sentence": fake.sentence,
    "paragraph": fake.paragraph,
    "url": fake.url,
    "ip_address": fake.ipv4,
    "category": lambda: random.choice(["A", "B", "C", "D"]),
    "status": lambda: random.choice(["active", "inactive", "pending", "closed"]),
}


def _parse_schema(natural_language_request: str) -> dict:
    """Uses the fast local model once to turn a request like 'generate
    50000 rows of customer data with name, email, signup date, and
    lifetime value' into a structured field list + row count."""
    field_types = ", ".join(FIELD_GENERATORS.keys())
    prompt = f"""
    Extract a dataset generation request into JSON with keys:
    - "row_count": integer (default 1000 if not specified, cap at 500000)
    - "dataset_name": short snake_case name for the file
    - "fields": a list of field names, each mapped to the closest matching type from this list: [{field_types}]
      Output fields as a list of {{"name": "<field name the user wants>", "type": "<closest type from the list>"}}

    Output ONLY valid JSON.
    Request: "{natural_language_request}"
    """
    try:
        response = ollama.chat(
            model=model_router.select_model("dataset_synth"),
            messages=[{'role': 'system', 'content': prompt}],
            format='json'
        )
        parsed = json.loads(response['message']['content'].strip())
        parsed["row_count"] = min(int(parsed.get("row_count", 1000)), 500000)
        if not parsed.get("fields"):
            parsed["fields"] = [{"name": "id", "type": "id"}, {"name": "name", "type": "name"}]
        return parsed
    except Exception as e:
        print(f"[Dataset Synth Parse Error]: {e}")
        return {"row_count": 1000, "dataset_name": "mock_dataset", "fields": [{"name": "id", "type": "id"}, {"name": "name", "type": "name"}]}


def generate_dataset(natural_language_request: str) -> str:
    """Entry point for executor.py's 'dataset_synth' action."""
    schema = _parse_schema(natural_language_request)
    row_count = schema["row_count"]
    fields = schema["fields"]
    dataset_name = schema.get("dataset_name", "mock_dataset").replace(" ", "_")

    generators = []
    for field in fields:
        field_type = field.get("type", "sentence")
        gen = FIELD_GENERATORS.get(field_type, FIELD_GENERATORS["sentence"])
        generators.append((field["name"], gen))

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, f"{dataset_name}.csv")

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([name for name, _ in generators])
        for _ in range(row_count):
            writer.writerow([gen() for _, gen in generators])

    field_names = ", ".join(name for name, _ in generators)
    return (f"Synthesized {row_count} rows across [{field_names}], macha. "
            f"Saved to {output_path}.")
