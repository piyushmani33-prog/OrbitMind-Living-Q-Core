# Trajectory Replay Projection

## Purpose

U4.2B1 defines a deterministic, bounded, offline trajectory-replay projection for one pinned
Earth-orbit element set. It produces immutable geodetic samples and dateline-safe track segments
for a future presentation layer. It does not render, animate, persist, publish, or fetch anything.

The replay service is the scientific authority. A future U4.2B2 browser component may display and
interpolate these verified samples, but it must not propagate an orbit, transform frames, recompute
geodetic positions, or alter the source and limitation metadata.

## Supported boundary

`TrajectoryReplayRequest` accepts:

- one `PinnedOrbitElementSet` and bounded opaque trajectory reference;
- explicit timezone-aware start and end instants normalized to UTC;
- an integer sampling interval from 1 through 300 seconds;
- an explicit maximum sample count from 2 through 2,001; and
- an optional fixed `GeodeticPosition` observer.

The request duration must be positive and no longer than 24 hours. Validation calculates the exact
sample count before SGP4 initialization or propagation. Network lookup, source resolution,
persistence, scheduling, and implicit use of system local time are outside the service.

## Models

`TrajectoryReplaySample` stores an ordered sequence number, UTC timestamp, WGS84 geodetic latitude
and longitude in degrees, and WGS84 ellipsoid altitude in kilometres. When an observer is supplied,
azimuth, elevation, and slant range are present together. Samples are deterministic calculations;
partial or errored samples are not representable as completed replay output.

`TrajectoryTrackSegment` stores a contiguous range of sample indexes, its UTC start and end, and why
it began. The first segment starts with the request. Later segments begin only because of a
canonical-longitude dateline wrap.

`TrajectoryReplaySourceIdentity` contains safe object identity, the opaque trajectory reference,
source checksum and epoch, and pinned propagator/frame identifiers. It contains no raw TLE line,
source URL, provider response, cache path, or filesystem path.

`TrajectoryReplayResult` contains the ordered samples, ordered segments, source-relative start and
end offsets, deterministic references, and the fixed scientific limitation set. Its validator
requires exact endpoint inclusion, contiguous sequence and segment indexes, exact regular cadence,
complete segment membership, and consistency between observer input and observer-relative values.

## Sampling algorithm

Sampling is deterministic and endpoint-inclusive:

1. Compute the duration and expected sample count with integer microseconds.
2. Reject a request that exceeds its explicit limit or the global 2,001-sample limit.
3. Generate regular timestamps as `start + sequence * interval`.
4. Append the exact request end once.

If the duration divides evenly by the interval, the final regular sample is the end. If it does not,
the last regular sample precedes the end and the exact end is appended. Repeated floating-point
addition is not used, timestamps are unique, and no timestamp lies outside the request.

## Propagation and frame path

The reviewed path is:

`Pinned TLE -> python-sgp4/WGS72 -> TEME position -> IAU-1982 GMST rotation -> project PEF/Earth-fixed approximation -> iterative WGS84 geodetic conversion`

The public `propagate_sgp4_state` primitive in `space.propagation` is shared by the existing mission
propagation and replay service. The replay does not duplicate the SGP4 call path. It reuses
`teme_to_ecef_km`, `ecef_to_geodetic`, and, when requested, `look_angles_from_ecef`.

TEME vectors are never labeled as Earth-fixed vectors. UTC is supplied where UT1 would be required
for full Earth-orientation precision. No external Earth-orientation parameters, polar-motion
correction, full ITRF realization, terrain, refraction, weather, or optical model is used.

Latitude is WGS84 geodetic latitude, not geocentric latitude. Longitude uses the canonical range
`[-180, 180)` degrees. Altitude is kilometres relative to the WGS84 ellipsoid. The existing WGS84
conversion has an explicit polar branch and all serialized scientific values must be finite.

## Dateline segmentation

Segmentation does not project a map. It compares adjacent canonical longitudes and starts a new
segment when their absolute difference exceeds 180 degrees. Thus `179.5` followed by `-179.7` and
the reverse direction are split before a flat-map renderer can draw a false line across the world.

Every sample belongs to exactly one segment. Segments preserve sequence order and contain no lost or
duplicated sample index. A result validator rejects both a dateline crossing inside one segment and
a segment boundary without a dateline crossing.

## Deterministic references

The input reference covers schema and engine versions, element and source checksums, source epoch,
opaque trajectory reference, UTC interval, sample interval, explicit sample limit, optional observer,
and propagator/frame/geometry identifiers. It contains hashes and normalized metadata, not raw TLE
text or paths.

The result reference covers the complete canonical typed result except the result reference itself.
Fixed inputs and pinned software produce identical ordering and references. Source, observer, time,
step, or limit changes alter the input reference.

## Source age and claims

The result records signed start and end offsets from the pinned source epoch. These values expose the
prediction horizon without inventing a universal accuracy percentage or kilometre error guarantee.

Every result retains these boundaries:

- `Predicted trajectory replay; not live tracking.`
- `Predicted from the identified orbital element set using the pinned propagation and geometry model.`
- element age and object dynamics affect usefulness;
- UTC is used as a UT1 approximation and full EOP/polar-motion corrections are absent;
- this is a model prediction rather than a true current state; and
- there is no collision, maneuver, command, safety, approval, or certification authority.

The replay must not be described as real-time, a current true location, a live satellite, command
ready, operationally accurate, or certified.

## Failure and state semantics

Any required sample failure aborts the complete calculation with a bounded validation error. Earlier
locally computed samples are not returned as partial success. The service performs no database or
filesystem write, creates no artifact, and imports no API, source connector, network client,
persistence adapter, scheduler, agent, LLM, or quantum module.

## Reference validation

`tests/fixtures/trajectory_replay/iss_wgs84_reference.json` contains multiple non-equatorial ISS
samples and a dateline-adjacent pair. A one-off script generated it with python-sgp4 2.26/WGS72,
independently written IAU-1982 GMST and TEME-to-PEF rotation, and a closed-form Bowring WGS84
solution. The script did not import OrbitMind. This establishes implementation agreement for the
pinned model and fixture; it does not prove absolute orbital truth or a current satellite position.

## Planned U4.2B2 presentation

U4.2B2 may add a reviewed, local SVG presentation of this typed result. That later slice must keep
the scientific service authoritative, respect track segments, label interpolation as presentation,
show source age and limitations, and add no live/provider claim by implication.
