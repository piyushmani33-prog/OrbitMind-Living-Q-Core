"""Source-layer errors with safe, client-facing messages (SR-17)."""

from __future__ import annotations

from orbitmind.core.errors import OrbitMindError


class SourceError(OrbitMindError):
    """Base for source/connector failures."""

    code = "source_error"
    http_status = 502


class NetworkDisabledError(SourceError):
    """A live request was requested but network/source access is disabled by policy."""

    code = "network_disabled"
    http_status = 409


class SourceUnavailableError(SourceError):
    """The source could not be reached or returned no usable data."""

    code = "source_unavailable"
    http_status = 503


class SourceSchemaError(SourceError):
    """The source response failed schema/content validation."""

    code = "source_schema_error"
    http_status = 502


class DisallowedRequestError(SourceError):
    """The request violated transport policy (host/scheme/method/size)."""

    code = "disallowed_request"
    http_status = 400


class ObjectNotFoundError(SourceError):
    """The requested object was not found in the source catalogue."""

    code = "object_not_found"
    http_status = 404


class AmbiguousIdentifierError(SourceError):
    """The requested identifier matched multiple objects."""

    code = "ambiguous_identifier"
    http_status = 409
