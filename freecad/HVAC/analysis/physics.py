# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

################################################################################
#                                                                              #
#   Copyright (c) 2026 Francisco Rosa                                          #
#                                                                              #
#   This addon is free software; you can redistribute it and/or modify it      #
#   under the terms of the GNU Lesser General Public License as published      #
#   by the Free Software Foundation; either version 2.1 of the License, or     #
#   (at your option) any later version.                                        #
#                                                                              #
#   This addon is distributed in the hope that it will be useful,              #
#   but WITHOUT ANY WARRANTY; without even the implied warranty of             #
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.                       #
#                                                                              #
#   See the GNU Lesser General Public License for more details.                #
#                                                                              #
#   You should have received a copy of the GNU Lesser General Public           #
#   License along with this addon. If not, see https://www.gnu.org/licenses    #
#                                                                              #
################################################################################

"""
Airflow and duct-sizing formulas: friction loss, velocity, and duct sizing
by target velocity, friction rate, or static regain. Plain math, no FreeCAD
objects -- this module doesn't know what a "segment" or "network" is.

Everything here uses plain SI units (metres, m3/s, kg/m3, Pa), so it can be
unit-tested on its own. The addon's usual units (mm, L/s) are converted at
the call site, in the other analysis/ modules (pressure.py, sizing.py) and
the core/ adapters that build a SectionModel from FreeCAD properties.
"""

import math

from .model import SectionModel

# ----------------------------------------------------------------------------
# Unit conversion
# ----------------------------------------------------------------------------


def mm_to_m(value_mm):
    """Convert millimetres to metres."""
    return float(value_mm) / 1000.0


def lps_to_m3s(value_lps):
    """Convert litres/second to cubic metres/second."""
    return float(value_lps) / 1000.0


def m3s_to_lps(value_m3s):
    """Convert cubic metres/second to litres/second."""
    return float(value_m3s) * 1000.0


# ----------------------------------------------------------------------------
# Cross-section area
# ----------------------------------------------------------------------------


def circular_area(diameter_m):
    """Cross-section area of a circular duct."""
    d = float(diameter_m)
    if d <= 0.0:
        raise ValueError("diameter_m must be positive")
    return math.pi * (d**2) / 4.0


def rectangular_area(width_m, height_m):
    """Cross-section area of a rectangular duct."""
    w = float(width_m)
    h = float(height_m)
    if w <= 0.0 or h <= 0.0:
        raise ValueError("width_m and height_m must be positive")
    return w * h


def _oval_major_minor(width_m, height_m):
    """Sort an oval's two extents into (major, minor) -- a tall oval is just a wide one turned 90 degrees."""
    w = float(width_m)
    h = float(height_m)
    if w <= 0.0 or h <= 0.0:
        raise ValueError("width_m and height_m must be positive")
    return (w, h) if w >= h else (h, w)


def oval_area(width_m, height_m):
    """
    Cross-section area of a flat-oval (stadium/obround) duct.

    width_m / height_m = overall extents. Either one may be the longer
    side: the longer one is the major axis (along the straight sides), the
    shorter one is the minor axis (the diameter of the rounded end caps).
    This matches the oval section HVACLibraryAPI.make_profile draws.
    """
    major, minor = _oval_major_minor(width_m, height_m)
    r = minor / 2.0
    straight = major - minor
    # An oval is a rectangle (the straight middle part) plus a full circle
    # (the two rounded end caps, which together make one circle).
    return straight * minor + math.pi * (r**2)


# ----------------------------------------------------------------------------
# Hydraulic diameter (Dh = 4*Area / WettedPerimeter)
# ----------------------------------------------------------------------------


def hydraulic_diameter_circular(diameter_m):
    """Hydraulic diameter of a circular duct (== its diameter)."""
    d = float(diameter_m)
    if d <= 0.0:
        raise ValueError("diameter_m must be positive")
    return d


def hydraulic_diameter_rectangular(width_m, height_m):
    """Hydraulic diameter of a rectangular duct: 4A/P = 2wh/(w+h)."""
    w = float(width_m)
    h = float(height_m)
    if w <= 0.0 or h <= 0.0:
        raise ValueError("width_m and height_m must be positive")
    return (2.0 * w * h) / (w + h)


def hydraulic_diameter_oval(width_m, height_m):
    """Hydraulic diameter of a flat-oval (stadium/obround) duct: 4A/P."""
    major, minor = _oval_major_minor(width_m, height_m)
    straight = major - minor
    area = oval_area(major, minor)
    perimeter = 2.0 * straight + math.pi * minor
    return (4.0 * area) / perimeter


# ----------------------------------------------------------------------------
# Flow / velocity / Reynolds number
# ----------------------------------------------------------------------------


def velocity_from_flow(flow_m3_s, area_m2):
    """Mean duct velocity from volumetric flow rate and cross-section area."""
    a = float(area_m2)
    if a <= 0.0:
        raise ValueError("area_m2 must be positive")
    return float(flow_m3_s) / a


def reynolds_number(velocity_m_s, hydraulic_diameter_m, kinematic_viscosity_m2_s):
    """Reynolds number for duct flow."""
    nu = float(kinematic_viscosity_m2_s)
    if nu <= 0.0:
        raise ValueError("kinematic_viscosity_m2_s must be positive")
    return abs(float(velocity_m_s)) * float(hydraulic_diameter_m) / nu


# ----------------------------------------------------------------------------
# Friction factor and pressure loss
# ----------------------------------------------------------------------------


def friction_factor_altshul_tsal(reynolds, relative_roughness):
    """
    Explicit Darcy (Moody) friction factor approximation (Altshul-Tsal),
    avoiding an iterative Colebrook-White solve.

    relative_roughness = absolute_roughness_m / hydraulic_diameter_m
    """
    re = float(reynolds)
    eps_rel = float(relative_roughness)
    if re <= 0.0:
        raise ValueError("reynolds must be positive")
    if eps_rel < 0.0:
        raise ValueError("relative_roughness must be non-negative")

    f = 0.11 * (eps_rel + 68.0 / re) ** 0.25
    if f < 0.018:
        f = 0.85 * f + 0.0028
    return f


def velocity_pressure(air_density_kg_m3, velocity_m_s):
    """Dynamic (velocity) pressure: rho * V^2 / 2."""
    return float(air_density_kg_m3) * (float(velocity_m_s) ** 2) / 2.0


def darcy_weisbach_pressure_loss(friction_factor, length_m, hydraulic_diameter_m, air_density_kg_m3, velocity_m_s):
    """Straight-duct friction pressure loss via the Darcy-Weisbach equation."""
    dh = float(hydraulic_diameter_m)
    if dh <= 0.0:
        raise ValueError("hydraulic_diameter_m must be positive")
    length = float(length_m)
    if length < 0.0:
        raise ValueError("length_m must be non-negative")
    return float(friction_factor) * (length / dh) * velocity_pressure(air_density_kg_m3, velocity_m_s)


# ----------------------------------------------------------------------------
# Duct sizing: constant velocity (direct/closed-form)
#
# Solve duct dimensions from a required flow rate and a target velocity.
# Rectangular/oval ducts have two dimensions but sizing only fixes one
# number (area), so a "mode" picks how the second dimension is determined:
#   "aspect_ratio": width/height held at a fixed ratio, both solved from area
#   "fixed_height": height held fixed, width solved from area
#   "fixed_width":  width held fixed, height solved from area
# ----------------------------------------------------------------------------

_OVAL_SHAPE_FACTOR = 1.0 - math.pi / 4.0  # area(w,h) = h^2*(w/h - 1 + pi/4) for an oval


def circular_diameter_for_velocity(flow_m3_s, velocity_m_s):
    """Circular duct diameter that gives exactly the target velocity for the given flow."""
    if velocity_m_s <= 0.0:
        raise ValueError("velocity_m_s must be positive")
    area = float(flow_m3_s) / float(velocity_m_s)
    return 2.0 * math.sqrt(area / math.pi)


def rect_dims_for_velocity(flow_m3_s, velocity_m_s, mode, aspect_ratio=None, fixed_dim_m=None):
    """Rectangular duct (width_m, height_m) that gives exactly the target velocity."""
    if velocity_m_s <= 0.0:
        raise ValueError("velocity_m_s must be positive")
    area = float(flow_m3_s) / float(velocity_m_s)

    if mode == "aspect_ratio":
        if not aspect_ratio or aspect_ratio <= 0.0:
            raise ValueError("aspect_ratio must be positive")
        height = math.sqrt(area / aspect_ratio)
        return aspect_ratio * height, height
    if mode == "fixed_height":
        if not fixed_dim_m or fixed_dim_m <= 0.0:
            raise ValueError("fixed_dim_m must be positive")
        return area / fixed_dim_m, fixed_dim_m
    if mode == "fixed_width":
        if not fixed_dim_m or fixed_dim_m <= 0.0:
            raise ValueError("fixed_dim_m must be positive")
        return fixed_dim_m, area / fixed_dim_m
    raise ValueError("Unknown mode: {!r}".format(mode))


def _check_oval_aspect_ratio(aspect_ratio):
    """An oval's aspect ratio (width / height) may be above or below 1, but must be positive."""
    if not aspect_ratio or aspect_ratio <= 0.0:
        raise ValueError("aspect_ratio must be positive")


def _oval_free_dim_for_area(fixed_dim_m, area_m2):
    """
    The other extent of an oval, given one fixed extent and the target area.

    Works whichever of the two ends up longer:
    - target area >= a circle of the fixed diameter: the free extent is the
      major axis, and the area formula rearranges directly to it.
    - target area smaller than that circle: the free extent is the minor
      axis, and the area formula is quadratic in it (take the smaller root).
    """
    fixed = float(fixed_dim_m)
    if area_m2 >= math.pi * fixed**2 / 4.0:
        return fixed + area_m2 / fixed - math.pi * fixed / 4.0
    discriminant = fixed**2 - 4.0 * _OVAL_SHAPE_FACTOR * area_m2
    return (fixed - math.sqrt(max(discriminant, 0.0))) / (2.0 * _OVAL_SHAPE_FACTOR)


def oval_dims_for_velocity(flow_m3_s, velocity_m_s, mode, aspect_ratio=None, fixed_dim_m=None):
    """
    Flat-oval duct (width_m, height_m) that gives exactly the target
    velocity.

    An oval's area isn't a plain width*height product like a rectangle's,
    so each mode below rearranges the oval area formula differently to
    solve for its own free dimension. All three have an exact formula --
    no bisection needed.
    """
    if velocity_m_s <= 0.0:
        raise ValueError("velocity_m_s must be positive")
    area = float(flow_m3_s) / float(velocity_m_s)

    if mode == "aspect_ratio":
        _check_oval_aspect_ratio(aspect_ratio)
        # aspect_ratio = width / height. Below 1 the oval is taller than it
        # is wide, so solve the same shape turned 90 degrees and swap back.
        major_on_minor = aspect_ratio if aspect_ratio >= 1.0 else 1.0 / aspect_ratio
        # major = major_on_minor * minor, so area becomes a function of minor alone.
        minor = math.sqrt(area / (major_on_minor - 1.0 + math.pi / 4.0))
        major = major_on_minor * minor
        return (major, minor) if aspect_ratio >= 1.0 else (minor, major)
    if mode == "fixed_height":
        if not fixed_dim_m or fixed_dim_m <= 0.0:
            raise ValueError("fixed_dim_m must be positive")
        return _oval_free_dim_for_area(fixed_dim_m, area), fixed_dim_m
    if mode == "fixed_width":
        if not fixed_dim_m or fixed_dim_m <= 0.0:
            raise ValueError("fixed_dim_m must be positive")
        return fixed_dim_m, _oval_free_dim_for_area(fixed_dim_m, area)
    raise ValueError("Unknown mode: {!r}".format(mode))


# ----------------------------------------------------------------------------
# Duct sizing: constant friction rate (bisection)
#
# Friction rate depends on duct size in a tangled way (size changes area,
# hydraulic diameter, Reynolds number, and roughness ratio all at once), so
# there's no simple formula to invert like there is for constant velocity.
# Instead we bisect: for a fixed flow rate, a bigger duct always has a lower
# friction rate, so we can narrow in on the size that hits the target rate.
# ----------------------------------------------------------------------------


def _friction_rate_pa_per_m(
    area_m2,
    hydraulic_diameter_m,
    flow_m3_s,
    roughness_m,
    kinematic_viscosity_m2_s,
    air_density_kg_m3,
    friction_model=None,
):
    """
    Friction rate (Pa/m) at a trial size. `friction_model` is an
    analysis.friction model; None means Darcy-Weisbach with Altshul-Tsal.
    """
    if friction_model is not None:
        return friction_model.rate_pa_per_m(
            flow_m3_s, area_m2, hydraulic_diameter_m, roughness_m, air_density_kg_m3, kinematic_viscosity_m2_s
        )
    velocity_m_s = velocity_from_flow(flow_m3_s, area_m2)
    reynolds = reynolds_number(velocity_m_s, hydraulic_diameter_m, kinematic_viscosity_m2_s)
    friction_factor = friction_factor_altshul_tsal(reynolds, roughness_m / hydraulic_diameter_m)
    return darcy_weisbach_pressure_loss(friction_factor, 1.0, hydraulic_diameter_m, air_density_kg_m3, velocity_m_s)


def _solve_scale_for_friction_rate(
    area_and_dh_fn,
    flow_m3_s,
    target_rate_pa_per_m,
    roughness_m,
    kinematic_viscosity_m2_s,
    air_density_kg_m3,
    lo=0.01,
    hi=5.0,
    iterations=60,
    friction_model=None,
):
    """
    Find the duct size that hits the target friction rate (bisection).

    area_and_dh_fn(scale) -> (area_m2, hydraulic_diameter_m) for a trial
    size. If the target rate can't be reached inside [lo, hi] (e.g. an
    unrealistic target), clamps to whichever end is closest instead of
    raising -- callers can re-check the actual rate at the returned size if
    they need to know whether it was clamped.
    """

    def rate_at(scale):
        area_m2, dh_m = area_and_dh_fn(scale)
        return _friction_rate_pa_per_m(
            area_m2, dh_m, flow_m3_s, roughness_m, kinematic_viscosity_m2_s, air_density_kg_m3, friction_model
        )

    if rate_at(lo) <= target_rate_pa_per_m:
        return lo  # even the smallest allowed duct is already at/under the target rate
    if rate_at(hi) > target_rate_pa_per_m:
        return hi  # even the largest allowed duct still exceeds the target rate

    # Narrow the bracket until it converges on the crossing point.
    for _ in range(iterations):
        mid = (lo + hi) / 2.0
        if rate_at(mid) > target_rate_pa_per_m:
            lo = mid  # still too much friction -> try a bigger duct
        else:
            hi = mid  # under target -> a smaller duct would still work
    return (lo + hi) / 2.0


def circular_diameter_for_friction_rate(
    flow_m3_s, target_rate_pa_per_m, roughness_m, kinematic_viscosity_m2_s, air_density_kg_m3, friction_model=None
):
    """Circular duct diameter that gives (approximately) the target friction rate (Pa/m)."""

    def area_and_dh(diameter_m):
        return circular_area(diameter_m), hydraulic_diameter_circular(diameter_m)

    return _solve_scale_for_friction_rate(
        area_and_dh,
        flow_m3_s,
        target_rate_pa_per_m,
        roughness_m,
        kinematic_viscosity_m2_s,
        air_density_kg_m3,
        friction_model=friction_model,
    )


def rect_dims_for_friction_rate(
    flow_m3_s,
    target_rate_pa_per_m,
    roughness_m,
    kinematic_viscosity_m2_s,
    air_density_kg_m3,
    mode,
    aspect_ratio=None,
    fixed_dim_m=None,
    friction_model=None,
):
    """Rectangular duct (width_m, height_m) that gives (approximately) the target friction rate."""
    if mode == "aspect_ratio":
        if not aspect_ratio or aspect_ratio <= 0.0:
            raise ValueError("aspect_ratio must be positive")

        def area_and_dh(height_m):
            width_m = aspect_ratio * height_m
            return rectangular_area(width_m, height_m), hydraulic_diameter_rectangular(width_m, height_m)

        height = _solve_scale_for_friction_rate(
            area_and_dh,
            flow_m3_s,
            target_rate_pa_per_m,
            roughness_m,
            kinematic_viscosity_m2_s,
            air_density_kg_m3,
            friction_model=friction_model,
        )
        return aspect_ratio * height, height

    if mode == "fixed_height":
        if not fixed_dim_m or fixed_dim_m <= 0.0:
            raise ValueError("fixed_dim_m must be positive")
        height = fixed_dim_m

        def area_and_dh(width_m):
            return rectangular_area(width_m, height), hydraulic_diameter_rectangular(width_m, height)

        width = _solve_scale_for_friction_rate(
            area_and_dh,
            flow_m3_s,
            target_rate_pa_per_m,
            roughness_m,
            kinematic_viscosity_m2_s,
            air_density_kg_m3,
            friction_model=friction_model,
        )
        return width, height

    if mode == "fixed_width":
        if not fixed_dim_m or fixed_dim_m <= 0.0:
            raise ValueError("fixed_dim_m must be positive")
        width = fixed_dim_m

        def area_and_dh(height_m):
            return rectangular_area(width, height_m), hydraulic_diameter_rectangular(width, height_m)

        height = _solve_scale_for_friction_rate(
            area_and_dh,
            flow_m3_s,
            target_rate_pa_per_m,
            roughness_m,
            kinematic_viscosity_m2_s,
            air_density_kg_m3,
            friction_model=friction_model,
        )
        return width, height

    raise ValueError("Unknown mode: {!r}".format(mode))


def oval_dims_for_friction_rate(
    flow_m3_s,
    target_rate_pa_per_m,
    roughness_m,
    kinematic_viscosity_m2_s,
    air_density_kg_m3,
    mode,
    aspect_ratio=None,
    fixed_dim_m=None,
    friction_model=None,
):
    """Flat-oval duct (width_m, height_m) that gives (approximately) the target friction rate."""
    if mode == "aspect_ratio":
        _check_oval_aspect_ratio(aspect_ratio)

        def area_and_dh(height_m):
            width_m = aspect_ratio * height_m
            return oval_area(width_m, height_m), hydraulic_diameter_oval(width_m, height_m)

        height = _solve_scale_for_friction_rate(
            area_and_dh,
            flow_m3_s,
            target_rate_pa_per_m,
            roughness_m,
            kinematic_viscosity_m2_s,
            air_density_kg_m3,
            friction_model=friction_model,
        )
        return aspect_ratio * height, height

    if mode == "fixed_height":
        if not fixed_dim_m or fixed_dim_m <= 0.0:
            raise ValueError("fixed_dim_m must be positive")
        height = fixed_dim_m

        def area_and_dh(width_m):
            return oval_area(width_m, height), hydraulic_diameter_oval(width_m, height)

        width = _solve_scale_for_friction_rate(
            area_and_dh,
            flow_m3_s,
            target_rate_pa_per_m,
            roughness_m,
            kinematic_viscosity_m2_s,
            air_density_kg_m3,
            friction_model=friction_model,
        )
        return width, height

    if mode == "fixed_width":
        if not fixed_dim_m or fixed_dim_m <= 0.0:
            raise ValueError("fixed_dim_m must be positive")
        width = fixed_dim_m

        def area_and_dh(height_m):
            return oval_area(width, height_m), hydraulic_diameter_oval(width, height_m)

        height = _solve_scale_for_friction_rate(
            area_and_dh,
            flow_m3_s,
            target_rate_pa_per_m,
            roughness_m,
            kinematic_viscosity_m2_s,
            air_density_kg_m3,
            friction_model=friction_model,
        )
        return width, height

    raise ValueError("Unknown mode: {!r}".format(mode))


# ----------------------------------------------------------------------------
# Duct sizing: static regain (bisection)
#
# Idea: when air slows down going into a bigger duct, some of its velocity
# pressure turns back into static pressure -- this is "regain". Static
# regain sizing picks each section's size so that regain exactly cancels out
# that section's own friction loss. Done at every branch, this keeps static
# pressure roughly constant across the network instead of it dropping more
# and more the further downstream you go.
#
# This needs the UPSTREAM section's velocity already known, so sections must
# be sized in order, from the fan/source outward (see core.DuctSizer).
#
# Problem case: a small or short branch can have more regain available than
# it needs, even at a very slow (oversized) duct. min_velocity_m_s stops
# sizing from chasing an impractically large duct to use up all that regain
# -- it's a floor on velocity (a ceiling on duct size). If friction still
# beats regain even at that ceiling, we clamp there and report the section
# as "not balanced" (it may need a balancing damper instead).
#
# The balance below can also take a fitting_loss_pa: the fitting/dynamic
# loss of the junction this section takes off from (e.g. a tee's branch
# loss), on top of its own straight-duct friction -- so regain is weighed
# against everything the section actually has to overcome, not just pipe
# friction. That loss depends on the very duct sizes being solved for, so
# core.DuctSizer estimates it from a previous pass's proposed sizes and
# re-solves until sizes settle -- see DuctSizer._solveComponentStaticRegain
# for that iteration. Defaults to 0 (plain regain-vs-friction) for callers
# that don't have a fitting-loss estimate.
# ----------------------------------------------------------------------------


def _regain_minus_friction(
    area_and_dh_fn,
    scale,
    flow_m3_s,
    upstream_velocity_pressure_pa,
    regain_factor,
    length_m,
    roughness_m,
    kinematic_viscosity_m2_s,
    air_density_kg_m3,
    fitting_loss_pa=0.0,
    friction_model=None,
):
    """
    Regain minus (friction + fitting_loss_pa) for a trial duct size. Zero
    means balanced; positive means this size has more regain than it needs
    (could be smaller); negative means friction+fitting still exceeds
    regain (needs bigger).
    """
    area_m2, dh_m = area_and_dh_fn(scale)
    velocity_m_s = velocity_from_flow(flow_m3_s, area_m2)
    vp = velocity_pressure(air_density_kg_m3, velocity_m_s)
    friction = length_m * _friction_rate_pa_per_m(
        area_m2, dh_m, flow_m3_s, roughness_m, kinematic_viscosity_m2_s, air_density_kg_m3, friction_model
    )
    regain = regain_factor * (upstream_velocity_pressure_pa - vp)
    return regain - friction - fitting_loss_pa


def _solve_scale_for_static_regain(
    area_and_dh_fn,
    flow_m3_s,
    upstream_velocity_pressure_pa,
    regain_factor,
    length_m,
    roughness_m,
    kinematic_viscosity_m2_s,
    air_density_kg_m3,
    hi,
    lo=None,
    iterations=60,
    fitting_loss_pa=0.0,
    friction_model=None,
):
    """
    Find the duct size where regain exactly cancels friction (bisection).
    Bigger duct -> less friction and more regain, so this difference only
    ever grows as size grows, making the bracket well-posed.

    hi is the largest size allowed -- the size at the minimum allowed
    velocity (see the module note above). lo defaults to a tiny size (an
    effectively unbounded velocity); callers only pass their own lo for a
    real geometric lower bound.

    Returns (scale, balanced):
      - balanced=True: found a size where regain == friction.
      - balanced=False: no such size exists inside [lo, hi], so the result
        is clamped to hi (friction still beats regain even at the biggest
        allowed duct -- the classic static-regain failure case) or, rarely,
        to lo (regain already beats friction even at the tiny lo bound).
        Treat this as "may need a balancing damper here", not an error --
        a size is still returned either way.
    """
    if lo is None:
        lo = hi * 1e-4
    if lo >= hi:
        return hi, False

    def balance(scale):
        return _regain_minus_friction(
            area_and_dh_fn,
            scale,
            flow_m3_s,
            upstream_velocity_pressure_pa,
            regain_factor,
            length_m,
            roughness_m,
            kinematic_viscosity_m2_s,
            air_density_kg_m3,
            fitting_loss_pa,
            friction_model,
        )

    if balance(hi) < 0.0:
        return hi, False  # friction still wins even at the biggest allowed duct
    if balance(lo) >= 0.0:
        return lo, False  # regain already wins even at the tiny lower bound

    # Narrow the bracket until it converges on the crossing point.
    for _ in range(iterations):
        mid = (lo + hi) / 2.0
        if balance(mid) < 0.0:
            lo = mid  # still under-balanced -> try a bigger duct
        else:
            hi = mid  # already over-balanced -> a smaller duct would still work
    return (lo + hi) / 2.0, True


def circular_diameter_for_static_regain(
    flow_m3_s,
    upstream_velocity_pressure_pa,
    regain_factor,
    length_m,
    roughness_m,
    kinematic_viscosity_m2_s,
    air_density_kg_m3,
    min_velocity_m_s,
    fitting_loss_pa=0.0,
    friction_model=None,
):
    """Returns (diameter_m, balanced) -- see _solve_scale_for_static_regain for what balanced means."""

    def area_and_dh(diameter_m):
        return circular_area(diameter_m), hydraulic_diameter_circular(diameter_m)

    floor_diameter_m = circular_diameter_for_velocity(flow_m3_s, min_velocity_m_s)
    return _solve_scale_for_static_regain(
        area_and_dh,
        flow_m3_s,
        upstream_velocity_pressure_pa,
        regain_factor,
        length_m,
        roughness_m,
        kinematic_viscosity_m2_s,
        air_density_kg_m3,
        hi=floor_diameter_m,
        fitting_loss_pa=fitting_loss_pa,
        friction_model=friction_model,
    )


def rect_dims_for_static_regain(
    flow_m3_s,
    upstream_velocity_pressure_pa,
    regain_factor,
    length_m,
    roughness_m,
    kinematic_viscosity_m2_s,
    air_density_kg_m3,
    min_velocity_m_s,
    mode,
    aspect_ratio=None,
    fixed_dim_m=None,
    fitting_loss_pa=0.0,
    friction_model=None,
):
    """Returns (width_m, height_m, balanced) -- see _solve_scale_for_static_regain for what balanced means."""
    floor_w, floor_h = rect_dims_for_velocity(
        flow_m3_s, min_velocity_m_s, mode, aspect_ratio=aspect_ratio, fixed_dim_m=fixed_dim_m
    )

    if mode == "aspect_ratio":
        if not aspect_ratio or aspect_ratio <= 0.0:
            raise ValueError("aspect_ratio must be positive")

        def area_and_dh(height_m):
            width_m = aspect_ratio * height_m
            return rectangular_area(width_m, height_m), hydraulic_diameter_rectangular(width_m, height_m)

        height, balanced = _solve_scale_for_static_regain(
            area_and_dh,
            flow_m3_s,
            upstream_velocity_pressure_pa,
            regain_factor,
            length_m,
            roughness_m,
            kinematic_viscosity_m2_s,
            air_density_kg_m3,
            hi=floor_h,
            fitting_loss_pa=fitting_loss_pa,
            friction_model=friction_model,
        )
        return aspect_ratio * height, height, balanced

    if mode == "fixed_height":
        if not fixed_dim_m or fixed_dim_m <= 0.0:
            raise ValueError("fixed_dim_m must be positive")
        height = fixed_dim_m

        def area_and_dh(width_m):
            return rectangular_area(width_m, height), hydraulic_diameter_rectangular(width_m, height)

        width, balanced = _solve_scale_for_static_regain(
            area_and_dh,
            flow_m3_s,
            upstream_velocity_pressure_pa,
            regain_factor,
            length_m,
            roughness_m,
            kinematic_viscosity_m2_s,
            air_density_kg_m3,
            hi=floor_w,
            fitting_loss_pa=fitting_loss_pa,
            friction_model=friction_model,
        )
        return width, height, balanced

    if mode == "fixed_width":
        if not fixed_dim_m or fixed_dim_m <= 0.0:
            raise ValueError("fixed_dim_m must be positive")
        width = fixed_dim_m

        def area_and_dh(height_m):
            return rectangular_area(width, height_m), hydraulic_diameter_rectangular(width, height_m)

        height, balanced = _solve_scale_for_static_regain(
            area_and_dh,
            flow_m3_s,
            upstream_velocity_pressure_pa,
            regain_factor,
            length_m,
            roughness_m,
            kinematic_viscosity_m2_s,
            air_density_kg_m3,
            hi=floor_h,
            fitting_loss_pa=fitting_loss_pa,
            friction_model=friction_model,
        )
        return width, height, balanced

    raise ValueError("Unknown mode: {!r}".format(mode))


def oval_dims_for_static_regain(
    flow_m3_s,
    upstream_velocity_pressure_pa,
    regain_factor,
    length_m,
    roughness_m,
    kinematic_viscosity_m2_s,
    air_density_kg_m3,
    min_velocity_m_s,
    mode,
    aspect_ratio=None,
    fixed_dim_m=None,
    fitting_loss_pa=0.0,
    friction_model=None,
):
    """Returns (width_m, height_m, balanced) -- see _solve_scale_for_static_regain for what balanced means."""
    floor_w, floor_h = oval_dims_for_velocity(
        flow_m3_s, min_velocity_m_s, mode, aspect_ratio=aspect_ratio, fixed_dim_m=fixed_dim_m
    )

    if mode == "aspect_ratio":
        _check_oval_aspect_ratio(aspect_ratio)

        def area_and_dh(height_m):
            width_m = aspect_ratio * height_m
            return oval_area(width_m, height_m), hydraulic_diameter_oval(width_m, height_m)

        height, balanced = _solve_scale_for_static_regain(
            area_and_dh,
            flow_m3_s,
            upstream_velocity_pressure_pa,
            regain_factor,
            length_m,
            roughness_m,
            kinematic_viscosity_m2_s,
            air_density_kg_m3,
            hi=floor_h,
            fitting_loss_pa=fitting_loss_pa,
            friction_model=friction_model,
        )
        return aspect_ratio * height, height, balanced

    if mode == "fixed_height":
        if not fixed_dim_m or fixed_dim_m <= 0.0:
            raise ValueError("fixed_dim_m must be positive")
        height = fixed_dim_m

        def area_and_dh(width_m):
            return oval_area(width_m, height), hydraulic_diameter_oval(width_m, height)

        # The only upper limit on width is the min_velocity ceiling (floor_w);
        # width may end up above or below the fixed height.
        width, balanced = _solve_scale_for_static_regain(
            area_and_dh,
            flow_m3_s,
            upstream_velocity_pressure_pa,
            regain_factor,
            length_m,
            roughness_m,
            kinematic_viscosity_m2_s,
            air_density_kg_m3,
            hi=floor_w,
            fitting_loss_pa=fitting_loss_pa,
            friction_model=friction_model,
        )
        return width, height, balanced

    if mode == "fixed_width":
        if not fixed_dim_m or fixed_dim_m <= 0.0:
            raise ValueError("fixed_dim_m must be positive")
        width = fixed_dim_m

        def area_and_dh(height_m):
            return oval_area(width, height_m), hydraulic_diameter_oval(width, height_m)

        # The only upper limit on height is the min_velocity ceiling (floor_h);
        # height may end up above or below the fixed width.
        height, balanced = _solve_scale_for_static_regain(
            area_and_dh,
            flow_m3_s,
            upstream_velocity_pressure_pa,
            regain_factor,
            length_m,
            roughness_m,
            kinematic_viscosity_m2_s,
            air_density_kg_m3,
            hi=floor_h,
            fitting_loss_pa=fitting_loss_pa,
            friction_model=friction_model,
        )
        return width, height, balanced

    raise ValueError("Unknown mode: {!r}".format(mode))


# ----------------------------------------------------------------------------
# Section dispatch: profile ("Circular"/"Rectangular"/"Oval") -> area/hydraulic
# diameter. One place for the branching that used to be copy-pasted in
# AirflowSolver, DuctSizer, and HVACLibraryAPI.port_area.
# ----------------------------------------------------------------------------


def section_area_m2(section: SectionModel) -> float:
    """Cross-section area (m^2) of a SectionModel (dimensions in mm), or 0.0 if unset/degenerate."""
    if section.profile == "Circular":
        d = mm_to_m(section.diameter_mm)
        return circular_area(d) if d > 0.0 else 0.0
    if section.profile in ("Rectangular", "Oval"):
        w = mm_to_m(section.width_mm)
        h = mm_to_m(section.height_mm)
        if w <= 0.0 or h <= 0.0:
            return 0.0
        return rectangular_area(w, h) if section.profile == "Rectangular" else oval_area(w, h)
    return 0.0


def section_hydraulic_diameter_m(section: SectionModel) -> float:
    """Hydraulic diameter (m) of a SectionModel (dimensions in mm), or 0.0 if unset/degenerate."""
    if section.profile == "Circular":
        d = mm_to_m(section.diameter_mm)
        return hydraulic_diameter_circular(d) if d > 0.0 else 0.0
    if section.profile in ("Rectangular", "Oval"):
        w = mm_to_m(section.width_mm)
        h = mm_to_m(section.height_mm)
        if w <= 0.0 or h <= 0.0:
            return 0.0
        return (
            hydraulic_diameter_rectangular(w, h) if section.profile == "Rectangular" else hydraulic_diameter_oval(w, h)
        )
    return 0.0
