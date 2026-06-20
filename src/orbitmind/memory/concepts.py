"""Concept registry service (deterministic, curated)."""

from __future__ import annotations

from orbitmind.core.errors import ValidationError
from orbitmind.memory.models import ScientificConcept
from orbitmind.memory.repository import SqlAlchemyMemoryRepository


class ConceptService:
    """Registers curated scientific concepts + terms + senses."""

    def register(
        self, concept: ScientificConcept, repo: SqlAlchemyMemoryRepository
    ) -> ScientificConcept:
        if not concept.canonical_name.strip():
            raise ValidationError("concept canonical_name is required")
        repo.add_concept(concept)
        return concept
