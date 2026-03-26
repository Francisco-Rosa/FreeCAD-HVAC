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

import FreeCAD
import FreeCADGui as Gui
from PySide import QtWidgets, QtCore
from PySide.QtCore import QT_TRANSLATE_NOOP
translate = FreeCAD.Qt.translate

from . import hvaclib


class TaskPanelActivate:
    """A basic TaskPanel to select an HVAC netowrk to activate."""

    def __init__(self, hvac_networks, activate_callback=None):
        self.hvac_networks = hvac_networks
        self.activate_callback = activate_callback
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
            QtCore.QTimer.singleShot(0, lambda: self.activate_callback(self.hvac_networks_dict[selected_name], set_edit=False))
        return True

    def reject(self):
        """Called when the user clicks Cancel or closes the panel."""
        return True


class TaskPanelEditDuctNetwork:
    """A basic TaskPanel to edit an HVAC network."""

    def __init__(self, hvac_network, callback_add_base_object, callback_remove_base_object):
        self.hvac_network = hvac_network
        self.callback_add_base_object = callback_add_base_object
        self.callback_remove_base_object = callback_remove_base_object
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
        return hvaclib.isSketch(obj) or hvaclib.isWire(obj)

    def get_valid_selection(self, include_derived=True):
        """Return a list of valid objects for selection."""
        from .DuctNetwork import DuctNetwork
        selected_objects = Gui.Selection.getSelection()
        derived_objects = [obj for obj in selected_objects if hvaclib.isDuctSegment(obj)]
        
        valid_obs = {obj for obj in selected_objects if self.valid_obj(obj)}
        
        if include_derived:
            valid_obs_derived = set()
            for obj in derived_objects:
                base_obj = DuctNetwork.getOwnerBaseObject(obj)
                base_net = DuctNetwork.getOwnerNetwork(base_obj)
                if base_obj and base_net and base_net == self.hvac_network:
                    valid_obs_derived.add(base_obj)
            return list(valid_obs | valid_obs_derived)
        else:
            return list(valid_obs)

    ## Core methods

    def select_objects(self):
        """Enable selection of objects and add them to the list view."""
        valid_objects = self.get_valid_selection(include_derived=False)
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
        selected_objects = self.get_valid_selection(include_derived=True)
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
                    self.callback_add_base_object(self.hvac_network, obj)
                    break

        # Remove unselected items from Base folder
        existing_labels = [self.list_view.item(i).text() for i in range(self.list_view.count())]
        for obj in self.hvac_network.Base.OutList:
            if self.valid_obj(obj) and obj.Label not in existing_labels:
                self.callback_remove_base_object(self.hvac_network, obj)

        return True

    def reject(self):
        """Called when the user clicks Cancel or closes the panel."""
        return True


class TaskPanelNetworkTypeDefaults:
    """Task panel to edit network-level type defaults."""

    def __init__(self, network_obj, apply_callback=None):
        self.network_obj = network_obj
        self.apply_callback = apply_callback

        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(translate("HVAC_NetworkTypeDefaults", "HVAC Type Defaults"))

        layout = QtWidgets.QVBoxLayout(self.form)

        title = QtWidgets.QLabel(
            translate("HVAC_NetworkTypeDefaults", "Network: {}").format(network_obj.Label)
        )
        layout.addWidget(title)

        layout.addWidget(QtWidgets.QLabel(
            translate("HVAC_NetworkTypeDefaults", "Default library:")
        ))
        self.library_combo = QtWidgets.QComboBox()
        layout.addWidget(self.library_combo)

        layout.addWidget(QtWidgets.QLabel(
            translate("HVAC_NetworkTypeDefaults", "Default segment profile:")
        ))
        self.profile_combo = QtWidgets.QComboBox()
        layout.addWidget(self.profile_combo)
        
        layout.addWidget(self._makeSeparator())
        
        layout.addWidget(QtWidgets.QLabel(
            translate("HVAC_NetworkTypeDefaults", "Default dimensions:")
        ))
        
        layout.addLayout(self._buildDimensionEditors())

        # note = QtWidgets.QLabel(
        #     translate(
        #         "HVAC_NetworkTypeDefaults",
        #         "Junction types are auto selected based on parser/classifier output unless manually overridden."
        #     )
        # )
        # note.setWordWrap(True)
        # layout.addWidget(note)
        
        layout.addWidget(self._makeSeparator())
        
        layout.addWidget(QtWidgets.QLabel(
            translate("HVAC_NetworkTypeDefaults", "Default attachment:")
        ))
        layout.addLayout(self._buildAttachmentGrid())
        
        layout.addWidget(self._makeSeparator())
        
        layout.addWidget(QtWidgets.QLabel(
            translate("HVAC_NetworkTypeDefaults", "Default offset:")
        ))
        layout.addLayout(self._buildOffsetEditors())

        self._populateLibraries()
        self._loadFromNetwork()

        self.library_combo.currentIndexChanged.connect(self._refreshProfiles)

    def _makeSeparator(self):
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.HLine)
        line.setFrameShadow(QtWidgets.QFrame.Sunken)
        return line
        
    def _buildDimensionEditors(self):
        row = QtWidgets.QGridLayout()
        row.setContentsMargins(0, 0, 0, 0)
    
        self.default_diameter = QtWidgets.QDoubleSpinBox()
        self.default_height = QtWidgets.QDoubleSpinBox()
        self.default_width = QtWidgets.QDoubleSpinBox()
    
        for w in (self.default_diameter, self.default_width, self.default_height):
            w.setDecimals(3)
            w.setRange(0.0, 1e9)
            w.setSingleStep(10.0)
            w.setSuffix(" mm")
    
        row.addWidget(QtWidgets.QLabel("Diameter"), 0, 0)
        row.addWidget(self.default_diameter, 0, 1)
    
        row.addWidget(QtWidgets.QLabel("Height"), 1, 0)
        row.addWidget(self.default_height, 1, 1)
    
        row.addWidget(QtWidgets.QLabel("Width"), 2, 0)
        row.addWidget(self.default_width, 2, 1)
    
        return row
    
    def _buildAttachmentGrid(self):
        grid = QtWidgets.QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(1)
        grid.setVerticalSpacing(1)
    
        self.attachment_group = QtWidgets.QButtonGroup(self.form)
        self.attachment_group.setExclusive(True)
        self._attachment_buttons = {}
    
        items = [
            ("TopLeft",       "↖", 0, 0),
            ("TopCenter",     "↑", 0, 1),
            ("TopRight",      "↗", 0, 2),
            ("CenterLeft",    "←", 1, 0),
            ("Center",        "•", 1, 1),
            ("CenterRight",   "→", 1, 2),
            ("BottomLeft",    "↙", 2, 0),
            ("BottomCenter",  "↓", 2, 1),
            ("BottomRight",   "↘", 2, 2),
        ]
    
        for key, text, r, c in items:
            btn = QtWidgets.QToolButton()
            btn.setText(text)
            btn.setCheckable(True)
            btn.setToolTip(key)
            btn.setFixedSize(28, 24)
            self.attachment_group.addButton(btn)
            self._attachment_buttons[key] = btn
            grid.addWidget(btn, r, c)
    
        return grid
        
    def _buildOffsetEditors(self):
        row = QtWidgets.QGridLayout()

        self.offset_x = QtWidgets.QDoubleSpinBox()
        self.offset_y = QtWidgets.QDoubleSpinBox()
        self.offset_z = QtWidgets.QDoubleSpinBox()

        for w in (self.offset_x, self.offset_y, self.offset_z):
            w.setDecimals(3)
            w.setRange(-1e6, 1e6)
            w.setSingleStep(10.0)

        row.addWidget(QtWidgets.QLabel("X"), 0, 0)
        row.addWidget(self.offset_x, 0, 1)
        row.addWidget(QtWidgets.QLabel("Y"), 1, 0)
        row.addWidget(self.offset_y, 1, 1)
        row.addWidget(QtWidgets.QLabel("Z"), 2, 0)
        row.addWidget(self.offset_z, 2, 1)
    
        return row
    
    def _populateLibraries(self):
        reg = hvaclib.HVACLibraryService.get_hvac_library_registry()
        self.library_combo.clear()
        for lib in reg.list_libraries():
            self.library_combo.addItem(lib.label, lib.id)

    def _refreshProfiles(self):
        library_id = self.library_combo.currentData()
        current_profile = self.profile_combo.currentData()

        self.profile_combo.clear()
        if not library_id:
            return

        profiles = hvaclib.HVACLibraryService.segment_profiles_for_library(library_id)
        for profile in profiles:
            self.profile_combo.addItem(profile, profile)

        if current_profile:
            idx = self.profile_combo.findData(current_profile)
            if idx >= 0:
                self.profile_combo.setCurrentIndex(idx)
            elif profiles:
                self.profile_combo.setCurrentIndex(0)
        elif profiles:
            self.profile_combo.setCurrentIndex(0)

    def _loadFromNetwork(self):
        lib_id = getattr(self.network_obj, "DefaultLibraryId", "")
        if lib_id:
            idx = self.library_combo.findData(lib_id)
            if idx >= 0:
                self.library_combo.setCurrentIndex(idx)
                
        self._refreshProfiles()

        profile = getattr(self.network_obj, "DefaultSegmentProfile", "")
        if profile:
            idx = self.profile_combo.findData(profile)
            if idx >= 0:
                self.profile_combo.setCurrentIndex(idx)
                
        self.default_diameter.setValue(float(getattr(self.network_obj, "DefaultDiameter", 100.0)))
        self.default_width.setValue(float(getattr(self.network_obj, "DefaultWidth", 100.0)))
        self.default_height.setValue(float(getattr(self.network_obj, "DefaultHeight", 100.0)))
                
        attachment = str(getattr(self.network_obj, "DefaultAttachment", "Center"))
        if attachment in self._attachment_buttons:
            self._attachment_buttons[attachment].setChecked(True)
        elif "Center" in self._attachment_buttons:
            self._attachment_buttons["Center"].setChecked(True)
        
        offset = FreeCAD.Vector(getattr(self.network_obj, "DefaultOffset", FreeCAD.Vector(0, 0, 0)))
        self.offset_x.setValue(offset.x)
        self.offset_y.setValue(offset.y)
        self.offset_z.setValue(offset.z)
        
    def _selectedAttachment(self):
        for key, btn in self._attachment_buttons.items():
            if btn.isChecked():
                return key
        return "Center"
    
    def _currentOffset(self):
        return FreeCAD.Vector(
            self.offset_x.value(),
            self.offset_y.value(),
            self.offset_z.value(),
        )

    def accept(self):
        if self.apply_callback:
            self.apply_callback(
                self.network_obj,
                library_id=self.library_combo.currentData(),
                segment_profile=self.profile_combo.currentData(),
                default_attachment=self._selectedAttachment(),
                default_offset=self._currentOffset(),
                default_diameter=self.default_diameter.value(),
                default_width=self.default_width.value(),
                default_height=self.default_height.value(),
            )
        return True

    def reject(self):
        return True
        

class TaskPanelTypeEditor:
    """Task panel to edit library/type selection for selected HVAC geometry objects."""

    def __init__(self, objects, apply_callback=None):
        self.objects = [o for o in (objects or []) if o is not None]
        self.apply_callback = apply_callback
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(translate("HVAC_EditType", "Edit HVAC Type"))

        layout = QtWidgets.QVBoxLayout(self.form)

        info_text = translate(
            "HVAC_EditType",
            "Selected objects: {}"
        ).format(len(self.objects))
        self.info_label = QtWidgets.QLabel(info_text)
        layout.addWidget(self.info_label)

        self.object_names = QtWidgets.QListWidget()
        self.object_names.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        for obj in self.objects:
            self.object_names.addItem("{} ({})".format(obj.Label, obj.Name))
        layout.addWidget(self.object_names)

        # Library
        layout.addWidget(QtWidgets.QLabel(translate("HVAC_EditType", "Library:")))
        self.library_combo = QtWidgets.QComboBox()
        layout.addWidget(self.library_combo)

        # Type
        layout.addWidget(QtWidgets.QLabel(translate("HVAC_EditType", "Type:")))
        self.type_combo = QtWidgets.QComboBox()
        layout.addWidget(self.type_combo)

        self._populateLibraries()
        self._loadFromSelection()

        self.library_combo.currentIndexChanged.connect(self._refreshTypes)

    def _populateLibraries(self):
        self.library_combo.clear()
        reg = hvaclib.HVACLibraryService.get_hvac_library_registry()
        for lib in reg.list_libraries():
            self.library_combo.addItem(lib.label, lib.id)

    def _commonLibraryId(self):
        vals = {getattr(o, "LibraryId", "") for o in self.objects}
        return vals.pop() if len(vals) == 1 else ""

    def _commonTypeId(self):
        vals = {getattr(o, "TypeId", "") for o in self.objects}
        return vals.pop() if len(vals) == 1 else ""

    def _loadFromSelection(self):
        library_id = self._commonLibraryId()

        if library_id:
            idx = self.library_combo.findData(library_id)
            if idx >= 0:
                self.library_combo.setCurrentIndex(idx)

        self._refreshTypes()

        type_id = self._commonTypeId()
        if type_id:
            idx = self.type_combo.findData(type_id)
            if idx >= 0:
                self.type_combo.setCurrentIndex(idx)

    def _refreshTypes(self):
        self.type_combo.clear()
        if not self.objects:
            return

        library_id = self.library_combo.currentData()
        if not library_id:
            return

        reg = hvaclib.HVACLibraryService.get_hvac_library_registry()
        lib = reg.get_library(library_id)
        if lib is None:
            return

        ref = self.objects[0]

        if hvaclib.isDuctSegment(ref):
            # For segments, keep it simple:
            # show all segment types from the selected library.
            type_defs = lib.list_types(category="segment")

        else:
            # For junctions, keep family filtering.
            family = getattr(ref, "Family", "")
            profile = getattr(ref, "Profile", "")
            type_defs = lib.list_types(
                category="junction",
                family=family if family else None,
                profile=profile if profile else None,
            )

        for tdef in type_defs:
            self.type_combo.addItem(tdef.label, tdef.id)

    def accept(self):
        library_id = self.library_combo.currentData()
        type_id = self.type_combo.currentData()

        if self.apply_callback:
            QtCore.QTimer.singleShot(
                0,
                lambda: self.apply_callback(
                    self.objects,
                    library_id=library_id,
                    type_id=type_id,
                )
            )
        return True

    def reject(self):
        return True


class TaskPanelSegmentPlacementEditor:
    """Live editor for attachment, offset and profile X axis."""

    def __init__(self, objects, apply_callback=None):
        self.objects = [o for o in (objects or []) if o is not None]
        self.apply_callback = apply_callback
        self._loading = False
        self._attachment_buttons = {}
        self._axis_buttons = {}

        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(
            translate("HVAC_EditPlacement", "Edit Segment Placement")
        )

        layout = QtWidgets.QVBoxLayout(self.form)

        info_text = translate(
            "HVAC_EditPlacement",
            "Selected objects: {}"
        ).format(len(self.objects))
        self.info_label = QtWidgets.QLabel(info_text)
        layout.addWidget(self.info_label)

        self.object_names = QtWidgets.QListWidget()
        self.object_names.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        for obj in self.objects:
            self.object_names.addItem("{} ({})".format(obj.Label, obj.Name))
        if len(self.objects) > 1:
            layout.addWidget(self.object_names)
            
        layout.addWidget(self._makeSeparator())

        # Attachment
        layout.addWidget(QtWidgets.QLabel(
            translate("HVAC_EditPlacement", "Attachment:")
        ))
        layout.addLayout(self._buildAttachmentGrid())
        
        layout.addWidget(self._makeSeparator())

        # Offset
        layout.addWidget(QtWidgets.QLabel(
            translate("HVAC_EditPlacement", "Offset:")
        ))
        layout.addLayout(self._buildOffsetEditors())
        
        layout.addWidget(self._makeSeparator())
        
        # Profile X axis
        layout.addWidget(QtWidgets.QLabel(
            translate("HVAC_EditPlacement", "Profile X axis:")
        ))
        layout.addLayout(self._buildAxisButtons())

        self._loading = True
        try:
            self._loadFromSelection()
        finally:
            self._loading = False

    def _makeSeparator(self):
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.HLine)
        line.setFrameShadow(QtWidgets.QFrame.Sunken)
        line.setLineWidth(1)
        line.setMidLineWidth(0)
        return line
    
    def _buildAttachmentGrid(self):
        grid = QtWidgets.QGridLayout()
        
        self.attachment_group = QtWidgets.QButtonGroup(self.form)
        self.attachment_group.setExclusive(True)

        items = [
            ("TopLeft",       "↖", 0, 0),
            ("TopCenter",     "↑", 0, 1),
            ("TopRight",      "↗", 0, 2),
            ("CenterLeft",    "←", 1, 0),
            ("Center",        "•", 1, 1),
            ("CenterRight",   "→", 1, 2),
            ("BottomLeft",    "↙", 2, 0),
            ("BottomCenter",  "↓", 2, 1),
            ("BottomRight",   "↘", 2, 2),
        ]

        for key, text, r, c in items:
            btn = QtWidgets.QToolButton()
            btn.setText(text)
            btn.setCheckable(True)
            btn.setToolTip(key)
            btn.setMinimumSize(40, 32)
            self.attachment_group.addButton(btn)
            self._attachment_buttons[key] = btn
            grid.addWidget(btn, r, c)

        self.attachment_group.buttonClicked.connect(lambda _btn: self._applyNow())
        return grid

    def _buildOffsetEditors(self):
        row = QtWidgets.QGridLayout()

        self.offset_x = QtWidgets.QDoubleSpinBox()
        self.offset_y = QtWidgets.QDoubleSpinBox()
        self.offset_z = QtWidgets.QDoubleSpinBox()

        for w in (self.offset_x, self.offset_y, self.offset_z):
            w.setDecimals(3)
            w.setRange(-1e6, 1e6)
            w.setSingleStep(10.0)
            w.editingFinished.connect(self._applyNow)

        row.addWidget(QtWidgets.QLabel("X"), 0, 0)
        row.addWidget(self.offset_x, 0, 1)
        row.addWidget(QtWidgets.QLabel("Y"), 1, 0)
        row.addWidget(self.offset_y, 1, 1)
        row.addWidget(QtWidgets.QLabel("Z"), 2, 0)
        row.addWidget(self.offset_z, 2, 1)

        return row

    def _buildAxisButtons(self):
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(1)
        
        self.axis_group = QtWidgets.QButtonGroup(self.form)
        self.axis_group.setExclusive(True)

        axes = [
            ("Auto", FreeCAD.Vector(0, 0, 0)),
            ("X",    FreeCAD.Vector(1, 0, 0)),
            ("Y",    FreeCAD.Vector(0, 1, 0)),
            ("Z",    FreeCAD.Vector(0, 0, 1)),
        ]

        for label, vec in axes:
            btn = QtWidgets.QToolButton()
            btn.setText(label)
            btn.setCheckable(True)
            btn._axis_vec = FreeCAD.Vector(vec)
            self.axis_group.addButton(btn)
            self._axis_buttons[label] = btn
            row.addWidget(btn)

        self.axis_group.buttonClicked.connect(lambda _btn: self._applyNow())
        return row

    def _commonValue(self, getter):
        vals = []
        for obj in self.objects:
            try:
                vals.append(getter(obj))
            except Exception:
                vals.append(None)

        if not vals:
            return None

        first = vals[0]
        for v in vals[1:]:
            if v != first:
                return None
        return first

    def _loadFromSelection(self):
        attachment = self._commonValue(
            lambda o: str(getattr(o, "Attachment", "Center"))
        )
        if attachment in self._attachment_buttons:
            self._attachment_buttons[attachment].setChecked(True)
        elif "Center" in self._attachment_buttons:
            self._attachment_buttons["Center"].setChecked(True)

        offset = self._commonValue(
            lambda o: FreeCAD.Vector(getattr(o, "Offset", FreeCAD.Vector(0, 0, 0)))
        )
        if offset is not None:
            self.offset_x.setValue(offset.x)
            self.offset_y.setValue(offset.y)
            self.offset_z.setValue(offset.z)

        axis = self._commonValue(
            lambda o: FreeCAD.Vector(getattr(o, "ProfileXAxis", FreeCAD.Vector(0, 0, 0)))
        )

        if axis is None or axis == FreeCAD.Vector(0, 0, 0):
            self._axis_buttons["Auto"].setChecked(True)
        elif axis == FreeCAD.Vector(1, 0, 0):
            self._axis_buttons["X"].setChecked(True)
        elif axis == FreeCAD.Vector(0, 1, 0):
            self._axis_buttons["Y"].setChecked(True)
        elif axis == FreeCAD.Vector(0, 0, 1):
            self._axis_buttons["Z"].setChecked(True)
        else:
            self._axis_buttons["Auto"].setChecked(True)

    def _selectedAttachment(self):
        for key, btn in self._attachment_buttons.items():
            if btn.isChecked():
                return key
        return "Center"

    def _selectedProfileXAxis(self):
        for btn in self.axis_group.buttons():
            if btn.isChecked():
                return FreeCAD.Vector(btn._axis_vec)
        return FreeCAD.Vector(0, 0, 0)

    def _currentOffset(self):
        return FreeCAD.Vector(
            self.offset_x.value(),
            self.offset_y.value(),
            self.offset_z.value(),
        )

    def _applyNow(self):
        if self._loading or not self.apply_callback:
            return

        self.apply_callback(
            self.objects,
            attachment=self._selectedAttachment(),
            offset=self._currentOffset(),
            profile_x_axis=self._selectedProfileXAxis(),
        )

    def accept(self):
        # Live-apply panel; nothing extra on OK.
        return True

    def reject(self):
        return True
