
import json
import math
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List


app = FastAPI()

# Allow POST requests from any origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["*"],
)

# Load the supplied telemetry file.
DATA_FILE = Path(__file__).resolve().parent.parent / "q-vercel-latency.json"


class LatencyRequest(BaseModel):
    regions: List[str]
    threshold_ms: float = 180


def load_records():
    if not DATA_FILE.exists():
        raise HTTPException(
            status_code=500,
            detail="Telemetry JSON file was not found."
        )

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (json.JSONDecodeError, OSError):
        raise HTTPException(
            status_code=500,
            detail="Could not read telemetry JSON file."
        )

    # Support either a JSON array or records nested inside an object.
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ("records", "data", "telemetry", "pings"):
            if isinstance(data.get(key), list):
                return data[key]

    raise HTTPException(
        status_code=500,
        detail="Unexpected telemetry JSON structure."
    )


def get_value(record, possible_keys):
    for key in possible_keys:
        if key in record and record[key] is not None:
            return record[key]
    return None


def percentile_95(values):
    if not values:
        return 0.0

    values = sorted(values)
    position = 0.95 * (len(values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)

    if lower == upper:
        return float(values[lower])

    fraction = position - lower
    return float(
        values[lower] * (1 - fraction)
        + values[upper] * fraction
    )


@app.post("/")
def calculate_latency(request: LatencyRequest):
    records = load_records()
    results = []

    for region in request.regions:
        region_records = [
            record for record in records
            if isinstance(record, dict)
            and str(
                get_value(record, ["region", "location", "storefront"])
            ).lower() == region.lower()
        ]

        latencies = []
        uptimes = []

        for record in region_records:
            latency = get_value(
                record,
                ["latency_ms", "latencyMs", "latency"]
            )

            uptime = get_value(
                record,
                ["uptime", "uptime_pct", "uptime_percent"]
            )

            if latency is not None:
                try:
                    latencies.append(float(latency))
                except (ValueError, TypeError):
                    pass

            if uptime is not None:
                try:
                    uptimes.append(float(uptime))
                except (ValueError, TypeError):
                    pass

        results.append({
            "region": region,
            "avg_latency": (
                sum(latencies) / len(latencies)
                if latencies else 0.0
            ),
            "p95_latency": percentile_95(latencies),
            "avg_uptime": (
                sum(uptimes) / len(uptimes)
                if uptimes else 0.0
            ),
            "breaches": sum(
                latency > request.threshold_ms
                for latency in latencies
            ),
        })

    return {"results": results}
