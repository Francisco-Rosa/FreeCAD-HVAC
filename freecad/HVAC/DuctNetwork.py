# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the Solar addon.

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

from this import s
import FreeCAD
import FreeCADGui as Gui
from PySide import QtWidgets, QtCore
import freecad.HVAC.hvaclib as hvaclib

from PySide.QtCore import QT_TRANSLATE_NOOP
translate = FreeCAD.Qt.translate


#=================================================
# A. Helper classes
#=================================================


class NewSketchObserver:
    """New sketch creation observer"""

    def __init__(self, network_obj):
        self.network_obj = network_obj
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
            if self.created_sketch:
                DuctNetwork.addBaseObject(self.network_obj, self.created_sketch)
        finally:
            FreeCAD.removeDocumentObserver(self)


class NewDraftLineObserver:
    """Observe Draft line creation and add all created lines to the network
    after the Draft tool is closed.
    """

    def __init__(self, network_obj):
        self.network_obj = network_obj
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
            for obj in self.created_objects:
                if hvaclib.obj_is_wire(obj):
                    DuctNetwork.addBaseObject(self.network_obj, obj)
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
        if DuctNetwork.isDuctNetwork(obj):
            return
        if DuctSegment.isDuctSegment(obj):
            return
        if isinstance(getattr(obj, "Proxy", None), DuctManagedFolder):
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

            base = getattr(net, "Base", None)
            if base is None:
                continue

            # If the modified object is part of the network's base geometry
            if obj in base.OutList:
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
        if not DuctNetwork.isDuctNetwork(net):
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
                if DuctNetwork.isDuctNetwork(obj):
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
        net = DuctNetwork.getOwnerNetwork(obj)
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
            
            
#=================================================
# B. Main classes
#=================================================


class DuctManagedFolder:
    """Internal managed folder used by DuctNetwork."""

    def __init__(self, obj, owner=None, role=""):
        obj.Proxy = self
        if "OwnerNetworkName" not in obj.PropertiesList:
            # Store link as string to avoid cyclic dependency issue
            obj.addProperty("App::PropertyString", "OwnerNetworkName", "HVAC", "Owning duct network")
        if "FolderRole" not in obj.PropertiesList:
            obj.addProperty("App::PropertyString", "FolderRole", "HVAC", "Internal folder role")
        obj.OwnerNetworkName = owner.Name if owner else ""
        obj.FolderRole = role

    def onDocumentRestored(self, obj):
        obj.Proxy = self

    def execute(self, obj):
        """Required so the object can clear its touched state on recompute."""
        pass

    @staticmethod
    def getOwner(obj):
        return DuctNetwork.getOwnerNetwork(obj)

    @staticmethod
    def create(doc, name, owner, role):
        folder = doc.addObject("App::DocumentObjectGroupPython", name)
        DuctManagedFolder(folder, owner=owner, role=role)
        DuctManagedFolderViewProvider(folder.ViewObject)
        return folder


class DuctManagedFolderViewProvider:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def __getstate__(self):
        state = self.__dict__.copy()
        state.pop("Object", None)
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)

    def getIcon(self):
        return hvaclib.get_icon_path("Folder.svg")  # optional

    def onDelete(self, vobj, subelements):
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
            return list(self.Object.OutList)
        except Exception:
            return []

    def canDropObjects(self):
        return False

    def canDragObjects(self):
        return False


class DuctSegment:
    """Derived per-edge duct segment created from network base geometry."""

    TYPE = "DuctSegment"
    SECTION_SHAPES = hvaclib.DUCT_SECTION_SHAPES

    def __init__(self, obj, owner=None, key="", source_obj=None, source_index=0):
        obj.Proxy = self
        self._allow_delete = False
        self.setProperties(obj)
        self.updateSectionEditorModes(obj)
        self.updateMetadata(
            obj,
            owner=owner,
            key=key,
            source_obj=source_obj,
            source_index=source_index,
        )

    def onDocumentRestored(self, obj):
        obj.Proxy = self
        self._allow_delete = False
        self.setProperties(obj)
        self.updateSectionEditorModes(obj)
        
    def __getstate__(self):
        return None

    def __setstate__(self, state):
        self._allow_delete = False
        
    def onChanged(self, obj, prop):
        if prop == "SectionShape":
            self.updateSectionEditorModes(obj)
            
    def execute(self, obj):
        start_point = getattr(obj, "StartPoint", None)
        end_point = getattr(obj, "EndPoint", None)
        width = getattr(obj, "Width", None)
        height = getattr(obj, "Height", None)
        diameter = getattr(obj, "Diameter", None)
        section_shape = getattr(obj, "SectionShape", self.SECTION_SHAPES[0])
        if start_point is None or end_point is None:
            return
        try:
            if start_point.sub(end_point).Length > 0:
                if section_shape == self.SECTION_SHAPES[0]:
                    obj.Shape = hvaclib.create_rectangular_duct_geom(start_point, end_point, width, height)
                elif section_shape == self.SECTION_SHAPES[1]:
                    obj.Shape = hvaclib.create_circular_duct_geom(start_point, end_point, diameter)
        except Exception as e:
            print("HVAC - Error generating geometry \n" + str(e))

    def setProperties(self, obj):
        self._addProperty(obj, "App::PropertyString", "OwnerNetworkName", "HVAC", "Owning duct network")
        self._addProperty(obj, "App::PropertyString", "SegmentKey", "HVAC", "Runtime segment key")
        self._addProperty(obj, "App::PropertyString", "SourceObjectName", "HVAC", "Internal source object name")
        self._addProperty(obj, "App::PropertyInteger", "SourceIndex", "HVAC", "Zero-based line segment index in the source object")
        self._addProperty(obj, "App::PropertyInteger", "StartNode", "HVAC", "Graph start node id")
        self._addProperty(obj, "App::PropertyInteger", "EndNode", "HVAC", "Graph end node id")
        self._addProperty(obj, "App::PropertyVector", "StartPoint", "HVAC", "Segment start point")
        self._addProperty(obj, "App::PropertyVector", "EndPoint", "HVAC", "Segment end point")
        self._addProperty(obj, "App::PropertyLength", "CenterlineLength", "HVAC", "Computed centerline length")

        current_shape = getattr(obj, "SectionShape", self.SECTION_SHAPES[0])
        if "SectionShape" not in obj.PropertiesList:
            obj.addProperty("App::PropertyEnumeration", "SectionShape", "Duct Type", "Cross-section shape")
        obj.SectionShape = self.SECTION_SHAPES
        if current_shape in self.SECTION_SHAPES:
            obj.SectionShape = current_shape
        else:
            obj.SectionShape = self.SECTION_SHAPES[0]

        self._addProperty(obj, "App::PropertyLength", "Diameter", "Dimensions", "Circular duct diameter")
        if not obj.Diameter: obj.Diameter = 100.0
        self._addProperty(obj, "App::PropertyLength", "Width", "Dimensions", "Rectangular duct width")
        if not obj.Width: obj.Width = 100.0
        self._addProperty(obj, "App::PropertyLength", "Height", "Dimensions", "Rectangular duct height")
        if not obj.Height: obj.Height = 100.0
        
        self._addProperty(obj, "App::PropertyLength", "InsulationThickness", "Parameters", "Insulation thickness")
        self._addProperty(obj, "App::PropertyLength", "Roughness", "Parameters", "Wall roughness")
        self._addProperty(obj, "App::PropertyFloat", "FlowRate", "Parameters", "Design flow rate")
        self._addProperty(obj, "App::PropertyFloat", "Velocity", "Parameters", "Design air velocity")

        for prop in (
            "OwnerNetworkName",
            "SegmentKey",
            "SourceObjectName",
            "SourceIndex",
            "StartNode",
            "EndNode",
            "StartPoint",
            "EndPoint",
            "CenterlineLength",
        ):
            try:
                obj.setEditorMode(prop, 1)
            except Exception:
                pass

    def updateSectionEditorModes(self, obj):
        shape = getattr(obj, "SectionShape", self.SECTION_SHAPES[0])
        is_circular = shape == "Circular"
        try:
            obj.setEditorMode("Diameter", 0 if is_circular else 1)
            obj.setEditorMode("Width", 1 if is_circular else 0)
            obj.setEditorMode("Height", 1 if is_circular else 0)
        except Exception:
            pass

    def updateMetadata(self, obj, owner=None, key="", source_obj=None, source_index=0, start_node=0, end_node=0, start_point=None, end_point=None):
        changed = False
        
        if owner and getattr(obj, "OwnerNetworkName", "") != owner.Name:
            obj.OwnerNetworkName = owner.Name
            changed = True
    
        if key and getattr(obj, "SegmentKey", "") != key:
            obj.SegmentKey = key
            changed = True
    
        source_name = source_obj.Name if source_obj else ""
        if getattr(obj, "SourceObjectName", "") != source_name:
            obj.SourceObjectName = source_name
            changed = True
    
        if getattr(obj, "SourceIndex", None) != int(source_index):
            obj.SourceIndex = int(source_index)
            changed = True
    
        if getattr(obj, "StartNode", None) != int(start_node):
            obj.StartNode = int(start_node)
            changed = True
    
        if getattr(obj, "EndNode", None) != int(end_node):
            obj.EndNode = int(end_node)
            changed = True
    
        start_vec = None
        end_vec = None
    
        if start_point is not None:
            start_vec = FreeCAD.Vector(*start_point)
            if obj.StartPoint != start_vec:
                obj.StartPoint = start_vec
                changed = True
    
        if end_point is not None:
            end_vec = FreeCAD.Vector(*end_point)
            if obj.EndPoint != end_vec:
                obj.EndPoint = end_vec
                changed = True
    
        if start_vec is not None and end_vec is not None:
            length = end_vec.sub(start_vec).Length
            if abs(float(obj.CenterlineLength) - float(length)) > 1e-9:
                obj.CenterlineLength = length
                changed = True
    
        return changed

    @classmethod
    def create(cls, doc, name, owner, key, source_obj, source_index):
        segment = doc.addObject("Part::FeaturePython", name)
        cls(segment, owner=owner, key=key, source_obj=source_obj, source_index=source_index)
        DuctSegmentViewProvider(segment.ViewObject)
        return segment

    @staticmethod
    def isDuctSegment(obj):
        return bool(obj) and hasattr(obj, "Proxy") and isinstance(obj.Proxy, DuctSegment)

    @staticmethod
    def makeKey(obj_name, source_index):
        return "{}:{}".format(obj_name, int(source_index))

    @staticmethod
    def labelFor(source_obj, source_index):
        source_label = source_obj.Label if source_obj else "Segment"
        return "{} [{}]".format(source_label, int(source_index) + 1)

    @staticmethod
    def _addProperty(obj, prop_type, prop_name, group, description):
        if prop_name not in obj.PropertiesList:
            obj.addProperty(prop_type, prop_name, group, description)


class DuctSegmentViewProvider:
    """View provider for derived duct segment objects."""

    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def __getstate__(self):
        state = self.__dict__.copy()
        state.pop("Object", None)
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)

    def getIcon(self):
        return hvaclib.get_icon_path("DuctsIcon.svg")

    def onDelete(self, vobj, subelements):
        obj = vobj.Object
        owner = DuctNetwork.getOwnerNetwork(obj)
        if getattr(obj.Proxy, "_allow_delete", False):
            return True
        if owner and getattr(owner.Proxy, "_allow_internal_delete", False):
            return True
        FreeCAD.Console.PrintWarning(
            "HVAC - Internal segment '{}' cannot be deleted directly.\n".format(obj.Label)
        )
        return False

    def canDropObjects(self):
        return False

    def canDragObjects(self):
        return False


class DuctNetwork:
    """Visualize and configure HVAC duct network in FreeCAD's 3D view."""

    CONTEXT_KEY = hvaclib.DUCT_NETWORK_CONTEXT_KEY
    FOLDER_BASE_NAME = "Base"
    FOLDER_GEOMETRY_NAME = "Geometry"

    def __init__(self, obj):
        obj.Proxy = self
        self._runtime_param_cache = {}
        self._allow_internal_delete = False
        self._initial_sync = True
        self._sync_in_progress = False
        self._sync_scheduled = False
        self._sync_reason = None
        self._hidden_source_names = set()
        self.setProperties(obj)
        
    def __getstate__(self):
        state = self.__dict__.copy()
        state.pop("_hidden_source_names", None)
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)

    def onDocumentRestored(self, obj):
        obj.Proxy = self
        self._runtime_param_cache = {}
        self._allow_internal_delete = False
        self._initial_sync = True
        self._sync_in_progress = False
        self._sync_scheduled = False
        self._sync_reason = None
        self._hidden_source_names = set()
        self.setProperties(obj)
        self.requestSync(obj, initial_sync=True, reason="restore")
        
    def execute(self, obj):
        """Manual recompute of the network triggers deferred synchronization."""
        if self._sync_in_progress:
            return
        self.requestSync(obj, reason="execute")

    def setProperties(self, obj):
        """Gives the object properties to HVAC ducts."""
        doc = obj.Document

        # Base folder
        if "Base" not in obj.PropertiesList:
            obj.addProperty("App::PropertyLink", "Base", "HVAC", "Base (internal)")
        if getattr(obj, "Base", None) is None and doc is not None:
            folder_base = DuctManagedFolder.create(
                doc,
                f"{obj.Name}_{self.FOLDER_BASE_NAME}",
                owner=obj,
                role=self.FOLDER_BASE_NAME,
            )
            folder_base.Label = self.FOLDER_BASE_NAME
            obj.Base = folder_base
        elif obj.Base:
            if getattr(obj.Base, "OwnerNetworkName", "") != obj.Name:
                obj.Base.OwnerNetworkName = obj.Name
            if getattr(obj.Base, "FolderRole", "") != self.FOLDER_BASE_NAME:
                obj.Base.FolderRole = self.FOLDER_BASE_NAME

        # Geometry folder
        if "Geometry" not in obj.PropertiesList:
            obj.addProperty("App::PropertyLink", "Geometry", "HVAC", "Geometry (internal)")
        if getattr(obj, "Geometry", None) is None and doc is not None:
            folder_geometry = DuctManagedFolder.create(
                doc,
                f"{obj.Name}_{self.FOLDER_GEOMETRY_NAME}",
                owner=obj,
                role=self.FOLDER_GEOMETRY_NAME,
            )
            folder_geometry.Label = self.FOLDER_GEOMETRY_NAME
            obj.Geometry = folder_geometry
        elif obj.Geometry:
            if getattr(obj.Geometry, "OwnerNetworkName", "") != obj.Name:
                obj.Geometry.OwnerNetworkName = obj.Name
            if getattr(obj.Geometry, "FolderRole", "") != self.FOLDER_GEOMETRY_NAME:
                obj.Geometry.FolderRole = self.FOLDER_GEOMETRY_NAME

    @staticmethod
    def createObject(name):
        net = FreeCAD.ActiveDocument.addObject('App::DocumentObjectGroupPython', name)
        DuctNetwork(net)
        DuctNetworkViewProvider(net.ViewObject)
        return net

    @staticmethod
    def createSketchInteractive(obj):
        """
        Open the standard FreeCAD sketch creation panel and,
        after the sketch is created, move it under obj.Base.
        """
        if not obj or not DuctNetwork.isDuctNetwork(obj):
            return
        if FreeCAD.ActiveDocument is None or Gui.ActiveDocument is None:
            return

        # Make this network active in the 3D view context
        DuctNetwork.setActive(obj)
        
        # Install observer before running the command
        obs = NewSketchObserver(obj)
        FreeCAD.addDocumentObserver(obs)
        
        # Launch the built-in sketch creation command
        Gui.runCommand("Sketcher_NewSketch")

    @staticmethod
    def createDraftLineInteractive(obj):
        """
        Open the standard Draft Line command and, after the user exits the tool,
        move all newly created Draft line objects under obj.Base.
        """
        if not obj or not DuctNetwork.isDuctNetwork(obj):
            return
        if FreeCAD.ActiveDocument is None or Gui.ActiveDocument is None:
            return

        # Make this network active in the 3D view context
        DuctNetwork.setActive(obj)
        
        # Install observer before running the command
        obs = NewDraftLineObserver(obj)
        FreeCAD.addDocumentObserver(obs)
        
        # Launch the built-in Draft line creation command
        Gui.activateWorkbench("DraftWorkbench")
        Gui.runCommand("Draft_Line")

    @staticmethod
    def addBaseObject(net, obj):
        if not net or not obj:
            return False
        if not DuctNetwork.isDuctNetwork(net):
            return False
        if not hasattr(net, "Base") or net.Base is None:
            return False
        if not hasattr(obj, "Document") or obj.Document is None:
            return False
        if net.Document != obj.Document:
            return False
        if not (hvaclib.obj_is_sketch(obj) or hvaclib.obj_is_wire(obj)):
            return False
        if obj in net.Base.OutList:
            return False
        
        net.Base.addObject(obj)
        if getattr(net, "Proxy", None):
            net.Proxy.requestSync(net)
        net.Document.recompute()
        return True

    @staticmethod
    def removeBaseObject(net, obj):
        if not net or not obj:
            return False
        if not DuctNetwork.isDuctNetwork(net):
            return False
        if not hasattr(net, "Base") or net.Base is None:
            return False
        if net.Document != getattr(obj, "Document", None):
            return False
        if obj not in net.Base.OutList:
            return False
    
        net.Base.removeObject(obj)
        if getattr(net, "Proxy", None):
            net.Proxy.requestSync(net)
        net.Document.recompute()
        return True

    @staticmethod
    def removeGeometryObject(net, obj):
        """Remove a derived geometry object from the Geometry folder and document."""
        if not net or not obj or not DuctNetwork.isDuctNetwork(net):
            return False
        if getattr(obj, "Document", None) != net.Document:
            return False
        if DuctSegment.isDuctSegment(obj) and getattr(obj, "Proxy", None):
            obj.Proxy._allow_delete = True
        if hasattr(net, "Geometry") and net.Geometry and obj in net.Geometry.OutList:
            net.Geometry.removeObject(obj)
        net.Document.removeObject(obj.Name)
        return True

    @staticmethod
    def collectSegmentObjects(net):
        segments = {}
        geometry = getattr(net, "Geometry", None)
        if geometry is None:
            return segments
        for child in list(geometry.OutList):
            if not DuctSegment.isDuctSegment(child):
                continue
            key = getattr(child, "SegmentKey", "")
            if not key and getattr(child, "SourceObjectName", ""):
                key = DuctSegment.makeKey(child.SourceObjectName, child.SourceIndex)
            if key:
                segments[key] = child
        return segments

    @staticmethod
    def setActive(obj):
        """Set this DuctNetwork as the active container in the 3D view."""
        Gui.ActiveDocument.ActiveView.setActiveObject(DuctNetwork.CONTEXT_KEY, obj)

    @staticmethod
    def getActive(doc=None):
        """Get the active DuctNetwork container from the 3D view."""
        if not FreeCAD.GuiUp:
            return None
        if doc is None:
            doc = FreeCAD.ActiveDocument
        if doc is None or Gui.ActiveDocument is None:
            return None
        return Gui.ActiveDocument.ActiveView.getActiveObject(DuctNetwork.CONTEXT_KEY)
        
    def _setSegmentVisibilityDeferred(self, segment_obj, visible):
        if not FreeCAD.GuiUp:
            return

        def apply():
            try:
                if segment_obj is None or getattr(segment_obj, "Document", None) is None:
                    return
                vobj = getattr(segment_obj, "ViewObject", None)
                if vobj is None:
                    return
                vobj.Visibility = bool(visible)
            except Exception:
                pass

        QtCore.QTimer.singleShot(0, apply)

    def showAllGeometry(self, net):
        geometry = getattr(net, "Geometry", None)
        if geometry is None:
            return

        if getattr(geometry, "ViewObject", None):
            try:
                geometry.ViewObject.Visibility = True
            except Exception:
                pass

        for obj in list(geometry.OutList):
            if DuctSegment.isDuctSegment(obj):
                self._setSegmentVisibilityDeferred(obj, True)
                
    def _segmentFromBaseObject(self, seg, base_obj):
        return (
            seg is not None
            and base_obj is not None
            and DuctSegment.isDuctSegment(seg)
            and getattr(seg, "SourceObjectName", "") == base_obj.Name
        )
    
    def hideGeometryForBaseObject(self, net, base_obj):
        geometry = getattr(net, "Geometry", None)
        if geometry is None or base_obj is None:
            return
        for seg in list(geometry.OutList):
            if self._segmentFromBaseObject(seg, base_obj):
                self._setSegmentVisibilityDeferred(seg, False)
    
    def showGeometryForBaseObject(self, net, base_obj):
        geometry = getattr(net, "Geometry", None)
        if geometry is None or base_obj is None:
            return
        for seg in list(geometry.OutList):
            if self._segmentFromBaseObject(seg, base_obj):
                self._setSegmentVisibilityDeferred(seg, True)
    
    def setBaseObjectEditing(self, net, base_obj, editing):
        if net is None or base_obj is None:
            return
        if editing:
            self._hidden_source_names.add(base_obj.Name)
            self.hideGeometryForBaseObject(net, base_obj)
        else:
            self._hidden_source_names.discard(base_obj.Name)
            self.showGeometryForBaseObject(net, base_obj)

    @staticmethod
    def isDuctNetwork(obj):
        """Test whether obj is a DuctNetwork FeaturePython object."""
        return bool(obj) and hasattr(obj, "Proxy") and isinstance(obj.Proxy, DuctNetwork)
        
    @staticmethod
    def isBaseObject(obj):
        if obj is None:
            return False
        if not (hvaclib.obj_is_sketch(obj) or hvaclib.obj_is_wire(obj)):
            return False
            
        for net in hvaclib.allHVACNetworks(obj.Document):
            base = getattr(net, "Base", None)
            if base and obj in base.OutList:
                return True
        return False
        
    @staticmethod
    def isGeometryObject(obj):
        return bool(obj) and hasattr(obj, "Proxy") and isinstance(obj.Proxy, DuctSegment)
        
    @staticmethod
    def getOwnerNetwork(obj):
        """Return the owning duct network document object for an internal object."""
        if DuctNetwork.isGeometryObject(obj):
            owner_name = getattr(obj, "OwnerNetworkName", "")
            doc = getattr(obj, "Document", None)
            if owner_name and doc:
                return doc.getObject(owner_name)
            return None
        elif DuctNetwork.isBaseObject(obj):
            for net in hvaclib.allHVACNetworks(obj.Document):
                base = getattr(net, "Base", None)
                if base and obj in base.OutList:
                    return net
        return None
        
    @staticmethod
    def getOwnerBaseObject(obj):
        """Return the base object for a given geometry object."""
        if DuctNetwork.isGeometryObject(obj):
            owner_name = getattr(obj, "SourceObjectName", "")
            doc = getattr(obj, "Document", None)
            if owner_name and doc:
                return doc.getObject(owner_name)
        return None
    
    # Functions for syncing object data with the network parser
    
    def syncSegments(self, net, parser, initial_sync=False):
        """
        Synchronize the derived DuctSegment objects with the base geometry.

        This method compares the edges provided by the network parser against the
        existing segment objects. It creates new segments as needed, updates
        metadata for existing ones, and prunes segments that no longer correspond
        to any geometry in the base objects.

        Args:
            net: The DuctNetwork object to synchronize.
            parser: An hvaclib.DuctNetworkParser instance containing edge data.
            initial_sync (bool): True if this is the first synchronization pass.
        """
        doc = net.Document
        geometry = getattr(net, "Geometry", None)
        if doc is None or geometry is None:
            return False
        changed = False

        # Map current segment objects by their stable keys
        existing_segments = self.collectSegmentObjects(net)
        live_objs = set()

        # Synchronize edges from the parser with document objects
        for edge_ref in parser.edges():
            key = edge_ref.tag
            
            # Get source object corresponding to edge
            source_obj = doc.getObject(edge_ref.obj_name)
            if source_obj is None:
                continue

            # Find corresponding DuctSegment
            if initial_sync:
                # Search by index since Tag is regenerated when objects are created
                segment_obj = None
                matched_old_key = None
                for old_key, seg in existing_segments.items():
                    if seg.SourceObjectName == source_obj.Name and seg.SourceIndex == edge_ref.local_index:
                        segment_obj = seg
                        matched_old_key = old_key
                        break

                if matched_old_key is not None and matched_old_key != key:
                    existing_segments.pop(matched_old_key, None)
                    existing_segments[key] = segment_obj
            else:
                # Search by Tag
                segment_obj = existing_segments.get(key)
            
            # Create the ductsegment if element is not yet created
            if segment_obj is None:
                segment_obj = DuctSegment.create(
                    doc,
                    "{}_Seg_{}_{}".format(net.Name, source_obj.Name, edge_ref.local_index),
                    owner=net,
                    key=key,
                    source_obj=source_obj,
                    source_index=edge_ref.local_index,
                )
                changed = True
                # Only suppress visibility during interactive sketch creation
                if source_obj.Name in self._hidden_source_names:
                    self._setSegmentVisibilityDeferred(segment_obj, False)
                else:
                    self._setSegmentVisibilityDeferred(segment_obj, True)
                
            # Ensure the segment is correctly nested in the internal Geometry folder
            if segment_obj not in geometry.OutList:
                geometry.addObject(segment_obj)
                changed = True
            
            # Track segments that should remain in the document
            live_objs.add(segment_obj)         

            # Update segment properties based on the latest parser results
            start_node, end_node = parser.edge_nodes(edge_ref)
            start_point, end_point = parser.edge_line(edge_ref)
            meta_changed = segment_obj.Proxy.updateMetadata(
                segment_obj,
                owner=net,
                key=key,
                source_obj=source_obj,
                source_index=edge_ref.local_index,
                start_node=start_node,
                end_node=end_node,
                start_point=start_point,
                end_point=end_point,
            )
            changed = changed or meta_changed
            
            # Restore runtime-only params if this segment was previously deleted
            cached_params = self._runtime_param_cache.pop(key, None)
            if cached_params:
                restored = self._restoreSegmentUserParams(segment_obj, cached_params)
                changed = changed or restored
            
            # Update the user-facing label
            new_label = DuctSegment.labelFor(source_obj, edge_ref.local_index)
            if segment_obj.Label != new_label:
                segment_obj.Label = new_label
                changed = True

        # Remove segments that are no longer part of the network's base geometry
        for segment_obj in list(existing_segments.values()):
            if segment_obj not in live_objs:
                seg_key = getattr(segment_obj, "SegmentKey", "")
                if seg_key:
                    self._runtime_param_cache[seg_key] = self._segmentUserParams(segment_obj)
                self.removeGeometryObject(net, segment_obj)
                changed = True
        return changed
                
    def requestSync(self, obj, initial_sync=None, reason="unknown"):
        if initial_sync is not None:
            self._initial_sync = bool(initial_sync)
        
        if self._sync_scheduled:
            self._sync_reason = reason
            return
        
        self._sync_scheduled = True
        self._sync_reason = reason
        QtCore.QTimer.singleShot(0, lambda o=obj: self._runDeferredSync(o))
    
    def _runDeferredSync(self, obj):
        self._sync_scheduled = False
        self._sync_reason = None

        if obj is None or obj.Document is None:
            return
        if self._sync_in_progress:
            return
    
        base_folder = getattr(obj, "Base", None)
        geometry_folder = getattr(obj, "Geometry", None)
        if base_folder is None or geometry_folder is None:
            return
    
        self._sync_in_progress = True
        try:
            parser = hvaclib.DuctNetworkParser(list(base_folder.OutList))
            changed = self.syncSegments(obj, parser, initial_sync=self._initial_sync)
            self._initial_sync = False
            if changed:
                obj.Document.recompute()
        except Exception as err:
            FreeCAD.Console.PrintError(
                "HVAC - Failed to update segments for '{}': {}\n".format(obj.Label, err)
            )
        finally:
            self._sync_in_progress = False
    
    @staticmethod
    def _segmentUserParams(obj):
        return {
            "SectionShape": str(getattr(obj, "SectionShape", "")),
            "Diameter": float(getattr(obj, "Diameter", 0.0)),
            "Width": float(getattr(obj, "Width", 0.0)),
            "Height": float(getattr(obj, "Height", 0.0)),
            "InsulationThickness": float(getattr(obj, "InsulationThickness", 0.0)),
            "Roughness": float(getattr(obj, "Roughness", 0.0)),
            "FlowRate": float(getattr(obj, "FlowRate", 0.0)),
            "Velocity": float(getattr(obj, "Velocity", 0.0)),
        }
    
    @staticmethod
    def _restoreSegmentUserParams(obj, params):
        if not isinstance(params, dict):
            return False
    
        changed = False
    
        def set_if_needed(prop, value):
            nonlocal changed
            try:
                if getattr(obj, prop) != value:
                    setattr(obj, prop, value)
                    changed = True
            except Exception:
                pass
    
        if "SectionShape" in params:
            set_if_needed("SectionShape", params["SectionShape"])
        if "Diameter" in params:
            set_if_needed("Diameter", params["Diameter"])
        if "Width" in params:
            set_if_needed("Width", params["Width"])
        if "Height" in params:
            set_if_needed("Height", params["Height"])
        if "InsulationThickness" in params:
            set_if_needed("InsulationThickness", params["InsulationThickness"])
        if "Roughness" in params:
            set_if_needed("Roughness", params["Roughness"])
        if "FlowRate" in params:
            set_if_needed("FlowRate", params["FlowRate"])
        if "Velocity" in params:
            set_if_needed("Velocity", params["Velocity"])
    
        return changed


class DuctNetworkViewProvider:
    """A View Provider for the HVAC duct network object"""

    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def __getstate__(self):
        # Create a copy of the state and remove the non-serializable object
        state = self.__dict__.copy()
        if 'Object' in state:
            del state['Object']
        return state

    def __setstate__(self, state):
        # Restore the state
        self.__dict__.update(state)
        # self.Object will be restored later in attach()

    def getIcon(self):
        return hvaclib.get_icon_path("DuctsIcon.svg")

    def setEdit(self, vobj, mode):
        panel = TaskPanelEditDuctNetwork(vobj.Object)
        Gui.Control.showDialog(panel)
        return True

    def unsetEdit(self, vobj, mode):
        Gui.Control.closeDialog()
        return True

    def doubleClicked(self, vobj):
        obj = vobj.Object
        # Make it the active network
        activate_duct_network(obj, set_edit=False)
        return True

    def claimChildren(self):
        obj = self.Object
        kids = []
        try:
            if obj.Base: kids.append(obj.Base)
            if obj.Geometry: kids.append(obj.Geometry)
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
        net = vobj.Object
        delete_duct_networks([net], remove_internal_only=True)
        return True


#=================================================
# C. Command classes
#=================================================


class CommandCreateDuctNetwork:
    """Create HVAC Duct Network."""

    def QT_TRANSLATE_NOOP(self, text):
        return text

    def GetResources(self):
        return {'Pixmap': hvaclib.get_icon_path("CreateDuctsIcon.svg"),
                'MenuText': QT_TRANSLATE_NOOP('HVAC_CreateDuctNetwork', 'Create Network'),
                'ToolTip': QT_TRANSLATE_NOOP('HVAC_CreateDuctNetwork', 'Create HVAC Duct Network from Sketch/ Line base Geometries')}

    def IsActive(self):
        if Gui.ActiveDocument:
            return True
        else:
            return False

    def Activated(self):
        create_new_duct_network()


class CommandActivateDuctNetwork:
    """Activate HVAC Duct Network."""

    def __init__(self):
        self.task_panel = None

    def GetResources(self):
        return {
            'Pixmap': hvaclib.get_icon_path("ActivateDuctsIcon.svg"),
            "MenuText": QT_TRANSLATE_NOOP("HVAC_ActivateDuctNetwork", "Activate Network"),
            "ToolTip": QT_TRANSLATE_NOOP("HVAC_ActivateDuctNetwork", "Sets a HVAC duct network as the active one for editing."),
            "CmdType": "ForEdit",
        }

    def IsActive(self):
        if Gui.ActiveDocument is None:
            return False

        # Command is active only if there is at least one HVAC network in the document to activate
        if hvaclib.allHVACNetworks():
            return True

        return False

    def Activated(self):
        hvac_networks = hvaclib.allHVACNetworks()
        selected_hvac_networks = hvaclib.selectedHVACNetworks()

        if len(hvac_networks) == 1:
            # If there's only one, activate it directly without showing a dialog
            activate_duct_network(hvac_networks[0], set_edit=False)
        elif selected_hvac_networks:
            # Select first selected
            activate_duct_network(selected_hvac_networks[0], set_edit=False)
        elif len(hvac_networks) > 1:
            # If there are multiple, show a task panel to let the user choose
            self.task_panel = TaskPanelActivate(hvac_networks)
            Gui.Control.showDialog(self.task_panel)


class CommandModifyDuctNetwork:
    """Modify HVAC Duct Network."""

    def QT_TRANSLATE_NOOP(self, text):
        return text

    def GetResources(self):
        return {'Pixmap': hvaclib.get_icon_path("ModifyDuctsIcon.svg"),
                'MenuText': QT_TRANSLATE_NOOP('HVAC_ModifyDuctNetwork', 'Modify Network'),
                'ToolTip': QT_TRANSLATE_NOOP('HVAC_ModifyDuctNetwork',  'Modify the selected HVAC Duct Network')}

    def IsActive(self):
        if Gui.ActiveDocument:
            selected_hvac_networks = hvaclib.selectedHVACNetworks()
            active_hvac_network = hvaclib.activeHVACNetwork()
            if selected_hvac_networks or active_hvac_network:
                return True
        else:
            return False

    def Activated(self):
        selected_hvac_networks = hvaclib.selectedHVACNetworks()
        if selected_hvac_networks:
            modify_duct_network(selected_hvac_networks[0])
        else:
            active_hvac_network = hvaclib.activeHVACNetwork()
            modify_duct_network(active_hvac_network)
            
            
class CommandEditBaseObject:
    """Edit base object of selected duct."""

    def QT_TRANSLATE_NOOP(self, text):
        return text

    def GetResources(self):
        return {'Pixmap': hvaclib.get_icon_path("ModifyDuctsIcon.svg"),
                'MenuText': QT_TRANSLATE_NOOP('HVAC_EditBaseObject', 'Modify routing'),
                'ToolTip': QT_TRANSLATE_NOOP('HVAC_EditBaseObject',  'Modify routing of selected duct')}

    def IsActive(self):
        if Gui.ActiveDocument:
            active_hvac_network = hvaclib.activeHVACNetwork()
            selected_geom = hvaclib.selectedGeometryObjects()
            if active_hvac_network and selected_geom:
                return True
        else:
            return False

    def Activated(self):
        base_objs = hvaclib.selectedGeometryObjects()
        if base_objs:
            base = DuctNetwork.getOwnerBaseObject(base_objs[0])
            if base:
                if hvaclib.obj_is_sketch(base):
                    Gui.ActiveDocument.setEdit(base.Name)
                elif hvaclib.obj_is_wire(base):
                    Gui.Selection.clearSelection()
                    Gui.Selection.addSelection(base)
                    Gui.ActiveDocument.setEdit(base, 0)


class CommandDeleteDuctNetwork:
    """Delete a selected HVAC Duct Network."""

    def QT_TRANSLATE_NOOP(self, text):
        return text

    def GetResources(self):
        return {'Pixmap': hvaclib.get_icon_path("DeleteDuctsIcon.svg"),
                'MenuText': QT_TRANSLATE_NOOP('HVAC_DeleteDuctNetwork', 'Delete Network'),
                'ToolTip': QT_TRANSLATE_NOOP('HVAC_DeleteDuctNetwork', 'Delete the selected HVAC Duct Network')}

    def IsActive(self):
        if Gui.ActiveDocument:
            selected_hvac_networks = hvaclib.selectedHVACNetworks()
            if selected_hvac_networks:
                return True
        else:
            return False

    def Activated(self):
        selected_hvac_networks = hvaclib.selectedHVACNetworks()
        if selected_hvac_networks:
            delete_duct_networks(selected_hvac_networks)
            
    
class CommandCreateSketch:
    """interactively adds a sketch to the currently active network"""
    
    def QT_TRANSLATE_NOOP(self, text):
        return text
    
    def GetResources(self):
        return {
            "Pixmap": "Sketcher_NewSketch",
            "MenuText": QT_TRANSLATE_NOOP('HVAC_CreateSketch', 'New Sketch'),
            "ToolTip": QT_TRANSLATE_NOOP('HVAC_CreateSketch', 'Create a new sketch inside the active duct network')
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None and DuctNetwork.getActive() is not None

    def Activated(self):
        net = DuctNetwork.getActive()
        if net and DuctNetwork.isDuctNetwork(net):
            DuctNetwork.createSketchInteractive(net)
            
            
class CommandCreateLine:
    """Interactively adds Draft line objects to the currently active network."""

    def QT_TRANSLATE_NOOP(self, text):
        return text

    def GetResources(self):
        return {
            "Pixmap": "Draft_Line",
            "MenuText": QT_TRANSLATE_NOOP("HVAC_CreateLine", "New Line"),
            "ToolTip": QT_TRANSLATE_NOOP(
                "HVAC_CreateLine",
                "Create line objects inside the active duct network"
            ),
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None and DuctNetwork.getActive() is not None

    def Activated(self):
        net = DuctNetwork.getActive()
        if net and DuctNetwork.isDuctNetwork(net):
            DuctNetwork.createDraftLineInteractive(net)


#=================================================
# D. Task Panel classes
#=================================================


class TaskPanelActivate:
    """A basic TaskPanel to select an HVAC netowrk to activate."""

    def __init__(self, hvac_networks):
        self.hvac_networks = hvac_networks
        self.hvac_networks_dict = {}
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(translate("HVAC_ActivateDuctNetwork", "Activate Network"))

        layout = QtWidgets.QVBoxLayout(self.form)
        label = QtWidgets.QLabel(translate("HVAC_ActivateDuctNetwork", "Select Network :"))
        self.combo = QtWidgets.QComboBox()

        for net in self.hvac_networks:
            # Store the user-friendly Label for display, and the internal Name for activation
            self.combo.addItem(net.Label, net.Name)
            self.hvac_networks_dict[net.Name] = net

        layout.addWidget(label)
        layout.addWidget(self.combo)

    def accept(self):
        """Called when the user clicks OK."""
        selected_name = self.combo.currentData()
        if selected_name:
            QtCore.QTimer.singleShot(0, lambda: activate_duct_network(self.hvac_networks_dict[selected_name], set_edit=False))
        return True

    def reject(self):
        """Called when the user clicks Cancel or closes the panel."""
        return True


class TaskPanelEditDuctNetwork:
    """A basic TaskPanel to edit an HVAC network."""

    def __init__(self, hvac_network):
        self.hvac_network = hvac_network
        self.hvac_networks_dict = {}
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(translate("HVAC_EditDuctNetwork", "Edit Network"))

        layout = QtWidgets.QVBoxLayout(self.form)
        # Label for instructions
        label = QtWidgets.QLabel(translate("HVAC_EditDuctNetwork", "Base Objects in Network (Sketch/ Draft Line):"))
        layout.addWidget(label)
        # List view to display selected objects
        self.list_view = QtWidgets.QListWidget()
        self.list_view.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)  # Enable multiple selection
        layout.addWidget(self.list_view)

        # Populate existing objects under Base
        if self.hvac_network.Base:
            for obj in self.hvac_network.Base.OutList:
                if self.valid_obj(obj):
                    self.list_view.addItem(obj.Label)

        # Button to enable selection of objects
        self.select_button = QtWidgets.QPushButton(translate("HVAC_EditDuctNetwork", "Add Selected"))
        self.select_button.clicked.connect(self.select_objects)
        layout.addWidget(self.select_button)

        # Button to remove selected objects from the list view
        self.remove_button = QtWidgets.QPushButton(translate("HVAC_EditDuctNetwork", "Remove Selected"))
        self.remove_button.clicked.connect(self.remove_selected_objects)
        layout.addWidget(self.remove_button)

    ## Helper methods

    def valid_obj(self, obj):
        """Return True if the object is valid for selection."""
        return hvaclib.obj_is_sketch(obj) or hvaclib.obj_is_wire(obj)

    def get_valid_selection(self):
        """Return a list of valid objects for selection."""
        selected_objects = Gui.Selection.getSelection()
        return [obj for obj in selected_objects if self.valid_obj(obj)]

    ## Core methods

    def select_objects(self):
        """Enable selection of objects and add them to the list view."""
        valid_objects = self.get_valid_selection()
        existing_labels = [self.list_view.item(i).text() for i in range(self.list_view.count())]
        for obj in valid_objects:
            if obj.Label not in existing_labels:
                self.list_view.addItem(obj.Label)

    def remove_selected_objects(self):
        """Remove selected objects from the list view."""
        # Remove based on selected items in QListWidget
        selected_items = self.list_view.selectedItems()
        for item in selected_items:
            self.list_view.takeItem(self.list_view.row(item))
        # Remove based on selection in 3D view
        doc = self.hvac_network.Document
        selected_objects = Gui.Selection.getSelection()
        for obj in selected_objects:
            if obj in self.hvac_network.Base.OutList:
                for i in range(self.list_view.count()):
                    if self.list_view.item(i).text() == obj.Label:
                        self.list_view.takeItem(i)
                        break

    def accept(self):
        """Called when the user clicks OK."""
        selected_items = [self.list_view.item(i).text() for i in range(self.list_view.count())]
        doc = self.hvac_network.Document

        # Add selected items to Base folder
        for item_label in selected_items:
            for obj in doc.Objects:
                if obj.Label == item_label and obj not in self.hvac_network.Base.OutList:
                    DuctNetwork.addBaseObject(self.hvac_network, obj)
                    break

        # Remove unselected items from Base folder
        existing_labels = [self.list_view.item(i).text() for i in range(self.list_view.count())]
        for obj in self.hvac_network.Base.OutList:
            if self.valid_obj(obj) and obj.Label not in existing_labels:
                DuctNetwork.removeBaseObject(self.hvac_network, obj)

        return True

    def reject(self):
        """Called when the user clicks Cancel or closes the panel."""
        return True


#=================================================
# E. General functions
#=================================================

_hvac_change_observer = None

def ensure_change_observer():
    global _hvac_change_observer
    if _hvac_change_observer is None:
        _hvac_change_observer = DuctNetworkChangeObserver()
        FreeCAD.addDocumentObserver(_hvac_change_observer)

def create_new_duct_network(name="DuctNetwork", set_active=True):
    """Create new duct network"""
    # Create new duct netowork and create default folders
    net = DuctNetwork.createObject(name)
    print("HVAC - New DuctNetwork created")
    if set_active:
        # Set as active network and enable edit mode
        activate_duct_network(net, set_edit=False)

def activate_duct_network(net, set_edit=False):
    DuctNetwork.setActive(net)
    # Set network to edit mode
    if set_edit:
        Gui.ActiveDocument.setEdit(net.Name)
    else:
      pass
    hvaclib.refreshState()

def modify_duct_network(net):
    """Modify the selected HVAC duct network object"""
    # Set as active network and enable edit mode
    activate_duct_network(net, set_edit=True)
    print("HVAC - Edit DuctNetwork completed")

def delete_duct_networks(nets, remove_internal_only=False):
    """Delete the selected HVAC duct network object"""
    doc = FreeCAD.ActiveDocument
    for net in nets:
        if net.Document != doc:
            continue
            
        if hasattr(net, "Proxy") and net.Proxy:
            net.Proxy._allow_internal_delete = True
            
        if hasattr(net, "Geometry") and net.Geometry:
            for obj in list(net.Geometry.OutList):
                DuctNetwork.removeGeometryObject(net, obj)
            doc.removeObject(net.Geometry.Name)
            
        if hasattr(net, "Base") and net.Base:
            for obj in list(net.Base.OutList):
                net.Base.removeObject(obj)
            doc.removeObject(net.Base.Name)
            
        if not remove_internal_only:
            doc.removeObject(net.Name)
    hvaclib.refreshState()
    print("HVAC - Deleted selected {} DuctNetwork(s)".format(len(nets)))


#=================================================
# F. Register Commands
#=================================================

if FreeCAD.GuiUp:
    ensure_change_observer()
    FreeCAD.Gui.addCommand('HVAC_CreateDuctNetwork', CommandCreateDuctNetwork())
    FreeCAD.Gui.addCommand('HVAC_ModifyDuctNetwork', CommandModifyDuctNetwork())
    FreeCAD.Gui.addCommand('HVAC_EditBaseObject', CommandEditBaseObject())
    FreeCAD.Gui.addCommand('HVAC_DeleteDuctNetwork', CommandDeleteDuctNetwork())
    FreeCAD.Gui.addCommand('HVAC_ActivateDuctNetwork', CommandActivateDuctNetwork())
    FreeCAD.Gui.addCommand("HVAC_CreateSketch", CommandCreateSketch())
    FreeCAD.Gui.addCommand("HVAC_CreateLine", CommandCreateLine())
