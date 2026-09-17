from functools import lru_cache
from typing import Any

from django.conf import settings
from elasticsearch import Elasticsearch

from clx.app.models import DemoDocket


@lru_cache(maxsize=1)
def search_client() -> Elasticsearch:
    """The process-wide elasticsearch client."""
    return Elasticsearch(settings.ELASTICSEARCH_URL)


def demo_docket_index() -> str:
    """The alias the demo dockets index is reached through."""
    return f"{settings.ELASTICSEARCH_INDEX_PREFIX}-demo-docket"


DEMO_DOCKET_MAPPING: dict[str, Any] = {
    "dynamic": "strict",
    "properties": {
        "docket_id": {"type": "keyword"},
        "court_id": {"type": "keyword"},
        "case_name": {"type": "text"},
        "docket_number": {"type": "text"},
        "date_filed": {"type": "date"},
        "date_terminated": {"type": "date"},
        "nature_of_suit": {"type": "keyword"},
        "jurisdiction": {"type": "keyword"},
        "jury_demand": {"type": "keyword"},
        "cause": {"type": "text"},
        "assigned_to_str": {"type": "text"},
        "referred_to_str": {"type": "text"},
        "parties": {
            "properties": {
                "name": {"type": "text"},
                "type": {"type": "keyword"},
                "extra_info": {"type": "text"},
                "attorneys": {
                    "properties": {
                        "name": {"type": "text"},
                        "contact": {"type": "text"},
                        "roles": {"type": "keyword"},
                    },
                },
            },
        },
        "entries": {
            "properties": {
                "date_filed": {"type": "date"},
                "document_number": {"type": "keyword"},
                "description": {"type": "text"},
            },
        },
    },
}


def demo_docket_document(docket: DemoDocket) -> dict[str, Any]:
    """The search document for a docket, shaped to DEMO_DOCKET_MAPPING."""
    return {
        "docket_id": docket.docket_id,
        "court_id": docket.court_id,
        "case_name": docket.case_name,
        "docket_number": docket.docket_number,
        "date_filed": docket.date_filed,
        "date_terminated": docket.date_terminated,
        "nature_of_suit": docket.nature_of_suit,
        "jurisdiction": docket.jurisdiction,
        "jury_demand": docket.jury_demand,
        "cause": docket.cause,
        "assigned_to_str": docket.assigned_to_str,
        "referred_to_str": docket.referred_to_str,
        "parties": [
            {
                "name": party.name,
                "type": party.type,
                "extra_info": party.extra_info,
                "attorneys": [
                    {
                        "name": attorney.name,
                        "contact": attorney.contact,
                        "roles": attorney.roles,
                    }
                    for attorney in party.attorneys.all()
                ],
            }
            for party in docket.parties.all()
        ],
        "entries": [
            {
                "date_filed": entry.date_filed,
                "document_number": entry.document_number,
                "description": entry.description,
            }
            for entry in docket.entries.all()
        ],
    }
