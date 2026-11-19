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

# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The library layer: loads type-defs (JSON files describing a segment/junction
type) from disk, decides which type-def best matches a request from
NetworkParser/DuctNetwork sync, and dispatches to the right geometry backend
to build a type's actual shape.

Three main pieces:
  - HVACTypeDef and friends: the in-memory shape of one loaded type-def.
  - HVACLibrary: one loaded library's types, plus the matching/selection
    logic that picks the best type for a given topology/family/profile.
  - HVACLibraryRegistry: owns every loaded HVACLibrary, and is the single
    entry point core code calls into (loading, selection, geometry/loss
    dispatch) -- see freecad/HVAC/utils/hvaclib.py's HVACLibraryService for
    how the rest of the addon reaches this registry.
"""

import importlib
import json
import os
from dataclasses import dataclass, field

import FreeCAD

from . import geometry_result, validation
from .construction import ConstructionFeatureDef, ConstructionLayerDef, FeatureContext
from .library_api import HVACLibraryAPI
from .loss_api import HVACLossAPI


@dataclass
class HVACPropertyDef:
    """One user-facing property a type-def declares (name, FreeCAD property type, default, ...)."""

    name: str
    prop_type: str
    group: str = "HVAC"
    description: str = ""
    default: object = None
    editor_mode: int = 0
    required: bool = True
    validation: dict = field(default_factory=dict)
    # True: one value per connected port instead of one for the whole
    # fitting (see validation.PER_PORT_LIST_TYPES / PortValues).
    per_port: bool = False


@dataclass
class HVACGeometryDef:
    """Which geometry backend a type-def uses and where to find it (PartScript file / static descriptor)."""

    backend: str = ""
    file: str = ""
    descriptor: str = ""


@dataclass
class HVACLossVariantDef:
    """
    One conditional entry in a type-def's own "loss.variants" list -- the
    same physical fitting (one TypeId) can carry several flow-dependent
    loss formulas (e.g. an ordinary vs. bullhead tee, or an expanding vs.
    contracting transition) without needing a separate TypeId per flow
    case. `constraints` is evaluated by
    `validation.flow_classification_violations()` against the current
    classification context (flow_class/qualifiers/derived_values/...) --
    the exact same operators/keys a type-def's own top-level `constraints`
    uses, just scoped to "which loss function" instead of "which TypeId".
    See `HVACLibraryRegistry.call_loss()`/`validation.resolve_loss_variant()`.
    """

    constraints: dict = field(default_factory=dict)
    module: str = ""
    function: str = ""


# A type-def module name starting with this prefix is imported from the
# addon's shared fitting package instead of the library's own generators.
SHARED_MODULE_PREFIX = "shared:"
SHARED_FITTINGS_PACKAGE = "freecad.HVAC.library.fittings"

# Selection kinds a type descriptor may declare under "selection.kind".
GEOMETRY_BACKEND_GENERATOR = "generator"
GEOMETRY_BACKEND_PARTSCRIPT = "partscript"
GEOMETRY_BACKEND_STATIC = "static"
VALID_GEOMETRY_BACKENDS = {GEOMETRY_BACKEND_GENERATOR, GEOMETRY_BACKEND_PARTSCRIPT, GEOMETRY_BACKEND_STATIC}

SELECTION_KIND_MODEL = "model"
SELECTION_KIND_PLACEHOLDER = "placeholder"
SELECTION_KIND_INLINE = "inline"
VALID_SELECTION_KINDS = {SELECTION_KIND_MODEL, SELECTION_KIND_PLACEHOLDER, SELECTION_KIND_INLINE}

# Flow boundary conditions a terminal junction type-def may prescribe under
# its own top-level "flow_boundary" key -- see core/Junction.py's/
# core/Component.py's own FlowBoundary property for what each means to the
# solver (analysis/flow.py). "" means the type-def doesn't prescribe one at
# all (the user's own FlowBoundary choice, default "Auto", is left alone).
VALID_FLOW_BOUNDARIES = {"", "Auto", "Fixed", "Closed"}


@dataclass
class HVACSelectionDef:
    """
    Registry-driven selection metadata for a type descriptor.

    kind:
        "model"       -- a real, selectable geometry-producing type. Eligible
                          to become a DuctJunction's Primary DuctComponent
                          via automatic (topology, family, profile) matching.
        "placeholder" -- an invisible/marker fallback (never sticky; always
                          re-evaluated on sync so it can upgrade to a model).
        "inline"      -- a user-added-only device (damper, silencer, flex
                          connector, ...). Excluded from select_type()'s own
                          indexes entirely, so it's never chosen as a
                          Primary component *automatically*. It's still
                          reachable as a Primary component through a
                          deliberate manual choice, two ways: (a) as an
                          Inline component in a junction's chain, via
                          HVACLibrary.list_inline_types() for the "Add
                          Inline Component" UI action; (b) directly as the
                          Primary type itself, via HVACLibrary.list_types()
                          (the "change type" editor) -- and once manually
                          set that way, resolve_sticky_type() retains it
                          across sync like any other non-placeholder type.
    priority:
        Tiebreaker used only when choosing among multiple candidates that are
        otherwise equally specific (same tier: exact-profile model,
        Generic-profile model, or placeholder). Higher wins. Never used to
        replace an already-selected compatible type -- see
        HVACLibraryRegistry.resolve_sticky_type().
    """

    kind: str = SELECTION_KIND_MODEL
    priority: int = 0


@dataclass
class HVACTypeDef:
    """One loaded type-def -- the in-memory form of a library type's JSON file."""

    id: str
    label: str
    category: str
    topology: str
    family: list[str]
    profiles: list[str] = field(default_factory=list)
    constraints: dict = field(default_factory=dict)
    properties: list[HVACPropertyDef] = field(default_factory=list)
    geometry: HVACGeometryDef = field(default_factory=HVACGeometryDef)
    generator_module: str = ""
    generator_function: str = ""
    lengths_module: str = ""
    lengths_function: str = ""
    loss_module: str = ""
    loss_function: str = ""
    # Optional straight-duct friction model factory (segment types only):
    # JSON `"friction": {"module": ..., "function": ...}`, called through
    # call_friction(). Empty means the network's own friction model.
    friction_module: str = ""
    friction_function: str = ""
    # Optional flow-dependent loss variants -- see HVACLossVariantDef. Empty
    # for a type-def using the plain loss_module/loss_function form only
    # (the common case); when non-empty, resolve_loss_variant() picks
    # between them per-call, falling back to loss_module/loss_function as
    # an explicit wildcard/default if none of them apply.
    loss_variants: list[HVACLossVariantDef] = field(default_factory=list)
    selection: HVACSelectionDef = field(default_factory=HVACSelectionDef)
    # Construction layers this type declares (see library/construction.py
    # and the "construction" JSON block below) -- empty for a type that
    # hasn't been migrated to the multilayer model, which build_geometry()
    # treats as a single, roleless implicit layer (HVACLibraryAPI.single_layer).
    # Parsed from the JSON "construction"
    # block's own "layers" array.
    construction: list[ConstructionLayerDef] = field(default_factory=list)
    # Construction features this type declares (localized attachments --
    # flanges, stiffeners, seams, ... -- see library/construction.py).
    # Parsed from the JSON "construction" block's own "features" array.
    features: list[ConstructionFeatureDef] = field(default_factory=list)
    # Optional prescribed FlowBoundary ("Auto"/"Fixed"/"Closed", "" = not
    # declared) for a terminal (topology "end") junction type -- applied
    # once when a component adopts this type (core/Component.py's
    # updateMetadata()). If flow_boundary_locked is also true, it's instead
    # re-asserted on every sync so the user can never change it (e.g. a
    # duct-closure/end-cap fitting that must always stay "Closed").
    flow_boundary: str = ""
    flow_boundary_locked: bool = False


@dataclass(frozen=True)
class HVACMatchKey:
    """
    Index key for HVACLibrary's per-library match indexes:
    (category, topology, family) only -- deliberately no profile.

    A junction can have several different connected-port profiles at once
    (e.g. a Circular -> Rectangular transition, or a mixed-profile
    multiport), so there's no single profile value that could ever key a
    junction lookup correctly. Profile compatibility is instead checked
    per-candidate, after this structural lookup, by
    HVACLibrary._compatible() (which calls
    validation.context_violations() -- the same connected-port-profile
    check used everywhere else). See HVACLibrary.select_type().
    """

    category: str
    topology: str
    family: str


@dataclass(frozen=True)
class HVACTypeMatchRequest:
    """
    What NetworkParser/DuctNetwork sync is asking the registry to match.

    family is the classifier's literal family key (junctions: e.g.
    "branch.tee.3d", from JunctionAnalysis.family_key; segments:
    "straight_segment"/"curved_segment"). context carries whatever
    freecad/HVAC/library/validation.py's context_violations() needs for the
    second-stage constraint check (junctions: "connected_ports"/"topology";
    segments: "profile") -- topology/profile are auto-filled from this
    request's own fields if the caller didn't already put them in context.

    profile is NOT part of the match index (see HVACMatchKey) -- a junction
    may have several distinct connected-port profiles at once, so a single
    profile string can't key a junction lookup. It still matters for
    segments (a straight/curved run only ever has one profile, carried into
    context["profile"] for context_violations() to check) and it's kept
    here as a plain convenience default for that case; junction profile
    compatibility is authoritative from context["connected_ports"] alone.
    """

    category: str
    topology: str
    family: str
    profile: str
    context: dict = field(default_factory=dict)


@dataclass
class HVACTypeSelection:
    """Result of HVACLibrary/HVACLibraryRegistry.select_type()."""

    library_id: str
    type_def: "HVACTypeDef | None"
    status: str  # "exact" | "generic_profile" | "placeholder" | "retained" | "ambiguous" | "not_found"
    reason: str = ""
    candidates: tuple = ()


def _family_key_related(a, b):
    """
    True if classifier family key `a` and descriptor-declared family entry
    `b` refer to the same or an ancestor/descendant point in the dotted
    family hierarchy (e.g. "branch.tee" and "branch.tee.3d", or
    "end.terminal" and "end.terminal.diffuser").

    This is intentionally NOT used for automatic-selection index lookups
    (those require an exact literal family_key match per type-def author's
    explicit family list -- see HVACLibrary._rebuild_match_index). It's used
    for the second-stage compatibility check (matches_type()/select_type()'s
    per-candidate validation), so that e.g. a manually-selected
    end_diffuser_generic (family=["end.terminal.diffuser", ...]) stays sticky
    even though the classifier can never literally produce anything more
    specific than "end.terminal" for a degree-1 node.
    """
    if a == b:
        return True
    if b.startswith(a + "."):
        return True
    if a.startswith(b + "."):
        return True
    return False


@dataclass
class HVACLibrary:
    """
    One loaded library: its types, plus the indexes and matching logic used
    to pick the best type for a given topology/family/profile request.
    """

    id: str
    label: str
    root_path: str
    generators_package: str = ""
    default_construction: list[ConstructionLayerDef] = field(default_factory=list)
    types_by_id: dict = field(default_factory=dict)
    _index_dirty: bool = field(default=True, repr=False, compare=False)
    _model_match_index: dict = field(default_factory=dict, repr=False, compare=False)
    _placeholder_match_index: dict = field(default_factory=dict, repr=False, compare=False)

    def add_type(self, type_def: HVACTypeDef):
        self.types_by_id[type_def.id] = type_def
        self._index_dirty = True

    def get_type(self, type_id: str):
        return self.types_by_id.get(type_id)

    def _family_match(self, parent, child):
        return child == parent or child.startswith(parent + ".")

    def list_types(
        self,
        category=None,
        topology=None,
        family=None,
        profile=None,
        connected_ports=None,
        include_placeholders=True,
        classification=None,
    ):
        """Types matching the given filters, best-suited first.

        Ordered by the same ranking `select_type` uses (see
        docs/library-guide.md's "Type selection" section): a
        `kind: "model"` type before a `kind: "placeholder"` one; among
        those, one that declares a concrete profile before one that only
        matches via the "Generic" wildcard; then `selection.priority`
        descending. `id` breaks any remaining tie, only to keep the order
        deterministic -- it carries no ranking meaning of its own.

        `connected_ports`, when given, replaces the plain `profile`
        membership check below with the same per-port compatibility check
        select_type() uses (validation.context_violations()). A junction
        can have several different connected-port profiles at once, so a
        single `profile` string (e.g. a "Mixed" pseudo-profile read off an
        already-composed heterogeneous component) can never correctly
        filter it -- the same reason HVACMatchKey doesn't index on profile
        either. `profile` alone (no `connected_ports`) still works exactly
        as before, for callers with only one real profile to filter by
        (segments, or a homogeneous-profile junction).

        `classification` (only used together with `connected_ports`) is the
        node's own flow classification: a dict with any of "flow_class",
        "qualifiers" and "derived_values". With it, a type whose constraints
        rule out this node's flow (an entry fitting where air leaves, an
        eccentric transition between concentric ducts, ...) is left out,
        exactly as automatic selection would leave it out. A value the
        classifier could not work out never rules a type out.
        """
        use_ports = connected_ports is not None
        ctx = {"connected_ports": list(connected_ports or []), "topology": topology or ""} if use_ports else None
        if use_ports and classification:
            ctx["flow_class"] = classification.get("flow_class") or None
            ctx["qualifiers"] = dict(classification.get("qualifiers") or {})
            ctx["derived_values"] = dict(classification.get("derived_values") or {})

        out = []
        for t in self.types_by_id.values():
            if category and t.category != category:
                continue
            if topology and t.topology != topology:
                continue
            if family and not any(self._family_match(family, candidate) for candidate in t.family):
                continue
            if use_ports:
                if not validation.is_context_valid(t, ctx):
                    continue
            elif profile and t.profiles and profile not in t.profiles:
                continue
            if (
                not include_placeholders
                and getattr(t.selection, "kind", SELECTION_KIND_MODEL) == SELECTION_KIND_PLACEHOLDER
            ):
                continue
            out.append(t)

        def rank_key(t):
            kind = getattr(t.selection, "kind", SELECTION_KIND_MODEL)
            kind_rank = 0 if kind == SELECTION_KIND_MODEL else (1 if kind == SELECTION_KIND_PLACEHOLDER else 2)
            if use_ports:
                profile_rank = 0 if self._declares_concrete_profile(t) else 1
            else:
                exact_profile = bool(profile) and bool(t.profiles) and profile in t.profiles
                profile_rank = 0 if (exact_profile or not profile) else 1
            priority = getattr(t.selection, "priority", 0)
            return (kind_rank, profile_rank, -priority, t.id)

        out.sort(key=rank_key)
        return out

    def list_profiles(self, category=None, family=None):
        profiles = set()
        for t in self.types_by_id.values():
            if category and t.category != category:
                continue
            if family and not any(self._family_match(family, candidate) for candidate in t.family):
                continue
            for p in t.profiles or []:
                profiles.add(p)
        return sorted(profiles)

    def default_profile(self, category=None, family=None):
        profiles = self.list_profiles(category=category, family=family)
        return profiles[0] if profiles else ""

    def list_inline_types(self, topology=None, profile=None):
        """
        All selection.kind=="inline" junction types (dampers, silencers,
        flex connectors, ...) compatible with an optional topology/profile
        filter -- for the "Add Inline Component" UI action, not automatic
        Primary-fitting matching (see _rebuild_match_index). No family
        filter: unlike Primary selection, adding an inline component is
        always a direct user choice, so there's no classifier family key to
        match against.
        """
        out = []
        for t in self.types_by_id.values():
            if getattr(t.selection, "kind", SELECTION_KIND_MODEL) != SELECTION_KIND_INLINE:
                continue
            if t.category != "junction":
                continue
            if topology and t.topology not in (topology, "generic"):
                continue
            if profile and t.profiles and "Generic" not in t.profiles and profile not in t.profiles:
                continue
            out.append(t)
        return out

    # ------------------------------------------------------------------
    # Match indexes -- rebuilt lazily whenever a type is added/reloaded.
    # ------------------------------------------------------------------

    def _rebuild_match_index(self):
        """
        Build two lookup tables (real "model" types, and "placeholder"
        fallback types), keyed by (category, topology, family) so
        select_type() can jump straight to the structural candidates for a
        request instead of scanning every type. Profile compatibility is
        deliberately NOT part of this key -- see HVACMatchKey -- it's
        checked per-candidate afterwards, in select_type() itself.

        "inline"-kind types (see HVACSelectionDef) are deliberately left out
        of both indexes -- they must never be reachable through automatic
        Primary-fitting selection. They're looked up separately, by a plain
        scan, in list_inline_types() below.
        """
        self._model_match_index = {}
        self._placeholder_match_index = {}

        for t in self.types_by_id.values():
            kind = getattr(t.selection, "kind", SELECTION_KIND_MODEL)
            if kind == SELECTION_KIND_INLINE:
                continue
            target = self._model_match_index if kind == SELECTION_KIND_MODEL else self._placeholder_match_index
            for fam in t.family:
                key = HVACMatchKey(category=t.category, topology=t.topology, family=fam)
                target.setdefault(key, []).append(t)

        self._index_dirty = False

    def _ensure_match_index(self):
        if self._index_dirty:
            self._rebuild_match_index()

    @property
    def model_match_index(self):
        self._ensure_match_index()
        return self._model_match_index

    @property
    def placeholder_match_index(self):
        self._ensure_match_index()
        return self._placeholder_match_index

    def reindex(self):
        """Force an immediate rebuild of the match indexes."""
        self._rebuild_match_index()

    # ------------------------------------------------------------------
    # Automatic / compatibility matching
    # ------------------------------------------------------------------

    def _structural_candidates(self, index, request: HVACTypeMatchRequest):
        """All types indexed under this request's (category, topology, family) -- unfiltered by profile."""
        key = HVACMatchKey(request.category, request.topology, request.family)
        return list(index.get(key, []))

    @staticmethod
    def _declares_concrete_profile(type_def: HVACTypeDef):
        """
        True if this type declares real, specific profiles (e.g.
        ["Circular", "Rectangular"]) rather than the "Generic" wildcard (or
        no profiles at all, treated the same as "Generic" -- see
        validation.py, docs/library-guide.md).

        Used to rank a concrete-profile type ahead of a Generic-profile one
        among candidates that already passed _compatible() -- i.e. that
        already cover every connected port's actual profile. This replaces
        the old exact/generic index-key split, and works even when a
        junction's connected ports span more than one profile (a concrete
        type covering e.g. both "Circular" and "Rectangular" still ranks
        above a Generic one for a mixed-profile request).
        """
        profiles = set(type_def.profiles or [])
        return bool(profiles) and "Generic" not in profiles

    def _compatible(self, type_def: HVACTypeDef, request: HVACTypeMatchRequest):
        if type_def.category != request.category:
            return False
        if not any(_family_key_related(request.family, candidate) for candidate in type_def.family):
            return False

        ctx = dict(request.context or {})
        ctx.setdefault("topology", request.topology)
        ctx.setdefault("profile", request.profile)
        return validation.is_context_valid(type_def, ctx)

    @staticmethod
    def _rank_tier(candidates):
        """
        Return (winner_or_None, is_ambiguous, candidate_ids) for one
        specificity tier, using selection.priority as the tiebreaker.
        Never uses dict/list insertion order to break a tie.
        """
        if not candidates:
            return None, False, ()

        max_priority = max(getattr(t.selection, "priority", 0) for t in candidates)
        top = [t for t in candidates if getattr(t.selection, "priority", 0) == max_priority]
        ids = tuple(t.id for t in candidates)

        if len(top) == 1:
            return top[0], False, ids
        return None, True, tuple(sorted(t.id for t in top))

    def select_type(self, request: HVACTypeMatchRequest, strict=False) -> HVACTypeSelection:
        """
        Choose the best compatible type for `request` in this library.

        Structural candidates (same category/topology/family) are pulled
        from the index in one shot -- see HVACMatchKey -- then filtered
        down to the ones actually compatible with this request via
        _compatible() (which validates connected-port profiles for a
        junction, or context["profile"] for a segment, via
        validation.context_violations() -- the single authoritative
        profile-compatibility check, not duplicated here).

        Compatible candidates are then split into tiers, in priority order
        (see docs/library-guide.md):
            1. model,       declares concrete profile(s)
            2. model,       Generic-profile (wildcard) match
            3. placeholder, declares concrete profile(s)
            4. placeholder, Generic-profile match

        Within a tier, selection.priority breaks ties; a genuine tie (equal
        highest priority, more than one candidate) is ambiguous -- in
        strict mode this is reported as status="ambiguous"; otherwise a
        console warning is logged and matching falls through to the next
        tier (eventually a placeholder) rather than silently picking one.
        """
        self._ensure_match_index()

        model_compatible = [
            t for t in self._structural_candidates(self.model_match_index, request) if self._compatible(t, request)
        ]
        ph_compatible = [
            t
            for t in self._structural_candidates(self.placeholder_match_index, request)
            if self._compatible(t, request)
        ]

        tiers = (
            ([t for t in model_compatible if self._declares_concrete_profile(t)], "exact"),
            ([t for t in model_compatible if not self._declares_concrete_profile(t)], "generic_profile"),
            ([t for t in ph_compatible if self._declares_concrete_profile(t)], "placeholder"),
            ([t for t in ph_compatible if not self._declares_concrete_profile(t)], "placeholder"),
        )

        for candidates, status in tiers:
            winner, ambiguous, ids = self._rank_tier(candidates)
            if winner is not None:
                return HVACTypeSelection(library_id=self.id, type_def=winner, status=status, reason="", candidates=ids)
            if ambiguous:
                reason = (
                    "Ambiguous type selection in library '{}' for category={!r} topology={!r} "
                    "family={!r} profile={!r}: candidates {} tie at the same priority".format(
                        self.id, request.category, request.topology, request.family, request.profile, ids
                    )
                )
                if strict:
                    return HVACTypeSelection(
                        library_id=self.id, type_def=None, status="ambiguous", reason=reason, candidates=ids
                    )
                FreeCAD.Console.PrintWarning("HVAC - " + reason + "\n")
                # Fall through to the next (broader) tier rather than
                # silently picking one of the tied candidates.

        return HVACTypeSelection(
            library_id=self.id,
            type_def=None,
            status="not_found",
            reason=(
                "No compatible model or placeholder type found in library '{}' for "
                "category={!r} topology={!r} family={!r} profile={!r}".format(
                    self.id, request.category, request.topology, request.family, request.profile
                )
            ),
        )

    def matches_type(self, type_def, request: HVACTypeMatchRequest) -> bool:
        """Does this already-selected type remain valid for `request`?"""
        if type_def is None:
            return False
        return self._compatible(type_def, request)


class HVACLibraryRegistry:
    """
    Owns every loaded HVACLibrary and is the single entry point the rest of
    the addon calls into: loading libraries from disk, type selection, and
    dispatching to a type's geometry/loss backend.
    """

    def __init__(self):
        self._libraries = {}
        self._active_library_id = None
        self._loaded = False
        self._search_paths = []

    def clear(self):
        self._libraries = {}
        self._active_library_id = None
        self._loaded = False

    def register_library(self, library: HVACLibrary):
        self._libraries[library.id] = library
        if self._active_library_id is None:
            self._active_library_id = library.id

    def get_library(self, library_id: str):
        return self._libraries.get(library_id)

    def list_libraries(self):
        return list(self._libraries.values())

    def set_active_library(self, library_id: str):
        if library_id in self._libraries:
            self._active_library_id = library_id
            return True
        return False

    def get_active_library(self):
        if self._active_library_id is None:
            return None
        return self._libraries.get(self._active_library_id)

    def resolve_type(self, library_id: str, type_id: str):
        """Exact TypeId lookup. Never fuzzy -- geometry execution relies on this."""
        lib = self.get_library(library_id)
        if lib is None:
            return None
        return lib.get_type(type_id)

    def select_type(self, library_id: str, request: HVACTypeMatchRequest, strict=False) -> HVACTypeSelection:
        """Automatic selection: choose the best compatible type in `library_id`."""
        lib = self.get_library(library_id)
        if lib is None:
            return HVACTypeSelection(
                library_id=library_id,
                type_def=None,
                status="not_found",
                reason="Unknown HVAC library '{}'".format(library_id),
            )
        return lib.select_type(request, strict=strict)

    def matches_type(self, library_id: str, type_id: str, request: HVACTypeMatchRequest) -> bool:
        """Compatibility check: does `type_id` in `library_id` remain valid for `request`?"""
        lib = self.get_library(library_id)
        if lib is None:
            return False
        return lib.matches_type(lib.get_type(type_id), request)

    def list_inline_types(self, library_id: str, topology=None, profile=None):
        """See HVACLibrary.list_inline_types."""
        lib = self.get_library(library_id)
        if lib is None:
            return []
        return lib.list_inline_types(topology=topology, profile=profile)

    def resolve_sticky_type(
        self, library_id: str, current_type_id: str, request: HVACTypeMatchRequest, strict=False
    ) -> HVACTypeSelection:
        """
        Normal (non-reset) synchronization policy:

            current TypeId exists, resolves in library_id, is not a
            placeholder, and remains compatible with `request`?
                -> retain it (status="retained")
            otherwise
                -> automatic selection (select_type)

        Placeholders are deliberately never retained here -- they're
        re-evaluated every sync so they can upgrade to a real model.

        An "inline"-kind current type (a damper/VAV/...) IS retained here
        if the user manually picked it as this component's Primary type via
        the "change type" editor (list_types() includes inline types for
        that manual picker, unlike select_type()'s own automatic-selection
        indexes) -- sync must not silently discard a deliberate manual
        choice back to whatever select_type() would have auto-picked.
        select_type() itself still never returns an inline type fresh (see
        _rebuild_match_index), so one can only ever end up "retained" here,
        never freshly auto-selected.
        """
        lib = self.get_library(library_id)
        if lib is not None and current_type_id:
            current_type = lib.get_type(current_type_id)
            if current_type is not None:
                kind = getattr(current_type.selection, "kind", SELECTION_KIND_MODEL)
                if kind != SELECTION_KIND_PLACEHOLDER and lib.matches_type(current_type, request):
                    return HVACTypeSelection(
                        library_id=library_id,
                        type_def=current_type,
                        status="retained",
                        reason="Current type remains compatible",
                        candidates=(current_type_id,),
                    )

        return self.select_type(library_id, request, strict=strict)

    def import_generator(self, library_id: str, module_name: str):
        """
        Import the Python module a type-def names for its generator, trim
        measurement, loss or feature function.

        A plain name ("junctions") is a module inside the library's own
        generators_package. A name with the "shared:" prefix
        ("shared:losses") is one of the addon's shared fitting modules
        under library/fittings/ instead, so several libraries can use the
        same standard fitting code without each keeping a copy of it.
        """
        module_name = str(module_name or "")
        if module_name.startswith(SHARED_MODULE_PREFIX):
            shared_name = module_name[len(SHARED_MODULE_PREFIX) :]
            # Only a plain module name is allowed -- no dots or path parts.
            if not shared_name.isidentifier():
                raise ValueError("Invalid shared fitting module '{}'".format(module_name))
            return importlib.import_module("{}.{}".format(SHARED_FITTINGS_PACKAGE, shared_name))

        lib = self.get_library(library_id)
        if lib is None:
            raise ValueError("Unknown HVAC library '{}'".format(library_id))
        if not lib.generators_package:
            raise ValueError("HVAC library '{}' has no generators_package".format(library_id))
        full_module = "{}.{}".format(lib.generators_package, module_name)
        return importlib.import_module(full_module)

    def resolve_library_file(self, library_id: str, relative_path: str):
        lib = self.get_library(library_id)
        if lib is None:
            raise ValueError("Unknown HVAC library '{}'".format(library_id))
        root = os.path.realpath(lib.root_path)
        path = os.path.realpath(os.path.join(root, relative_path))
        if os.path.commonpath([root, path]) != root:
            raise ValueError("Library path escapes library root: '{}'".format(relative_path))
        return path

    def resolve_params(self, type_def: HVACTypeDef, obj=None, supplied=None):
        return validation.resolve_params(type_def, obj=obj, supplied=supplied)

    def _prepare_geometry_context(self, type_def: HVACTypeDef, context: dict):
        prepared = dict(context or {})
        prepared["hvac_api"] = HVACLibraryAPI
        prepared["hvac_api_version"] = HVACLibraryAPI.API_VERSION
        prepared["loss_api"] = HVACLossAPI
        prepared["loss_api_version"] = HVACLossAPI.API_VERSION
        # The type-def's own declared construction layers, in order -- so a
        # generator/PartScript can hand them straight to
        # HVACLibraryAPI.build_envelopes()/build_layered_geometry() without
        # reaching past the API into Library.py's own HVACTypeDef.
        prepared["construction_layers"] = list(getattr(type_def, "construction", []) or [])

        # The type's resolved property values: anything the caller supplied
        # (already resolved, or raw overrides) on top of the object's own
        # values and the type-def defaults. One key, "properties".
        supplied = dict(prepared.get("properties") or {})
        # The caller's FreeCAD object (contexts.CALLER_KEYS) is read here and
        # never handed on: library code sees only the documented keys.
        resolved = self.resolve_params(type_def, obj=prepared.pop("obj", None), supplied=supplied) or {}
        # Supplied values the type does not declare are passed through as given.
        prepared["properties"] = {**supplied, **resolved}
        validation.validate_context(type_def, prepared)
        return prepared

    def build_geometry(self, library_id: str, type_def: HVACTypeDef, context: dict):
        """
        Build a type's geometry by dispatching to whichever of the three
        supported geometry backends it declares: "partscript" (a Python
        script under the library), "static" (a pre-built BREP/STEP file
        plus a placement descriptor), or "generator" (a Python function,
        geometry.module / geometry.function). Whatever the backend returns
        ({"layers": {...}}, the one result form) is normalized here, once,
        into a real
        GeometryResult -- every caller downstream (DuctSegment/DuctComponent/
        DuctJunction) only ever sees a GeometryResult, never a raw dict.

        Each returned layer's `roles` is then stamped on from the type-def's
        own declared construction (matched by layer id) -- this is the one
        place a raw geometry dict and the type-def's construction defs are
        both in scope together, so it's where role vocabulary gets attached.
        """
        context = self._prepare_geometry_context(type_def, context)
        geometry = getattr(type_def, "geometry", None)
        backend = str(getattr(geometry, "backend", "") or "").lower()
        if not backend and type_def.generator_module and type_def.generator_function:
            # An HVACTypeDef built in code (not loaded from JSON, where the
            # backend is required) may name only its generator.
            backend = GEOMETRY_BACKEND_GENERATOR

        if backend == "partscript":
            from . import partscript_shapes

            script_path = self.resolve_library_file(library_id, geometry.file)
            raw = partscript_shapes.execute_partscript(script_path, context)
        elif backend == "static":
            from . import static_shapes

            descriptor_path = self.resolve_library_file(library_id, geometry.descriptor)
            raw = static_shapes.build_static_geometry(descriptor_path, context)
        elif backend == GEOMETRY_BACKEND_GENERATOR:
            # A Python function: geometry.module / geometry.function.
            module = self.import_generator(library_id, type_def.generator_module)
            func = getattr(module, type_def.generator_function)
            raw = func(context)
        else:
            raise ValueError("Type '{}' uses unsupported geometry backend '{}'".format(type_def.id, backend))

        result = geometry_result.normalize(raw)

        layer_defs_by_id = {ldef.id: ldef for ldef in getattr(type_def, "construction", []) or []}
        for layer_id, layer_geometry in result.layers.items():
            layer_def = layer_defs_by_id.get(layer_id)
            if layer_def is not None:
                layer_geometry.roles = list(layer_def.roles)

        self._build_features(library_id, type_def, context, result)

        return result

    def _build_features(self, library_id: str, type_def: HVACTypeDef, context: dict, result):
        """
        Second pass, after the backend's own layers are built and
        normalized: resolve and invoke each of the type-def's own declared
        construction.features generators, storing each enabled one's
        returned Part.Shape into result.features. A feature's own
        enabled_parameter/visible_parameter/parameters only ever reference
        property names already resolved into context["properties"] by
        _prepare_geometry_context() above -- no second parameter
        resolution, per the "existing parameter system, unchanged" rule.

        Unlike geometry backends (partscript/static/legacy generator, one
        per type, declared via type_def.geometry/generator_module), feature
        generators default to one fixed, conventional module --
        <library's generators_package>.features -- resolved the same way
        generator_module/loss_module already are (import_generator()), so a
        PartScript-backed type (which has no generator_module of its own)
        still has a well-defined place for its own feature generators. A
        feature can override this default via its own "module" JSON key
        (ConstructionFeatureDef.module), exactly like "loss" already lets a
        type-def point at any module for its own loss function -- imported
        modules are cached per name here so several features sharing (or
        not sharing) a module each only get imported once per call.
        """
        feature_defs = getattr(type_def, "features", None) or []
        if not feature_defs:
            return

        params = dict(context.get("properties", {}) or {})
        modules_by_name = {}

        for feature_def in feature_defs:
            enabled = True
            if feature_def.enabled_parameter:
                enabled = bool(params.get(feature_def.enabled_parameter, True))
            if not enabled:
                continue

            host_layer_geometry = result.layers.get(feature_def.host_layer)
            if host_layer_geometry is None:
                raise ValueError(
                    "Feature '{}' on type '{}' references host_layer '{}', which this "
                    "type's geometry backend never returned".format(feature_def.id, type_def.id, feature_def.host_layer)
                )

            visible = True
            if feature_def.visible_parameter:
                visible = bool(params.get(feature_def.visible_parameter, True))

            feature_params = {name: params.get(name) for name in feature_def.parameters}

            ctx = FeatureContext(
                parameters=feature_params,
                host_layer=host_layer_geometry,
                context=context,
                host_layer_id=feature_def.host_layer,
                result=result,
            )

            module_name = feature_def.module or "features"
            features_module = modules_by_name.get(module_name)
            if features_module is None:
                features_module = self.import_generator(library_id, module_name)
                modules_by_name[module_name] = features_module
            generator_func = getattr(features_module, feature_def.generator)

            shape = generator_func(HVACLibraryAPI, ctx)

            result.features[feature_def.id] = geometry_result.FeatureGeometry(
                shape=shape, role=feature_def.role, visible=visible
            )

    def call_generator(self, library_id: str, type_def: HVACTypeDef, context: dict):
        return self.build_geometry(library_id, type_def, context)

    def measure_connection_lengths(self, library_id: str, type_def: HVACTypeDef, context: dict):
        """
        Call a type's optional, independently-declared connection-length
        measurement function (JSON `"connection_lengths": {"module": ...,
        "function": ...}`, parsed onto HVACTypeDef.lengths_module/
        lengths_function) -- a lightweight pre-build trim measurement that
        must NOT construct final geometry, so junction/component
        composition (DuctJunction._peekConnectionLengths) can learn a
        component's own per-port trims without building and discarding a
        full Shape first.

        Uses the exact same context preparation/parameter resolution as
        build_geometry() (_prepare_geometry_context()) -- there is no
        separate, possibly-diverging context-building path for
        measurement -- then dispatches type_def.lengths_module/
        lengths_function the same way build_geometry() dispatches
        generator_module/generator_function.

        Returns the standard connection-length record list
        ([{"edge_key", "segment_end", "length"}, ...], normalized/
        validated by _normalize_connection_lengths() -- see that method),
        or None if the type declares no connection_lengths function at all
        (caller should fall back to reading GeometryResult.
        connection_lengths off a full build_geometry() call instead --
        this is the one legitimate "nothing declared" signal, the same
        convention call_loss() already uses for a type with no loss
        function wired up).
        """
        if not type_def.lengths_module or not type_def.lengths_function:
            return None
        context = self._prepare_geometry_context(type_def, context)
        module = self.import_generator(library_id, type_def.lengths_module)
        func = getattr(module, type_def.lengths_function, None)
        if func is None:
            raise ValueError(
                "Type '{}' declares connection_lengths function '{}' in module '{}', but it wasn't found there".format(
                    type_def.id, type_def.lengths_function, type_def.lengths_module
                )
            )
        raw = func(context)
        return self.normalize_connection_lengths(raw, type_def.id)

    # Tiny negative floating-point noise (e.g. -1e-9 mm from a geometric
    # calculation that should have landed on exactly 0.0) is expected and
    # clamped away below; anything beyond this is a real bug in the
    # library's own layout math, not noise.
    _NEGATIVE_LENGTH_TOLERANCE_MM = 1e-6

    @classmethod
    def normalize_connection_lengths(cls, raw, type_id):
        """
        Normalize a connection-length result -- from either
        measure_connection_lengths()'s own lengths_function or a geometry
        backend's GeometryResult.connection_lengths -- into the one
        standard record shape every caller (DuctJunction, DuctComponent)
        already expects: [{"edge_key": str, "segment_end": str | None,
        "length": float}, ...]. The one place this gets validated, so
        neither DuctJunction.py nor a library backend needs its own ad hoc
        checking (see DuctJunction._peekConnectionLengths(), which routes
        both its measurement and its geometry-fallback path through this
        same method).
        """
        if raw is None:
            return []
        try:
            entries = list(raw)
        except TypeError:
            raise ValueError(
                "Type '{}': connection-length result must be a list of records, got {}".format(
                    type_id, type(raw).__name__
                )
            )

        out = []
        for entry in entries:
            edge_key = entry.get("edge_key") if hasattr(entry, "get") else None
            if not edge_key:
                raise ValueError("Type '{}': a connection-length record is missing 'edge_key'".format(type_id))
            segment_end = entry.get("segment_end")
            raw_length = entry.get("length", 0.0)
            try:
                length = float(raw_length)
            except (TypeError, ValueError):
                raise ValueError(
                    "Type '{}': connection-length record for '{}' has a non-numeric length {!r}".format(
                        type_id, edge_key, raw_length
                    )
                )
            if length < 0.0:
                if length < -cls._NEGATIVE_LENGTH_TOLERANCE_MM:
                    raise ValueError(
                        "Type '{}': connection-length record for '{}' is materially negative ({} mm)".format(
                            type_id, edge_key, length
                        )
                    )
                length = 0.0
            out.append({"edge_key": str(edge_key), "segment_end": segment_end, "length": length})
        return out

    def call_loss(self, library_id: str, type_def: HVACTypeDef, context: dict):
        """
        Call the type's optional fitting-loss function. Returns an
        analysis.loss.LossEvaluation: a list of LossPath entries (each a
        directed from_edge_key -> to_edge_key flow path, referenced to
        `reference_edge_key`'s own velocity) plus an overall LossStatus
        (EXACT/APPROXIMATION/CUSTOM/FALLBACK/UNSUPPORTED) and an optional
        warning. UNSUPPORTED (empty paths) means the type's loss function
        found no formula for the current flow topology (caller should apply
        a fallback coefficient) -- see library/loss_api.py's own docstring
        for the full shape and library/junction_losses.py generator files
        for how a type's own loss function builds one.

        When the type-def declares `loss.variants` (flow-dependent loss
        formulas for one physical fitting -- see HVACLossVariantDef), the
        actual module/function are picked per-call by
        validation.resolve_loss_variant() from the current classification
        context (`context["flow_class"]`/`"qualifiers"`/`"derived_values"`,
        the same shape context_violations() reads); a plain type-def
        without variants keeps using loss_module/loss_function unchanged.
        """
        loss_module, loss_function = validation.resolve_loss_variant(type_def, context)
        if not loss_module or not loss_function:
            return None
        module = self.import_generator(library_id, loss_module)
        func = getattr(module, loss_function, None)
        if func is None:
            return None
        context["hvac_api"] = HVACLibraryAPI
        context["hvac_api_version"] = HVACLibraryAPI.API_VERSION
        context["loss_api"] = HVACLossAPI
        context["loss_api_version"] = HVACLossAPI.API_VERSION
        return func(context)

    def call_friction(self, library_id: str, type_def: HVACTypeDef, context: dict):
        """
        Call a segment type's friction model factory, or return None when
        the type declares none. The factory gets `context` (`properties`,
        `roughness_mm`, `base_model` -- the network's own model, which
        a factory can scale or wrap -- and `friction`, the
        analysis.friction module) and returns a friction model: anything
        with `rate_pa_per_m(flow_m3_s, area_m2, dh_m, roughness_m,
        density_kg_m3, kinematic_viscosity_m2_s)`.
        """
        if not type_def.friction_module or not type_def.friction_function:
            return None
        module = self.import_generator(library_id, type_def.friction_module)
        func = getattr(module, type_def.friction_function, None)
        if func is None:
            raise ValueError(
                "Type '{}': friction function '{}' not found in '{}'".format(
                    type_def.id, type_def.friction_function, type_def.friction_module
                )
            )
        from ..analysis import friction as friction_models

        context["friction"] = friction_models
        return func(context)

    def set_search_paths(self, paths):
        self._search_paths = [p for p in (paths or []) if p]

    def add_search_path(self, path):
        if path and path not in self._search_paths:
            self._search_paths.append(path)

    def ensure_loaded(self):
        """Load libraries once, on first use -- a no-op on every call after the first."""
        if self._loaded:
            return

        self.scan_paths()

        if not self._libraries:
            FreeCAD.Console.PrintError("HVAC - No HVAC libraries found in configured search paths.\n")

        self._loaded = True

    def scan_paths(self):
        """Forget every previously-loaded library and scan all search paths again from scratch."""
        self._libraries = {}
        self._active_library_id = None

        for root in self._search_paths:
            self.scan_path(root)

    def scan_path(self, root_path):
        """Treat every subfolder of root_path as one candidate library and try to load it."""
        if not root_path or not os.path.isdir(root_path):
            return

        for entry in sorted(os.listdir(root_path)):
            lib_dir = os.path.join(root_path, entry)
            if not os.path.isdir(lib_dir):
                continue
            try:
                lib = self.load_library_from_folder(lib_dir)
                if lib is not None:
                    self.register_library(lib)
            except Exception as e:
                # One bad library shouldn't block the others from loading.
                FreeCAD.Console.PrintWarning("HVAC - Failed to load library from '{}': {}\n".format(lib_dir, e))

    def reload(self):
        self._loaded = False
        self.ensure_loaded()

    @staticmethod
    def _check_required_api(lib_id, manifest):
        """
        Refuse a library written for another API version: library.json may
        say `"requires_api": {"geometry": N, "loss": M}`, the
        HVACLibraryAPI / HVACLossAPI API_VERSION it was written against.
        """
        required = dict(manifest.get("requires_api") or {})
        running = {"geometry": HVACLibraryAPI.API_VERSION, "loss": HVACLossAPI.API_VERSION}
        for key, version in required.items():
            if key not in running:
                raise ValueError("Library '{}': unknown requires_api key '{}'".format(lib_id, key))
            if int(version) != int(running[key]):
                raise ValueError(
                    "Library '{}' was written for the {} API version {}, this addon provides version {}".format(
                        lib_id, key, version, running[key]
                    )
                )

    def load_library_from_folder(self, lib_dir):
        """Load one library from a folder: its library.json manifest, then every type-def under type_roots."""
        manifest_path = os.path.join(lib_dir, "library.json")
        if not os.path.isfile(manifest_path):
            return None

        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        lib_id = manifest["id"]
        label = manifest.get("label", lib_id)
        self._check_required_api(lib_id, manifest)
        generators_package = manifest.get("generators_package", "")
        type_roots = manifest.get("type_roots", ["types"])
        default_construction = self._parse_construction_layers(
            (manifest.get("default_construction", {}) or {}).get("layers", [])
        )

        library = HVACLibrary(
            id=lib_id,
            label=label,
            root_path=lib_dir,
            generators_package=generators_package,
            default_construction=default_construction,
        )

        for rel_root in type_roots:
            abs_root = os.path.join(lib_dir, rel_root)
            self._load_type_defs_from_tree(abs_root, library)

        return library

    def _load_type_defs_from_tree(self, root_dir, library):
        """Recursively load every *.json type-def file under root_dir into library."""
        if not os.path.isdir(root_dir):
            return

        for dirpath, _, filenames in os.walk(root_dir):
            for fn in filenames:
                if not fn.lower().endswith(".json"):
                    continue
                fpath = os.path.join(dirpath, fn)
                type_def = self._load_type_def_file(fpath)
                if not type_def.construction:
                    type_def.construction = [
                        ConstructionLayerDef(
                            id=layer.id,
                            roles=list(layer.roles),
                            default_material_role=layer.default_material_role,
                            default_material_uuid=layer.default_material_uuid,
                            thickness_property=layer.thickness_property,
                        )
                        for layer in library.default_construction
                    ]
                library.add_type(type_def)

    @staticmethod
    def _check_known_constraint_keys(constraints, type_id, filepath, label):
        """
        Raise ValueError if `constraints` (a type-def's own top-level
        "constraints", or one loss variant's own "constraints") references
        an unrecognized qualifier or derived_values key -- see
        validation.unknown_flow_constraint_keys(). Without this, a typo'd
        key (e.g. "aera_ratio") would silently become a permanent no-op
        constraint instead of failing at load time.
        """
        unknown_qualifiers, unknown_top_level = validation.unknown_flow_constraint_keys(constraints)
        if not unknown_qualifiers and not unknown_top_level:
            return
        parts = []
        if unknown_qualifiers:
            parts.append("unknown qualifier key(s) {}".format(unknown_qualifiers))
        if unknown_top_level:
            parts.append("unknown constraint key(s) {}".format(unknown_top_level))
        raise ValueError(
            "Type '{}' in '{}' has {} in its own '{}'".format(type_id, filepath, " and ".join(parts), label)
        )

    @staticmethod
    def _parse_construction_layers(layers_raw):
        return [
            ConstructionLayerDef(
                id=layer_raw["id"],
                roles=list(layer_raw.get("roles", []) or []),
                default_material_role=layer_raw.get("default_material_role"),
                default_material_uuid=layer_raw.get("default_material_uuid"),
                thickness_property=layer_raw.get("thickness_property"),
            )
            for layer_raw in (layers_raw or [])
        ]

    def _load_type_def_file(self, filepath):
        """Parse one type-def JSON file into an HVACTypeDef -- a plain field-by-field mapping."""
        with open(filepath, "r", encoding="utf-8") as f:
            raw = json.load(f)

        props = []
        for p in raw.get("properties", []) or []:
            # Reject keys nothing reads, so a typo can't become a rule that is never enforced.
            unknown_keys = validation.unknown_property_def_keys(p)
            if unknown_keys:
                raise ValueError(
                    "Type-def '{}': property '{}' has unknown key(s) {}".format(
                        filepath, p.get("name", "?"), ", ".join(unknown_keys)
                    )
                )
            props.append(
                HVACPropertyDef(
                    name=p["name"],
                    prop_type=p["prop_type"],
                    group=p.get("group", "HVAC"),
                    description=p.get("description", ""),
                    default=p.get("default", None),
                    editor_mode=int(p.get("editor_mode", 0)),
                    required=bool(p.get("required", True)),
                    validation=dict(p.get("validation", {}) or {}),
                    per_port=bool(p.get("per_port", False)),
                )
            )
            if props[-1].prop_type == "App::PropertyEnumeration" and not props[-1].validation.get("enum"):
                raise ValueError(
                    "Type-def '{}': enumeration property '{}' needs its choices in validation.enum".format(
                        filepath, props[-1].name
                    )
                )
            if props[-1].per_port and props[-1].prop_type not in validation.PER_PORT_LIST_TYPES:
                raise ValueError(
                    "Type-def '{}': property '{}' is per_port, which is not supported for {} (only {})".format(
                        filepath, props[-1].name, props[-1].prop_type, ", ".join(sorted(validation.PER_PORT_LIST_TYPES))
                    )
                )

        if "generator" in raw:
            raise ValueError(
                "Type '{}' in '{}': the top-level 'generator' key was replaced by "
                '"geometry": {{"backend": "generator", "module": ..., "function": ...}}'.format(raw.get("id", "?"), filepath)
            )
        gen = {}
        lengths = raw.get("connection_lengths", {}) or {}
        loss = raw.get("loss", {}) or {}
        friction = raw.get("friction", {}) or {}
        if friction and not (friction.get("module") and friction.get("function")):
            raise ValueError("Type '{}' in '{}' has a friction entry with no module/function".format(raw.get("id", "?"), filepath))

        constraints = dict(raw.get("constraints", {}) or {})
        self._check_known_constraint_keys(constraints, raw.get("id", "?"), filepath, "constraints")

        loss_variants = []
        for index, variant_raw in enumerate(loss.get("variants", []) or []):
            variant_module = variant_raw.get("module", "")
            variant_function = variant_raw.get("function", "")
            if not variant_module or not variant_function:
                raise ValueError(
                    "Type '{}' in '{}' has a loss variant with no module/function".format(raw.get("id", "?"), filepath)
                )
            variant_constraints = dict(variant_raw.get("constraints", {}) or {})
            self._check_known_constraint_keys(
                variant_constraints, raw.get("id", "?"), filepath, "loss.variants[{}].constraints".format(index)
            )
            loss_variants.append(
                HVACLossVariantDef(constraints=variant_constraints, module=variant_module, function=variant_function)
            )

        geometry_raw = raw.get("geometry", {}) or {}
        backend = str(geometry_raw.get("backend", "") or "")
        if backend not in VALID_GEOMETRY_BACKENDS:
            raise ValueError(
                "Type '{}' in '{}' needs geometry.backend, one of {}".format(
                    raw.get("id", "?"), filepath, ", ".join(sorted(VALID_GEOMETRY_BACKENDS))
                )
            )
        if backend == GEOMETRY_BACKEND_GENERATOR:
            gen = {"module": geometry_raw.get("module", ""), "function": geometry_raw.get("function", "")}
            if not gen["module"] or not gen["function"]:
                raise ValueError(
                    "Type '{}' in '{}': a generator backend needs module and function".format(raw.get("id", "?"), filepath)
                )
        geometry = HVACGeometryDef(
            backend=backend,
            file=geometry_raw.get("file", ""),
            descriptor=geometry_raw.get("descriptor", ""),
        )

        family = raw["family"]
        if isinstance(family, str):
            family = [family]

        selection_raw = raw.get("selection", {}) or {}
        selection_kind = str(selection_raw.get("kind", SELECTION_KIND_MODEL) or SELECTION_KIND_MODEL)
        if selection_kind not in VALID_SELECTION_KINDS:
            raise ValueError(
                "Type '{}' in '{}' has invalid selection.kind '{}'; expected one of {}".format(
                    raw.get("id", "?"), filepath, selection_kind, sorted(VALID_SELECTION_KINDS)
                )
            )
        selection = HVACSelectionDef(kind=selection_kind, priority=int(selection_raw.get("priority", 0) or 0))

        flow_boundary = str(raw.get("flow_boundary", "") or "")
        if flow_boundary not in VALID_FLOW_BOUNDARIES:
            raise ValueError(
                "Type '{}' in '{}' has invalid flow_boundary '{}'; expected one of {}".format(
                    raw.get("id", "?"), filepath, flow_boundary, sorted(VALID_FLOW_BOUNDARIES)
                )
            )
        flow_boundary_locked = bool(raw.get("flow_boundary_locked", False))

        # "construction" is an object with its own "layers"/"features"
        # arrays (see docs/type-def-reference.md's "Construction
        # layers"/"Construction features" sections) -- both optional, a
        # type-def with no "construction" block at all keeps behaving as a
        # single, roleless implicit layer with no features.
        construction_raw = raw.get("construction", {}) or {}

        construction = self._parse_construction_layers(construction_raw.get("layers", []))

        features = []
        for feature_raw in construction_raw.get("features", []) or []:
            features.append(
                ConstructionFeatureDef(
                    id=feature_raw["id"],
                    role=feature_raw.get("role", ""),
                    host_layer=feature_raw.get("host_layer", ""),
                    module=feature_raw.get("module", ""),
                    generator=feature_raw.get("generator", ""),
                    enabled_parameter=feature_raw.get("enabled_parameter"),
                    visible_parameter=feature_raw.get("visible_parameter"),
                    parameters=list(feature_raw.get("parameters", []) or []),
                )
            )

        return HVACTypeDef(
            id=raw["id"],
            label=raw.get("label", raw["id"]),
            category=raw["category"],
            topology=raw.get("topology", "generic"),
            family=family,
            profiles=list(raw.get("profiles", []) or []),
            constraints=constraints,
            properties=props,
            geometry=geometry,
            generator_module=gen.get("module", ""),
            generator_function=gen.get("function", ""),
            lengths_module=lengths.get("module", ""),
            lengths_function=lengths.get("function", ""),
            loss_module=loss.get("module", ""),
            loss_function=loss.get("function", ""),
            loss_variants=loss_variants,
            friction_module=friction.get("module", ""),
            friction_function=friction.get("function", ""),
            selection=selection,
            construction=construction,
            features=features,
            flow_boundary=flow_boundary,
            flow_boundary_locked=flow_boundary_locked,
        )
