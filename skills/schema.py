"""JSON schema for persisted skills."""
from __future__ import annotations

SKILL_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "skill_id": {"type": "string"},
        "skill_type": {
            "type": "string",
            "enum": ["crawler", "response_template", "memory_weight"],
        },
        "platform": {"type": "string"},
        "source_layer": {"type": "string"},
        "tool_name": {"type": "string"},
        "description": {"type": "string"},
        "logic": {"type": "string"},
        "input_template": {"type": "object"},
        "success_rate": {"type": "number"},
        "created_by": {"type": "string", "enum": ["runtime_learning", "manual"]},
        "created_at": {"type": "string"},
        "last_used": {"type": "string"},
        "version": {"type": "integer"},
        "usage_count": {"type": "integer"},
        "success_count": {"type": "integer"},
        "failure_count": {"type": "integer"},
        "consecutive_failures": {"type": "integer"},
        "heal_required": {"type": "boolean"},
        "metadata": {"type": "object"},
    },
    "required": [
        "skill_id",
        "skill_type",
        "platform",
        "source_layer",
        "tool_name",
        "description",
        "logic",
        "created_by",
        "created_at",
        "version",
    ],
}
