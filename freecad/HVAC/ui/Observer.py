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

import json
import math
import FreeCAD
import FreeCADGui as Gui
from freecad.HVAC.core.Segment import DuctSegment
from pivy import coin
from PySide import QtWidgets, QtCore, QtGui
from PySide.QtCore import QT_TRANSLATE_NOOP
translate = FreeCAD.Qt.translate

from ..utils import hvaclib
from ..ui import Toolbar
from ..core import _component_results
from ..library.construction import ROLE_FLOW_SURFACE, ROLE_STRUCTURAL_SHELL


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

        # Create temporary toolbar
        self._temp_toolbar = Toolbar.FloatingBaseEditToolbar
        Toolbar.create_toolbar(self._temp_toolbar)

    def slotCreatedObject(self, obj):
        # Called when a new object is created in the document
        if self.finished or self.tracked_sketch is not None or self.edit_mode:
            return
        if obj and obj.Document == self.doc and hvaclib.isSketch(obj):
            self.tracked_sketch = obj
            self._attach_arrows()
            Toolbar.show_toolbar(self._temp_toolbar)
            
    def set_modified_sketch(self, sketch):
        """Set the modified sketch and attach arrows if in edit mode."""
        if self.edit_mode:
            self.tracked_sketch = sketch
            self._attach_arrows()
            Toolbar.show_toolbar(self._temp_toolbar)
            
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
            Toolbar.hide_toolbar(self._temp_toolbar)
        
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
                

class DuctDirectionEditSession:
    """
    Temporary edit mode for reversing base-object directions.

    Behaviour:
    - enable base direction arrows
    - hide generated geometry
    - suspend network sync
    - set reverse-direction cursor
    - selecting a base edge/object runs HVAC_ReverseGeometryDirection
    - on exit, restore visibility, arrows, sync, and cursor
    """

    def __init__(self, network_obj):
        self.network_obj = network_obj
        self.doc = getattr(network_obj, "Document", None)
        self.active = False
        self._busy = False
        self._old_show_arrows = None
        self._cursor_set = False

    def start(self):
        if self.active:
            return

        if self.network_obj is None or self.doc is None:
            return

        self.active = True

        # Make this network active.
        try:
            self.network_obj.Proxy.setActive()
        except Exception:
            pass

        # Suspend sync while directions are being edited.
        try:
            self.network_obj.Proxy.suspendSync()
        except Exception:
            pass

        # Hide generated duct geometry.
        try:
            self.network_obj.Proxy.hideAllGeometry()
        except Exception:
            pass

        # Enable base direction arrows.
        try:
            vobj = self.network_obj.ViewObject
            self._old_show_arrows = bool(vobj.ShowBaseDirectionArrows)
            vobj.ShowBaseDirectionArrows = True
            self.network_obj.ViewObject.Proxy.refreshBaseDirectionArrows()
        except Exception:
            pass

        # Change cursor to reverse command icon.
        self._setCursor()

        # Observe selection.
        Gui.Selection.addObserver(self)

        FreeCAD.Console.PrintMessage(
            "HVAC - Direction edit mode started. Select base edges/objects to reverse.\n"
        )

    def stop(self, request_sync=True):
        if not self.active:
            return

        self.active = False

        try:
            Gui.Selection.removeObserver(self)
        except Exception:
            pass

        self._restoreCursor()

        # Disable or restore direction arrows.
        try:
            vobj = self.network_obj.ViewObject
            if self._old_show_arrows is not None:
                vobj.ShowBaseDirectionArrows = self._old_show_arrows
            else:
                vobj.ShowBaseDirectionArrows = False
            self.network_obj.ViewObject.Proxy.refreshBaseDirectionArrows()
        except Exception:
            pass

        # Show generated geometry again.
        try:
            self.network_obj.Proxy.showAllGeometry()
        except Exception:
            pass

        # Resume sync and request network update.
        try:
            self.network_obj.Proxy.resumeSync(request_sync=request_sync)
        except Exception:
            pass

        try:
            FreeCAD.ActiveDocument.recompute()
        except Exception:
            pass

        FreeCAD.Console.PrintMessage("HVAC - Direction edit mode closed.\n")

    # -------------------------------------------------
    # Selection observer API
    # -------------------------------------------------

    def addSelection(self, doc_name, obj_name, sub_name, point):
        if not self.active or self._busy:
            return

        doc = FreeCAD.getDocument(doc_name)
        if doc is None or doc != self.doc:
            return

        obj = doc.getObject(obj_name)
        if obj is None:
            return

        # Only act on base objects belonging to this network.
        if obj not in list(getattr(self.network_obj.Base, "OutList", []) or []):
            return

        if not (hvaclib.isSketch(obj) or hvaclib.isWire(obj)):
            return

        # For sketches, only reverse selected edges.
        # Ignore full sketch selection without EdgeN subelement.
        if hvaclib.isSketch(obj) and not str(sub_name or "").startswith("Edge"):
            return

        self._busy = True
        try:
            Gui.runCommand("HVAC_ReverseGeometryDirection")

            # Rebuild only direction arrows, not generated geometry.
            try:
                parser = self.network_obj.Proxy.getParser(
                    rebuild=True,
                    set_node_groups=False,
                )
                self.network_obj.ViewObject.Proxy.refreshBaseDirectionArrows(parser)
            except Exception:
                self.network_obj.ViewObject.Proxy.refreshBaseDirectionArrows()

            # Clear selection so the same edge can be clicked again.
            QtCore.QTimer.singleShot(0, Gui.Selection.clearSelection)

        finally:
            self._busy = False

    # -------------------------------------------------
    # Cursor handling
    # -------------------------------------------------

    def _setCursor(self):
        try:
            icon_path = hvaclib.get_icon_path("ReverseDirection.svg")
            pixmap = QtGui.QPixmap(icon_path)
            if not pixmap.isNull():
                cursor = QtGui.QCursor(pixmap.scaled(24, 24))
                QtWidgets.QApplication.setOverrideCursor(cursor)
                self._cursor_set = True
        except Exception:
            self._cursor_set = False

    def _restoreCursor(self):
        try:
            QtWidgets.QApplication.restoreOverrideCursor()
        except Exception:
            pass
        self._cursor_set = False


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

    # Property edits wait for their transaction (see _type_schema.request_sync_after_edit):
    # the property editor commits it when a typed value is entered (Enter or
    # leaving the field), and aborts it on Escape (the value goes back).
    def slotCommitTransaction(self, doc):
        self._flushEditSyncs(doc)

    def slotAbortTransaction(self, doc):
        self._flushEditSyncs(doc)

    def _flushEditSyncs(self, doc):
        for net in hvaclib.allHVACNetworks(doc):
            proxy = getattr(net, "Proxy", None)
            if proxy is not None and hasattr(proxy, "runEditSync"):
                # After the commit/abort has finished, not inside it.
                QtCore.QTimer.singleShot(0, proxy.runEditSync)

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

    def _startEditedBaseObject(self, obj):
        """
        Begin tracking `obj` -- the actual App document object, not a
        ViewProvider -- as the base object now in edit mode.

        Extracted from the old polling _checkEditedBaseObject() so both
        slotInEdit() (the normal, event-driven path) and
        _checkEditedBaseObject() (a one-time bootstrap for an edit session
        already in progress when the workbench activates -- see its own
        docstring) share the exact same logic.
        """
        # Only HVAC-supported base object types are relevant.
        if not (hvaclib.isSketch(obj) or hvaclib.isWire(obj)):
            return

        # Find the owning network.
        net = hvaclib.getOwnerNetwork(obj)
        if net is None:
            return

        # Already tracking this exact network/object -- nothing to do.
        if self._edited_net is net and self._edited_base_obj is obj:
            return

        # Editing switched to a different object -- close out the old one first.
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

    def slotInEdit(self, vobj):
        """
        Gui document observer callback -- fired the instant a ViewProvider
        actually enters edit mode. Replaces the old getInEdit() poll, which
        could observe a still-None edit state during FreeCAD's transition
        into edit mode and miss the edited object entirely; this fires only
        once the transition is complete, so there's no window to race.
        """
        obj = getattr(vobj, "Object", None)
        if obj is not None:
            self._startEditedBaseObject(obj)

    def slotResetEdit(self, vobj):
        """Gui document observer callback -- fired when edit mode ends."""
        obj = getattr(vobj, "Object", None)
        if obj is self._edited_base_obj:
            self._finishEditedBaseObject()

    def _checkEditedBaseObject(self):
        """
        One-time bootstrap only -- NOT a periodic poll. slotInEdit()/
        slotResetEdit() above are the normal, event-driven mechanism; this
        method exists solely for the case where the HVAC workbench is
        activated while some object is already mid-edit, since no
        slotInEdit() fires for an edit session that started before this
        observer was registered. Scheduled to run exactly once, via
        QtCore.QTimer.singleShot(0, ...), right after the observer is
        created (see init_gui.py's setObservers()).
        """
        if not FreeCAD.GuiUp or Gui.ActiveDocument is None:
            return

        in_edit = Gui.ActiveDocument.getInEdit()
        obj = getattr(in_edit, "Object", None) if in_edit else None
        if obj is not None:
            self._startEditedBaseObject(obj)


class DuctNetworkGuiEditObserver:
    """
    Minimal Gui document observer adapter, forwarding slotInEdit()/
    slotResetEdit() to a DuctNetworkChangeObserver instance.

    Kept separate (registered via Gui.addDocumentObserver()) rather than
    making DuctNetworkChangeObserver itself both an App and a Gui document
    observer -- App and Gui document observers are two distinct FreeCAD
    registrations with two distinct callback surfaces (property/undo-redo
    vs. edit-mode/view events), and mixing both sets of slots onto one
    object blurs which registration is responsible for which behaviour.
    """

    def __init__(self, owner):
        self.owner = owner

    def slotInEdit(self, vobj):
        self.owner.slotInEdit(vobj)

    def slotResetEdit(self, vobj):
        self.owner.slotResetEdit(vobj)


class DuctNetworkSelectionObserver:
    def __init__(self):
        self._redirecting = False

    @staticmethod
    def _is_component(obj):
        proxy = getattr(obj, "Proxy", None)
        return getattr(proxy, "TYPE", "") in ("DuctComponent", "DuctSegment")

    def _resolveComponent(self, doc_name, obj_name, sub_name):
        """Look up obj_name and return it if it's a redirectable component
        with a sub-element picked, else None -- shared by addSelection and
        setPreselection, which redirect clicks resp. hover highlighting the
        same way."""
        if self._redirecting or not sub_name:
            return None
        doc = FreeCAD.getDocument(doc_name)
        if doc is None:
            return None
        obj = doc.getObject(obj_name)
        if obj is None or not self._is_component(obj):
            return None
        return obj

    def addSelection(self, doc_name, obj_name, sub_name, pos):
        obj = self._resolveComponent(doc_name, obj_name, sub_name)
        if obj is None:
            return
        self._redirecting = True
        try:
            Gui.Selection.removeSelection(doc_name, obj_name, sub_name)
            Gui.Selection.addSelection(obj)
        finally:
            self._redirecting = False

    def setPreselection(self, doc_name, obj_name, sub_name):
        obj = self._resolveComponent(doc_name, obj_name, sub_name)
        if obj is None:
            return
        self._redirecting = True
        try:
            QtCore.QTimer.singleShot(0, Gui.Selection.clearPreselection)
            QtCore.QTimer.singleShot(0, lambda: Gui.Selection.setPreselection(obj, ""))
        finally:
            self._redirecting = False


class FlowBoundaryDialog(QtWidgets.QDialog):
    """
    Terminal/port popup for editing a junction's Flow Condition (Auto/
    Fixed/Closed) and Flow Rate together -- see FlowBoundary/DesignFlowRate
    on core/Junction.py. Reads/writes the real FreeCAD properties directly
    (no separate dialog-side state): the dialog is seeded from the
    junction's current properties, and the properties are only ever written
    once, on accept.

    Never references a type id/family name -- a locked terminal (e.g. a
    duct closure/end cap) is detected purely from the Primary component's
    plain FlowBoundaryLocked bool, so this dialog stays generic across
    whatever library types happen to prescribe/lock a flow condition.
    """

    CONDITIONS = ("Auto", "Fixed", "Closed")

    def __init__(self, junction, parent=None):
        super().__init__(parent)
        self.setWindowTitle(translate("HVAC", "Flow Condition"))

        primary = junction.Proxy.getPrimaryComponent() if getattr(junction, "Proxy", None) else None
        self.locked = bool(getattr(primary, "FlowBoundaryLocked", False)) if primary is not None else False
        current_condition = str(getattr(junction, "FlowBoundary", "Auto") or "Auto")
        current_rate = float(getattr(junction, "DesignFlowRate", 0.0) or 0.0)

        layout = QtWidgets.QFormLayout(self)

        self.condition_combo = QtWidgets.QComboBox()
        self.condition_combo.addItems([
            translate("HVAC", "Auto"), translate("HVAC", "Fixed"), translate("HVAC", "Closed"),
        ])
        self.condition_combo.setCurrentIndex(self.CONDITIONS.index(current_condition))
        layout.addRow(translate("HVAC", "Flow Condition:"), self.condition_combo)

        self.rate_spin = QtWidgets.QDoubleSpinBox()
        self.rate_spin.setRange(0.0, 1.0e6)
        self.rate_spin.setDecimals(2)
        self.rate_spin.setSuffix(" L/s")
        self.rate_spin.setValue(current_rate)
        layout.addRow(translate("HVAC", "Flow Rate:"), self.rate_spin)

        if self.locked:
            self.condition_combo.setEnabled(False)
            self.rate_spin.setEnabled(False)
            note = QtWidgets.QLabel(
                translate("HVAC", "Locked by the selected fitting type.")
            )
            layout.addRow(note)
        else:
            self.condition_combo.currentIndexChanged.connect(self._onConditionChanged)
            self._onConditionChanged(self.condition_combo.currentIndex())

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _onConditionChanged(self, index):
        condition = self.CONDITIONS[index]
        if condition == "Fixed":
            self.rate_spin.setEnabled(True)
        else:
            if condition == "Closed":
                self.rate_spin.setValue(0.0)
            self.rate_spin.setEnabled(False)

    def condition(self):
        return self.CONDITIONS[self.condition_combo.currentIndex()]

    def rate(self):
        return self.rate_spin.value()


class TerminalFlowRateObserver:
    """
    Session-scoped 3D overlay, active while a Calculate Airflow / Size
    Ducts task panel is open: draws one colored flow-direction arrow plus
    one colored port plane at every terminal ("end" topology) junction in
    the network -- green if that terminal's Flow Condition is "Fixed",
    orange if it's "Closed" (a sealed terminal), red if it's still "Auto"
    -- and lets a user click an arrow to edit that terminal's Flow
    Condition/Flow Rate from a dialog (FlowBoundaryDialog, above). Purely visual/
    interactive -- like buildArrowCoinNodes'/buildPortHighlightCoinNode's
    own overlays, this never touches the document or undo stack except
    for the one property write a user explicitly makes through the
    dialog.

    Both the arrow's length and its separation from the terminal scale
    with that terminal's own duct dimension (the larger of width/height,
    or diameter) -- length equal to that dimension, separation 20% of it
    -- rather than a fixed size, so it reads sensibly against ducts of any
    size. The port plane reuses buildPortHighlightCoinNode's own "2x port
    dimension, translated to the port's real (post-fitting) position"
    convention, exactly like TaskPanelEditInlineComponents' own port
    highlight.

    Clicking is handled with a plain Coin3D SoEventCallback + its own
    built-in pick, checked against each arrow's/plane's own SoSeparator --
    these are never real FreeCAD document objects, so FreeCAD's normal
    Gui.Selection mechanism can't see them on its own. Both the arrow and
    its port plane are pickable -- only the text label is decorative only.
    """

    FALLBACK_DIMENSION_MM = 100.0
    SEPARATION_FRACTION = 0.2
    COLOR_SET = (0.0, 0.7, 0.0)
    COLOR_UNSET = (0.85, 0.0, 0.0)
    COLOR_CLOSED = (1.0, 0.55, 0.0)
    COLOR_TEXT = (0, 0, 0)
    TRANSPARENCY = 0.5
    DIALOG_DELAY_MS = 200
    SELECTION_CLEAR_DELAY_MS = 250

    def __init__(self, network_obj):
        self.network_obj = network_obj
        self._root = None
        self._event_callback_node = None
        self._arrows = []  # [(SoSeparator, junction_obj), ...] -- pickable
        self._planes = []  # [(SoSeparator, junction_obj), ...] -- pickable
        self._labels = []  # [SoSeparator, ...] -- decorative only
        self._label_orienter = LabelOrienter()
        self._attached = False

    def start(self):
        vobj = getattr(self.network_obj, "ViewObject", None)
        if vobj is None:
            return
        self._root = coin.SoSeparator()
        self._event_callback_node = coin.SoEventCallback()
        self._event_callback_node.addEventCallback(
            coin.SoMouseButtonEvent.getClassTypeId(), self._onMouseClick
        )
        self._root.addChild(self._event_callback_node)
        vobj.RootNode.addChild(self._root)
        self._attached = True
        self._label_orienter.start()
        self.refresh()

    def stop(self):
        if self._root is not None:
            try:
                vobj = getattr(self.network_obj, "ViewObject", None)
                if vobj is not None and self._attached:
                    vobj.RootNode.removeChild(self._root)
            except Exception:
                pass
        self._root = None
        self._event_callback_node = None
        self._arrows = []
        self._planes = []
        self._labels = []
        self._label_orienter.stop()
        self._attached = False

    def setVisible(self, visible):
        """
        Detach/reattach this whole overlay from the ViewObject's own scene
        graph, without tearing down _arrows/_planes/_labels -- used by
        AirflowResultObserver to hide the terminal flow-rate overlay while
        its own junction/segment result overlay is showing (the two would
        otherwise clutter the same terminal junctions), and show it again
        once both of that observer's overlays are switched off.
        """
        vobj = getattr(self.network_obj, "ViewObject", None)
        if vobj is None or self._root is None:
            return
        visible = bool(visible)
        if visible and not self._attached:
            vobj.RootNode.addChild(self._root)
            self._attached = True
        elif not visible and self._attached:
            vobj.RootNode.removeChild(self._root)
            self._attached = False

    def refresh(self):
        """Rebuild every terminal's arrow/plane/label from the junctions' current DesignFlowRate/geometry."""
        if self._root is None:
            return
        # Child 0 is the event callback node -- keep it, drop only the arrows/planes/labels.
        while self._root.getNumChildren() > 1:
            self._root.removeChild(self._root.getNumChildren() - 1)
        self._arrows = []
        self._planes = []
        self._labels = []
        self._label_orienter.clear()

        for junction in self._terminalJunctions():
            self._buildOverlayForJunction(junction)

    def _terminalJunctions(self):
        geometry = getattr(self.network_obj, "Geometry", None)
        if geometry is None:
            return []
        return [
            obj for obj in geometry.OutList
            if hvaclib.isDuctJunction(obj) and getattr(obj, "Topology", "") == "end"
        ]

    def _buildOverlayForJunction(self, junction):
        center = getattr(junction, "CenterPoint", None)
        if center is None:
            return
        try:
            analysis = json.loads(getattr(junction, "AnalysisJson", "") or "{}")
        except Exception:
            analysis = {}
        ports = analysis.get("connected_ports") or []
        if not ports:
            return

        port = ports[0]
        direction = port.get("direction")
        flow_into_junction = port.get("flow_into_junction")
        if not direction or flow_into_junction is None:
            return

        width, height = hvaclib.get_section_extents(port.get("section_params", {}) or {})
        dimension = max(width, height) if (width > 0.0 and height > 0.0) else self.FALLBACK_DIMENSION_MM
        separation = dimension * self.SEPARATION_FRACTION

        design_flow_rate = float(getattr(junction, "DesignFlowRate", 0.0) or 0.0)
        flow_boundary = str(getattr(junction, "FlowBoundary", "Auto") or "Auto")
        if flow_boundary == "Closed":
            color = self.COLOR_CLOSED
        elif flow_boundary == "Auto":
            color = self.COLOR_UNSET
        else:
            color = self.COLOR_SET

        plane_port = hvaclib.translated_port_position(junction, port)
        arrow_origin = plane_port.get("position", center)

        arrow_node = buildTerminalFlowArrowCoinNode(
            arrow_origin, direction, bool(flow_into_junction), separation, dimension, color, self.TRANSPARENCY,
        )
        if arrow_node is not None:
            self._root.addChild(arrow_node)
            self._arrows.append((arrow_node, junction))

        plane_node = buildPortHighlightCoinNode(plane_port, color=color, transparency=self.TRANSPARENCY)
        if plane_node is not None:
            self._root.addChild(plane_node)
            self._planes.append((plane_node, junction))

        if flow_boundary == "Fixed":
            label_text = "{:.0f} L/s".format(design_flow_rate)
        elif flow_boundary == "Closed":
            label_text = "Closed"
        else:
            label_text = "Auto"
        label_node = buildFlowRateLabelCoinNode(
            plane_port, label_text, self.COLOR_TEXT, orienter=self._label_orienter
        )
        if label_node is not None:
            self._root.addChild(label_node)
            self._labels.append(label_node)

    def _onMouseClick(self, user_data, event_callback):
        event = event_callback.getEvent()
        if not (
            isinstance(event, coin.SoMouseButtonEvent)
            and event.getButton() == coin.SoMouseButtonEvent.BUTTON1
        ):
            return

        picked = event_callback.getPickedPoint()
        if picked is None:
            return

        junction = self._junctionForPickedPath(picked.getPath())
        if junction is None:
            return

        # Consume both the press AND the release for this click -- opening
        # a modal dialog on DOWN means the matching BUTTON1 UP event
        # arrives as a separate callback invocation afterwards; leaving
        # that one unhandled let FreeCAD's own selection logic treat it as
        # a stray click and pop its Object/Face/Edge/Other picker menu.
        event_callback.setHandled()

        if event.getState() != coin.SoButtonEvent.DOWN:
            return

        # The dialog has to open asynchronously -- opening it straight from
        # this callback keeps the mouse button looking "held" for as long
        # as the modal dialog is up, which FreeCAD reads as a long-press
        # and pops its own Object/Face/Edge/Other clarify-selection menu.
        # But going async means this click still completes as an ordinary
        # FreeCAD selection before our dialog opens, so clear that stray
        # selection shortly after -- nothing should stay highlighted just
        # from clicking a flow arrow.
        QtCore.QTimer.singleShot(self.DIALOG_DELAY_MS, lambda j=junction: self._openFlowRateDialog(j))
        QtCore.QTimer.singleShot(self.SELECTION_CLEAR_DELAY_MS, Gui.Selection.clearSelection)

    def _junctionForPickedPath(self, path):
        for node, junction in self._arrows + self._planes:
            if path.containsNode(node):
                return junction
        return None

    def _openFlowRateDialog(self, junction):
        dialog = FlowBoundaryDialog(junction, Gui.getMainWindow())
        if dialog.exec_() != QtWidgets.QDialog.Accepted or dialog.locked:
            return

        condition = dialog.condition()
        rate = 0.0 if condition != "Fixed" else dialog.rate()
        changed = False
        if str(getattr(junction, "FlowBoundary", "Auto") or "Auto") != condition:
            junction.FlowBoundary = condition
            changed = True
        if condition == "Fixed" and float(getattr(junction, "DesignFlowRate", 0.0) or 0.0) != rate:
            junction.DesignFlowRate = rate
            changed = True

        if changed:
            doc = getattr(junction, "Document", None)
            if doc is not None:
                doc.recompute()
        self.refresh()


def valueToHeatColor(value, min_value, max_value):
    """
    Map `value` onto a blue (low) -> yellow (mid) -> red (high) heat-map
    color, given the current [min_value, max_value] range -- the one
    shared color scale AirflowResultObserver uses for both its junction
    planes and segment overlays, whichever result parameter is currently
    selected to drive color. A degenerate range (max_value <= min_value,
    e.g. every value in view happens to be identical) returns the
    mid-scale color rather than dividing by zero.
    """
    if max_value <= min_value:
        t = 0.5
    else:
        t = (value - min_value) / (max_value - min_value)
    t = max(0.0, min(1.0, t))
    if t < 0.5:
        f = t / 0.5
        return (f, f, 1.0 - f)
    f = (t - 0.5) / 0.5
    return (1.0, 1.0 - f, 0.0)


def _buildLegendBarCoinNode(label, min_value, max_value, row_index=0, steps=24):
    """
    Build one screen-space HUD node: a horizontal color-scale gradient bar
    (following valueToHeatColor) with a caption and min/max value labels,
    pinned near the bottom-left of the 3D view -- see
    AirflowResultObserver._refreshLegend.

    Uses Coin's standard "orthographic camera with viewportMapping =
    LEAVE_ALONE" HUD technique: an SoOrthographicCamera set up this way,
    plus everything drawn after it inside the same SoSeparator, lands in a
    fixed [-1, 1] normalized-viewport space rather than world space, so
    the legend stays put on screen regardless of how the real camera pans,
    zooms, or rotates. The depth test is switched off so it always draws
    on top of the model.

    row_index: 0 for the bottom-most legend; each further row stacks
    directly above it -- lets a caller show both a junction and a segment
    legend at once without them overlapping.
    """
    root = coin.SoSeparator()
    root.renderCaching.setValue(coin.SoSeparator.OFF)

    pick_style = coin.SoPickStyle()
    pick_style.style.setValue(coin.SoPickStyle.UNPICKABLE)
    root.addChild(pick_style)

    try:
        depth = coin.SoDepthBuffer()
        depth.test.setValue(False)
        root.addChild(depth)
    except AttributeError:
        pass  # older Coin builds without SoDepthBuffer -- legend still draws, just depth-tested

    camera = coin.SoOrthographicCamera()
    camera.viewportMapping.setValue(coin.SoCamera.LEAVE_ALONE)
    camera.position.setValue(0, 0, 5)
    camera.nearDistance.setValue(1.0)
    camera.farDistance.setValue(10.0)
    camera.height.setValue(2.0)
    root.addChild(camera)

    light_model = coin.SoLightModel()
    light_model.model.setValue(coin.SoLightModel.BASE_COLOR)
    root.addChild(light_model)

    bar_width = 0.5
    bar_height = 0.04
    row_step = 0.2
    base_x = -0.95
    base_y = -0.92 + row_index * row_step

    caption = coin.SoSeparator()
    caption_translate = coin.SoTranslation()
    caption_translate.translation.setValue(base_x, base_y + bar_height + 0.02, 0)
    caption.addChild(caption_translate)
    caption_mat = coin.SoMaterial()
    caption_mat.diffuseColor.setValue(0, 0, 0)
    caption.addChild(caption_mat)
    caption_font = coin.SoFont()
    caption_font.size.setValue(16.0)
    caption.addChild(caption_font)
    caption_text = coin.SoText2()
    caption_text.string.setValue(str(label))
    caption_text.justification.setValue(coin.SoText2.LEFT)
    caption.addChild(caption_text)
    root.addChild(caption)

    # Gradient bar: `steps` adjoining quads sweeping min_value -> max_value
    # through valueToHeatColor -- Coin has no built-in gradient fill.
    step_width = bar_width / float(max(steps, 1))
    for i in range(steps):
        t = i / float(max(steps - 1, 1))
        value = min_value + t * (max_value - min_value)
        color = valueToHeatColor(value, min_value, max_value)
        x0 = base_x + i * step_width
        x1 = x0 + step_width

        quad_sep = coin.SoSeparator()
        mat = coin.SoMaterial()
        mat.diffuseColor.setValue(*color)
        quad_sep.addChild(mat)
        coords = coin.SoCoordinate3()
        coords.point.setValues(0, 4, [
            (x0, base_y, 0), (x1, base_y, 0), (x1, base_y + bar_height, 0), (x0, base_y + bar_height, 0),
        ])
        quad_sep.addChild(coords)
        face = coin.SoFaceSet()
        face.numVertices.setValue(4)
        quad_sep.addChild(face)
        root.addChild(quad_sep)

    for value, x, justification in (
        (min_value, base_x, coin.SoText2.LEFT),
        (max_value, base_x + bar_width, coin.SoText2.RIGHT),
    ):
        value_sep = coin.SoSeparator()
        value_translate = coin.SoTranslation()
        value_translate.translation.setValue(x, base_y - 0.05, 0)
        value_sep.addChild(value_translate)
        value_mat = coin.SoMaterial()
        value_mat.diffuseColor.setValue(0, 0, 0)
        value_sep.addChild(value_mat)
        value_font = coin.SoFont()
        value_font.size.setValue(16.0)
        value_sep.addChild(value_font)
        value_text = coin.SoText2()
        value_text.string.setValue("{:.1f}".format(value))
        value_text.justification.setValue(justification)
        value_sep.addChild(value_text)
        root.addChild(value_sep)

    return root


def _element_label(obj):
    """Number, else Label, else Name -- how results name a duct or node."""
    return str(getattr(obj, "Number", "") or getattr(obj, "Label", "") or getattr(obj, "Name", ""))


class AirflowResultObserver:
    """
    Session-scoped 3D overlay, active while a Calculate Airflow results
    panel is open and at least one of its two "Enable" checkboxes is on:
    draws a colored plane (plus a small flow-direction arrow attached at
    its top-right corner) at every real port of every solved junction,
    and/or a colored solid box encapsulating every solved segment's own
    length -- colored by whichever result parameter is currently
    selected (junction: Flow Rate/Static Pressure; segment: Velocity/
    Friction Drop/Pressure Loss) via valueToHeatColor(), auto-ranged over
    every value currently in view. Text values (all of a node's own
    result numbers) are always shown, regardless of which one drives
    color. Both Flow Rate and Static Pressure are genuinely per-port: each
    leg of a multiport fitting shows its own value, sourced from the
    retained per-port fitting result where available (see
    _junctionPortFlow/_junctionPortStaticPressure) -- falling back to the
    junction's own single shared value only for a port with no such
    result (an inlet, or a terminal with no fitting loss at all).

    Reuses TerminalFlowRateObserver's own Coin builder functions
    (buildPortHighlightCoinNode/buildFlowRateLabelCoinNode/
    buildTerminalFlowArrowCoinNode) rather than duplicating geometry code.
    No click handling (unlike TerminalFlowRateObserver); the only input it
    reads is mouse movement, for the hover tooltip: once the mouse rests
    (HOVER_DELAY_MS) it ray-picks its own planes and boxes, else asks the
    view for the duct or fitting under the cursor, and shows that result as
    a tooltip-style popup of its own (text from core/_component_results.py). Like that overlay, this
    never touches the document/undo stack, with one deliberate exception:
    while either visualization is enabled, every segment/component's own
    ShapeAppearance in the network is temporarily overridden to a neutral
    gray (snapshotted first, and restored exactly when both are disabled
    or the observer stops), so the result overlay's own colors read
    clearly against a de-emphasized duct model.

    While either overlay is on, TerminalFlowRateObserver's own terminal
    arrow/plane overlay is hidden (via its setVisible()) rather than left
    showing underneath -- otherwise the two would double up on the same
    terminal junctions -- and shown again once both are switched off.

    Also draws a horizontal color-scale legend HUD, pinned to the bottom
    left of the 3D view regardless of camera pan/zoom/rotation -- see
    _refreshLegend/_buildLegendBarCoinNode.
    """

    NEUTRAL_COLOR = (0.6, 0.6, 0.6)
    JUNCTION_ARROW_LENGTH_FRACTION = 0.4  # fraction of the port's own dimension
    JUNCTION_ARROW_INSET_FRACTION = 0.15  # how far inside the plane's corner the arrow's base sits
    JUNCTION_TOP_EXTEND = 0.5  # extra plane height above the port's own top edge, for text/arrow room
    SEGMENT_OVERLAY_SCALE = 1.25  # multiplies (duct dimension + 2 x outward construction-layer growth)
    TRANSPARENCY = 0.4
    COLOR_TEXT = (0, 0, 0)
    LEGEND_STEPS = 24  # gradient slices drawn across the legend bar

    # Result tooltip (Stage 9 item 1): shown once the mouse has rested this long.
    HOVER_DELAY_MS = 350
    HOVER_PICK_RADIUS = 4
    # The tooltip stays while the cursor is within this many pixels of where
    # it opened; moving further closes it and re-picks.
    HOVER_HOLD_PX = 10
    HOVER_WATCH_MS = 200

    JUNCTION_COLOR_FIELDS = ("flow_rate", "static_pressure")
    JUNCTION_COLOR_LABELS = {
        "flow_rate": "Flow Rate (L/s)",
        "static_pressure": "Static Pressure (Pa)",
    }
    SEGMENT_COLOR_FIELDS = ("velocity", "friction_drop", "pressure_loss")
    SEGMENT_COLOR_LABELS = {
        "velocity": "Velocity (m/s)",
        "friction_drop": "Friction Drop (Pa)",
        "pressure_loss": "Pressure Loss (Pa)",
    }

    def __init__(self, network_obj, result, terminal_observer=None):
        self.network_obj = network_obj
        self.result = result
        self._terminal_observer = terminal_observer
        self._root = None
        self._legend_root = None
        self._appearance_snapshot = {}  # {obj_name: [App.Material, ...] or None}
        self._label_orienter = LabelOrienter()

        self.junction_enabled = False
        self.junction_color_by = self.JUNCTION_COLOR_FIELDS[0]
        self.junction_range_override = None  # (min, max), or None for auto -- manual range: TODO, not yet exposed in the UI

        self.segment_enabled = False
        self.segment_color_by = self.SEGMENT_COLOR_FIELDS[0]
        self.segment_range_override = None  # (min, max), or None for auto -- manual range: TODO, not yet exposed in the UI

        # Hover tooltips: overlay nodes to describe, the last mouse position,
        # and an idle timer so picking only happens once the mouse rests.
        self._hover_root = None
        self._hover_targets = []  # [(SoNode, callable returning the tooltip text), ...]
        self._hover_pos = None
        self._hover_timer = None
        self._hover_shown_at = None  # (x, y) global cursor position the current tip opened at
        self._hover_watch = None
        self._tip = None

    def start(self):
        vobj = getattr(self.network_obj, "ViewObject", None)
        if vobj is None:
            return
        self._root = coin.SoSeparator()
        vobj.RootNode.addChild(self._root)
        self._label_orienter.start()
        self._attachHover(vobj)
        self._attachLegend()
        self.refresh()

    def stop(self):
        self._detachHover()
        self._label_orienter.stop()
        self._restoreAppearance()
        if self._root is not None:
            try:
                vobj = getattr(self.network_obj, "ViewObject", None)
                if vobj is not None:
                    vobj.RootNode.removeChild(self._root)
            except Exception:
                pass
        self._root = None
        self._detachLegend()
        if self._terminal_observer is not None:
            self._terminal_observer.setVisible(True)

    def setResult(self, result):
        """Point at a fresh AirflowSolveResult (e.g. after "Run Revised Calculation") and redraw."""
        self.result = result
        self.refresh()

    def setJunctionEnabled(self, enabled):
        self.junction_enabled = bool(enabled)
        self.refresh()

    def setJunctionColorBy(self, field_name):
        self.junction_color_by = field_name
        self.refresh()

    def setSegmentEnabled(self, enabled):
        self.segment_enabled = bool(enabled)
        self.refresh()

    def setSegmentColorBy(self, field_name):
        self.segment_color_by = field_name
        self.refresh()

    def refresh(self):
        if self._root is None:
            return
        self._root.removeAllChildren()
        self._hover_targets = []
        self._label_orienter.clear()

        active = self.junction_enabled or self.segment_enabled
        if active:
            self._applyNeutralAppearance()
        else:
            self._restoreAppearance()
        if self._terminal_observer is not None:
            self._terminal_observer.setVisible(not active)

        if self.junction_enabled:
            self._buildJunctionOverlays()
        if self.segment_enabled:
            self._buildSegmentOverlays()

        self._refreshLegend()

    # ------------------------------------------------------------------
    # Junction port planes
    # ------------------------------------------------------------------

    def _allJunctionResults(self):
        return [junc for comp in self.result.components for junc in comp.junctions]

    def _segmentResultsByKey(self):
        return {s.key: s for comp in self.result.components for s in comp.segments}

    def _primaryPortResultsByEdge(self):
        """
        {edge_key: ComponentPortRow} for every real edge with a retained
        Primary fitting result -- see core/AirflowSolver.ComponentPortRow /
        core/_component_results.py. A real edge is ever an "outlet" (the
        only role that gets a retained result) for at most one node, so
        there's never more than one entry per edge_key here.
        """
        return {
            row.edge_key: row
            for comp in self.result.components
            for row in comp.component_ports
            if row.component_role == "Primary"
        }

    @staticmethod
    def _junctionPortFlow(port, junc_res, port_row_by_edge, seg_by_key):
        """
        This specific port's own flow, not the junction's single lumped
        total_flow_lps repeated at every port -- each leg of a multiport
        fitting genuinely carries its own distinct flow (see
        core/_component_results.py). Prefers the new per-port fitting
        result (ComponentPortRow.flow_lps, populated for a port that
        received a fitting-loss contribution); falls back to that port's
        own connected segment (still per-port, just not retained as a
        fitting result -- e.g. an inlet leg, which never receives one);
        falls back to the junction's own total only if neither is
        resolvable (should not normally happen for a real port).

        port_row_by_edge is keyed purely by edge_key, with exactly one
        entry per real edge (from whichever node has that edge as an
        OUTLET -- see _primaryPortResultsByEdge). A real edge has two
        ends/ports (one per node it connects), so this port's own
        flow_into_junction must be checked before trusting that lookup --
        otherwise the edge's one retained row would get reused for BOTH
        of its ends, when it only ever describes the outlet side.
        """
        edge_key = port.get("edge_key")
        if port.get("flow_into_junction") is False:
            row = port_row_by_edge.get(edge_key)
            if row is not None:
                return row.flow_lps
        seg = seg_by_key.get(edge_key)
        if seg is not None:
            return seg.flow_lps
        return junc_res.total_flow_lps

    @staticmethod
    def _junctionPortStaticPressure(port, junc_res, port_row_by_edge):
        """
        This specific port's own static pressure -- an outlet leg (the
        only ports that ever get a retained fitting result) carries its
        own distinct value, already derived by analysis/pressure.py's
        Phase G from that same leg's own pressure_drop_pa (see
        ComponentPortRow.static_pressure_pa's own docstring: a real
        per-leg subtraction, not the node's value copied onto every port).
        Falls back to the junction's own shared static_pressure_pa for a
        port with no such entry (an inlet, or a terminal with no fitting
        loss at all) -- that IS this port's own correct value in those
        cases, since there is nothing to subtract away from it there.

        Same edge-role check as _junctionPortFlow: port_row_by_edge's one
        entry per edge only ever describes that edge's OUTLET side, so it
        must never be reused for the inlet side of the very same edge
        (that inlet port's own real value is its own node's static
        pressure, not the far end's).
        """
        edge_key = port.get("edge_key")
        if port.get("flow_into_junction") is False:
            row = port_row_by_edge.get(edge_key)
            if row is not None and row.static_pressure_pa is not None:
                return row.static_pressure_pa
        return junc_res.static_pressure_pa

    def _junctionPortValue(self, port, junc_res, port_row_by_edge, seg_by_key):
        """The value driving this port's own color/legend ranging."""
        if self.junction_color_by == "static_pressure":
            return self._junctionPortStaticPressure(port, junc_res, port_row_by_edge)
        return self._junctionPortFlow(port, junc_res, port_row_by_edge, seg_by_key)

    def _junctionPortEntries(self):
        """
        Every real port across every solved junction, each paired with its
        own JunctionResult, plus the two lookups _junctionPortValue/
        _junctionPortFlow need to resolve that port's own value -- shared
        by _buildJunctionOverlays (the actual overlay colors/labels) and
        _refreshLegend (the legend bar's own range), so the two can never
        drift apart. Returns ([(junction, port, junc_res), ...], seg_by_key,
        port_row_by_edge); the list is empty if nothing is solved yet.
        """
        junction_results = self._allJunctionResults()
        if not junction_results:
            return [], {}, {}
        seg_by_key = self._segmentResultsByKey()
        port_row_by_edge = self._primaryPortResultsByEdge()

        entries = []
        for junc_res in junction_results:
            junction = junc_res.obj
            try:
                analysis = json.loads(getattr(junction, "AnalysisJson", "") or "{}")
            except Exception:
                analysis = {}
            for port in analysis.get("connected_ports") or []:
                entries.append((junction, port, junc_res))
        return entries, seg_by_key, port_row_by_edge

    def _buildJunctionOverlays(self):
        junction_ports, seg_by_key, port_row_by_edge = self._junctionPortEntries()
        if not junction_ports:
            return

        values = [
            self._junctionPortValue(port, junc_res, port_row_by_edge, seg_by_key)
            for _, port, junc_res in junction_ports
        ]
        min_value, max_value = self.junction_range_override or (min(values), max(values))

        for junction, port, junc_res in junction_ports:
            value = self._junctionPortValue(port, junc_res, port_row_by_edge, seg_by_key)
            color = valueToHeatColor(value, min_value, max_value)
            self._buildJunctionPortOverlay(junction, port, junc_res, color, port_row_by_edge, seg_by_key)

    def _buildJunctionPortOverlay(self, junction, port, junc_res, color, port_row_by_edge, seg_by_key):
        direction = port.get("direction")
        flow_into_junction = port.get("flow_into_junction")
        if not direction or flow_into_junction is None:
            return

        real_port = hvaclib.translated_port_position(junction, port)

        # `direction` only says which way the port's own segment runs, not
        # which way air actually travels through it -- flow_into_junction
        # says that. Feeding the flow-travel direction into the plane/
        # arrow/label builders below (instead of the raw port direction)
        # keeps all three consistent with each other, and makes a viewer
        # standing where flow is actually headed see non-mirrored text --
        # see buildTerminalFlowArrowCoinNode's own arrow-direction
        # convention just below.
        display_direction = direction if flow_into_junction else tuple(-d for d in direction)
        display_port = dict(real_port)
        display_port["direction"] = display_direction

        plane_node = buildPortHighlightCoinNode(
            display_port, color=color, transparency=self.TRANSPARENCY, top_extend=self.JUNCTION_TOP_EXTEND,
        )
        if plane_node is not None:
            self._root.addChild(plane_node)
            self._hover_targets.append(
                (plane_node, lambda: self._portTooltip(junction, port, junc_res, port_row_by_edge, seg_by_key))
            )

        width, height = hvaclib.get_section_extents(display_port.get("section_params", {}) or {})
        dimension = max(width, height) if (width > 0.0 and height > 0.0) else 100.0
        arrow_length = dimension * self.JUNCTION_ARROW_LENGTH_FRACTION
        inset = dimension * self.JUNCTION_ARROW_INSET_FRACTION

        frame = _viewerFacingPlaneFrame(display_port, top_extend=self.JUNCTION_TOP_EXTEND)
        if frame is not None:
            origin, x_dir, y_dir, _, half_w, _, half_h_top = frame
            # The arrow's base always sits just inside the plane's own
            # top-right corner (never right at/beyond the edge). Passing
            # flow_into_junction=True unconditionally always selects
            # buildTerminalFlowArrowCoinNode's "base near, tip far" branch
            # -- combined with display_direction (already flipped above
            # when needed) this makes the tip always point in the port's
            # real flow-travel direction, with the base as the one fixed
            # attachment point regardless of which way flow runs.
            base_point = origin + x_dir * (half_w - inset) + y_dir * (half_h_top - inset)
            arrow_node = buildTerminalFlowArrowCoinNode(
                base_point, display_direction, True, 0.0, arrow_length, color, self.TRANSPARENCY,
            )
            if arrow_node is not None:
                self._root.addChild(arrow_node)

        # This port's own flow -- not the junction's single total repeated
        # at every port (see _junctionPortFlow's own docstring). Always
        # flow here, regardless of which field currently drives color.
        port_flow_lps = self._junctionPortFlow(port, junc_res, port_row_by_edge, seg_by_key)

        # Row 0's slot (the plane's newly-extended top strip) is left
        # clear for the arrow above -- text starts at row 1.
        flow_label = buildFlowRateLabelCoinNode(
            display_port, "{:.1f} L/s".format(port_flow_lps), self.COLOR_TEXT,
            row_index=1, top_extend=self.JUNCTION_TOP_EXTEND, orienter=self._label_orienter,
        )
        if flow_label is not None:
            self._root.addChild(flow_label)

        # This port's own static pressure -- not the junction's single
        # shared value repeated at every port (see
        # _junctionPortStaticPressure's own docstring).
        port_static_pressure_pa = self._junctionPortStaticPressure(port, junc_res, port_row_by_edge)
        pressure_label = buildFlowRateLabelCoinNode(
            display_port, "{:.1f} Pa".format(port_static_pressure_pa), self.COLOR_TEXT,
            row_index=2, top_extend=self.JUNCTION_TOP_EXTEND, orienter=self._label_orienter,
        )
        if pressure_label is not None:
            self._root.addChild(pressure_label)

    # ------------------------------------------------------------------
    # Segment overlays
    # ------------------------------------------------------------------

    def _allSegmentResults(self):
        return [seg for comp in self.result.components for seg in comp.segments]

    def _segmentValue(self, seg_res):
        if self.segment_color_by == "friction_drop":
            return seg_res.friction_loss_pa
        if self.segment_color_by == "pressure_loss":
            return seg_res.total_loss_pa
        return seg_res.velocity_ms

    @staticmethod
    def _outwardLayerGrowth(seg_obj):
        """
        Sum of every construction layer's own thickness that grows the
        section outward from the core wall -- every declared layer except
        the one(s) playing flow_surface/structural_shell (the base wall,
        which shrinks inward, not outward). Generalizes the old fixed
        InsulationThickness-only overlay margin to however many wrap layers
        a type declares (insulation, an outer jacket, ...); a layer with no
        declared thickness_property (or a not-yet-migrated type with no
        construction block at all) contributes 0.
        """
        library_id = getattr(seg_obj, "LibraryId", "")
        type_id = getattr(seg_obj, "TypeId", "")
        if not library_id or not type_id:
            return 0.0
        reg = hvaclib.HVACLibraryService.get_hvac_library_registry()
        type_def = reg.resolve_type(library_id, type_id)
        if type_def is None:
            return 0.0

        total = 0.0
        for ldef in getattr(type_def, "construction", []) or []:
            if ROLE_FLOW_SURFACE in ldef.roles or ROLE_STRUCTURAL_SHELL in ldef.roles:
                continue
            if not ldef.thickness_property:
                continue
            total += float(getattr(seg_obj, ldef.thickness_property, 0.0) or 0.0)
        return total

    @staticmethod
    def _segmentGeometry(seg_obj):
        """
        Pull a duct segment's own centerline (start, end, unit direction,
        midpoint, length) plus its profile axis/section/outward construction
        growth, shared by the segment overlay's solid box (spans
        start->end) and its text label (placed on the box's own top face --
        see _buildSegmentOverlays). Returns None if the segment has no
        usable geometry yet.
        """
        start = getattr(seg_obj, "EffectiveStartPoint", None)
        end = getattr(seg_obj, "EffectiveEndPoint", None)
        if start is None or end is None:
            return None
        start_v = FreeCAD.Vector(start)
        end_v = FreeCAD.Vector(end)
        direction = end_v - start_v
        length = direction.Length
        if length <= 1e-6:
            return None
        direction.normalize()

        profile_x_axis = None
        raw_axis = getattr(seg_obj, "ProfileXAxis", None)
        if raw_axis is not None and FreeCAD.Vector(raw_axis).Length > 1e-9:
            profile_x_axis = hvaclib.vec_to_xyz(raw_axis)

        return {
            "start": start_v,
            "end": end_v,
            "midpoint": (start_v + end_v) * 0.5,
            "direction": direction,
            "length": length,
            "profile_x_axis": profile_x_axis,
            "section_params": hvaclib.get_segment_section_params(seg_obj),
            "outward_growth": AirflowResultObserver._outwardLayerGrowth(seg_obj),
        }

    def _buildSegmentOverlays(self):
        segment_results = self._allSegmentResults()
        if not segment_results:
            return
        values = [self._segmentValue(s) for s in segment_results]
        min_value, max_value = self.segment_range_override or (min(values), max(values))

        for seg_res in segment_results:
            geometry = self._segmentGeometry(seg_res.obj)
            if geometry is None:
                continue
            color = valueToHeatColor(self._segmentValue(seg_res), min_value, max_value)

            width, height = hvaclib.get_section_extents(geometry["section_params"])
            if width <= 0.0 or height <= 0.0:
                width = height = 100.0
            # Overlay must clear the duct's own outward construction layers
            # (insulation, an outer jacket, ...), not just its bare core
            # wall -- grow by 2x their combined thickness (they wrap both
            # sides) before applying the overlay's own extra margin.
            outward_growth = geometry["outward_growth"]
            box_width = (width + 2.0 * outward_growth) * self.SEGMENT_OVERLAY_SCALE
            box_height = (height + 2.0 * outward_growth) * self.SEGMENT_OVERLAY_SCALE

            overlay_node = buildSegmentOverlayCoinNode(
                geometry["midpoint"], geometry["direction"], geometry["profile_x_axis"],
                box_width, box_height, geometry["length"],
                color, self.TRANSPARENCY,
            )
            if overlay_node is not None:
                self._root.addChild(overlay_node)
                self._hover_targets.append((overlay_node, lambda s=seg_res: self._segmentTooltip(s)))

            # Text sits on the box's own top (longitudinal) face -- not a
            # cross-sectional plane at one end -- running along the duct's
            # length rather than facing across it. box_y (the frame below)
            # is the box's "up"/height axis; make_profile_frame's own
            # y_dir = z_dir x x_dir, so re-deriving a frame with normal
            # box_y and preferred_x box_z(=direction) gives a face frame
            # whose own x_dir is the duct's length axis and whose own
            # y_dir is the box's width axis -- see the module docstring
            # note in _viewerFacingPlaneFrame for the "pass -direction"
            # convention that keeps the text from rendering mirrored.
            _, box_x, box_y, _ = hvaclib.make_profile_frame(
                geometry["direction"], geometry["profile_x_axis"], geometry["midpoint"],
            )
            top_face_center = geometry["midpoint"] + box_y * (box_height * 0.5)
            top_face_port = {
                "position": hvaclib.vec_to_xyz(top_face_center),
                "direction": hvaclib.vec_to_xyz(box_y * -1.0),
                "profile_x_axis": hvaclib.vec_to_xyz(geometry["direction"]),
                "section_params": {"Width": geometry["length"], "Height": box_width},
            }

            velocity_label = buildFlowRateLabelCoinNode(
                top_face_port, "{:.2f} m/s".format(seg_res.velocity_ms), self.COLOR_TEXT,
                row_index=0, scale=1.0, orienter=self._label_orienter,
            )
            if velocity_label is not None:
                self._root.addChild(velocity_label)

            friction_label = buildFlowRateLabelCoinNode(
                top_face_port, "{:.1f} Pa".format(seg_res.friction_loss_pa), self.COLOR_TEXT,
                row_index=1, scale=1.0, orienter=self._label_orienter,
            )
            if friction_label is not None:
                self._root.addChild(friction_label)

            loss_label = buildFlowRateLabelCoinNode(
                top_face_port, "{:.1f} Pa".format(seg_res.total_loss_pa), self.COLOR_TEXT,
                row_index=2, scale=1.0, orienter=self._label_orienter,
            )
            if loss_label is not None:
                self._root.addChild(loss_label)

    # ------------------------------------------------------------------
    # Hover tooltips (Stage 9 item 1)
    # ------------------------------------------------------------------

    def _attachHover(self, vobj):
        self._hover_root = coin.SoSeparator()
        callback = coin.SoEventCallback()
        callback.addEventCallback(coin.SoLocation2Event.getClassTypeId(), self._onMouseMove)
        self._hover_root.addChild(callback)
        vobj.RootNode.addChild(self._hover_root)
        self._hover_timer = QtCore.QTimer()
        self._hover_timer.setSingleShot(True)
        self._hover_timer.timeout.connect(self._onHoverIdle)
        # Closes the tip once the cursor has moved away from it, also when it
        # leaves the 3D view (which then sends no more mouse events here).
        self._hover_watch = QtCore.QTimer()
        self._hover_watch.setInterval(self.HOVER_WATCH_MS)
        self._hover_watch.timeout.connect(self._watchTip)

    def _detachHover(self):
        for timer in (self._hover_timer, getattr(self, "_hover_watch", None)):
            if timer is not None:
                timer.stop()
        self._hover_timer = None
        self._hover_watch = None
        if self._hover_root is not None:
            try:
                vobj = getattr(self.network_obj, "ViewObject", None)
                if vobj is not None:
                    vobj.RootNode.removeChild(self._hover_root)
            except Exception:
                pass
        self._hover_root = None
        self._hover_targets = []
        self._hideTip()
        if getattr(self, "_tip", None) is not None:
            self._tip.deleteLater()
            self._tip = None

    def _tipLabel(self):
        """
        Our own tooltip-looking popup. QToolTip is not used: the 3D view's
        event handling closes it within about a second whatever its
        timeout, so this one is shown and hidden only by this observer.
        """
        if getattr(self, "_tip", None) is None:
            tip = QtWidgets.QLabel(Gui.getMainWindow(), QtCore.Qt.ToolTip | QtCore.Qt.FramelessWindowHint)
            tip.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)
            tip.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
            tip.setPalette(QtWidgets.QToolTip.palette())
            tip.setFont(QtWidgets.QToolTip.font())
            tip.setAutoFillBackground(True)
            tip.setFrameShape(QtWidgets.QFrame.Box)
            tip.setMargin(4)
            tip.setTextFormat(QtCore.Qt.PlainText)
            self._tip = tip
        return self._tip

    def _showTip(self, text, global_pos):
        tip = self._tipLabel()
        tip.setText(text)
        tip.adjustSize()
        tip.move(global_pos + QtCore.QPoint(16, 20))
        tip.show()
        tip.raise_()
        self._hover_shown_at = (global_pos.x(), global_pos.y())
        if self._hover_watch is not None:
            self._hover_watch.start()

    def _hideTip(self):
        self._hover_shown_at = None
        if getattr(self, "_hover_watch", None) is not None:
            self._hover_watch.stop()
        if getattr(self, "_tip", None) is not None:
            self._tip.hide()

    def _cursorNearTip(self):
        if self._hover_shown_at is None:
            return False
        cursor = QtGui.QCursor.pos()
        sx, sy = self._hover_shown_at
        return abs(cursor.x() - sx) <= self.HOVER_HOLD_PX and abs(cursor.y() - sy) <= self.HOVER_HOLD_PX

    def _watchTip(self):
        if not self._cursorNearTip():
            self._hideTip()

    def _onMouseMove(self, user_data, event_callback):
        # Never handled here: the move still reaches FreeCAD (preselection, navigation).
        self._hover_pos = event_callback.getEvent().getPosition()
        if self._hover_shown_at is not None:
            if self._cursorNearTip():
                return  # still on what the open tip describes: leave it alone
            self._hideTip()
        if self._hover_timer is not None:
            self._hover_timer.start(self.HOVER_DELAY_MS)

    def _onHoverIdle(self):
        try:
            text = self._hoverText()
        except Exception as e:
            FreeCAD.Console.PrintLog("HVAC - result tooltip: {}\n".format(e))
            text = ""
        if text:
            self._showTip(text, QtGui.QCursor.pos())
        else:
            self._hideTip()

    def _hoverText(self):
        """Tooltip for what is under the cursor: an overlay plane or box first, else a duct or fitting of this network."""
        view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
        if view is None:
            return ""
        if self._hover_targets and self._hover_pos is not None and self._root is not None:
            # Pick through the whole scene (the ray needs the camera), keeping
            # every hit: the nearest overlay plane or box wins, even when a
            # duct or the overlay's own text is in front of it.
            render_manager = view.getViewer().getSoRenderManager()
            pick = coin.SoRayPickAction(render_manager.getViewportRegion())
            pick.setPoint(self._hover_pos)
            pick.setRadius(self.HOVER_PICK_RADIUS)
            pick.setPickAll(True)
            pick.apply(render_manager.getSceneGraph())
            picked_points = pick.getPickedPointList()
            for i in range(picked_points.getLength()):
                path = picked_points[i].getPath()
                for node, describe in self._hover_targets:
                    if path.containsNode(node):
                        return describe()

        info = view.getObjectInfo(view.getCursorPos())
        if not info:
            return ""
        obj = FreeCAD.ActiveDocument.getObject(info.get("Object", "")) if FreeCAD.ActiveDocument else None
        if obj is None or hvaclib.getOwnerNetwork(obj) != self.network_obj:
            return ""
        if hvaclib.isDuctSegment(obj):
            seg_res = next((s for s in self._allSegmentResults() if s.obj == obj), None)
            return self._segmentTooltip(seg_res) if seg_res is not None else ""
        if hvaclib.isDuctComponent(obj):
            rows = [row for comp in self.result.components for row in comp.component_ports if row.component_obj == obj]
            return _component_results.component_tooltip(_element_label(obj), rows)
        return ""

    def _segmentTooltip(self, seg_res):
        obj = seg_res.obj
        return _component_results.segment_tooltip(
            _element_label(obj), seg_res, float(getattr(obj, "EffectiveLength", 0.0) or 0.0)
        )

    def _portTooltip(self, junction, port, junc_res, port_row_by_edge, seg_by_key):
        edge_key = port.get("edge_key")
        seg_res = seg_by_key.get(edge_key)
        leg = _element_label(seg_res.obj) if seg_res is not None else str(edge_key)
        return _component_results.port_tooltip(
            "Node {}, leg {}".format(_element_label(junction), leg),
            self._junctionPortFlow(port, junc_res, port_row_by_edge, seg_by_key),
            self._junctionPortStaticPressure(port, junc_res, port_row_by_edge),
            port_row_by_edge.get(edge_key),
        )

    # ------------------------------------------------------------------
    # Temporary neutral appearance override
    # ------------------------------------------------------------------

    def _applyNeutralAppearance(self):
        geometry = getattr(self.network_obj, "Geometry", None)
        if geometry is None:
            return
        for obj in geometry.OutList:
            if not (hvaclib.isDuctSegment(obj) or hvaclib.isDuctComponent(obj)):
                continue
            vobj = getattr(obj, "ViewObject", None)
            if vobj is None or not hasattr(vobj, "ShapeAppearance"):
                continue
            if obj.Name not in self._appearance_snapshot:
                try:
                    self._appearance_snapshot[obj.Name] = list(vobj.ShapeAppearance)
                except Exception:
                    self._appearance_snapshot[obj.Name] = None
            try:
                shape = getattr(obj, "Shape", None)
                face_count = len(shape.Faces) if (shape is not None and not shape.isNull()) else 1
                neutral = FreeCAD.Material()
                neutral.DiffuseColor = self.NEUTRAL_COLOR
                vobj.ShapeAppearance = [neutral] * max(face_count, 1)
            except Exception:
                pass

    def _restoreAppearance(self):
        if not self._appearance_snapshot:
            return
        doc = getattr(self.network_obj, "Document", None)
        for obj_name, appearance in self._appearance_snapshot.items():
            obj = doc.getObject(obj_name) if doc is not None else None
            vobj = getattr(obj, "ViewObject", None) if obj is not None else None
            if vobj is None or appearance is None:
                continue
            try:
                vobj.ShapeAppearance = appearance
            except Exception:
                pass
        self._appearance_snapshot = {}

    # ------------------------------------------------------------------
    # Color-scale legend (screen-space HUD, bottom-left of the 3D view)
    # ------------------------------------------------------------------

    def _attachLegend(self):
        """
        Insert an (initially empty) screen-space HUD separator into the
        3D view's own scene graph -- as a sibling of the network's model
        content, not a child of it, since a HUD element must stay fixed
        on screen rather than move/scale with the model as the camera
        pans, zooms, or rotates. See _buildLegendBarCoinNode for how it's
        actually drawn.
        """
        try:
            scene = Gui.ActiveDocument.ActiveView.getSceneGraph()
        except Exception:
            return
        self._legend_root = coin.SoSeparator()
        try:
            scene.addChild(self._legend_root)
        except Exception:
            self._legend_root = None

    def _detachLegend(self):
        if self._legend_root is None:
            return
        try:
            Gui.ActiveDocument.ActiveView.getSceneGraph().removeChild(self._legend_root)
        except Exception:
            pass
        self._legend_root = None

    def _refreshLegend(self):
        if self._legend_root is None:
            return
        self._legend_root.removeAllChildren()

        rows = []
        if self.junction_enabled:
            junction_ports, seg_by_key, port_row_by_edge = self._junctionPortEntries()
            if junction_ports:
                values = [
                    self._junctionPortValue(port, junc_res, port_row_by_edge, seg_by_key)
                    for _, port, junc_res in junction_ports
                ]
                min_value, max_value = self.junction_range_override or (min(values), max(values))
                rows.append((self.JUNCTION_COLOR_LABELS.get(self.junction_color_by, self.junction_color_by), min_value, max_value))
        if self.segment_enabled:
            results = self._allSegmentResults()
            if results:
                values = [self._segmentValue(s) for s in results]
                min_value, max_value = self.segment_range_override or (min(values), max(values))
                rows.append((self.SEGMENT_COLOR_LABELS.get(self.segment_color_by, self.segment_color_by), min_value, max_value))

        for row_index, (label, min_value, max_value) in enumerate(rows):
            node = _buildLegendBarCoinNode(label, min_value, max_value, row_index=row_index, steps=self.LEGEND_STEPS)
            if node is not None:
                self._legend_root.addChild(node)


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

def _viewerFacingPlaneFrame(port, scale=2.0, top_extend=0.0):
    """
    Shared geometry for both buildPortHighlightCoinNode and
    buildFlowRateLabelCoinNode: a port's own connection-plane frame, faced
    toward a viewer standing on the open side of that port and looking
    toward the duct (i.e. looking along the port's own direction) --
    passing `direction` itself into make_profile_frame would face the
    frame's normal AWAY from that viewer, which is why text drawn in it
    used to render as its own mirror image.

    scale: same "plane size = scale x port dimension" convention as
    buildPortHighlightCoinNode's own `scale` -- must match whatever value
    the caller passed there, so the two stay the same physical size.

    top_extend: extra height added above the plane's own top edge only
    (as a fraction of the plane's un-extended full height), leaving the
    bottom edge where it was -- see buildPortHighlightCoinNode's own
    `top_extend`. Used by AirflowResultObserver's junction port overlay to
    make room for its text/arrow without also having to be given directly.

    Returns (origin, x_dir, y_dir, placement, half_w, half_h_bottom,
    half_h_top) -- the plane's bottom edge sits at -half_h_bottom, its top
    edge at +half_h_top (equal to half_h_bottom when top_extend is 0) --
    or None if `port` has no usable position.
    """
    position = port.get("position")
    if not position:
        return None
    direction = port.get("direction") or (0.0, 0.0, 1.0)
    preferred_x = port.get("profile_x_axis")
    section_params = port.get("section_params", {}) or {}

    width, height = hvaclib.get_section_extents(section_params)
    if width <= 0.0 or height <= 0.0:
        # Section params missing/degenerate -- fall back to a fixed size
        # rather than drawing a zero-area (invisible) highlight.
        width = height = 100.0
    half_w = width * (scale * 0.5)
    half_h_bottom = height * (scale * 0.5)
    half_h_top = half_h_bottom * (1.0 + 2.0 * top_extend)

    origin = FreeCAD.Vector(*position)
    placement, x_dir, y_dir, _ = hvaclib.make_profile_frame(
        FreeCAD.Vector(direction) * -1.0, preferred_x, origin
    )
    return origin, x_dir, y_dir, placement, half_w, half_h_bottom, half_h_top

def buildPortHighlightCoinNode(port, color=(0.2, 0.6, 1.0), transparency=0.5, scale=2.0, top_extend=0.0):
    """
    Build one Coin node: a semi-transparent quad marking a junction port's
    connection plane, centered on the port and sized to ~`scale`x its own
    section extents (2x by default). Used by TaskPanelEditInlineComponents
    so a user can see which physical port "Attach to edge" currently
    refers to, before committing to it; by TerminalFlowRateObserver for
    its own terminal-port plane, colored to match that terminal's flow
    arrow; and by AirflowResultObserver for its junction-port planes (2x,
    with extra top_extend for text/arrow room).

    top_extend: extra height added above the plane's own top edge only (as
    a fraction of the plane's un-extended full height) -- the bottom edge
    stays put, so the plane grows asymmetrically upward. 0.0 (the default)
    reproduces the old symmetric-about-`position` quad exactly.

    port: a connected_ports-style dict (position, direction, profile_x_axis,
    section_params -- see NetworkParser.JunctionPort). `position` is taken
    as-is here -- the caller is responsible for translating it to the
    actual physical connection point (see TaskPanelEditInlineComponents.
    _highlightCurrentPort / hvaclib.translated_port_position()), since a
    raw connected_ports position is only the pre-fitting shared anchor
    point, not where a duct wall / existing inline device chain actually
    ends.
    """
    position = port.get("position") or (0.0, 0.0, 0.0)
    direction = port.get("direction") or (0.0, 0.0, 1.0)
    preferred_x = port.get("profile_x_axis")
    section_params = port.get("section_params", {}) or {}

    width, height = hvaclib.get_section_extents(section_params)
    if width <= 0.0 or height <= 0.0:
        # Section params missing/degenerate -- fall back to a fixed size
        # rather than drawing a zero-area (invisible) highlight.
        width = height = 100.0
    half_w = width * (scale * 0.5)
    half_h = height * (scale * 0.5)
    top_half_h = half_h * (1.0 + 2.0 * top_extend)

    origin = FreeCAD.Vector(*position)
    _, x_dir, y_dir, _ = hvaclib.make_profile_frame(direction, preferred_x, origin)

    p1 = origin - x_dir * half_w - y_dir * half_h
    p2 = origin + x_dir * half_w - y_dir * half_h
    p3 = origin + x_dir * half_w + y_dir * top_half_h
    p4 = origin - x_dir * half_w + y_dir * top_half_h

    root = coin.SoSeparator()

    mat = coin.SoMaterial()
    mat.diffuseColor.setValue(*color)
    mat.transparency.setValue(transparency)
    root.addChild(mat)

    coords = coin.SoCoordinate3()
    coords.point.setValues(0, 4, [
        (p1.x, p1.y, p1.z),
        (p2.x, p2.y, p2.z),
        (p3.x, p3.y, p3.z),
        (p4.x, p4.y, p4.z),
    ])
    root.addChild(coords)

    face = coin.SoFaceSet()
    face.numVertices.setValue(4)
    root.addChild(face)

    return root

def buildSegmentOverlayCoinNode(position, direction, profile_x_axis, width, height, depth, color, transparency):
    """
    Build one Coin node: a solid box encapsulating a duct segment's own
    length -- used by AirflowResultObserver's segment overlay instead of
    buildPortHighlightCoinNode's flat quad, so it reads as wrapping the
    duct along its whole run rather than marking one cross-section.

    position: the box's own center (the segment's own midpoint, so the
    box's fixed `depth` extends the same distance past each end).
    direction: the box's long (depth) axis -- the segment's own
    centerline direction.
    width/height: box cross-section, along the section's own local x/y
    axes (profile_x_axis, or an automatic stable axis if that's None).
    depth: box size along `direction` -- the segment's own length.
    """
    origin = FreeCAD.Vector(position)
    placement, _, _, _ = hvaclib.make_profile_frame(direction, profile_x_axis, origin)

    root = coin.SoSeparator()

    mat = coin.SoMaterial()
    mat.diffuseColor.setValue(*color)
    mat.transparency.setValue(transparency)
    root.addChild(mat)

    transform = coin.SoTransform()
    transform.translation.setValue(origin.x, origin.y, origin.z)
    transform.rotation.setValue(*placement.Rotation.Q)
    root.addChild(transform)

    # SoCube's own local axes: width along X, height along Y, depth along
    # Z -- and make_profile_frame's placement maps local Z to `direction`,
    # so this box's length runs along the segment's own centerline.
    box = coin.SoCube()
    box.width.setValue(width)
    box.height.setValue(height)
    box.depth.setValue(depth)
    root.addChild(box)

    return root

# Approximate glyph aspect ratio (width:height) -- used to estimate a
# string's rendered width from font size alone, since SoText3 has no
# built-in "measure this string" query. Just an approximation (the actual
# default font isn't necessarily this exact width), good enough to keep
# long strings from visibly overflowing the plane.
MONOSPACE_CHAR_WIDTH_RATIO = 0.6

def _labelVariantAxes(x_dir, y_dir, variant):
    """
    The text axes (tx, ty) of one of a flat label's 8 orientations in its
    plane: variant // 4 picks the side it reads from (0 front, 1 back, i.e.
    mirrored so it reads right from behind), variant % 4 the number of
    quarter turns about the plane normal. Variant 0 is the original layout.
    """
    tx = FreeCAD.Vector(x_dir) * (-1.0 if variant // 4 else 1.0)
    ty = FreeCAD.Vector(y_dir)
    for _turn in range(variant % 4):
        # A quarter turn (counter-clockwise seen from the reading side): x -> y, y -> -x.
        tx, ty = ty, tx * -1.0
    return tx, ty


def chooseLabelVariant(x_dir, y_dir, view_dir, view_up, current=0, hold=0.3):
    """
    Which of a flat label's 8 orientations (see _labelVariantAxes) to show
    for a camera looking along `view_dir` with `view_up` up on screen.

    The label stays as originally laid out unless the camera sees it from
    behind (then it flips in its plane, so it is not mirrored) or the text
    would read upside down or sideways (then it turns by quarter turns, e.g.
    when the camera looks from below). `current` is the variant shown now;
    another quarter turn only wins when its up is better by more than
    `hold`, so labels don't flicker near 45 degrees.
    """
    normal = FreeCAD.Vector(x_dir).cross(FreeCAD.Vector(y_dir))
    # SoText3 reads from the side its local +Z points to, i.e. a camera looking along -normal.
    back = 1 if FreeCAD.Vector(view_dir).dot(normal) > 0.0 else 0
    up = FreeCAD.Vector(view_up)
    scores = [_labelVariantAxes(x_dir, y_dir, back * 4 + turn)[1].dot(up) for turn in range(4)]
    best = max(range(4), key=lambda turn: scores[turn])
    # Keep the turn already shown (or the original one after a flip) unless another is clearly better.
    keep = current % 4 if current // 4 == back else 0
    turn = best if scores[best] > scores[keep] + hold else keep
    return back * 4 + turn


class LabelOrienter:
    """
    Keeps the flat result labels readable as the camera moves. Each label
    is built with all 8 of its orientations under one SoSwitch
    (buildFlowRateLabelCoinNode); this watches the active 3D view's camera
    and sets every switch to chooseLabelVariant()'s pick. One per overlay
    observer: start() with the overlay, clear() before rebuilding its
    labels, stop() with it.
    """

    def __init__(self):
        self._labels = []  # [(SoSwitch, x_dir, y_dir), ...]
        self._camera = None
        self._sensor = None

    def start(self):
        self._attach()

    def stop(self):
        self._detach()
        self._labels = []

    def clear(self):
        self._labels = []

    def add(self, switch, x_dir, y_dir):
        self._labels.append((switch, FreeCAD.Vector(x_dir), FreeCAD.Vector(y_dir)))
        view = self._viewAxes()
        if view is not None:
            switch.whichChild = chooseLabelVariant(x_dir, y_dir, view[0], view[1], current=0)

    @staticmethod
    def _activeCamera():
        try:
            view = Gui.ActiveDocument.ActiveView
            return view.getCameraNode()
        except Exception:
            return None

    def _attach(self):
        self._detach()
        camera = self._activeCamera()
        if camera is None:
            return
        self._camera = camera
        self._sensor = coin.SoFieldSensor(self._onCameraMoved, None)
        self._sensor.attach(camera.orientation)

    def _detach(self):
        if self._sensor is not None:
            try:
                self._sensor.detach()
            except Exception:
                pass
        self._sensor = None
        self._camera = None

    def _viewAxes(self):
        """(view direction, up direction) of the watched camera, or None."""
        camera = self._camera
        if camera is None:
            return None
        rotation = camera.orientation.getValue()
        view_dir = rotation.multVec(coin.SbVec3f(0.0, 0.0, -1.0))
        up = rotation.multVec(coin.SbVec3f(0.0, 1.0, 0.0))
        return FreeCAD.Vector(*view_dir.getValue()), FreeCAD.Vector(*up.getValue())

    def _onCameraMoved(self, *_args):
        # Switching between perspective and orthographic replaces the camera
        # node; follow the new one so the labels keep turning.
        camera = self._activeCamera()
        if camera is not None and camera is not self._camera:
            self._attach()
        view = self._viewAxes()
        if view is None:
            return
        for switch, x_dir, y_dir in self._labels:
            variant = chooseLabelVariant(x_dir, y_dir, view[0], view[1], current=switch.whichChild.getValue())
            if variant != switch.whichChild.getValue():
                switch.whichChild = variant


def buildFlowRateLabelCoinNode(port, text, color, row_index=0, scale=2.0, top_extend=0.0, orienter=None):
    """
    Build one Coin node: a world-space text label lying flat on the port's
    own highlight plane (see buildPortHighlightCoinNode -- same port dict,
    same scale/top_extend, so the two line up exactly), sized to 15% of
    that plane's own height (shrunk further if needed so it can't overflow
    past the plane's own edges) and anchored just inside its top-right
    corner, as seen by a viewer facing the terminal. Used by
    TerminalFlowRateObserver/AirflowResultObserver to print result values
    right on a port's own plane, so the value itself is readable at a
    glance instead of only being implied by the plane/arrow color.

    The label is built in all 8 of its in-plane orientations under one
    SoSwitch (front or back, times four quarter turns -- see
    _labelVariantAxes). Variant 0 is the original layout; `orienter` (a
    LabelOrienter) switches a label to another one only when the camera
    sees it from behind or from below, so it never reads mirrored or upside
    down. Without an orienter the label keeps variant 0.

    port: a connected_ports-style dict (position, direction, profile_x_axis,
    section_params -- see NetworkParser.JunctionPort). `position` must
    already be the port's real (translated) location, not the raw
    pre-fitting anchor -- see hvaclib.translated_port_position().

    row_index: 0 for the top line; each further row stacks directly below
    the previous one (same fixed row height, regardless of any individual
    row's own shrink-to-fit scaling) -- lets a caller show several values
    (e.g. flow rate AND static pressure) on the same plane. Row height/
    spacing is measured off the plane's un-extended height, so extending
    the plane (top_extend) only adds room above row 0, it doesn't change
    existing rows' own size or spacing.

    Uses SoText3 (real 3D, world-sized text), not SoText2 (fixed-size,
    screen-facing) -- the whole point is a height measured in real mm
    against the plane's own size, which only SoText3 supports.
    """
    frame = _viewerFacingPlaneFrame(port, scale=scale, top_extend=top_extend)
    if frame is None:
        return None
    origin, x_dir, y_dir, _placement, half_w, half_h_bottom, half_h_top = frame
    plane_height = 2.0 * half_h_bottom  # rows are sized/spaced off the un-extended plane
    row_height = plane_height * 0.15  # fixed row pitch, independent of any row's own shrink-to-fit
    margin = plane_height * 0.05  # inward padding from the plane's own edges
    text_str = str(text)

    # How far the plane reaches from its origin along each in-plane axis
    # direction (it is taller above its centre when top_extend is set).
    def reach(axis):
        if abs(axis.dot(x_dir)) > 0.5:
            return half_w
        return half_h_top if axis.dot(y_dir) > 0.0 else half_h_bottom

    root = coin.SoSeparator()
    mat = coin.SoMaterial()
    mat.diffuseColor.setValue(*color)
    root.addChild(mat)
    switch = coin.SoSwitch()
    root.addChild(switch)

    for variant in range(8):
        tx, ty = _labelVariantAxes(x_dir, y_dir, variant)

        # Step 1: shrink the text, if needed, so a long string can't
        # overflow the plane -- SoText3 has no auto-fit, so estimate the
        # rendered width from an approximate glyph width.
        text_height = row_height
        available_width = reach(tx) + reach(tx * -1.0) - 2.0 * margin
        estimated_width = len(text_str) * text_height * MONOSPACE_CHAR_WIDTH_RATIO
        if available_width > 0.0 and estimated_width > available_width:
            text_height *= available_width / estimated_width

        # Step 2: anchor just inside the plane's top-right corner (as this
        # orientation reads), each further row one row_height lower.
        anchor = origin + tx * (reach(tx) - margin) + ty * (reach(ty) - margin - row_height * (row_index + 1))

        # Step 3: the text, lying in the plane with this orientation's axes.
        child = coin.SoSeparator()
        transform = coin.SoTransform()
        transform.translation.setValue(anchor.x, anchor.y, anchor.z)
        transform.rotation.setValue(*FreeCAD.Rotation(tx, ty, tx.cross(ty), "ZXY").Q)
        child.addChild(transform)
        font = coin.SoFont()
        font.size.setValue(text_height)
        child.addChild(font)
        text_node = coin.SoText3()
        text_node.string.setValue(text_str)
        text_node.justification = coin.SoText3.RIGHT
        child.addChild(text_node)
        switch.addChild(child)

    switch.whichChild = 0
    if orienter is not None:
        orienter.add(switch, x_dir, y_dir)
    return root

def buildTerminalFlowArrowCoinNode(
    origin, direction, flow_into_junction, offset_mm, length_mm, color, transparency=0.0,
):
    """
    Build one Coin node: a colored cone-and-shaft arrow marking a terminal
    junction's design flow rate, offset into the open space beyond the
    terminal (not overlapping the duct itself) -- see
    TerminalFlowRateObserver.

    origin: the terminal's real, post-fitting port position (see
    utils/hvaclib.translated_port_position) -- the same point the
    matching port-highlight plane is drawn at, not the junction's own
    (pre-fitting) CenterPoint, so the arrow lines up with the actual
    terminal face rather than floating at the node's logical center.
    direction: the terminal's single real port's own direction (points
    away from the junction, into the duct network -- see
    NetworkParser.JunctionPort) -- the arrow is drawn on the opposite side,
    in the open space the terminal faces.
    flow_into_junction: True if flow enters the junction from the duct
    (a supply outlet -- air continues on outward past the terminal, into
    the room), False if flow leaves the junction into the duct (a return/
    extract inlet -- air is drawn in from the room). Standard HVAC
    drafting convention: a supply arrow points away from the duct (tail
    near, head far); a return arrow points toward the duct (head near,
    tail far).
    """
    away_dir = FreeCAD.Vector(direction) * -1.0
    if away_dir.Length <= 1e-9:
        return None
    away_dir.normalize()

    near_point = FreeCAD.Vector(origin) + away_dir * offset_mm
    far_point = near_point + away_dir * length_mm

    head_len = length_mm * 0.5
    head_radius = head_len * 0.35
    shaft_radius = head_radius * 0.5

    if flow_into_junction:
        # Supply: arrow points away from the duct -- head at the far end.
        tip, tail, head_dir = far_point, near_point, away_dir
    else:
        # Return/extract: arrow points toward the duct -- head at the near end.
        tip, tail, head_dir = near_point, far_point, away_dir * -1.0

    cone_base_point = tip - head_dir * head_len
    cone_center = tip - head_dir * (head_len * 0.5)
    shaft_len = (cone_base_point - tail).Length
    shaft_center = tail + head_dir * (shaft_len * 0.5)

    # Coin SoCone/SoCylinder align to +Y by default -- rotate Y to head_dir.
    y_axis = FreeCAD.Vector(0, 1, 0)
    rot_axis = y_axis.cross(head_dir)
    dot = max(-1.0, min(1.0, y_axis.dot(head_dir)))
    if rot_axis.Length > 1e-9:
        rot_axis.normalize()
        rot_angle = math.acos(dot)
    elif dot > 0:
        rot_axis, rot_angle = FreeCAD.Vector(1, 0, 0), 0.0
    else:
        rot_axis, rot_angle = FreeCAD.Vector(1, 0, 0), math.pi

    def make_transform(point, rot_ax, angle):
        xf = coin.SoTransform()
        xf.translation.setValue(point.x, point.y, point.z)
        xf.rotation.setValue(coin.SbVec3f(rot_ax.x, rot_ax.y, rot_ax.z), angle)
        return xf

    root = coin.SoSeparator()

    mat = coin.SoMaterial()
    mat.diffuseColor.setValue(*color)
    mat.transparency.setValue(transparency)
    root.addChild(mat)

    cone_sep = coin.SoSeparator()
    cone_sep.addChild(make_transform(cone_center, rot_axis, rot_angle))
    cone = coin.SoCone()
    cone.bottomRadius.setValue(head_radius)
    cone.height.setValue(head_len)
    cone_sep.addChild(cone)
    root.addChild(cone_sep)

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

        yield (
            hvaclib.vec_to_xyz(v1),
            hvaclib.vec_to_xyz(v2)
        )
