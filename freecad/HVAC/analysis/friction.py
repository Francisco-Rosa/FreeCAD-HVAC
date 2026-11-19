# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Straight-duct friction models. Plain math, no FreeCAD.

A friction model turns (flow, section, roughness, air) into a friction rate
in Pa/m. Every solver asks the segment's own model (SegmentModel.friction_model)
through `rate_pa_per_m()` below; a segment without one gets the default,
Darcy-Weisbach with the Altshul-Tsal friction factor -- the only formula
there was before friction models existed.

Built in:
  - DarcyWeisbach("altshul_tsal" | "colebrook")
  - TableFriction: a friction chart as rows of (diameter, velocity or flow,
    rate), interpolated log-log.
  - ExpressionFriction: a user formula in Q, V, Dh, eps, rho, nu, Re. It is
    parsed with `ast` and evaluated by a small walker that only knows
    numbers, those names, + - * / ** and a few math functions. `eval` is
    never used.
  - ScaledFriction: any model times a constant factor, e.g. the SMACNA
    Fig. 14-4 correction for compressed flexible duct
    (`flex_compression_factor`).

Air density and temperature corrections (SMACNA Fig. 14-5) are not a
separate multiplier: the Darcy-Weisbach models already use the network's
AirDensity and AirKinematicViscosity, which is what that chart corrects
for. A table or expression model is used as given.
"""

import ast
import bisect
import csv
import io
import math

from . import physics

ALTSHUL_TSAL = "altshul_tsal"
COLEBROOK = "colebrook"


class FrictionModel:
    """
    Interface every friction model implements (duck-typed; subclassing is
    optional). All arguments are SI: m3/s, m2, m, kg/m3, m2/s.
    """

    label = "friction model"

    def rate_pa_per_m(self, flow_m3_s, area_m2, dh_m, roughness_m, density_kg_m3, kinematic_viscosity_m2_s):
        raise NotImplementedError


def friction_factor_colebrook(reynolds, relative_roughness, iterations=50):
    """
    Darcy friction factor from the Colebrook-White equation, solved by
    fixed-point iteration from the Altshul-Tsal estimate. Laminar flow
    (Re < 2000) uses 64/Re.
    """
    reynolds = float(reynolds)
    if reynolds <= 0.0:
        return 0.0
    if reynolds < 2000.0:
        return 64.0 / reynolds
    eps_rel = max(float(relative_roughness), 0.0)
    f = physics.friction_factor_altshul_tsal(reynolds, eps_rel)
    for _ in range(iterations):
        rhs = -2.0 * math.log10(eps_rel / 3.7 + 2.51 / (reynolds * math.sqrt(f)))
        new_f = 1.0 / (rhs * rhs)
        if abs(new_f - f) < 1e-12:
            return new_f
        f = new_f
    return f


class DarcyWeisbach(FrictionModel):
    """Darcy-Weisbach with an explicit (Altshul-Tsal) or implicit (Colebrook) friction factor."""

    def __init__(self, factor=ALTSHUL_TSAL):
        if factor not in (ALTSHUL_TSAL, COLEBROOK):
            raise ValueError(
                "Unknown friction factor {!r}; expected {!r} or {!r}".format(factor, ALTSHUL_TSAL, COLEBROOK)
            )
        self.factor = factor
        self.label = "Darcy-Weisbach ({})".format("Altshul-Tsal" if factor == ALTSHUL_TSAL else "Colebrook")

    def rate_pa_per_m(self, flow_m3_s, area_m2, dh_m, roughness_m, density_kg_m3, kinematic_viscosity_m2_s):
        velocity = physics.velocity_from_flow(flow_m3_s, area_m2)
        reynolds = physics.reynolds_number(velocity, dh_m, kinematic_viscosity_m2_s)
        if self.factor == COLEBROOK:
            f = friction_factor_colebrook(reynolds, roughness_m / dh_m)
        else:
            f = physics.friction_factor_altshul_tsal(reynolds, roughness_m / dh_m)
        return physics.darcy_weisbach_pressure_loss(f, 1.0, dh_m, density_kg_m3, velocity)


DEFAULT_MODEL = DarcyWeisbach()


def rate_pa_per_m(model, flow_m3_s, area_m2, dh_m, roughness_m, density_kg_m3, kinematic_viscosity_m2_s):
    """
    Friction rate (Pa/m) from `model`, or from the default model when it is
    None. Zero for no flow or a degenerate section. Raises ValueError when
    a model returns something that is not a finite, non-negative number.
    """
    if flow_m3_s <= 0.0 or area_m2 <= 0.0 or dh_m <= 0.0:
        return 0.0
    model = model or DEFAULT_MODEL
    rate = float(model.rate_pa_per_m(flow_m3_s, area_m2, dh_m, roughness_m, density_kg_m3, kinematic_viscosity_m2_s))
    if not math.isfinite(rate) or rate < 0.0:
        raise ValueError("Friction model '{}' returned {!r} Pa/m".format(getattr(model, "label", model), rate))
    return rate


class ScaledFriction(FrictionModel):
    """`base` (None = the default model) multiplied by a constant factor."""

    def __init__(self, base, factor, label=""):
        factor = float(factor)
        if not math.isfinite(factor) or factor <= 0.0:
            raise ValueError("Friction factor multiplier must be positive, got {!r}".format(factor))
        self.base = base
        self.factor = factor
        self.label = label or "{} x {:.3g}".format(getattr(base or DEFAULT_MODEL, "label", "friction"), factor)

    def rate_pa_per_m(self, flow_m3_s, area_m2, dh_m, roughness_m, density_kg_m3, kinematic_viscosity_m2_s):
        return self.factor * rate_pa_per_m(
            self.base, flow_m3_s, area_m2, dh_m, roughness_m, density_kg_m3, kinematic_viscosity_m2_s
        )


# ----------------------------------------------------------------------------
# SMACNA Fig. 14-4: pressure loss correction factor for unextended flexible
# duct, by percent of compression length. Read off the printed chart (its
# vertical axis is logarithmic); expect a few percent of reading error.
# ----------------------------------------------------------------------------

_FLEX_COMPRESSION = [(0.0, 1.00), (5.0, 1.50), (10.0, 1.95), (15.0, 2.55), (20.0, 3.00), (25.0, 3.50), (30.0, 4.00)]


def flex_compression_factor(compression_percent):
    """
    Fig. 14-4 multiplier for a flexible duct compressed by
    `compression_percent` of its fully extended length (0 to 30 %).
    Outside the chart the value is clamped to its ends.
    """
    x = min(max(float(compression_percent), 0.0), _FLEX_COMPRESSION[-1][0])
    xs = [p[0] for p in _FLEX_COMPRESSION]
    i = min(max(bisect.bisect_right(xs, x) - 1, 0), len(xs) - 2)
    (x0, y0), (x1, y1) = _FLEX_COMPRESSION[i], _FLEX_COMPRESSION[i + 1]
    # The chart's vertical axis is logarithmic: interpolate log(factor).
    t = (x - x0) / (x1 - x0)
    return math.exp(math.log(y0) + t * (math.log(y1) - math.log(y0)))


# ----------------------------------------------------------------------------
# Table friction
# ----------------------------------------------------------------------------

BASIS_VELOCITY = "velocity"
BASIS_FLOW = "flow"


def _loglog(x, xs, ys):
    """Log-log interpolation of y(x) over sorted xs; extrapolates the end segment (friction is a power law)."""
    if len(xs) == 1:
        return ys[0]
    i = min(max(bisect.bisect_right(xs, x) - 1, 0), len(xs) - 2)
    lx0, lx1 = math.log(xs[i]), math.log(xs[i + 1])
    ly0, ly1 = math.log(ys[i]), math.log(ys[i + 1])
    return math.exp(ly0 + (math.log(x) - lx0) * (ly1 - ly0) / (lx1 - lx0))


class TableFriction(FrictionModel):
    """
    A friction chart: rows of (diameter_mm, x, rate_pa_per_m) where x is the
    velocity in m/s (basis "velocity") or the flow in L/s (basis "flow").
    The diameter is compared with the duct's hydraulic diameter. The rate is
    interpolated log-log along x for each tabulated diameter, then log-log
    between the two diameters around the duct's; beyond the table both are
    extrapolated along the end segment. Roughness and air properties are
    ignored: the table is taken as already made for the duct material and air.
    """

    def __init__(self, rows, basis=BASIS_VELOCITY, label="friction table"):
        if basis not in (BASIS_VELOCITY, BASIS_FLOW):
            raise ValueError(
                "Unknown table basis {!r}; expected {!r} or {!r}".format(basis, BASIS_VELOCITY, BASIS_FLOW)
            )
        curves = {}
        for row in rows:
            diameter, x, rate = (float(v) for v in row)
            if diameter <= 0.0 or x <= 0.0 or rate <= 0.0:
                raise ValueError("Friction table values must all be positive, got {!r}".format(tuple(row)))
            curves.setdefault(diameter, {})[x] = rate
        if not curves:
            raise ValueError("Friction table has no rows")
        self.basis = basis
        self.label = label
        self.diameters_mm = sorted(curves)
        self._curves = []
        for diameter in self.diameters_mm:
            points = sorted(curves[diameter].items())
            self._curves.append(([p[0] for p in points], [p[1] for p in points]))

    def rate_pa_per_m(self, flow_m3_s, area_m2, dh_m, roughness_m, density_kg_m3, kinematic_viscosity_m2_s):
        if self.basis == BASIS_VELOCITY:
            x = physics.velocity_from_flow(flow_m3_s, area_m2)
        else:
            x = physics.m3s_to_lps(flow_m3_s)
        rates = [_loglog(x, xs, ys) for xs, ys in self._curves]
        return _loglog(dh_m * 1000.0, self.diameters_mm, rates)

    @classmethod
    def from_csv(cls, text, label="friction table"):
        """
        Parse CSV text with a header row naming three columns: a diameter
        column (`diameter_mm`), either `velocity_ms` or `flow_lps`, and
        `pa_per_m`. Blank lines and lines starting with '#' are skipped.
        """
        lines = [line for line in io.StringIO(text) if line.strip() and not line.lstrip().startswith("#")]
        reader = csv.reader(lines)
        try:
            header = [h.strip().lower() for h in next(reader)]
        except StopIteration:
            raise ValueError("Friction table CSV is empty") from None
        columns = {name: i for i, name in enumerate(header)}
        if "diameter_mm" not in columns or "pa_per_m" not in columns:
            raise ValueError("Friction table CSV needs 'diameter_mm' and 'pa_per_m' columns, got {}".format(header))
        if "velocity_ms" in columns:
            basis, x_col = BASIS_VELOCITY, columns["velocity_ms"]
        elif "flow_lps" in columns:
            basis, x_col = BASIS_FLOW, columns["flow_lps"]
        else:
            raise ValueError("Friction table CSV needs a 'velocity_ms' or a 'flow_lps' column, got {}".format(header))
        rows = []
        for line_no, row in enumerate(reader, start=2):
            try:
                rows.append((float(row[columns["diameter_mm"]]), float(row[x_col]), float(row[columns["pa_per_m"]])))
            except (IndexError, ValueError):
                raise ValueError("Friction table CSV row {} is not three numbers: {!r}".format(line_no, row)) from None
        return cls(rows, basis=basis, label=label)


# ----------------------------------------------------------------------------
# Expression friction (whitelist evaluator, never eval)
# ----------------------------------------------------------------------------

EXPRESSION_VARIABLES = {
    "Q": "flow (m3/s)",
    "V": "velocity (m/s)",
    "Dh": "hydraulic diameter (m)",
    "A": "area (m2)",
    "eps": "absolute roughness (m)",
    "rho": "air density (kg/m3)",
    "nu": "kinematic viscosity (m2/s)",
    "Re": "Reynolds number",
}

_FUNCTIONS = {
    "sqrt": math.sqrt,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "abs": abs,
    "min": min,
    "max": max,
}
_CONSTANTS = {"pi": math.pi, "e": math.e}
_BINARY = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Pow: lambda a, b: a**b,
}
_UNARY = {ast.UAdd: lambda a: a, ast.USub: lambda a: -a}
_MAX_EXPRESSION_LENGTH = 500


def _compile(node, text):
    """Turn a parsed expression into a closure over a variables dict, rejecting anything not whitelisted."""
    if isinstance(node, ast.Expression):
        return _compile(node.body, text)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        value = float(node.value)
        return lambda env: value
    if isinstance(node, ast.Name):
        name = node.id
        if name in EXPRESSION_VARIABLES:
            return lambda env: env[name]
        if name in _CONSTANTS:
            value = _CONSTANTS[name]
            return lambda env: value
        raise ValueError(
            "Unknown name '{}' in friction expression {!r}; allowed: {}".format(
                name, text, ", ".join(list(EXPRESSION_VARIABLES) + list(_CONSTANTS))
            )
        )
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        op, left, right = _BINARY[type(node.op)], _compile(node.left, text), _compile(node.right, text)
        return lambda env: op(left(env), right(env))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        op, operand = _UNARY[type(node.op)], _compile(node.operand, text)
        return lambda env: op(operand(env))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCTIONS:
        if node.keywords:
            raise ValueError("Keyword arguments are not allowed in friction expression {!r}".format(text))
        func = _FUNCTIONS[node.func.id]
        args = [_compile(arg, text) for arg in node.args]
        return lambda env: func(*(arg(env) for arg in args))
    raise ValueError(
        "Friction expression {!r} uses '{}', which is not allowed (only numbers, the variables, "
        "+ - * / **, and {})".format(text, type(node).__name__, ", ".join(_FUNCTIONS))
    )


class ExpressionFriction(FrictionModel):
    """
    A friction rate (Pa/m) from a formula, e.g.
    `0.0175 * rho * V**1.9 / Dh**1.22` or
    `0.02 / Dh * rho * V**2 / 2`. Variables: see EXPRESSION_VARIABLES.
    """

    def __init__(self, text, label=""):
        text = str(text or "").strip()
        if not text:
            raise ValueError("Friction expression is empty")
        if len(text) > _MAX_EXPRESSION_LENGTH:
            raise ValueError("Friction expression is longer than {} characters".format(_MAX_EXPRESSION_LENGTH))
        try:
            tree = ast.parse(text, mode="eval")
        except SyntaxError as exc:
            raise ValueError("Friction expression {!r} is not valid: {}".format(text, exc.msg)) from None
        self.text = text
        self.label = label or "expression {}".format(text)
        self._fn = _compile(tree, text)

    def evaluate(self, **variables):
        """Evaluate with explicit variable values (all of EXPRESSION_VARIABLES)."""
        try:
            return float(self._fn(variables))
        except (ArithmeticError, ValueError, TypeError) as exc:
            raise ValueError("Friction expression {!r} failed: {}".format(self.text, exc)) from None

    def rate_pa_per_m(self, flow_m3_s, area_m2, dh_m, roughness_m, density_kg_m3, kinematic_viscosity_m2_s):
        velocity = physics.velocity_from_flow(flow_m3_s, area_m2)
        return self.evaluate(
            Q=flow_m3_s,
            V=velocity,
            Dh=dh_m,
            A=area_m2,
            eps=roughness_m,
            rho=density_kg_m3,
            nu=kinematic_viscosity_m2_s,
            Re=physics.reynolds_number(velocity, dh_m, kinematic_viscosity_m2_s),
        )
