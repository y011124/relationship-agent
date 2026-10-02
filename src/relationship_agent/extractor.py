"""Convenience extraction API using the same contracts as the full workflow."""
from .providers import build_model_client
from .schemas import SCHEMAS, validate_stage
OUTPUT_SCHEMA = SCHEMAS["extract"]


def mock_extract(user_message):
    payload = {"user_message": user_message, "language": "zh"}
    return validate_stage("extract", build_model_client().complete_json("extract", payload), payload)


def api_extract(user_message, **settings):
    payload = {"user_message": user_message, "language": "zh"}
    return build_model_client("api", **settings).complete_json("extract", payload)


glm_extract = api_extract
