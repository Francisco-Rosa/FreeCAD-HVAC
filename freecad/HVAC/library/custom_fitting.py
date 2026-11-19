# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Custom fittings (ROADMAP 6.3): fitting a user-modelled fitting, described
by its own ports, onto a network node. Pure math with numpy, no FreeCAD.

A custom port is a frame in the fitting's own coordinates: an origin at the
centre of the opening, `z` pointing out of the fitting, `x` along the width
of a rectangular or oval opening. A duct port is the network's: every duct
of a node starts at the node point and runs along its outward `direction`.

`fit()` finds which custom port goes on which duct, the rigid placement that
puts every custom port on its duct's centre line pointing along it, and how
far out along each duct the port lands (its trim).

`fit_in_place()` is for a fitting left where it was modelled: the ducts were
drawn to end on its ports (each duct then has its own end point, there is no
single node), so nothing moves; it only works out which port each duct meets
and the trims.
"""

import itertools
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

# A placed port further than this off its duct is an error.
ANGLE_TOLERANCE_DEG = 1.0
OFFSET_TOLERANCE_MM = 1.0
# Up to this many ports every assignment is tried; above it, a greedy one.
_EXHAUSTIVE_LIMIT = 7


class CustomFitError(ValueError):
    pass


@dataclass
class CustomPort:
    """One port of a custom fitting, in the fitting's own coordinates (mm)."""

    name: str
    origin: tuple
    z: tuple
    x: Optional[tuple] = None
    profile: str = ""
    section: Dict[str, float] = field(default_factory=dict)


@dataclass
class DuctEnd:
    """
    One duct at the node: its edge key, outward direction and (optional)
    profile x axis. `position` is where the duct ends (only fit_in_place()
    needs it; fit() takes the shared node point instead).
    """

    edge_key: str
    direction: tuple
    x: Optional[tuple] = None
    profile: str = ""
    section: Dict[str, float] = field(default_factory=dict)
    position: Optional[tuple] = None


@dataclass
class FitResult:
    rotation: np.ndarray  # 3 x 3, custom frame -> world
    translation: np.ndarray  # 3, world position of the custom frame's origin
    mapping: Dict[str, int]  # edge_key -> index into the custom ports
    trims: Dict[str, float]  # edge_key -> distance from the node to the placed port, along the duct
    angle_errors: Dict[str, float]  # edge_key -> degrees between placed port z and the duct
    offset_errors: Dict[str, float]  # edge_key -> mm from the placed port origin to the duct's centre line
    warnings: List[str] = field(default_factory=list)


def _unit(v):
    v = np.asarray(v, dtype=float)
    n = np.linalg.norm(v)
    if n <= 1e-12:
        raise CustomFitError("zero-length direction")
    return v / n


def _angle_deg(a, b):
    return math.degrees(math.acos(max(-1.0, min(1.0, float(np.dot(_unit(a), _unit(b)))))))


def _rotation_between(a, b):
    """The smallest rotation taking unit vector a onto unit vector b (Rodrigues)."""
    a, b = _unit(a), _unit(b)
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    if np.linalg.norm(v) < 1e-12:
        if c > 0.0:
            return np.eye(3)
        # Opposite: half a turn about any axis square to a.
        axis = np.cross(a, [1.0, 0.0, 0.0])
        if np.linalg.norm(axis) < 1e-6:
            axis = np.cross(a, [0.0, 1.0, 0.0])
        axis = _unit(axis)
        return 2.0 * np.outer(axis, axis) - np.eye(3)
    vx = np.array([[0.0, -v[2], v[1]], [v[2], 0.0, -v[0]], [-v[1], v[0], 0.0]])
    return np.eye(3) + vx + vx @ vx * (1.0 / (1.0 + c))


def _kabsch(sources, targets):
    """Rotation R minimising sum |R s - t|^2 over unit vector pairs, or None when they fix no unique rotation."""
    h = np.zeros((3, 3))
    for s, t in zip(sources, targets):
        h += np.outer(s, t)
    u, sing, vt = np.linalg.svd(h)
    if sing[1] < 1e-6 * max(sing[0], 1e-12):
        return None  # all pairs parallel: the roll about them is free
    d = np.sign(np.linalg.det(vt.T @ u.T)) or 1.0
    return vt.T @ np.diag([1.0, 1.0, d]) @ u.T


def _rotation_for(ports, ducts, order):
    """Best rotation for one assignment (custom port order[i] on duct i): z onto direction, x onto x where known."""
    sources, targets = [], []
    for duct, index in zip(ducts, order):
        sources.append(_unit(ports[index].z))
        targets.append(_unit(duct.direction))
    rotation = _kabsch(sources, targets)
    if rotation is None:
        # Every port on one axis (a straight-through fitting): align that axis,
        # then fix the roll from the width axes, when both sides have one.
        rotation = _rotation_between(sources[0], targets[0])
        for duct, index in zip(ducts, order):
            if ports[index].x is not None and duct.x is not None:
                axis = targets[0]
                placed = rotation @ _unit(ports[index].x)
                placed -= axis * float(np.dot(placed, axis))
                wanted = _unit(duct.x) - axis * float(np.dot(_unit(duct.x), axis))
                if np.linalg.norm(placed) > 1e-9 and np.linalg.norm(wanted) > 1e-9:
                    rotation = _rotation_between(placed, wanted) @ rotation
                break
    return rotation


def _score(ports, ducts, order, rotation):
    return sum(
        1.0 - float(np.dot(rotation @ _unit(ports[index].z), _unit(duct.direction)))
        for duct, index in zip(ducts, order)
    )


def _assignments(count, fixed):
    """Every candidate order (custom port index per duct), honouring `fixed` {duct index: port index}."""
    free_ducts = [i for i in range(count) if i not in fixed]
    free_ports = [j for j in range(count) if j not in fixed.values()]
    if len(free_ducts) <= _EXHAUSTIVE_LIMIT:
        for perm in itertools.permutations(free_ports):
            order = [0] * count
            for i, j in fixed.items():
                order[i] = j
            for i, j in zip(free_ducts, perm):
                order[i] = j
            yield order
    else:
        order = [0] * count
        for i, j in fixed.items():
            order[i] = j
        for i, j in zip(free_ducts, free_ports):
            order[i] = j
        yield order


def match(ports, ducts, overrides=None):
    """
    (order, rotation): order[i] is the custom port placed on ducts[i]. Every
    assignment is tried (up to 7 free ports) and the one whose ports point
    best along their ducts wins; ties keep the lower port numbers first.
    `overrides` {edge_key: port index} pins ports by hand.
    """
    if len(ports) != len(ducts):
        raise CustomFitError(
            "The custom fitting has {} port(s) but the node has {} duct(s)".format(len(ports), len(ducts))
        )
    if not ports:
        raise CustomFitError("The custom fitting has no ports")
    fixed = {}
    for i, duct in enumerate(ducts):
        if overrides and duct.edge_key in overrides:
            j = int(overrides[duct.edge_key])
            if not 0 <= j < len(ports):
                raise CustomFitError(
                    "Port override for duct '{}' names port {} of {}".format(duct.edge_key, j + 1, len(ports))
                )
            if j in fixed.values():
                raise CustomFitError("Port {} is assigned to two ducts".format(j + 1))
            fixed[i] = j
    best = None
    for order in _assignments(len(ports), fixed):
        rotation = _rotation_for(ports, ducts, order)
        score = _score(ports, ducts, order, rotation)
        if best is None or score < best[0] - 1e-9:
            best = (score, order, rotation)
    return best[1], best[2]


def fit(ports, ducts, node, overrides=None):
    """
    Place the custom fitting on the node. `node` is the node point (mm); every
    duct's centre line is node + s * direction. Returns a FitResult; raises
    CustomFitError when a port cannot be put on its duct within
    ANGLE_TOLERANCE_DEG / OFFSET_TOLERANCE_MM, or lands behind the node.
    """
    node = np.asarray(node, dtype=float)
    order, rotation = match(ports, ducts, overrides)
    origins = [rotation @ np.asarray(ports[index].origin, dtype=float) for index in order]
    directions = [_unit(duct.direction) for duct in ducts]

    # Least squares for the translation: every placed port origin on its
    # duct's centre line. Any direction the ducts leave free (all ports on
    # one axis, or a single port) is fixed by putting the ports' centroid on
    # the node, without disturbing the constrained directions.
    a = np.zeros((3, 3))
    b = np.zeros(3)
    for origin, d in zip(origins, directions):
        perp = np.eye(3) - np.outer(d, d)
        a += perp
        b += perp @ (node - origin)
    values, vectors = np.linalg.eigh(a)
    constrained = values > 1e-9 * max(float(values.max()), 1.0)
    translation = np.zeros(3)
    for value, vector, keep in zip(values, vectors.T, constrained):
        if keep:
            translation += vector * float(np.dot(vector, b)) / value
    centroid_gap = node - np.mean(origins, axis=0) - translation
    for vector, keep in zip(vectors.T, constrained):
        if not keep:
            translation += vector * float(np.dot(vector, centroid_gap))

    trims, angle_errors, offset_errors, problems = {}, {}, {}, []
    mapping = {}
    for duct, index, origin, d in zip(ducts, order, origins, directions):
        placed = origin + translation
        rel = placed - node
        along = float(np.dot(rel, d))
        offset = float(np.linalg.norm(rel - along * d))
        angle = _angle_deg(rotation @ _unit(ports[index].z), d)
        mapping[duct.edge_key] = index
        trims[duct.edge_key] = along
        angle_errors[duct.edge_key] = angle
        offset_errors[duct.edge_key] = offset
        name = ports[index].name or "port {}".format(index + 1)
        if angle > ANGLE_TOLERANCE_DEG:
            problems.append("{} points {:.1f} deg away from duct '{}'".format(name, angle, duct.edge_key))
        if offset > OFFSET_TOLERANCE_MM:
            problems.append("{} sits {:.1f} mm off the centre line of duct '{}'".format(name, offset, duct.edge_key))
        if along < -OFFSET_TOLERANCE_MM:
            problems.append("{} lands {:.1f} mm behind the node on duct '{}'".format(name, -along, duct.edge_key))
    if problems:
        raise CustomFitError("The custom fitting does not fit this node: " + "; ".join(problems))

    warnings = _size_warnings(ports, ducts, mapping)
    return FitResult(rotation, translation, mapping, trims, angle_errors, offset_errors, warnings)


def fit_in_place(ports, ducts, overrides=None):
    """
    A custom fitting that stays where it was modelled: every duct was drawn
    to end on one of its ports, so the placement is the identity. `ports`
    and every duct's `position` must be in the same coordinates.

    Each duct takes the free port nearest its end point (`overrides`
    {edge_key: port index} pins one by hand); its trim is how far out along
    the duct that port sits from the duct's end. Ports no duct reaches are
    left open, with a warning. Raises CustomFitError when a duct has no
    port, or its port points away from it or sits off its centre line
    (ANGLE_TOLERANCE_DEG / OFFSET_TOLERANCE_MM), or lies behind its end
    (a gap between the fitting and the duct).
    """
    if not ports:
        raise CustomFitError("The custom fitting has no ports")
    if len(ducts) > len(ports):
        raise CustomFitError(
            "The custom fitting has {} port(s) but {} duct(s) end on it".format(len(ports), len(ducts))
        )
    for duct in ducts:
        if duct.position is None:
            raise CustomFitError("Duct '{}' has no end point".format(duct.edge_key))

    # Step 1: hand-pinned ports first.
    mapping = {}
    for duct in ducts:
        if overrides and duct.edge_key in overrides:
            j = int(overrides[duct.edge_key])
            if not 0 <= j < len(ports):
                raise CustomFitError(
                    "Port override for duct '{}' names port {} of {}".format(duct.edge_key, j + 1, len(ports))
                )
            if j in mapping.values():
                raise CustomFitError("Port {} is assigned to two ducts".format(j + 1))
            mapping[duct.edge_key] = j

    # Step 2: every other duct takes the nearest free port, closest pairs first.
    pairs = sorted(
        (float(np.linalg.norm(np.asarray(port.origin, float) - np.asarray(duct.position, float))), i, j)
        for i, duct in enumerate(ducts)
        if duct.edge_key not in mapping
        for j, port in enumerate(ports)
        if j not in mapping.values()
    )
    for _distance, i, j in pairs:
        if ducts[i].edge_key not in mapping and j not in mapping.values():
            mapping[ducts[i].edge_key] = j

    # Step 3: check each pair and measure its trim.
    trims, angle_errors, offset_errors, problems = {}, {}, {}, []
    for duct in ducts:
        index = mapping[duct.edge_key]
        port = ports[index]
        d = _unit(duct.direction)
        rel = np.asarray(port.origin, float) - np.asarray(duct.position, float)
        along = float(np.dot(rel, d))
        offset = float(np.linalg.norm(rel - along * d))
        angle = _angle_deg(port.z, d)
        trims[duct.edge_key] = along
        angle_errors[duct.edge_key] = angle
        offset_errors[duct.edge_key] = offset
        name = port.name or "port {}".format(index + 1)
        if angle > ANGLE_TOLERANCE_DEG:
            problems.append("{} points {:.1f} deg away from duct '{}'".format(name, angle, duct.edge_key))
        if offset > OFFSET_TOLERANCE_MM:
            problems.append("{} sits {:.1f} mm off the centre line of duct '{}'".format(name, offset, duct.edge_key))
        if along < -OFFSET_TOLERANCE_MM:
            problems.append("duct '{}' starts {:.1f} mm beyond {}, leaving a gap".format(duct.edge_key, -along, name))
    if problems:
        raise CustomFitError("The ducts do not end on the custom fitting's ports: " + "; ".join(problems))

    warnings = _size_warnings(ports, ducts, mapping)
    used = set(mapping.values())
    for j, port in enumerate(ports):
        if j not in used:
            warnings.append("{} has no duct: it is left open".format(port.name or "port {}".format(j + 1)))
    return FitResult(np.eye(3), np.zeros(3), mapping, trims, angle_errors, offset_errors, warnings)


def _size_warnings(ports, ducts, mapping):
    """A warning for every duct whose profile or size differs from the custom port it meets."""
    warnings = []
    for duct in ducts:
        index = mapping[duct.edge_key]
        port = ports[index]
        if not port.profile or not duct.profile:
            continue
        if port.profile != duct.profile or not _same_section(port.section, duct.section):
            warnings.append(
                "{} is {} but duct '{}' is {}: a reducer is needed".format(
                    port.name or "port {}".format(index + 1),
                    describe_section(port.profile, port.section),
                    duct.edge_key,
                    describe_section(duct.profile, duct.section),
                )
            )
    return warnings


def _same_section(a, b, tolerance=0.5):
    keys = [k for k in ("Diameter", "Width", "Height") if float(a.get(k, 0.0) or 0.0) or float(b.get(k, 0.0) or 0.0)]
    return all(abs(float(a.get(k, 0.0) or 0.0) - float(b.get(k, 0.0) or 0.0)) <= tolerance for k in keys)


def describe_section(profile, section):
    if profile == "Circular":
        return "round {:.0f}".format(float(section.get("Diameter", 0.0) or 0.0))
    return "{} {:.0f} x {:.0f}".format(
        (profile or "?").lower(), float(section.get("Width", 0.0) or 0.0), float(section.get("Height", 0.0) or 0.0)
    )
