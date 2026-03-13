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

"""This module implements HVAC duct description classes."""

import FreeCAD
import FreeCADGui as Gui
from PySide import QtWidgets, QtCore
from PySide.QtCore import QT_TRANSLATE_NOOP
translate = FreeCAD.Qt.translate

from . import hvaclib


class NewSketchObserver:
    """New sketch creation observer"""

    def __init__(self, network_obj, callback):
        self.network_obj = network_obj
        self.callback = callback
        self.doc = network_obj.Document
        self.created_sketch = None
        self._finished = False
        self._seen_dialog = False

        self._timer = QtCore.QTimer()
        self._timer.setInterval(200)
        self._timer.timeout.connect(self.check_finished)
        self._timer.start()

    def slotCreatedObject(self, obj):
        # Called when a new object is created in the document
        if self._finished or self.created_sketch is not None:
            return
        if obj and obj.Document == self.doc and hvaclib.obj_is_sketch(obj):
            self.created_sketch = obj

    def check_finished(self):
        """Detect when the sketch edition has been exited."""
        if self._finished:
            return
        # Sketcher normally opens a task panel/dialog while active.
        if Gui.Control.activeDialog():
            self._seen_dialog = True
            return
        # Finalize only after the dialog has appeared once and then closed.
        if self._seen_dialog:
            QtCore.QTimer.singleShot(0, self.finalize)
            return True

    def finalize(self):
        if self._finished:
            return
        self._finished = True
        self._timer.stop()
        
        try:
            self.callback(self.network_obj, self.created_sketch)
        finally:
            FreeCAD.removeDocumentObserver(self)


class NewDraftLineObserver:
    """Observe Draft line creation and add all created lines to the network
    after the Draft tool is closed.
    """

    def __init__(self, network_obj, callback):
        self.network_obj = network_obj
        self.callback = callback
        self.doc = network_obj.Document
        self.created_objects = []
        self._finished = False
        self._seen_dialog = False

        self._timer = QtCore.QTimer()
        self._timer.setInterval(200)
        self._timer.timeout.connect(self.check_finished)
        self._timer.start()

    def slotCreatedObject(self, obj):
        """Called whenever a new object is created in the document."""
        if self._finished:
            return
        if not obj or obj.Document != self.doc:
            return
        if obj not in self.created_objects:
            self.created_objects.append(obj)

    def check_finished(self):
        """Detect when the Draft command has been exited."""
        if self._finished:
            return
        # Draft Line normally opens a task panel/dialog while active.
        if Gui.Control.activeDialog():
            self._seen_dialog = True
            return
        # Finalize only after the dialog has appeared once and then closed.
        if self._seen_dialog:
            QtCore.QTimer.singleShot(0, self.finalize)
            return True

    def finalize(self):
        if self._finished:
            return
        self._finished = True
        self._timer.stop()
        
        try:
            self.callback(self.network_obj, self.created_objects)
        finally:
            # Switch back workbench to HVAC
            Gui.activateWorkbench(hvaclib.WORKBENCH_NAME)
            # Always remove observer after one use
            FreeCAD.removeDocumentObserver(self)


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
            
        if obj is None:
            return
        doc = getattr(obj, "Document", None)
        if doc is None:
            return

        # Ignore internal managed objects to avoid circular updates
        if hvaclib.isDuctNetwork(obj) or hvaclib.isDuctSegment(obj) or hvaclib.isDuctManagedFolder(obj):
            return

        # React only to properties relevant to geometry updates
        if hvaclib.obj_is_sketch(obj):
            relevant_props = ("Geometry", "Shape", "Placement")
        elif hvaclib.obj_is_wire(obj):
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
            proxy.requestSync(net, reason="observer")
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
                        proxy.requestSync(obj, initial_sync=True, reason="undo_redo")
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
            if hvaclib.obj_is_wire(obj):
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
            
            proxy.setBaseObjectEditing(net, obj, False)
            proxy.requestSync(net, reason="edit_finished")

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
        if not ( hvaclib.obj_is_sketch(obj) or hvaclib.obj_is_wire(obj) ):
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
            proxy.setBaseObjectEditing(net, obj, True)
