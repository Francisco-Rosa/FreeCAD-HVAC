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
GUI-only ViewProvider classes for core/Network.py's DuctManagedFolder and
DuctNetwork -- split out so core/Network.py itself can import cleanly
without FreeCADGui/PySide/pivy installed (see that module's own comments on
why this matters, and ARCHITECTURE.md's "GUI/core split" note). Every call
back into core/Network.py here is a lazy, in-method import, so this module
never imports core.Network at module scope either -- avoids a cycle with
core/Network.py's own (also lazy) construction of these two classes.
"""

import math

import FreeCAD
import FreeCADGui as Gui
from pivy import coin

from ..utils import hvaclib
from ..ui import TaskPanel
from ..core.NetworkParser import DuctNetworkParser


class DuctManagedFolderViewProvider:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def dumps(self):
        return None

    def loads(self, state):
        pass

    def getIcon(self):
        return hvaclib.get_icon_path("DuctsIcon.svg")

    def onDelete(self, vobj, subelements):
        from ..core.Network import DuctNetwork

        obj = vobj.Object
        owner = DuctNetwork.getOwnerNetwork(obj)
        # Allow deletion only when the owner network itself is being deleted
        if owner and getattr(owner.Proxy, "_allow_internal_delete", False):
            return True
        FreeCAD.Console.PrintWarning(
            "HVAC - Internal folder '{}' cannot be deleted directly.\n".format(obj.Label)
        )
        return False

    def claimChildren(self):
        try:
            # DuctComponent objects live in this folder's OutList (so
            # collectComponentObjects can find them), but they're claimed
            # by their parent DuctJunction for tree display (see
            # DuctJunctionViewProvider.claimChildren) -- filter them out
            # here or they'd show up twice.
            return [o for o in self.Object.OutList if not hvaclib.isDuctComponent(o)]
        except Exception:
            return []

    def canDropObjects(self):
        return False

    def canDragObjects(self):
        return False


class DuctNetworkViewProvider:
    """A View Provider for the HVAC duct network object"""

    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

        self._baseDirectionRoot = coin.SoSeparator()
        self._baseDirectionRoot.setName("HVAC_BaseDirectionArrows")
        vobj.RootNode.addChild(self._baseDirectionRoot)

        self.ensureDirectionArrowProperties(vobj)

        try:
            vobj.addDisplayMode(self._baseDirectionRoot, "Direction Arrows")
            vobj.DisplayMode = "Direction Arrows"
        except Exception:
            pass

        self.refreshBaseDirectionArrows()

    def dumps(self):
        return None

    def loads(self, state):
        pass

    def getIcon(self):
        return hvaclib.get_icon_path("DuctsIcon.svg")

    def setEdit(self, vobj, mode):

        def callback_add_base_object(net, obj):
            net.Proxy.addBaseObject(obj)

        def callback_remove_base_object(net, obj):
            net.Proxy.removeBaseObject(obj)

        panel = TaskPanel.TaskPanelEditDuctNetwork(vobj.Object,
            callback_add_base_object = callback_add_base_object,
            callback_remove_base_object = callback_remove_base_object
        )
        Gui.Control.showDialog(panel)
        return True

    def unsetEdit(self, vobj, mode):
        Gui.Control.closeDialog()
        return True

    def doubleClicked(self, vobj):
        from ..core.Network import activate_duct_network

        obj = vobj.Object
        # Make it the active network
        activate_duct_network(obj, set_edit=False)
        obj.Proxy.selectAllGeometry()
        return True

    def claimChildren(self):
        obj = self.Object
        kids = []
        try:
            if obj.Base: kids.append(obj.Base)
            if obj.Geometry: kids.append(obj.Geometry)
            if obj.Topology: kids.append(obj.Topology)
        except Exception:
            pass
        return kids

    def canDropObjects(self):
        # Returning False prevents users from dragging items into this group via the Tree View
        return False

    def canDragObjects(self):
        # Prevents users from dragging the managed folders OUT of the group
        return False

    def onDelete(self, vobj, subelements):
        from ..core.Network import delete_duct_networks

        net = vobj.Object
        delete_duct_networks([net], remove_internal_only=True)
        return True

    def onChanged(self, vobj, prop):
        if prop in ("ShowBaseDirectionArrows", "BaseDirectionArrowSize"):
            self.refreshBaseDirectionArrows()

    # Functions for managing base direction arrows

    def ensureDirectionArrowProperties(self, vobj):
        try:
            if "ShowBaseDirectionArrows" not in vobj.PropertiesList:
                vobj.addProperty(
                    "App::PropertyBool",
                    "ShowBaseDirectionArrows",
                    "HVAC",
                    "Show direction arrows for base geometry"
                )
                vobj.ShowBaseDirectionArrows = False
        except Exception:
            pass

        try:
            if "BaseDirectionArrowSize" not in vobj.PropertiesList:
                vobj.addProperty(
                    "App::PropertyFloat",
                    "BaseDirectionArrowSize",
                    "HVAC",
                    "Size multiplier for base direction arrows"
                )
                vobj.BaseDirectionArrowSize = 1.0
        except Exception:
            pass

    def _buildArrowCoinNode(self, lines, size_scale=1.0):
        """
        Build one Coin3D node containing all direction arrows as 3D cones.
        lines: [(sp, ep, tag, edge_no), ...]
        """
        root = coin.SoSeparator()

        # Draw filled faces with one color
        mat = coin.SoMaterial()
        mat.diffuseColor.setValue(1.0, 0.15, 0.0)
        mat.specularColor.setValue(0.4, 0.4, 0.4)
        mat.shininess.setValue(0.6)
        root.addChild(mat)

        for sp, ep, _tag, _edge_no in lines:
            p0 = FreeCAD.Vector(*sp) if not hasattr(sp, 'x') else FreeCAD.Vector(sp)
            p1 = FreeCAD.Vector(*ep) if not hasattr(ep, 'x') else FreeCAD.Vector(ep)

            direction = p1 - p0
            length = direction.Length
            if length < 1e-9:
                continue
            direction.normalize()

            # sizing
            arrow_len   = max(5.0, min(length * 0.25, 80.0)) * max(0.05, float(size_scale))
            arrow_len   = min(arrow_len, length * 0.8)
            head_len    = arrow_len * 0.5
            head_radius = head_len * 0.4
            shaft_len   = arrow_len - head_len
            shaft_radius = head_radius * 0.5

            # geometry: chain from tip backwards
            tip         = p0 + direction * (length * 0.6)
            cone_center = tip  - direction * (head_len * 0.5)
            cone_base   = tip  - direction * (head_len)
            shaft_center = cone_base - direction * (shaft_len * 0.5)

            # rotation: Coin SoCone/SoCylinder align to +Y, rotate Y → direction
            y_axis    = FreeCAD.Vector(0, 1, 0)
            rot_axis  = y_axis.cross(direction)
            dot       = max(-1.0, min(1.0, y_axis.dot(direction)))
            if rot_axis.Length > 1e-9:
                rot_axis.normalize()
                rot_angle = math.acos(dot)
            else:
                # direction is parallel to Y axis
                if dot > 0:
                    # already +Y, identity — no rotation needed
                    rot_axis  = FreeCAD.Vector(1, 0, 0)
                    rot_angle = 0.0
                else:
                    # exactly -Y, flip 180° around X (or Z, either works)
                    rot_axis  = FreeCAD.Vector(1, 0, 0)
                    rot_angle = math.pi

            def make_transform(center, rot_ax, angle):
                xf = coin.SoTransform()
                xf.translation.setValue(center.x, center.y, center.z)
                xf.rotation.setValue(coin.SbVec3f(rot_ax.x, rot_ax.y, rot_ax.z), angle)
                return xf

            # cone head
            cone_sep = coin.SoSeparator()
            cone_sep.addChild(make_transform(cone_center, rot_axis, rot_angle))
            cone = coin.SoCone()
            cone.bottomRadius.setValue(head_radius)
            cone.height.setValue(head_len)
            cone_sep.addChild(cone)
            root.addChild(cone_sep)

            # cylinder shaft — anchored to cone base, never recomputed independently
            shaft_sep = coin.SoSeparator()
            shaft_sep.addChild(make_transform(shaft_center, rot_axis, rot_angle))
            cyl = coin.SoCylinder()
            cyl.radius.setValue(shaft_radius)
            cyl.height.setValue(shaft_len)
            shaft_sep.addChild(cyl)
            root.addChild(shaft_sep)

        return root

    def refreshBaseDirectionArrows(self, parser=None):
        """
        Rebuild base direction arrows.

        Uses DuctNetworkParser.all_lines, not separate Draft/Sketch parsing.
        """
        root = getattr(self, "_baseDirectionRoot", None)
        net = self.Object

        if root is None or net is None:
            return

        root.removeAllChildren()

        if net.ViewObject.ShowBaseDirectionArrows is False:
            return

        try:
            if parser is None:
                parser = DuctNetworkParser()
                parser.compile_lines_from_objects(list(net.Base.OutList))

            lines = list(getattr(parser, "all_lines", []) or [])

            try:
                size_scale = float(net.ViewObject.BaseDirectionArrowSize)
            except Exception:
                size_scale = 1.0

            arrow_node = self._buildArrowCoinNode(lines, size_scale=size_scale)
            root.addChild(arrow_node)

        except Exception as e:
            FreeCAD.Console.PrintError(
                "HVAC - Failed to refresh base direction arrows.\n"
            )
            FreeCAD.Console.PrintError(str(e))
