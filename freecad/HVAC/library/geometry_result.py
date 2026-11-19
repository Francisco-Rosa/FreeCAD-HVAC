# SPDX-License-Identifier: LGPL-2.1-or-later
"""
The typed result every geometry backend dispatch (PartScript, static
BREP/STEP, legacy generator function) ultimately returns: a GeometryResult
holding one LayerGeometry per construction layer a type declares (see
library/construction.py), plus the non-shape outputs (connection lengths,
trim planes, computed properties) generators have always been able to
report.

Generator/PartScript/static-descriptor authors never construct these
dataclasses themselves -- per CLAUDE.md's "external code uses only
HVACLibraryAPI" rule, they return plain dicts of the form
`{"layers": {id: {"shape": ...}}, ...}` (see HVACLibraryAPI.single_layer for
a one-solid fitting).
normalize() is the one place a raw backend return value is turned into a
real GeometryResult -- called once, from HVACLibraryRegistry.build_geometry()
(which also stamps each layer's `roles` from the type-def's own declared
construction, since normalize() itself has no access to the type-def), so
every caller downstream (DuctSegment/DuctComponent/DuctJunction) always
deals with a real GeometryResult, never a bare dict.
"""

from dataclasses import dataclass, field

from .construction import FeatureGeometry, LayerGeometry  # noqa: F401 -- re-exported for GeometryResult.features consumers

# Top-level raw-dict keys normalize() understands by name; anything else is
# preserved verbatim on GeometryResult.extra rather than silently dropped.
_KNOWN_RAW_KEYS = {
    "layers",
    "connection_lengths",
    "computed_properties",
    "property_choices",
    "start_trim_plane_json",
    "end_trim_plane_json",
}

# Legacy backends (static BREP/STEP, FCStd-template generators) only ever
# return one shape via {"shape": ...} -- normalize() wraps that as a single
# layer under this id. No roles are implied; the type-def's own
# "construction" block is what stamps roles on afterwards, if declared.
# The layer id a one-solid result uses when its type declares no
# construction layers (HVACLibraryAPI.single_layer).
LEGACY_SHAPE_LAYER_ID = "shape"


@dataclass
class GeometryResult:
    """
    The full result of building one type's geometry for one sync/execute
    call. `layers` holds arbitrary library-defined layer ids -> LayerGeometry
    (see library/construction.py) -- no layer id or count is required or
    assumed here; a type may return one layer or many.

    `features` holds arbitrary library-defined feature ids -> FeatureGeometry
    -- unlike `layers`, this is never populated from a raw backend dict
    (normalize() leaves it empty); HVACLibraryRegistry.build_geometry()
    fills it in as a second pass, after the backend's own layers are built
    and normalized, by resolving and invoking each of the type-def's own
    declared construction.features generators (see Library.py). A disabled
    feature (its own enabled_parameter resolves False) has no entry here at
    all, not an entry with a null shape.
    """

    layers: dict = field(default_factory=dict)
    features: dict = field(default_factory=dict)
    connection_lengths: list = field(default_factory=list)
    computed_properties: dict = field(default_factory=dict)
    # Drop-down property name -> the choices that make sense for this
    # geometry (a subset of the type-def's own enum); a property not named
    # here offers every choice. See core/_geometry_apply.apply_property_choices.
    property_choices: dict = field(default_factory=dict)
    start_trim_plane_json: "str | None" = None
    end_trim_plane_json: "str | None" = None
    # Any other top-level key a backend returned that normalize() doesn't
    # know about by name -- preserved rather than dropped, for forward
    # compatibility with descriptor/generator outputs this module doesn't
    # yet interpret.
    extra: dict = field(default_factory=dict)


def _coerce_layer(value):
    """One layers[id] entry -> a LayerGeometry, accepting either a real
    LayerGeometry (new-style backend) or a plain {"shape": ...} dict (what
    generator/PartScript authors actually write, per the "only
    HVACLibraryAPI" rule -- they never import this module)."""
    if isinstance(value, LayerGeometry):
        return value
    if isinstance(value, dict):
        return LayerGeometry(shape=value.get("shape"))
    # A bare Part.Shape (or None) is also accepted directly as shorthand.
    return LayerGeometry(shape=value)


def normalize(raw) -> GeometryResult:
    """
    Turn whatever a geometry backend returned into a real GeometryResult.

    Accepts:
      - a GeometryResult already (returned as-is);
      - a dict with a "layers" key (the only dict form).
    """
    if isinstance(raw, GeometryResult):
        return raw

    if isinstance(raw, dict):
        if "layers" not in raw:
            raise TypeError(
                'A geometry backend must return {"layers": {layer_id: {"shape": ...}}}; the '
                '{"shape": ...} form was removed (HVACLibraryAPI.single_layer builds a one-layer result)'
            )
        layers = {str(layer_id): _coerce_layer(value) for layer_id, value in dict(raw.get("layers") or {}).items()}

        return GeometryResult(
            layers=layers,
            connection_lengths=list(raw.get("connection_lengths", []) or []),
            computed_properties=dict(raw.get("computed_properties", {}) or {}),
            property_choices={
                str(name): [str(choice) for choice in choices or []]
                for name, choices in dict(raw.get("property_choices", {}) or {}).items()
            },
            start_trim_plane_json=raw.get("start_trim_plane_json"),
            end_trim_plane_json=raw.get("end_trim_plane_json"),
            extra={k: v for k, v in raw.items() if k not in _KNOWN_RAW_KEYS},
        )

    raise TypeError("Geometry backend must return a GeometryResult or dict, got {!r}".format(type(raw)))
