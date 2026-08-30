"""Churn under both keyings, computed exactly as the Stage 0 analyser did.

The service dedups on the semantic key. It measures churn under BOTH that key and
FeedEntity.id, because Stage 0's finding was that the two can disagree -- and a
disagreement that stops being measured becomes an assumption (ADR 0009 decision 1).

The definition is the analyser's, unchanged: the fraction of keys added, removed,
or whose id-cleared payload changed, over the union of both snapshots' keys.
"""
from __future__ import annotations


def churn(previous: dict, current: dict) -> float | None:
    union = set(previous) | set(current)
    if not union:
        return None
    added = len(set(current) - set(previous))
    removed = len(set(previous) - set(current))
    modified = sum(1 for key in set(previous) & set(current) if previous[key] != current[key])
    return (added + removed + modified) / len(union)


class ChurnTracker:
    """Holds one previous snapshot per keying and reports per-snapshot churn."""

    def __init__(self) -> None:
        self._previous_semantic: dict | None = None
        self._previous_entity_id: dict | None = None
        self.semantic: list[float] = []
        self.entity_id: list[float] = []

    def observe(self, by_semantic: dict, by_entity_id: dict) -> dict:
        result = {"semantic": None, "entity_id": None}
        if self._previous_semantic is not None:
            value = churn(self._previous_semantic, by_semantic)
            if value is not None:
                result["semantic"] = value
                self.semantic.append(value)
        if self._previous_entity_id is not None:
            value = churn(self._previous_entity_id, by_entity_id)
            if value is not None:
                result["entity_id"] = value
                self.entity_id.append(value)
        self._previous_semantic = by_semantic
        self._previous_entity_id = by_entity_id
        return result
