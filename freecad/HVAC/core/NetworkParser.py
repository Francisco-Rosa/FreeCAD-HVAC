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

from dataclasses import dataclass
import math

import FreeCAD, Part

from ..utils import hvaclib
from ..utils.hvaclib import (
    isWire,
    isSketch,
    vec_to_xyz,
    nx
)


@dataclass(frozen=True)
class EdgeRef:
    """Stable reference to an edge created from (obj_name, local_line_index)."""
    obj_name: str
    local_index: int
    tag: str

@dataclass
class JunctionPort:
    """
    Generic junction port descriptor.

    edge_key : stable segment key, e.g. "Sketch001:0"

    segment_end:
        "start" or "end" relative to the connected segment.

    direction:
        Unit vector pointing away from the junction along the segment.
        This is geometric port direction, not necessarily flow direction.

    flow_role:
        "inlet"  -> flow enters this junction through this port.
        "outlet" -> flow leaves this junction through this port.
        "unknown" -> direction could not be resolved.

    flow_direction:
        Unit vector in actual flow direction at this port.

    flow_into_junction:
        True  -> flow enters junction.
        False -> flow leaves junction.
        None  -> unknown.
    """

    edge_key: str
    segment_end: str
    position: tuple
    direction: tuple

    profile: str
    section_params: dict
    attachment: str
    user_offset: tuple
    profile_x_axis: tuple | None = None

    flow_role: str = "unknown"
    flow_direction: tuple | None = None
    flow_into_junction: bool | None = None
    
@dataclass
class EdgePair:
    """Represents a connection relationship (collinear or orthogonal)."""
    a: int
    b: int
    angle: float
    eccentricity: float
    
@dataclass
class NodeAnalysis:
    # Reference
    node_id: int
    node_key: str
    member_ids: list[int]
    member_points: list[tuple[float, float, float]]
    edge_refs: list[EdgeRef]
    connected_ports: list[JunctionPort]
    # Basic geometric data
    point: tuple[float, float, float]  # Representative XYZ coordinates
    degree: int
    port_origins: list[tuple[float, float, float]]
    edge_vectors: list[tuple[float, float, float]]
    edge_angles: dict[str, float] # (e1, e2): angle)
    edge_eccentricities: dict[str, float] # (e1, e2): eccentricity
    # Derived geometric data
    collinear_pairs: list[EdgePair]
    orthogonal_pairs: list[EdgePair]
    is_coplanar: bool
    
@dataclass
class JunctionAnalysis:
    topology: str
    family: str
    family_tags: list[str]
    family_key: str
    # Flow classification: independent of topology/family/family_key, derived
    # purely from base-segment orientation (JunctionPort.flow_role/
    # flow_direction), never from the hydraulic solver -- see
    # classify_flow()/TOPOLOGY_CLASSIFICATION.md.
    flow_class: str
    qualifiers: dict
    derived_values: dict
    connected_ports: list[JunctionPort]
    # Basic geometric data
    point: tuple[float, float, float]  # Representative XYZ coordinates
    degree: int
    port_origins: list[tuple[float, float, float]]
    edge_vectors: list[tuple[float, float, float]]
    edge_angles: dict[str, float] # (e1, e2): angle)
    edge_eccentricities: dict[str, float] # (e1, e2): eccentricity
    # Derived geometric data
    collinear_pairs: list[EdgePair]
    orthogonal_pairs: list[EdgePair]
    is_coplanar: bool


class DuctNetworkParser:
    """
    Parse duct base geometry into two graph layers:

    1. Geometric graph
       Built directly from actual line endpoints.
       Nodes in this graph are snapped geometric endpoints.

    2. Analysis graph
       Built from the geometric graph after applying optional node groups.
       A node group collapses multiple geometric nodes into one analysis node
       (supernode) for topology / junction analysis.

    Important:
    - Segment geometry still comes from the geometric graph.
    - Connectivity / degree / junction classification uses the analysis graph.
    """

    def __init__(self, objs=None, node_groups=None):
        
        self.tol = 1e-6
        self.angle_tol_degree = 2.0
        
        # ------------------------------------------------------------------
        # Raw extracted line storage
        # ------------------------------------------------------------------
        self.lines_map = {}   # obj_name -> [(sp, ep, tag), ...]
        self.all_lines = []   # [(sp, ep, tag), ...]

        # ------------------------------------------------------------------
        # Geometric graph storage
        # These represent actual snapped geometric endpoints.
        # ------------------------------------------------------------------
        self.node_id_by_key = {}   # snapped point key -> geometric node id
        self.node_point = {}       # geometric node id -> xyz tuple
        self.edge_u_v = {}         # edge_ref -> (geom_u, geom_v)
        self.edge_geom = {}        # edge_ref -> (sp, ep)
        self.obj_edges = {}        # obj_name -> [edge_ref, ...]

        self.graph = None          # networkx graph on geometric nodes

        # ------------------------------------------------------------------
        # Analysis graph storage
        # These are grouped "supernodes" used for logical connectivity.
        # ------------------------------------------------------------------
        self.node_groups_input = list(node_groups or [])

        self.analysis_node_by_geom_node = {}   # geometric node id -> analysis node id
        self.analysis_node_members = {}        # analysis node id -> [geometric node ids]
        self.analysis_node_point = {}          # analysis node id -> representative xyz
        self.analysis_edge_u_v = {}          # edge_ref -> (analysis_u, analysis_v)

        self.analysis_graph = None             # networkx graph on analysis nodes

        # Build parser state
        if objs:
            self.compile_lines_from_objects(objs)
        self.build_graph()

    # ======================================================================
    # Basic point / node helpers
    # ======================================================================

    def _point_snap_key(self, point_xyz):
        """
        Return the snapped/quantized key used to merge nearby geometric points.
        """
        p = point_xyz
        t = self.tol
        return (
            int(round(p[0] / t)),
            int(round(p[1] / t)),
            int(round(p[2] / t)),
        )

    def _get_or_create_geometric_node_id(self, point_xyz):
        """
        Return the geometric node id for a point, creating one if needed.
        """
        snap_key = self._point_snap_key(point_xyz)
        node_id = self.node_id_by_key.get(snap_key)

        if node_id is None:
            node_id = len(self.node_id_by_key) + 1
            self.node_id_by_key[snap_key] = node_id
            self.node_point[node_id] = point_xyz

        return node_id

    def _get_analysis_members(self, analysis_node_id):
        """
        Return the geometric member nodes of an analysis node.

        In the normal grouped case, analysis_node_id will be found in
        self.analysis_node_members.

        As a fallback, if a geometric node id is passed directly, treat it as
        a singleton analysis node.
        """
        members = self.analysis_node_members.get(analysis_node_id)
        if members is not None:
            return list(members)
        return [analysis_node_id]

    def _find_edge_member_node_in_analysis_node(self, edge_ref, analysis_node_id):
        """
        For a given analysis node and edge, return the geometric member node
        inside that analysis node that the edge touches.

        Example:
            analysis node A groups geometric nodes [3, 7, 8]
            edge_ref touches node 7
            -> return 7
        """
        geom_u, geom_v = self.edge_nodes(edge_ref)
        member_set = set(self._get_analysis_members(analysis_node_id))

        if geom_u in member_set:
            return geom_u
        if geom_v in member_set:
            return geom_v
        return None

    def _get_edge_end_label_for_analysis_node(self, edge_ref, analysis_node_id):
        """
        Return:
            'start' if the local geometric member node is the edge start
            'end'   if the local geometric member node is the edge end
            ''      if the edge is not incident to the analysis node
        """
        member_geom_node = self._find_edge_member_node_in_analysis_node(
            edge_ref, analysis_node_id
        )
        if member_geom_node is None:
            return ""

        geom_start, geom_end = self.edge_nodes(edge_ref)

        if member_geom_node == geom_start:
            return "start"
        if member_geom_node == geom_end:
            return "end"
        return ""

    # ======================================================================
    # Line extraction from source objects
    # ======================================================================

    def _store_parsed_line(self, obj, sp, ep, tag, edge_no):
        """
        Store one parsed line under both:
        - per-object storage
        - global storage
        """
        obj_name = getattr(obj, "Name", None)
        if not obj_name:
            return

        self.lines_map.setdefault(obj_name, []).append((sp, ep, tag, edge_no))
        self.all_lines.append((sp, ep, tag, edge_no))
        
    def _iter_line_segments_from_sketch(self, sketch_obj, tol=1e-9):
        """
        Yield per-geometry path records for supported non-construction sketch
        geometries.
    
        Output tuple:
            (
                start_xyz,
                end_xyz,
                tag,
                path_json,
                start_dir_xyz,
                end_dir_xyz,
            )
        """
        geos = getattr(sketch_obj, "Geometry", []) or []
    
        for slno, geo in enumerate(geos):
            try:
                if sketch_obj.getConstruction(slno):
                    continue
            except Exception:
                pass
    
            sp = getattr(geo, "StartPoint", None)
            ep = getattr(geo, "EndPoint", None)
            if sp is None or ep is None:
                continue
    
            if (sp.sub(ep)).Length <= tol:
                continue
    
            tag = hvaclib.makeLineKey(sketch_obj.Name, slno)
    
            # Build a Part edge from sketch geometry
            kind = hvaclib.GeomType(geo)
            if kind == "Unknown":
                continue

            # Raises for geometry Part cannot turn into an edge, before it is used.
            Part.Edge(geo)
    
            yield (
                vec_to_xyz(sp),
                vec_to_xyz(ep),
                tag,
                slno
            )

    def _iter_line_segments_from_shape(self, obj, tol=1e-9):
        """
        Yield per-edge path records for supported shape edges.
    
        Output tuple:
            (
                start_xyz,
                end_xyz,
                tag,
                path_json,
                start_dir_xyz,
                end_dir_xyz,
            )
        """
        shape = getattr(obj, "Shape", None)
        if shape is None:
            return
    
        for slno, edge in enumerate(getattr(shape, "Edges", []) or []):
            curve = getattr(edge, "Curve", None)
            kind = hvaclib.GeomType(curve)
            if curve is None or kind == "Unknown":
                continue
    
            v1 = edge.Vertexes[0].Point
            v2 = edge.Vertexes[-1].Point
            if (v1.sub(v2)).Length <= tol:
                continue
    
            tag = hvaclib.makeLineKey(obj.Name, slno)
    
            yield (
                vec_to_xyz(v1),
                vec_to_xyz(v2),
                tag,
                slno
            )

    # ======================================================================
    # Public line compilation
    # ======================================================================

    def compile_lines_from_objects(self, objs):
        """
        Parse all supported source objects into line segments.
        """
        self.lines_map = {}
        self.all_lines = []

        for obj in objs:
            if isWire(obj):
                for sp, ep, tag, edge_no in self._iter_line_segments_from_shape(obj):
                    self._store_parsed_line(obj, sp, ep, tag, edge_no)

            elif isSketch(obj):
                for sp, ep, tag, edge_no in self._iter_line_segments_from_sketch(obj):
                    self._store_parsed_line(obj, sp, ep, tag, edge_no)

        return self.lines_map, self.all_lines

    # ======================================================================
    # Node group handling
    # ======================================================================

    def set_node_groups(self, node_groups):
        """
        Set user-defined node groups and rebuild only the analysis graph.

        Each group is a collection of geometric nodes that should behave as
        one logical supernode for connectivity analysis.

        Accepted group item formats:
        - geometric node ids
        - snapped node keys used in self.node_id_by_key
        """
        self.node_groups_input = list(node_groups or [])
        self._rebuild_analysis_graph_from_groups()

    def _resolve_group_entry_to_geometric_node(self, entry):
        """
        Resolve one group entry into a geometric node id.

        Supported:
        - int: direct geometric node id
        - snapped key present in self.node_id_by_key
        """
        if isinstance(entry, int):
            return entry if entry in self.node_point else None

        resolved = self.node_id_by_key.get(entry)
        if resolved is not None:
            return resolved

        return None

    def _normalize_and_merge_node_groups(self):
        """
        Convert raw input groups into clean merged groups of valid geometric nodes.

        Rules:
        - invalid entries are ignored
        - duplicate entries are removed
        - groups with < 2 valid nodes are discarded
        - overlapping groups are merged
        """
        raw_groups = []

        # Step 1: resolve raw entries to valid geometric node ids
        for group in self.node_groups_input:
            resolved_nodes = []
            for entry in (group or []):
                node_id = self._resolve_group_entry_to_geometric_node(entry)
                if node_id is not None:
                    resolved_nodes.append(node_id)

            # Remove duplicates within the group
            resolved_nodes = sorted(set(resolved_nodes))

            if len(resolved_nodes) >= 2:
                raw_groups.append(set(resolved_nodes))

        # Step 2: merge overlapping groups
        merged = list(raw_groups)
        for group in raw_groups:
            merged_into_existing = False

            for i, existing_group in enumerate(merged):
                if existing_group & group:
                    merged[i] = existing_group | group
                    merged_into_existing = True
                    break

            if not merged_into_existing:
                merged.append(set(group))

        # Step 3: repeat merge until no overlaps remain
        changed = True
        while changed:
            changed = False
            new_merged = []

            while merged:
                current = merged.pop()
                found_overlap = False

                for i, other in enumerate(merged):
                    if current & other:
                        merged[i] = current | other
                        found_overlap = True
                        changed = True
                        break

                if not found_overlap:
                    new_merged.append(current)

            merged = new_merged

        return [sorted(group) for group in merged]

    # ======================================================================
    # Graph building
    # ======================================================================

    def build_graph(self, tol=1e-6):
        """
        Build both parser graph layers:

        1. Geometric graph
           Based directly on actual snapped endpoints.

        2. Analysis graph
           Built from the geometric graph after collapsing user-defined node
           groups into supernodes.
        """
        self.tol = float(tol)

        # --------------------------------------------------------------
        # Reset geometric graph state
        # --------------------------------------------------------------
        self.node_id_by_key.clear()
        self.node_point.clear()
        self.edge_u_v.clear()
        self.edge_geom.clear()
        self.obj_edges.clear()

        geometric_graph = nx.Graph()

        # --------------------------------------------------------------
        # Build geometric graph from parsed lines
        # --------------------------------------------------------------
        for obj_name, lines in self.lines_map.items():
            for slno, (sp, ep, tag, edge_no) in enumerate(lines):
                geom_u = self._get_or_create_geometric_node_id(sp)
                geom_v = self._get_or_create_geometric_node_id(ep)

                edge_ref = EdgeRef(obj_name=obj_name, local_index=edge_no, tag=tag)

                self.edge_u_v[edge_ref] = (geom_u, geom_v)
                self.edge_geom[edge_ref] = (sp, ep)
                self.obj_edges.setdefault(obj_name, []).append(edge_ref)

                geometric_graph.add_edge(
                    geom_u, geom_v,
                    key=edge_ref,
                    obj=obj_name,
                    local_index=edge_no,
                    sp=sp,
                    ep=ep,
                )

        self.graph = geometric_graph

        # --------------------------------------------------------------
        # Build analysis graph from geometric graph + node groups
        # --------------------------------------------------------------
        self._rebuild_analysis_graph_from_groups()

        return geometric_graph

    def _rebuild_analysis_graph_from_groups(self):
        """
        Rebuild the analysis graph after applying node groups.

        Each geometric node maps to exactly one analysis node:
        - grouped nodes -> shared analysis node
        - ungrouped nodes -> singleton analysis node

        Edges internal to the same analysis node are ignored in the analysis
        graph, because they do not contribute to junction connectivity.
        """
        # Reset analysis structures
        self.analysis_node_by_geom_node.clear()
        self.analysis_node_members.clear()
        self.analysis_node_point.clear()
        self.analysis_edge_u_v.clear()

        next_analysis_node_id = 1
        grouped_geom_nodes = set()

        # --------------------------------------------------------------
        # Step 1: create analysis nodes for declared groups
        # --------------------------------------------------------------
        for members in self._normalize_and_merge_node_groups():
            analysis_node_id = next_analysis_node_id
            next_analysis_node_id += 1

            self.analysis_node_members[analysis_node_id] = list(members)

            for geom_node_id in members:
                self.analysis_node_by_geom_node[geom_node_id] = analysis_node_id
                grouped_geom_nodes.add(geom_node_id)

        # --------------------------------------------------------------
        # Step 2: create singleton analysis nodes for ungrouped geom nodes
        # --------------------------------------------------------------
        for geom_node_id in sorted(self.node_point.keys()):
            if geom_node_id in grouped_geom_nodes:
                continue

            analysis_node_id = next_analysis_node_id
            next_analysis_node_id += 1

            self.analysis_node_members[analysis_node_id] = [geom_node_id]
            self.analysis_node_by_geom_node[geom_node_id] = analysis_node_id

        # --------------------------------------------------------------
        # Step 3: compute representative point for each analysis node
        # --------------------------------------------------------------
        for analysis_node_id, members in self.analysis_node_members.items():
            pts = [FreeCAD.Vector(*self.node_point[n]) for n in members]
            if not pts:
                continue

            centroid = FreeCAD.Vector(0, 0, 0)
            for p in pts:
                centroid = centroid + p

            centroid = centroid * (1.0 / float(len(pts)))
            self.analysis_node_point[analysis_node_id] = vec_to_xyz(centroid)

        # --------------------------------------------------------------
        # Step 4: build analysis graph edges
        # --------------------------------------------------------------
        analysis_graph = nx.Graph()

        for edge_ref, (geom_u, geom_v) in self.edge_u_v.items():
            analysis_u = self.analysis_node_by_geom_node.get(geom_u, geom_u)
            analysis_v = self.analysis_node_by_geom_node.get(geom_v, geom_v)

            self.analysis_edge_u_v[edge_ref] = (analysis_u, analysis_v)

            # Ignore internal edges within the same grouped node
            if analysis_u == analysis_v:
                continue

            analysis_graph.add_edge(
                analysis_u, analysis_v,
                key=edge_ref,
                obj=edge_ref.obj_name,
                local_index=edge_ref.local_index,
            )

        self.analysis_graph = analysis_graph
        return analysis_graph

    # ======================================================================
    # Junction port creation
    # ======================================================================

    def build_junction_ports(self, analysis_node_id, edge_refs, segment_map=None):
        """
        Build generic junction ports for an analysis node.
    
        For grouped analysis nodes:
        - one logical analysis node may represent multiple geometric points
        - each incident edge still uses its own actual geometric member point
    
        This keeps topology logical while keeping port placement geometric.
        """
        ports = []
        segment_map = segment_map or {}
    
        for edge_ref in edge_refs:
            edge_key = edge_ref.tag
    
            # ----------------------------------------------------------
            # Find which geometric member of the group this edge touches
            # ----------------------------------------------------------
            member_geom_node = self._find_edge_member_node_in_analysis_node(
                edge_ref, analysis_node_id
            )
            if member_geom_node is None:
                continue
    
            # ----------------------------------------------------------
            # Determine whether this node touches the start or end of edge
            # ----------------------------------------------------------
            segment_end = self._get_edge_end_label_for_analysis_node(
                edge_ref, analysis_node_id
            )
            if segment_end not in ("start", "end"):
                continue
    
            # ----------------------------------------------------------
            # Use the actual geometric member point as local port origin
            # ----------------------------------------------------------
            member_point = FreeCAD.Vector(*self.node_point[member_geom_node])
    
            sp, ep = self.edge_line(edge_ref)
            sp_vec = FreeCAD.Vector(*sp)
            ep_vec = FreeCAD.Vector(*ep)
            
            if segment_end == "start":
                other_point = ep_vec
            else:
                other_point = sp_vec

            direction_from_port = other_point - member_point
            direction_along_segment = ep_vec - sp_vec

            if direction_from_port.Length <= 1e-9:
                continue

            direction_from_port.normalize()
            
            # ----------------------------------------------------------
            # Read segment properties if the segment object is available
            # ----------------------------------------------------------
            seg_obj = segment_map.get(edge_key)
            if seg_obj:
                section_params = hvaclib.get_segment_section_params(seg_obj)
                profile = getattr(seg_obj, "Profile", "")
                attachment = getattr(seg_obj, "Attachment", "Center")
                user_offset = getattr(seg_obj, "Offset", FreeCAD.Vector(0, 0, 0))
                profile_x_axis = getattr(seg_obj, "ProfileXAxis", FreeCAD.Vector(0, 0, 0))
                
                # Override port directions from curve tangent
                edge = seg_obj.Proxy.resolveSourceEdge()
                if edge:
                    edge_info = hvaclib.parse_edge_info(edge)
                    if segment_end == "start":
                        direction_from_port = edge_info["start_direction"]
                        direction_along_segment = edge_info["start_direction"]
                    elif segment_end == "end":
                        direction_from_port = -edge_info["end_direction"]
                        direction_along_segment = edge_info["end_direction"]
            else:
                section_params = {}
                profile = ""
                attachment = "Center"
                user_offset = FreeCAD.Vector(0, 0, 0)
                profile_x_axis = FreeCAD.Vector(0, 0, 0)

            # ----------------------------------------------------------
            # Flow interpretation
            # ----------------------------------------------------------
            # Base geometry direction is interpreted as flow direction:
            # segment start -> segment end.
            #
            # At segment start:
            #     flow leaves the junction into the segment -> outlet.
            #
            # At segment end:
            #     flow enters the junction from the segment -> inlet.
            # ----------------------------------------------------------
            flow_direction = FreeCAD.Vector(direction_along_segment)
            
            if flow_direction.Length <= 1e-9:
                flow_role = "unknown"
                flow_into_junction = None
                flow_direction_xyz = None
            else:
                flow_direction.normalize()
            
                flow_into_junction = segment_end == "end"
                flow_role = "inlet" if flow_into_junction else "outlet"
                flow_direction_xyz = vec_to_xyz(flow_direction)
        
            # ----------------------------------------------------------
            # Compute actual profile-aware port position
            # ----------------------------------------------------------
            base_point = FreeCAD.Vector(member_point)
            final_position = hvaclib.compute_port_position(
                base_point,
                direction_along_segment,
                section_params,
                attachment,
                user_offset,
                profile_x_axis,
            )
    
            ports.append(JunctionPort(
                edge_key=edge_key,
                segment_end=segment_end,
                position=vec_to_xyz(final_position),
                direction=vec_to_xyz(direction_from_port),
                profile=profile,
                section_params=section_params,
                attachment=attachment,
                user_offset=vec_to_xyz(user_offset),
                profile_x_axis=(
                    vec_to_xyz(profile_x_axis)
                    if profile_x_axis.Length > 1e-12 else None
                ),
                flow_role=flow_role,
                flow_direction=flow_direction_xyz,
                flow_into_junction=flow_into_junction,
            ))
    
        return ports

    # ======================================================================
    # Junction analysis
    # ======================================================================

    def build_junction_analysis(self, node_id, segment_map=None):
        degree = self.node_degree(node_id)
        if degree <= 0:
            return
            
        # Get connected ports
        edge_refs = self.node_edges(node_id)
        connected_ports = self.build_junction_ports(
            node_id,
            edge_refs,
            segment_map=segment_map
        )
        
        # Get node analysis and junction classifications
        analysis = self.node_analysis(node_id, connected_ports)
        topology = self.classify_node_topology(analysis)
        family, family_tags = self.classify_junction_family(analysis)
        family_key = self.make_junction_family_key(topology, family, *family_tags)
        flow_class, qualifiers, derived_values = self.classify_flow(analysis, topology)

        # Build analysis object for the junction
        junction_analysis = JunctionAnalysis(
            topology=topology,
            family=family,
            family_tags=family_tags,
            family_key=family_key,
            flow_class=flow_class,
            qualifiers=qualifiers,
            derived_values=derived_values,
            connected_ports=connected_ports,
            # Basic geometric data
            point=analysis.point,
            degree=degree,
            port_origins=analysis.port_origins,
            edge_vectors=analysis.edge_vectors,
            edge_angles=analysis.edge_angles,
            edge_eccentricities=analysis.edge_eccentricities,
            # Derived geometric data
            collinear_pairs=analysis.collinear_pairs,
            orthogonal_pairs=analysis.orthogonal_pairs,
            is_coplanar=analysis.is_coplanar
        )
        return junction_analysis
        
    # ======================================================================
    # Public graph queries
    # ======================================================================

    def node_count(self):
        """
        Number of analysis nodes (supernodes).
        """
        return len(self.analysis_node_members)

    def edge_count(self):
        """
        Number of geometric edges parsed from source geometry.
        """
        return len(self.edge_u_v)

    def nodes(self):
        """
        Return analysis node ids.
        """
        return sorted(self.analysis_node_members.keys())

    def geometric_nodes(self):
        """
        Return raw geometric node ids.
        """
        return sorted(self.node_point.keys())
        
    def geometric_node_point_map(self):
        """
        Return geometric point map: node id -> (x,y,z)
        """
        return dict(self.node_point)

    def node_xyz(self, analysis_node_id):
        """
        Return representative point of an analysis node.

        For grouped nodes, this is the centroid of member geometric nodes.
        """
        return self.analysis_node_point[analysis_node_id]

    def node_group_members(self, analysis_node_id):
        """
        Return geometric node ids that belong to this analysis node.
        """
        return list(self._get_analysis_members(analysis_node_id))
        
    def node_group_members_xyz(self, analysis_node_id):
        """
        Return geometric points corresponding to an analysis node.
        """
        geo_nids = self._get_analysis_members(analysis_node_id)
        points = [self.node_point[id] for id in geo_nids]
        return points

    def edges(self):
        """
        Return all parsed edge references.
        """
        return list(self.edge_u_v.keys())

    def edges_of_obj(self, obj_name):
        """
        Return all edge refs belonging to one source object.
        """
        return list(self.obj_edges.get(obj_name, []))

    def edge_nodes(self, edge_ref):
        """
        Return geometric endpoint node ids of an edge.
        """
        return self.edge_u_v[edge_ref]

    def edge_analysis_nodes(self, edge_ref):
        """
        Return analysis endpoint node ids of an edge.
        """
        return self.analysis_edge_u_v[edge_ref]

    def edge_line(self, edge_ref):
        """
        Return raw geometric line endpoints (sp, ep) for an edge.
        """
        return self.edge_geom[edge_ref]

    def connected_components(self):
        """
        Return connected components of the analysis graph.
        """
        if self.analysis_graph is None:
            raise RuntimeError("Analysis graph not built. Call build_graph() first.")

        return [sorted(list(c)) for c in nx.connected_components(self.analysis_graph)]

    def shortest_path_by_points(self, p1, p2):
        """
        Find shortest path in the analysis graph between two geometric points.
        The points are first snapped to geometric nodes, then mapped to their
        analysis nodes.
        """
        if self.analysis_graph is None:
            raise RuntimeError("Analysis graph not built. Call build_graph() first.")

        geom_n1 = self.node_id_by_key[self._point_snap_key(p1)]
        geom_n2 = self.node_id_by_key[self._point_snap_key(p2)]

        analysis_n1 = self.analysis_node_by_geom_node[geom_n1]
        analysis_n2 = self.analysis_node_by_geom_node[geom_n2]

        return nx.shortest_path(self.analysis_graph, analysis_n1, analysis_n2)

    # ======================================================================
    # Node identity / classification helpers
    # ======================================================================

    def geometric_node_key(self, geom_node_id):
        local_labels = []
        
        for edge_ref, (geom_u, geom_v) in self.edge_u_v.items():
            if geom_u == geom_node_id:
                local_labels.append(edge_ref.tag + "_s")
            elif geom_v == geom_node_id:
                local_labels.append(edge_ref.tag + "_e")

        if local_labels:
            return "+".join(sorted(local_labels))
        else:
            return str(self._point_snap_key(self.node_point[geom_node_id]))
        
    
    def node_key(self, analysis_node_id):
        """
        Return a persistent key for the analysis node.

        Singleton analysis node:
            preserve existing behavior as much as possible.

        Grouped analysis node:
            create a grouped key from member geometric-node edge labels.
        """
        members = self.node_group_members(analysis_node_id)

        # ------------------------------------------------------------------
        # Singleton analysis node -> preserve old-style key
        # ------------------------------------------------------------------
        if len(members) == 1:
            geom_node_id = members[0]
            incident_edges = self.node_edges(analysis_node_id)

            if len(incident_edges) == 0:
                return self._point_snap_key(self.node_point[geom_node_id])

            elif len(incident_edges) == 1:
                member_node = self._find_edge_member_node_in_analysis_node(
                    incident_edges[0], analysis_node_id
                )
                geom_u, geom_v = self.edge_u_v[incident_edges[0]]

                if member_node == geom_u:
                    label = "s"
                elif member_node == geom_v:
                    label = "e"
                else:
                    return self._point_snap_key(self.node_point[geom_node_id])

                return incident_edges[0].tag + "_" + label

            else:
                return "_".join(sorted([eref.tag for eref in incident_edges]))

        # ------------------------------------------------------------------
        # Grouped analysis node -> stable grouped key
        # ------------------------------------------------------------------
        parts = []

        for geom_node_id in sorted(members):
            parts.append(self.geometric_node_key(geom_node_id))

        return "group:" + "|".join(parts)

    def node_degree(self, analysis_node_id):
        """
        Degree of an analysis node in the analysis graph.
        """
        if self.analysis_graph is None:
            raise RuntimeError("Analysis graph not built. Call build_graph() first.")

        return int(self.analysis_graph.degree[analysis_node_id])

    def node_edges(self, analysis_node_id):
        """
        Return edge refs incident to an analysis node.

        Internal edges whose both ends collapse into the same analysis node
        are excluded.
        """
        incident_refs = []

        for edge_ref, (analysis_u, analysis_v) in self.analysis_edge_u_v.items():
            if analysis_u == analysis_v:
                continue
            if analysis_u == analysis_node_id or analysis_v == analysis_node_id:
                incident_refs.append(edge_ref)

        return incident_refs

    def node_vectors(self, analysis_node_id):
        """
        Return normalized edge direction vectors for an analysis node.
        Direction points away from the node.

        Important:
        For grouped analysis nodes, vectors are computed from the actual local
        geometric member node touched by each edge, not from the analysis-node
        centroid.
        """
        vectors = []

        for edge_ref in self.node_edges(analysis_node_id):
            member_geom_node = self._find_edge_member_node_in_analysis_node(
                edge_ref, analysis_node_id
            )
            if member_geom_node is None:
                continue

            local_point = FreeCAD.Vector(*self.node_point[member_geom_node])

            sp, ep = self.edge_line(edge_ref)
            sp_vec = FreeCAD.Vector(*sp)
            ep_vec = FreeCAD.Vector(*ep)

            geom_u, geom_v = self.edge_nodes(edge_ref)

            if member_geom_node == geom_u:
                other = ep_vec
            elif member_geom_node == geom_v:
                other = sp_vec
            else:
                # Fallback, should rarely happen
                other = ep_vec if (sp_vec.sub(local_point)).Length <= self.tol else sp_vec

            direction = other - local_point

            if direction.Length > self.tol:
                direction.normalize()
                vectors.append((edge_ref, direction))

        return vectors
        
    @staticmethod
    def make_junction_family_key(topology, family, *qualifiers):
            parts = [topology, family]
            parts.extend([q for q in qualifiers if q])
            return ".".join(parts)
        
    @staticmethod
    def split_junction_family_key(key):
        parts = (key or "").split(".")
        topology = parts[0] if len(parts) > 0 else ""
        family = parts[1] if len(parts) > 1 else ""
        qualifiers = parts[2:] if len(parts) > 2 else []
        return topology, family, qualifiers

    @staticmethod
    def _angle_bw_vectors(vec_a, vec_b):
        """
        Return angle between two vectors in degrees.
        """
        vec_a = FreeCAD.Vector(vec_a).normalize()
        vec_b = FreeCAD.Vector(vec_b).normalize()
        
        dot = max(-1.0, min(1.0, float(vec_a.dot(vec_b))))
        return math.degrees(math.acos(dot))
    
    @staticmethod    
    def _distance_between_lines(origin_i, dir_i, origin_j, dir_j):
        """
        Compute the perpendicular distance between two lines in 3D.
        Each line is defined by a FreeCAD.Vector origin and direction.
        Handles parallel/coincident lines as a special case.
        """    
        u_i = FreeCAD.Vector(dir_i).normalize()
        u_j = FreeCAD.Vector(dir_j).normalize()
        w0  = FreeCAD.Vector(origin_i) - FreeCAD.Vector(origin_j)
    
        cross = u_i.cross(u_j)
        denom = cross.Length
    
        if denom < 1e-10:
            # Lines are parallel — distance is |w0 × u_i|
            return w0.cross(u_i).Length
    
        # Skew lines — |(w0 · (d_i × d_j))| / |d_i × d_j|
        return abs(w0.dot(cross)) / denom
    
    def _edge_angles(self, edge_vectors):
        """
        Return a dictionary of edge angles.
        """
        edge_angles = {}
        for i in range(len(edge_vectors)):
            for j in range(i + 1, len(edge_vectors)):
                ang = self._angle_bw_vectors(edge_vectors[i], edge_vectors[j])
                edge_angles[str((i, j))] = ang
        return edge_angles

    def _edge_eccentricities(self, port_origins, edge_vectors):
        """
        Return a dictionary of edge eccentricities.
        """
        edge_eccentricities = {}
        for i in range(len(edge_vectors)):
            for j in range(i + 1, len(edge_vectors)):
                pos_i = port_origins[i]
                pos_j = port_origins[j]
                vec_i = edge_vectors[i]
                vec_j = edge_vectors[j]
                edge_eccentricities[str((i, j))] = self._distance_between_lines(pos_i, vec_i, pos_j, vec_j)
        return edge_eccentricities

    @staticmethod
    def _pair_angle_lookup(edge_angles, i, j):
        """
        Look up the precomputed angle (degrees) between ports i and j from
        a node's own edge_angles dict (keyed by the sorted index pair --
        see _edge_angles()/node_analysis()). Shared by
        classify_junction_family() and the flow classifier so both read
        the exact same angle for the exact same port pair, rather than
        each recomputing it independently from raw direction vectors.
        """
        a, b = sorted((i, j))
        return abs(edge_angles[str((a, b))])

    @staticmethod
    def _pair_eccentricity_lookup(edge_eccentricities, i, j):
        """Look up the precomputed eccentricity between ports i and j (see _pair_angle_lookup)."""
        a, b = sorted((i, j))
        return edge_eccentricities[str((a, b))]

    def _collinear_pairs(self, origins, vectors):
        """
        Return incident edge pairs whose directions are approximately opposite.
        """
        pairs = []

        for i in range(len(vectors)):
            for j in range(i + 1, len(vectors)):
                ang = self._angle_bw_vectors(vectors[i], vectors[j])
                ecc = self._distance_between_lines(origins[i], vectors[i], origins[j], vectors[j])
                if abs(ang - 180.0) <= self.angle_tol_degree:
                    pairs.append(EdgePair(
                        a = i,
                        b = j,
                        angle = ang,
                        eccentricity = ecc
                    ))

        return pairs
        
    def _orthogonal_pairs(self, origins, vectors):
        """
        Return incident edge pairs whose directions are approximately orthogonal.
        """
        pairs = []
        for i in range(len(vectors)):
            for j in range(i + 1, len(vectors)):
                ang = self._angle_bw_vectors(vectors[i], vectors[j])
                ecc = self._distance_between_lines(origins[i], vectors[i], origins[j], vectors[j])
                if abs(ang - 90.0) <= self.angle_tol_degree:
                    pairs.append(EdgePair(
                        a = i,
                        b = j,
                        angle = ang,
                        eccentricity = ecc
                    ))
        return pairs

    def node_analysis(self, analysis_node_id, connected_ports):
        """
        Return analysis summary for one analysis node.
        """
        # Basic node data
        node_id = int(analysis_node_id)
        node_key = self.node_key(analysis_node_id)
        point = self.node_xyz(analysis_node_id)
        degree = self.node_degree(analysis_node_id)
        # Group members
        member_ids = self.node_group_members(analysis_node_id)
        member_points = [self.node_point[n] for n in member_ids]
        # Edge data
        edge_refs = self.node_edges(analysis_node_id)
        # vectors = self.node_vectors(analysis_node_id)
        
        # Basic geometric data
        port_origins = [connected_ports[i].position for i in range(len(connected_ports))]
        edge_vectors = [connected_ports[i].direction for i in range(len(connected_ports))]
        edge_angles = self._edge_angles(edge_vectors)
        edge_eccentricities = self._edge_eccentricities(port_origins, edge_vectors)
        is_coplanar = all(ecc < self.tol for ecc in edge_eccentricities.values())
        # Features
        collinear_pairs = self._collinear_pairs(port_origins, edge_vectors)
        orthogonal_pairs = self._orthogonal_pairs(port_origins, edge_vectors)
        
        return NodeAnalysis(
            node_id = node_id,
            node_key = node_key,
            member_ids = member_ids,
            member_points = member_points,
            edge_refs = edge_refs,
            connected_ports = connected_ports,
            # Basic geometric data
            point = point,
            degree = degree,
            port_origins = port_origins,
            edge_vectors = edge_vectors,
            edge_angles = edge_angles,
            edge_eccentricities = edge_eccentricities,
            # Derived geometric data
            collinear_pairs = collinear_pairs,
            orthogonal_pairs = orthogonal_pairs,
            is_coplanar = is_coplanar
        )
        
    def classify_node_topology(self, node_analysis):
        """
        Return topology (degree) based classification of node.
        """
        degree = node_analysis.degree

        if degree <= 0:
            return "isolated"
        if degree == 1:
            return "end"
        if degree == 2:
            return "through"
        if degree == 3:
            return "branch"
        if degree == 4:
            return "cross"
        return "multiport"
        
    def classify_junction_family(self, node_analysis):
        """
        Classify the geometric family of a junction node.
    
        This is a geometry-family classifier layered on top of the
        degree-based topology classifier.
    
        Families are intentionally generic and profile-independent.
    
        Returns one of:
            degree 1:
                terminal
    
            degree 2:
                straight
                offset
                bend_90
                bend_90.3d
                bend
                bend.3d
                
            degree 3:
                tee
                tee.3d
                lateral_tee
                lateral_tee.3d
                wye
                wye.3d
                generic
    
            degree 4:
                cross
                cross.3d
                double_wye
                double_wye.3d
                generic
    
            degree >= 5:
                multiport
                multiport.3d
        """
        degree = node_analysis.degree
        
        edge_angles = node_analysis.edge_angles
        edge_eccentricities= node_analysis.edge_eccentricities
        
        collinear_pairs = node_analysis.collinear_pairs
        is_coplanar = node_analysis.is_coplanar
        
        def _disjoint_pair_set(pairs):
            """
            Return True if the given two pairs are disjoint and cover 4 unique ports.
            """
            if len(pairs) != 2:
                return False
            used = set()
            for p in pairs:
                used.add(p.a)
                used.add(p.b)
            return len(used) == 4
    
        def _zero_ecc_pair_count(pairs):
            return sum(1 for p in pairs if p.eccentricity <= self.tol)
    
        def _find_remaining_index(pair, count):
            used = {pair.a, pair.b}
            for idx in range(count):
                if idx not in used:
                    return idx
            return None
    
        def _pair_angle(i, j):
            return self._pair_angle_lookup(edge_angles, i, j)

        def _pair_eccentricity(i, j):
            return self._pair_eccentricity_lookup(edge_eccentricities, i, j)
    
        # ------------------------------------------------------------
        # degree 0 / invalid
        # ------------------------------------------------------------
        if degree <= 0:
            return "isolated", []
    
        # ------------------------------------------------------------
        # degree 1
        # ------------------------------------------------------------
        if degree == 1:
            return "terminal", []
    
        # ------------------------------------------------------------
        # degree 2
        # ------------------------------------------------------------
        if degree == 2:
            # Collinear => through condition
            if len(collinear_pairs) == 1:
                ports = node_analysis.connected_ports
                same_section = len(ports) == 2 and self._sections_equal(ports[0], ports[1])
                if not same_section:
                    # A profile/size change at the joint -- a real transition
                    # fitting, whether or not the axes also happen to be
                    # displaced (see TOPOLOGY_CLASSIFICATION.md).
                    return "transition", []
                if _pair_eccentricity(0, 1) < self.tol:
                    return "straight", []
                else:
                    return "offset", []

            # Not collinear => change in direction
            else:
                angle = _pair_angle(0, 1)
                if is_coplanar:
                    if abs(angle - 90.0) <= self.angle_tol_degree:
                        return "bend_90", []
                    else:
                        return "bend", []
                else:
                    if abs(angle - 90.0) <= self.angle_tol_degree:
                        return "bend_90", ["3d"]
                    else:
                        return "bend", ["3d"]
    
        # ------------------------------------------------------------
        # degree 3
        # ------------------------------------------------------------
        if degree == 3:
            # Case 1: one collinear pair -> trunk + branch
            if len(collinear_pairs) == 1:
                trunk = collinear_pairs[0]
                branch_idx = _find_remaining_index(trunk, 3)
                # Ensure branch is found
                assert branch_idx is not None
                    
                # branch angle with trunk directions
                ang1 = _pair_angle(branch_idx, trunk.a)
                ang2 = _pair_angle(branch_idx, trunk.b)
                branch_ang = min(ang1, ang2)
    
                if is_coplanar:
                    # 90 deg branch
                    if abs(branch_ang - 90.0) <= self.angle_tol_degree:
                        return "tee", []
                    # non-90 deg branch
                    else:
                        return "lateral_tee", []
                else:
                    # 90 deg branch
                    if abs(branch_ang - 90.0) <= self.angle_tol_degree:
                        return "tee", ["3d"]
                    # non-90 deg branch
                    else:
                        return "lateral_tee", ["3d"]
    
            # Case 2: no collinear pair -> split / wye type
            elif len(collinear_pairs) == 0:
                if is_coplanar:
                    return "wye", []
                else:
                    return "wye", ["3d"]
            else:
                return "generic", []
    
        # ------------------------------------------------------------
        # degree 4
        # ------------------------------------------------------------
        if degree == 4:
            
            # Cross
            if len(collinear_pairs) >= 2:
                # Try to find two disjoint collinear pairs
                disjoint = None
                for i in range(len(collinear_pairs)):
                    for j in range(i + 1, len(collinear_pairs)):
                        cand = [collinear_pairs[i], collinear_pairs[j]]
                        if _disjoint_pair_set(cand):
                            disjoint = cand
                            break
                    if disjoint:
                        break
                
                # If disjoint collinear_pairs exists
                if disjoint:
                    # Check whether cross is near orthogonal between the two runs
                    p0, p1 = disjoint
                    a = p0.a
                    b = p0.b
                    c = p1.a
                    d = p1.b
    
                    inter_angles = [
                        _pair_angle(a, c),
                        _pair_angle(a, d),
                        _pair_angle(b, c),
                        _pair_angle(b, d),
                    ]
                    near_90 = sum(1 for ang in inter_angles if abs(ang - 90.0) <= self.angle_tol_degree)
                    
                    if near_90 >= 2 and is_coplanar:
                        return "cross", []
                    elif near_90 >= 2 and not is_coplanar:
                        return "cross", ["3d"]
            
            # Double wye
            elif len(collinear_pairs) == 1:
                trunk = collinear_pairs[0]
                e1 = trunk.a
                e2 = trunk.b
                rem_idx = [i for i in [0,1,2,3] if i not in [e1, e2]]
                angles_1 = [_pair_angle(e1, rem_idx[0]), _pair_angle(e1, rem_idx[1])]
                angles_2 = [_pair_angle(e2, rem_idx[0]), _pair_angle(e2, rem_idx[1])]
                # Select smallest of set of angles
                angles = angles_1 if sum(angles_1) < sum(angles_2) else angles_2
                # If angles are same
                if abs(angles[0] - angles[1]) < self.angle_tol_degree:
                    if is_coplanar:
                        return "double_wye", []
                    else:
                        return "double_wye", ["3d"]
    
            # No clean two-run cross found
            return "generic", []
    
        # ------------------------------------------------------------
        # degree >= 5
        # ------------------------------------------------------------
        if degree >= 5:
            if is_coplanar:
                return "multiport", []
            return "multiport", ["3d"]

    # ======================================================================
    # Flow classification (flow_class / qualifiers / derived_values)
    # ======================================================================
    #
    # This is a second, independent classifier layered on top of
    # topology/family: it never changes family_key, and it never asks the
    # hydraulic solver anything -- direction always comes from
    # JunctionPort.flow_role/flow_direction, which is itself derived purely
    # from base-segment orientation (segment start -> segment end), see
    # build_junction_ports() above.

    def _geom_tol(self, characteristic_size, rel_tol=1e-6):
        """
        Shared size-relative geometry tolerance: max(self.tol, rel_tol *
        characteristic_size). self.tol is the absolute floor (same value
        used to snap the geometric graph itself), rel_tol scales it up
        for larger ducts so floating-point round-off on a big section
        doesn't get mistaken for a real geometric difference. Used
        everywhere this classifier compares two dimensions/positions
        against each other -- never a scattered literal 1e-6.
        """
        return max(self.tol, rel_tol * abs(characteristic_size))

    def _sections_equal(self, port_a, port_b):
        """
        True if two ports share the same section within a size-relative
        tolerance (see _geom_tol). Never area alone: two differently-
        shaped sections can share an area without being "the same
        section" for through.straight/offset vs. through.transition
        classification purposes.
        """
        profile_a = str(port_a.profile or "")
        profile_b = str(port_b.profile or "")
        if not profile_a or profile_a != profile_b:
            return False

        ext_a = hvaclib.get_section_extents(port_a.section_params or {})
        ext_b = hvaclib.get_section_extents(port_b.section_params or {})
        if (ext_a[0] > 0.0 and ext_a[1] > 0.0) or (ext_b[0] > 0.0 and ext_b[1] > 0.0):
            # Known Circular/Rectangular/Oval extents -- compare width/height
            # (or diameter-as-box) with a tolerance scaled to their own size.
            size = max(ext_a[0], ext_a[1], ext_b[0], ext_b[1])
            tol = self._geom_tol(size)
            return abs(ext_a[0] - ext_b[0]) <= tol and abs(ext_a[1] - ext_b[1]) <= tol

        # Generic/custom profile with no recognized Width/Height/Diameter
        # schema -- fall back to an exact canonical signature match (making
        # this size-relative too would need a documented generic-profile
        # dimension schema, out of scope here).
        return hvaclib.profile_signature(profile_a, port_a.section_params) == hvaclib.profile_signature(
            profile_b, port_b.section_params
        )

    def classify_flow(self, node_analysis, topology):
        """
        Return (flow_class, qualifiers, derived_values) for one node.

        "through" (degree-2, collinear) and "branch" (degree-3) nodes get
        qualifiers and derived values as well. An "end" node only gets
        entry/exit, and a "cross"/"multiport" node only diverging/converging
        -- see TOPOLOGY_CLASSIFICATION.md.
        """
        ports = node_analysis.connected_ports

        if topology == "end" and len(ports) == 1:
            return self._classify_end_flow(ports[0]), {}, {}

        if topology in ("cross", "multiport"):
            return self._classify_manifold_flow(ports), {}, {}

        if topology == "through" and len(ports) == 2 and len(node_analysis.collinear_pairs) == 1:
            return self._classify_through_flow(ports[0], ports[1])

        if topology == "branch" and len(ports) == 3:
            return self._classify_branch_flow(ports, node_analysis)

        return "unknown", {}, {}

    def _classify_end_flow(self, port):
        """
        Which way air passes the open end of a duct: "entry" (air comes into
        the duct system here, e.g. an intake or a return grille), "exit"
        (air leaves it here) or "unknown".
        """
        role = str(port.flow_role or "unknown")
        # A port's role is seen from the node: an "inlet" brings air to the
        # node, and at an open end that air has nowhere to go but out.
        if role == "inlet":
            return "exit"
        if role == "outlet":
            return "entry"
        return "unknown"

    def _classify_manifold_flow(self, ports):
        """
        "diverging" (one inlet, the rest outlets), "converging" (one outlet,
        the rest inlets) or "unknown" (anything else, including several
        inlets and several outlets at once) for a node of four or more ports.
        """
        roles = [str(p.flow_role or "unknown") for p in ports]
        n_in = roles.count("inlet")
        n_out = roles.count("outlet")
        if n_in + n_out != len(ports):
            return "unknown"
        if n_in == 1 and n_out >= 2:
            return "diverging"
        if n_out == 1 and n_in >= 2:
            return "converging"
        return "unknown"

    def _resolve_inlet_outlet(self, port_a, port_b):
        """
        (inlet, outlet) ordering of two ports from their own flow_role --
        base-segment orientation is the sole source of truth here (see
        build_junction_ports()). Returns (None, None) when the pair isn't
        exactly one inlet and one outlet: an ambiguous or unresolved pair
        must never fall back to an arbitrary port order, since that could
        silently mislabel a contraction as an expansion (or vice versa).
        """
        if port_a.flow_role == "inlet" and port_b.flow_role == "outlet":
            return port_a, port_b
        if port_b.flow_role == "inlet" and port_a.flow_role == "outlet":
            return port_b, port_a
        return None, None

    def _classify_through_flow(self, port_a, port_b):
        inlet, outlet = self._resolve_inlet_outlet(port_a, port_b)
        if inlet is None or outlet is None:
            # Direction unresolved -- never guess expansion/contraction or
            # any direction-dependent qualifier/derived value from an
            # arbitrary port order.
            return "unknown", {}, {}

        qualifiers = {}
        derived = {}

        profile_in = str(inlet.profile or "")
        profile_out = str(outlet.profile or "")
        if profile_in or profile_out:
            qualifiers["inlet_profile"] = profile_in
            qualifiers["outlet_profile"] = profile_out
            qualifiers["profile_relation"] = "same" if profile_in and profile_in == profile_out else "mixed"

        area_in = hvaclib.profile_area(profile_in, inlet.section_params)
        area_out = hvaclib.profile_area(profile_out, outlet.section_params)

        flow_class = "unknown"
        if area_in is not None and area_out is not None:
            if math.isclose(area_in, area_out, rel_tol=1e-6, abs_tol=1e-6):
                flow_class = "constant"
            elif area_out > area_in:
                flow_class = "expansion"
            else:
                flow_class = "contraction"
            if area_in > 0.0:
                derived["area_ratio"] = area_out / area_in

        ext_in = hvaclib.get_section_extents(inlet.section_params or {})
        ext_out = hvaclib.get_section_extents(outlet.section_params or {})
        if ext_in[0] > 0.0 and ext_in[1] > 0.0:
            derived["aspect_ratio_in"] = ext_in[0] / ext_in[1]
        if ext_out[0] > 0.0 and ext_out[1] > 0.0:
            derived["aspect_ratio_out"] = ext_out[0] / ext_out[1]

        alignment, alignment_qualifiers, offset_ratio = self._classify_alignment(
            inlet, outlet, profile_in, profile_out, ext_in, ext_out
        )
        if alignment:
            qualifiers["alignment"] = alignment
            qualifiers.update(alignment_qualifiers)
        if offset_ratio is not None:
            derived["offset_ratio"] = offset_ratio

        transition_form = self._classify_transition_form(profile_in, profile_out, ext_in, ext_out)
        if transition_form:
            qualifiers["transition_form"] = transition_form

        return flow_class, qualifiers, derived

    def _classify_alignment(self, inlet, outlet, profile_in, profile_out, ext_in, ext_out):
        """
        Return (alignment, extra_qualifiers, offset_ratio) for a through
        pair, using each port's own actual profile-aware position
        (JunctionPort.position already accounts for Attachment/Offset --
        see compute_port_position()), computed in ONE common local frame
        so "top"/"bottom"/"left"/"right" have one consistent physical
        meaning regardless of which port (inlet/outlet) is being looked
        at -- through-port `direction` fields point opposite ways, so
        interpreting each port's own direction independently would be
        wrong. The frame's longitudinal axis is the inlet's actual FLOW
        direction (not its `direction` field, which points upstream/away
        from the junction) -- this is the same vector
        compute_port_position() itself used against the inlet's own
        ProfileXAxis (base-segment direction, see build_junction_ports()),
        so the frame stays consistent with how ProfileXAxis was originally
        interpreted; the transverse reference is the inlet's own
        ProfileXAxis, per hvaclib's "X -> Left, Y -> Top" convention.
        """
        pos_in = FreeCAD.Vector(*inlet.position)
        pos_out = FreeCAD.Vector(*outlet.position)
        delta = pos_out - pos_in

        w_in, h_in = ext_in
        w_out, h_out = ext_out
        ref_dim = ((w_in + h_in) + (w_out + h_out)) / 4.0

        flow_dir = inlet.flow_direction
        z_dir = FreeCAD.Vector(*flow_dir) if flow_dir else FreeCAD.Vector(0, 0, 0)
        if z_dir.Length <= 1e-12:
            # No frame to resolve a transverse offset against -- offset_ratio
            # is undefined here, never the raw (possibly longitudinal) delta.
            return "unknown", {}, None

        preferred_x = FreeCAD.Vector(*inlet.profile_x_axis) if inlet.profile_x_axis else None
        try:
            _, x_dir, y_dir, _ = hvaclib.make_profile_frame(z_dir, preferred_x=preferred_x)
        except ValueError:
            return "unknown", {}, None

        delta_x = delta.dot(x_dir)
        delta_y = delta.dot(y_dir)

        # offset_ratio is the TRANSVERSE offset only (perpendicular to flow,
        # in this common frame) -- delta's own longitudinal component along
        # z_dir is deliberately dropped, never folded into the ratio.
        transverse_offset = math.hypot(delta_x, delta_y)
        offset_ratio = (transverse_offset / ref_dim) if ref_dim > 1e-9 else None

        tol = self._geom_tol(ref_dim)

        rectangular = profile_in == "Rectangular" and profile_out == "Rectangular"
        round_profiles = {"Circular", "Oval"}
        round_pair = profile_in in round_profiles and profile_out in round_profiles

        if rectangular or round_pair:
            # Same "one side flush, offset entirely to the other side"
            # test for both: for a round/oval pair, ext_in/ext_out are
            # (D, D) for Circular (so half_dw == half_dh -- the classic
            # tangent-edges eccentric reducer, independent of which axis
            # the offset lands on) or the real (Width, Height) for Oval.
            # Only Rectangular gets aligned_side/aligned_corner and the
            # double_eccentric (corner) case -- a round or oval section has
            # no corners, so that case falls through to "offset" instead.
            half_dw = (w_out - w_in) / 2.0
            half_dh = (h_out - h_in) / 2.0

            x_centered = abs(delta_x) <= tol
            x_right = abs(delta_x - half_dw) <= tol
            x_left = abs(delta_x + half_dw) <= tol
            y_centered = abs(delta_y) <= tol
            y_top = abs(delta_y + half_dh) <= tol
            y_bottom = abs(delta_y - half_dh) <= tol

            if x_centered and y_centered:
                return "concentric", {}, offset_ratio

            if x_centered and abs(half_dh) > tol and (y_top or y_bottom):
                qualifiers = {"aligned_side": "top" if y_top else "bottom"} if rectangular else {}
                return "eccentric", qualifiers, offset_ratio

            if y_centered and abs(half_dw) > tol and (x_left or x_right):
                qualifiers = {"aligned_side": "left" if x_left else "right"} if rectangular else {}
                return "eccentric", qualifiers, offset_ratio

            if rectangular and (x_left or x_right) and (y_top or y_bottom):
                corner = "{}_{}".format("top" if y_top else "bottom", "left" if x_left else "right")
                return "double_eccentric", {"aligned_corner": corner}, offset_ratio

            return "offset", {}, offset_ratio

        # Mixed profile families (e.g. Circular -> Rectangular): alignment
        # isn't a well-defined concept across different section shapes.
        return "unknown", {}, offset_ratio

    def _classify_transition_form(self, profile_in, profile_out, ext_in, ext_out):
        """
        Return a generic transition-form qualifier where reliably derivable
        from profile/extent data alone -- never a SMACNA-specific fitting id.
        Returns "" (no qualifier at all) when there's no actual section
        change to classify (e.g. a through.straight/offset pair that
        happens to reach this same code path); "unknown" when a real
        change occurred but this profile family isn't reliably
        classifiable into the vocabulary below (Oval/Generic/custom).
        """
        if not profile_in or not profile_out:
            return "unknown"
        if profile_in != profile_out:
            return "profile_change"

        tol = self._geom_tol(max(ext_in[0], ext_in[1], ext_out[0], ext_out[1]))
        w_changed = abs(ext_in[0] - ext_out[0]) > tol
        h_changed = abs(ext_in[1] - ext_out[1]) > tol
        if not w_changed and not h_changed:
            return ""

        if profile_in == "Circular":
            return "conical"

        if profile_in == "Rectangular":
            return "pyramidal" if (w_changed and h_changed) else "single_plane"

        # Oval/Generic/custom: a real change occurred but this profile
        # family isn't reliably classifiable into the vocabulary above --
        # never silently mapped onto the Circular/Rectangular SMACNA forms.
        return "unknown"

    def _classify_branch_flow(self, ports, node_analysis):
        qualifiers = {}
        derived = {}

        roles = [str(p.flow_role or "unknown") for p in ports]
        n_in = roles.count("inlet")
        n_out = roles.count("outlet")

        lone_idx = None
        if n_in == 1 and n_out == 2:
            flow_class = "diverging"
            lone_idx = roles.index("inlet")
        elif n_in == 2 and n_out == 1:
            flow_class = "converging"
            lone_idx = roles.index("outlet")
        else:
            flow_class = "unknown"

        profiles = [str(p.profile or "") for p in ports if p.profile]
        if profiles:
            qualifiers["profile_relation"] = "same" if len(set(profiles)) <= 1 else "mixed"

        # common_leg / area_ratio only resolve for a tee/lateral_tee (one
        # geometrically identified run/trunk pair) -- a wye has none.
        collinear_pairs = node_analysis.collinear_pairs
        if len(collinear_pairs) == 1:
            trunk = collinear_pairs[0]
            branch_idx = next(i for i in range(3) if i not in (trunk.a, trunk.b))

            if lone_idx is not None:
                qualifiers["common_leg"] = "run" if lone_idx in (trunk.a, trunk.b) else "branch"

            area_run = hvaclib.profile_area(ports[trunk.a].profile, ports[trunk.a].section_params)
            area_branch = hvaclib.profile_area(ports[branch_idx].profile, ports[branch_idx].section_params)
            if area_run and area_branch and area_run > 0.0:
                derived["area_ratio"] = area_branch / area_run

            # Geometric branch angle (degrees) between the branch leg and
            # whichever trunk leg it's closer to -- the same acute-angle
            # convention classify_junction_family() already uses to split
            # tee (~90 deg) from lateral_tee, and read from the exact same
            # precomputed edge_angles a node's family classification already
            # used, rather than recomputing it from raw direction vectors.
            ang_a = self._pair_angle_lookup(node_analysis.edge_angles, branch_idx, trunk.a)
            ang_b = self._pair_angle_lookup(node_analysis.edge_angles, branch_idx, trunk.b)
            derived["branch_angle"] = min(ang_a, ang_b)

        return flow_class, qualifiers, derived
