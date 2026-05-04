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
#                                      `                                        #
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

"""This module implements HVAC duct description classes."""

import math
import FreeCAD
import FreeCADGui as Gui
from pivy import coin
from PySide import QtWidgets, QtCore
from PySide.QtCore import QT_TRANSLATE_NOOP
translate = FreeCAD.Qt.translate

from ..utils import hvaclib


class SketchObserver:
    """New sketch creation/ modification observer"""

    def __init__(self, network_obj, callback, edit_mode=False):
        self.network_obj = network_obj
        self.callback = callback
        self.edit_mode = edit_mode
        self.doc = network_obj.Document
        self.tracked_sketch = None
        self.finished = False
        self._seen_dialog = False
        self._arrow_root = None  # For showing base direction arrows
        
        # Suspend sync to prevent transient sync requests while sketching
        if self.network_obj and hasattr(self.network_obj, "Proxy") and self.network_obj.Proxy:
            self.network_obj.Proxy.suspendSync()
            
        self._timer = QtCore.QTimer()
        self._timer.setInterval(200)
        self._timer.timeout.connect(self.check_finished)
        self._timer.start()

    def slotCreatedObject(self, obj):
        # Called when a new object is created in the document
        if self.finished or self.tracked_sketch is not None or self.edit_mode:
            return
        if obj and obj.Document == self.doc and hvaclib.isSketch(obj):
            self.tracked_sketch = obj
            self._attach_arrows()
            
    def set_modified_sketch(self, sketch):
        """Set the modified sketch and attach arrows if in edit mode."""
        if self.edit_mode:
            self.tracked_sketch = sketch
            self._attach_arrows()
            
    def _attach_arrows(self):
        """Inject arrow separator into the sketch's Coin scene."""
        try:
            vp = self.network_obj.ViewObject
            if vp is None:
                return
            self._arrow_root = coin.SoSeparator()
            vp.RootNode.addChild(self._arrow_root)
        except Exception:
            FreeCAD.Console.PrintError("Unable to attach arrows to sketch")
            pass
            
    def _detach_arrows(self):
        """Remove arrow separator from the sketch's Coin scene."""
        if self._arrow_root is None:
            return
        try:
            vp = self.network_obj.ViewObject
            if vp is not None:
                vp.RootNode.removeChild(self._arrow_root)
        except Exception:
            pass
        self._arrow_root = None
        
    def _sync_arrows(self):
        if self._arrow_root is None:
            return
        self._arrow_root.removeAllChildren()
        lines = [
            (geo.StartPoint, geo.EndPoint)
            for geo in self.tracked_sketch.Geometry
            if hasattr(geo, 'StartPoint') and hasattr(geo, 'EndPoint')
        ]
        if lines:
            self._arrow_root.addChild(buildArrowCoinNodes(lines))
        
    def slotChangedObject(self, obj, prop):
        """Rebuild arrows whenever sketch geometry changes while editing."""
        if self.finished or self.tracked_sketch is None:
            return
        if obj != self.tracked_sketch or prop != "Geometry":
            return
        self._sync_arrows()

    def check_finished(self):
        """Detect when the sketch edition has been exited."""
        if self.finished:
            return
        # Sketcher normally opens a task panel/dialog while active.
        if Gui.Control.activeDialog():
            self._seen_dialog = True
            return
        # Finalize only after the dialog has appeared once and then closed.
        if self._seen_dialog:
            self._timer.stop()
            QtCore.QTimer.singleShot(0, self.finalize)
            return True

    def finalize(self):
        if self.finished:
            return
        self.finished = True
        
        if self.tracked_sketch is not None:
            self._detach_arrows()
        
        try:
            self.callback(self.network_obj, self.tracked_sketch)
        finally:
            FreeCAD.removeDocumentObserver(self)
            # Resume sync after sketching is done and request sync
            if self.network_obj and hasattr(self.network_obj, "Proxy") and self.network_obj.Proxy:
                self.network_obj.Proxy.resumeSync(request_sync=True)


class DraftLineObserver:
    """Observe Draft line creation/ modification and add all created lines to the network
    after the Draft tool is closed.
    """

    def __init__(self, network_obj, callback, edit_mode=False):
        self.network_obj = network_obj
        self.callback = callback
        self.edit_mode = edit_mode
        self.doc = network_obj.Document
        self.tracked_objects = []
        self.finished = False
        self._seen_dialog = False
        self._arrow_root = None  # For showing base direction arrows
        
        # Suspend sync to prevent transient sync requests while creating lines
        if self.network_obj and hasattr(self.network_obj, "Proxy") and self.network_obj.Proxy:
            self.network_obj.Proxy.suspendSync()

        self._timer = QtCore.QTimer()
        self._timer.setInterval(200)
        self._timer.timeout.connect(self.check_finished)
        self._timer.start()

    def slotCreatedObject(self, obj):
        """Called whenever a new object is created in the document."""
        if self.finished or self.edit_mode:
            return
        if not obj or obj.Document != self.doc:
            return
        if obj not in self.tracked_objects:
            self.tracked_objects.append(obj)
            
    def set_modified_line(self, line):
        """Set the modified line and attach arrows if in edit mode."""
        if self.edit_mode:
            self.tracked_objects.append(line)
            self._attach_arrows()
            
    def _attach_arrows(self):
        """Inject arrow separator into the sketch's Coin scene."""
        try:
            vp = self.network_obj.ViewObject
            if vp is None:
                return
            self._arrow_root = coin.SoSeparator()
            vp.RootNode.addChild(self._arrow_root)
        except Exception:
            FreeCAD.Console.PrintError("Unable to attach arrows to sketch")
            pass
            
    def _detach_arrows(self):
        """Remove arrow separator from the sketch's Coin scene."""
        if self._arrow_root is None:
            return
        try:
            vp = self.network_obj.ViewObject
            if vp is not None:
                vp.RootNode.removeChild(self._arrow_root)
        except Exception:
            pass
        self._arrow_root = None
        
    def _sync_arrows(self):
        if self._arrow_root is None:
            return
        self._arrow_root.removeAllChildren()
        lines = []
        for obj in self.tracked_objects:
            lines.extend(iter_line_segments_from_shape(obj))
        if lines:
            self._arrow_root.addChild(buildArrowCoinNodes(lines))
        
    def slotChangedObject(self, obj, prop):
        """Rebuild arrows whenever line geometry changes while editing."""
        if self.finished or self.tracked_objects is None:
            return
        if obj not in self.tracked_objects:
            return
        self._sync_arrows()

    def check_finished(self):
        """Detect when the Draft command has been exited."""
        if self.finished:
            return
        # Draft Line normally opens a task panel/dialog while active.
        if Gui.Control.activeDialog():
            self._seen_dialog = True
            return
        # Finalize only after the dialog has appeared once and then closed.
        if self._seen_dialog:
            self._timer.stop()
            QtCore.QTimer.singleShot(0, self.finalize)
            return True

    def finalize(self):
        if self.finished:
            return
        self.finished = True
        
        if self.tracked_objects is not None:
            self._detach_arrows()
        
        try:
            self.callback(self.network_obj, self.tracked_objects)
        finally:
            # Always remove observer after one use
            FreeCAD.removeDocumentObserver(self)
            # Resume sync after creation is done and request sync
            if self.network_obj and hasattr(self.network_obj, "Proxy") and self.network_obj.Proxy:
                self.network_obj.Proxy.resumeSync(request_sync=True)
            # Switch back workbench to HVAC
            Gui.activateWorkbench(hvaclib.WORKBENCH_NAME)
                

class DuctNetworkChangeObserver:
    """
    Observe changes in base objects and resync owning duct networks.

    This observer monitors property changes in Sketches or Draft Wires that define
    the paths for HVAC duct networks. When a base geometry object is modified,
    the observer schedules a synchronization task to update the derived
    3D geometry of the corresponding DuctNetwork.
    """

    def __init__(self) -> None:
        self._scheduled: set[str] = set()
        self._undo_redo_in_progress: bool = False
        self._sync_in_progress: bool = False
        self.edit_observer = None
        
        self._edit_timer = QtCore.QTimer()
        self._edit_timer.setInterval(hvaclib.OBSERVER_TIMER_POLL_INTERVAL)
        self._edit_timer.timeout.connect(self._checkEditedBaseObject)
        self._edit_timer.start()
        
        self._edited_net = None
        self._edited_base_obj = None

    def slotChangedObject(self, obj: object, prop: str) -> None:
        """
        Callback triggered when an object property is changed.

        Checks if the modified object is used as a base for any HVAC duct network
        and schedules a sync if geometry-relevant properties were changed.

        Args:
            obj: The document object that was changed.
            prop: The name of the property that was modified.
        """
        if self._undo_redo_in_progress or self._sync_in_progress:
            return
            
        if obj is None or self._edited_net is None:
            return
        doc = getattr(obj, "Document", None)
        if doc is None:
            return

        # Ignore internal managed objects to avoid circular updates
        if hvaclib.isDuctNetwork(obj) or hvaclib.isDuctSegment(obj) or hvaclib.isDuctManagedFolder(obj):
            return

        # React only to properties relevant to geometry updates
        if hvaclib.isSketch(obj):
            relevant_props = ("Geometry", "Shape", "Placement")
        elif hvaclib.isWire(obj):
            relevant_props = ("Points", "Shape", "Placement")
        else:
            return

        if prop not in relevant_props:
            return

        for net in hvaclib.allHVACNetworks(doc):
            # If the modified object is part of the network's base geometry
            if obj in net.Base.OutList:
                if net.Name in self._scheduled:
                    continue

                self._scheduled.add(net.Name)
                # Schedule sync via a single-shot timer to ensure it runs after 
                # the current calculation cycle has finished.
                QtCore.QTimer.singleShot(0, lambda n=net: self._doSync(n))

    def slotUndoDocument(self, doc):
        self._undo_redo_in_progress = True
        QtCore.QTimer.singleShot(0, lambda d=doc: self._resyncAllNetworks(d))

    def slotRedoDocument(self, doc):
        self._undo_redo_in_progress = True
        QtCore.QTimer.singleShot(0, lambda d=doc: self._resyncAllNetworks(d))

    # Sync watcher
    
    def _doSync(self, net):
        if net is None:
            return

        self._scheduled.discard(net.Name)

        if getattr(net, "Document", None) is None:
            return
        if not hvaclib.isDuctNetwork(net):
            return
        
        proxy = getattr(net, "Proxy", None)
        if proxy is None:
            return
                    
        self._sync_in_progress = True
        try:
            proxy.requestSync()
        finally:
            self._sync_in_progress = False

    def _resyncAllNetworks(self, doc):
        try:
            if doc is None:
                return

            self._scheduled.clear()
            self._sync_in_progress = True

            for obj in doc.Objects:
                if hvaclib.isDuctNetwork(obj):
                    proxy = getattr(obj, "Proxy", None)
                    if proxy:
                        proxy.requestSync(initial_sync=True)
        finally:
            self._sync_in_progress = False
            self._undo_redo_in_progress = False
       
    # Visibility watcher
        
    def _finishEditedBaseObject(self):
        """
        Finalize the tracking state when a base geometry object exits edit mode.

        Resets internal references and notifies the parent network's proxy to
        restore normal segment visibility and perform a final synchronization.
        """
        net = self._edited_net
        obj = self._edited_base_obj
        self._edited_net = None
        self._edited_base_obj = None
        
        if net is None or obj is None:
            return

        proxy = getattr(net, "Proxy", None)
        if proxy:
            # Patch: turn off snapper for wire objects
            if hvaclib.isWire(obj):
                try:
                    if hasattr(Gui, "Snapper") and Gui.Snapper:
                        try:
                            Gui.Snapper.off()
                        except TypeError:
                            Gui.Snapper.off(False)
                        except Exception:
                            pass
                        try:
                            Gui.Snapper.hide()
                        except Exception:
                            pass
                except Exception:
                    pass
            
            proxy.setBaseObjectEditing(obj, False)            
            # Resume sync after editing is done and request sync
            if net and hasattr(net, "Proxy") and net.Proxy:
                net.Proxy.resumeSync(request_sync=True)
        
        # Reset sketch/ line observer
        self.edit_observer = None

    def _checkEditedBaseObject(self):
        """
        Monitor the active document to detect when base objects enter or exit edit mode.

        This method is called periodically via a timer to identify if a Sketch 
        or Draft Wire managed by an HVAC network is currently being edited. 
        It toggles the visibility of derived 3D geometry through the network 
        proxy to facilitate editing.
        """        
        if not FreeCAD.GuiUp or Gui.ActiveDocument is None:
            return

        # Query the current edited object
        in_edit = Gui.ActiveDocument.getInEdit()
        obj = getattr(in_edit, "Object", None) if in_edit else None

        # Check if the object type is relevant
        if not ( hvaclib.isSketch(obj) or hvaclib.isWire(obj) ):
            if self._edited_base_obj is not None:
                self._finishEditedBaseObject()
            return

        # Find the owning network
        net = hvaclib.getOwnerNetwork(obj)
        if net is None:
            if self._edited_base_obj is not None:
                self._finishEditedBaseObject()
            return

        # If the same object is still being edited
        if self._edited_net is net and self._edited_base_obj is obj:
            return

        # If editing switched to a different object
        if self._edited_base_obj is not None:
            self._finishEditedBaseObject()

        # Record the new editing state
        self._edited_net = net
        self._edited_base_obj = obj

        # Hide the geometry belonging to that base object
        proxy = getattr(net, "Proxy", None)
        if proxy:
            proxy.setBaseObjectEditing(obj, True)
            
        # Suspend sync to prevent transient sync requests while editing
        if net and hasattr(net, "Proxy") and net.Proxy:
            net.Proxy.suspendSync()
            
        # Setup and manage observers
        if not self.edit_observer:
            def callback(obj, sketch):
                pass
                
            if hvaclib.isSketch(obj):
                self.edit_observer = SketchObserver(self._edited_net, callback, edit_mode=True)
                self.edit_observer.set_modified_sketch(obj)
            elif hvaclib.isWire(obj):
                self.edit_observer = DraftLineObserver(self._edited_net, callback, edit_mode=True)
                self.edit_observer.set_modified_line(obj)
                
            FreeCAD.addDocumentObserver(self.edit_observer)
            self.edit_observer._sync_arrows()
            FreeCAD.ActiveDocument.recompute()


def buildArrowCoinNodes(lines, size_scale=1.0):
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

    for sp, ep in lines:
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

def iter_line_segments_from_shape(obj, tol=1e-9):
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
            hvaclib.vec_to_xyz(v1),
            hvaclib.vec_to_xyz(v2)
        )
