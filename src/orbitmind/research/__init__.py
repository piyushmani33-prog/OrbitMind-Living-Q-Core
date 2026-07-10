"""Governed offline research-learning foundation (U4.0A).

Learning here means a structured record written through an injected repository port.
This package does not modify model weights, code, permissions, or runtime policy.
"""

from orbitmind.research.models import (
    DerivedResearchClaim,
    NormalizedResearchDocument,
    OpenResearchActivation,
    ResearchCycleRecord,
    ResearchEvidence,
    ResearchGap,
    ResearchInput,
    ResearchLearningRecord,
    ResearchRequest,
    UserResearchResult,
)
from orbitmind.research.service import GovernedResearchLearningService

__all__ = [
    "DerivedResearchClaim",
    "GovernedResearchLearningService",
    "NormalizedResearchDocument",
    "OpenResearchActivation",
    "ResearchCycleRecord",
    "ResearchEvidence",
    "ResearchGap",
    "ResearchInput",
    "ResearchLearningRecord",
    "ResearchRequest",
    "UserResearchResult",
]
