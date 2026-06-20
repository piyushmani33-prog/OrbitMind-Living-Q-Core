"""JPL SBDB lookup connector: resolve one asteroid/comet by identifier."""

from __future__ import annotations

import json
import time
from collections.abc import Callable

import httpx
from pydantic import ValidationError as PydanticValidationError

from orbitmind.persistence.source_repository import SourceRepository
from orbitmind.smallbody.identifiers import validate_small_body_identifier
from orbitmind.smallbody.models import SmallBodyLookupResult
from orbitmind.sources.cache import KeyedLock, SourceCacheStore
from orbitmind.sources.errors import (
    AmbiguousIdentifierError,
    ObjectNotFoundError,
    SourceSchemaError,
)
from orbitmind.sources.fetching import CachedSourceFetcher
from orbitmind.sources.jpl.common import canonical_cache_key, jpl_freshness
from orbitmind.sources.jpl.normalization import normalize_sbdb
from orbitmind.sources.jpl.sbdb_models import SbdbOutcome, SbdbResponse
from orbitmind.sources.models import SourceDefinition, SourcePolicy


class SbdbConnector:
    """Guarded JPL Small-Body Database lookup."""

    def __init__(
        self,
        definition: SourceDefinition,
        cache_store: SourceCacheStore,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        lock: KeyedLock | None = None,
    ) -> None:
        self._def = definition
        self._policy = definition.policy
        self._fetcher = CachedSourceFetcher(
            self._policy, cache_store, transport=transport, sleep=sleep, lock=lock
        )

    @property
    def source_id(self) -> str:
        return self._def.source_id

    def policy(self) -> SourcePolicy:
        return self._policy

    def lookup(
        self, identifier: str, repo: SourceRepository, *, force_refresh: bool = False
    ) -> SmallBodyLookupResult:
        validated = validate_small_body_identifier(identifier)
        params = {"sstr": validated, "phys-par": "1"}
        cache_key = canonical_cache_key(self.source_id, params)
        fetch = self._fetcher.fetch(
            cache_key=cache_key,
            url=self._policy.base_url,
            params=params,
            repo=repo,
            force_refresh=force_refresh,
        )
        try:
            response = SbdbResponse.model_validate(json.loads(fetch.body))
        except (json.JSONDecodeError, UnicodeDecodeError, PydanticValidationError) as exc:
            raise SourceSchemaError(f"SBDB response failed validation: {exc}") from exc

        outcome = response.outcome()
        if outcome is SbdbOutcome.NOT_FOUND:
            raise ObjectNotFoundError(f"no small body matched '{validated}'")
        if outcome is SbdbOutcome.AMBIGUOUS:
            count = len(response.matches or [])
            raise AmbiguousIdentifierError(
                f"identifier '{validated}' matched {count} objects; refine it"
            )

        record = normalize_sbdb(
            response,
            requested_identifier=validated,
            source_id=self.source_id,
            fetched_at=fetch.fetched_at,
            checksum=fetch.checksum,
            schema_version=self._policy.schema_version,
            policy_version=self._policy.policy_version,
            freshness=jpl_freshness(self._policy, fetch),
        )
        return SmallBodyLookupResult(
            record=record, from_cache=fetch.from_cache, cache_status=fetch.cache_status.value
        )
