# Mission Window Engine

## Purpose

U4.1A provides a deterministic offline application service for calculating geometric
elevation-threshold windows between one Earth-orbiting object and one fixed Earth
observer. It supports bounded satellite observation planning, ground-station contact
geometry, and educational orbital analysis. It adds no API, browser surface, persistence,
network access, provider activation, scheduler, or autonomous behavior.

The authoritative v1 statement is:

> Predicted from the identified orbital element set using the pinned propagation and
> geometry model.

The result is not current orbit truth, an operational contact authorization, or a
guarantee that an object is optically visible.

## Inputs

`MissionWindowRequest` accepts:

- one validated `PinnedOrbitElementSet` and bounded opaque trajectory reference;
- one WGS84 observer latitude/longitude and ellipsoid altitude in metres;
- an optional safe opaque observer label;
- UTC-aware start and end times with a maximum 24-hour horizon;
- a minimum elevation in `[0, 90)` degrees;
- a deterministic coarse step from 5 to 300 seconds.

Longitude uses the existing `[-180, 180]` east-positive convention. Observer altitude is
bounded to `[-500, 9000]` metres. The start/end-inclusive grid is limited to 2,001
samples, which may constrain the smallest step for a long request. There is no city
geocoding or observer-location lookup.

## Output Semantics

`MissionWindowResult` records source/object identity, source epoch, pinned propagation
and geometry model identifiers, observer and request bounds, source-epoch-to-request
offsets, ordered windows, fixed numerical tolerances, deterministic input/result
references, epistemic status, and limitations. A valid computation with no qualifying
window returns `completed` with an empty window tuple.

Each `MissionWindowEvent` contains rise, refined peak, and set times; rise/peak/set
azimuths; maximum elevation; positive duration; and explicit clipping flags. `rise_time`
or `set_time` equals the request boundary when the geometric event extends outside the
requested interval. Those clipped values are interval representations, not invented
crossing times outside the calculation horizon.

## Propagation, Frame, And Time Path

The service reuses `ObservationGeometryEvaluator`; it does not implement another orbit
propagator or coordinate transform:

1. The pinned TLE is parsed and checked for propagatability by `python-sgp4`.
2. SGP4 propagates with its WGS72 model and returns position in TEME kilometres.
3. The UTC instant is converted to a Julian date. The project approximates UT1 with UTC.
4. The IAU-1982 GMST polynomial rotates TEME into the project's PEF/Earth-fixed
   approximation. TEME is never labelled ECEF.
5. The WGS84 geodetic observer is converted to Earth-fixed coordinates.
6. The relative Earth-fixed vector is rotated into local east/north/up coordinates.
7. Azimuth is clockwise from true north in `[0, 360)`; elevation is in `[-90, 90]`.

No external Earth-orientation parameters, polar motion, terrain model, or atmospheric
refraction correction is applied. The Earth-fixed approximation must not be represented as
full high-precision ITRF processing.

## Event Search And Refinement

The search is bounded and deterministic:

- sample the complete request interval and always include its exact end;
- treat elevation equal to the threshold as geometrically in-window;
- bracket each detected below/above transition;
- refine rise and set with at most 50 bisection iterations to a 0.1-second time bracket;
- select the earliest coarse maximum on ties;
- refine the peak in its neighboring sample bracket with at most 40 ternary iterations to
  0.1 seconds;
- allow at most 256 windows and 50,000 total geometry evaluations.

Every propagation or geometry failure fails the complete calculation closed with a
bounded error. No partial window set is returned. Adjacent windows are ordered,
non-overlapping, and strictly positive in duration. A tangent-only threshold contact whose
duration is no greater than the event tolerance is omitted rather than emitted as a
zero-duration window.

Coarse sampling can still miss an event that rises above and falls below the threshold
entirely between adjacent samples. Refinement improves detected events; it cannot recover
an unbracketed event. This limitation is always present in the result.

## Determinism And Reference Fixture

Fixed normalized inputs produce identical serialized output and SHA-256 input/result
references. Ordering and tie handling are fixed. The bundled ISS reference test uses
`data/samples/iss_zarya.tle` and the independently generated values recorded in
`tests/fixtures/mission_windows/iss_equator_reference.json`. That reference used a
one-off scalar calculation with python-sgp4 2.26, independently written IAU-1982 GMST,
WGS84 observer ECEF, ENU look-angle equations, a one-second scan, and 0.001-second event
refinement; it did not import OrbitMind observation-geometry or mission-window code.

## Accuracy And Limitations

The result reports source epoch and prediction offsets so callers can assess element age.
No universal distance-error guarantee, accuracy percentage, or optical-visibility claim is
made. Accuracy depends on element quality and age, object dynamics, maneuvers, drag,
atmospheric uncertainty, frame/time approximations, and observer coordinates.

Every result states:

> Geometric window only; optical visibility is not assessed.

Brightness, weather, clouds, refraction, terrain obstruction, eclipse, sunlight, observer
twilight, RF link budget, sensor field of view, and regulatory/tasking eligibility are not
computed.

## Prohibited Claims

U4.1A must not be described as live tracking, 100% accurate, certified, taskable,
command-ready, collision-safe, maneuver guidance, guaranteed contact, or guaranteed
naked-eye visibility. It calculates a deterministic model result from identified pinned
inputs.

## Future Extensions

The immutable request/result and injected evaluator boundary can later support separately
reviewed work for ground-station scheduling, spacecraft-to-spacecraft line of sight,
eclipse events, and lunar or planetary mission geometry. Those extensions require their
own frame, ephemeris, uncertainty, and verification decisions; they must not be routed
through SGP4 by convenience.
