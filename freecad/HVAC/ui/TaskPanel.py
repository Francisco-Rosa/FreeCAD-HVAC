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

import contextlib
import json
import traceback

import FreeCAD
import FreeCADGui as Gui
import Materials
import MatGui  # registers MatGui::MaterialTreeWidget with Gui.UiLoader -- see MaterialPickerDialog
from PySide import QtWidgets, QtCore
from PySide.QtCore import QT_TRANSLATE_NOOP
translate = FreeCAD.Qt.translate

from ..utils import hvaclib
from ..utils import materials as hvac_materials
from ..core import _construction_schema
from ..library.construction import ALL_LAYER_ROLES, role_property_suffix
from ..ui.Observer import buildPortHighlightCoinNode, TerminalFlowRateObserver, AirflowResultObserver


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
        from ..core.Network import DuctNetwork
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


class TaskPanelDirectionEditMode:
    """Side panel shown while duct direction edit mode is active."""

    def __init__(self, network_obj, session):
        self.network_obj = network_obj
        self.session = session

        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(
            translate("HVAC_DirectionEditMode", "Edit Duct Directions")
        )

        layout = QtWidgets.QVBoxLayout(self.form)

        title = QtWidgets.QLabel(
            translate(
                "HVAC_DirectionEditMode",
                "Direction edit mode is active.",
            )
        )
        title.setWordWrap(True)
        layout.addWidget(title)

        help_text = QtWidgets.QLabel(
            translate(
                "HVAC_DirectionEditMode",
                "Select a base Sketch edge or Draft route object to reverse its direction."
            )
        )
        help_text.setWordWrap(True)
        layout.addWidget(help_text)

        close_button = QtWidgets.QPushButton(
            translate("HVAC_DirectionEditMode", "Close Direction Edit Mode")
        )
        close_button.clicked.connect(self._close)
        layout.addWidget(close_button)

        layout.addStretch(1)

    def _close(self):
        self.session.stop(request_sync=True)
        Gui.Control.closeDialog()

    def accept(self):
        self.session.stop(request_sync=True)
        return True

    def reject(self):
        self.session.stop(request_sync=True)
        return True


class MaterialPickerDialog(QtWidgets.QDialog):
    """
    Modal "pick any FreeCAD material" dialog, built from FreeCAD's own
    native Material browser widget (MatGui::MaterialTreeWidget) -- the same
    tree used by the Material workbench/editor and by other addons (e.g.
    CAM's own "Assign Material" dialog in Path/Main/Gui/Job.py). No HVAC-
    specific material list: every material known to FreeCAD (built-in, this
    addon's own, other addons', user-defined) shows up here unfiltered.
    """

    def __init__(self, title, parent=None):
        super(MaterialPickerDialog, self).__init__(parent)
        self.uuid = None

        self.setWindowTitle(title)

        self.materialTree = Gui.UiLoader().createWidget("MatGui::MaterialTreeWidget")
        self.materialTreeWidget = MatGui.MaterialTreeWidget(self.materialTree)

        self.okButton = QtWidgets.QPushButton(translate("HVAC", "OK"))
        self.cancelButton = QtWidgets.QPushButton(translate("HVAC", "Cancel"))
        self.okButton.clicked.connect(self.accept)
        self.cancelButton.clicked.connect(self.reject)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.materialTree)

        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(self.okButton)
        button_layout.addWidget(self.cancelButton)
        layout.addLayout(button_layout)
        self.setLayout(layout)

        self.materialTree.onMaterial.connect(self._onMaterial)

    def _onMaterial(self, uuid):
        self.uuid = uuid


class MaterialPickerRow(QtWidgets.QWidget):
    """
    One "<current material name> [Browse...]" row, reused by
    TaskPanelEditMaterial (per-object casing/insulation) and
    TaskPanelNetworkTypeDefaults (network-level defaults) -- both just need
    "show what's currently set, let the user replace it via
    MaterialPickerDialog." `touched` is False until the user actually picks
    something, so a caller can tell "left alone" apart from "re-picked the
    same material" and skip re-applying anything unnecessarily.
    """

    def __init__(self, dialog_title, initial_label, parent=None):
        super(MaterialPickerRow, self).__init__(parent)
        self.material = None
        self.touched = False
        self._dialog_title = dialog_title

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.name_label = QtWidgets.QLabel(initial_label)
        self.browse_button = QtWidgets.QPushButton(translate("HVAC", "Browse..."))
        self.browse_button.clicked.connect(self._browse)
        layout.addWidget(self.name_label, 1)
        layout.addWidget(self.browse_button)

    def _browse(self):
        dialog = MaterialPickerDialog(self._dialog_title, parent=self)
        if dialog.exec_() == QtWidgets.QDialog.Accepted and dialog.uuid:
            material = hvac_materials.get_material_by_uuid(dialog.uuid)
            if material is not None:
                self.material = material
                self.touched = True
                self.name_label.setText(material.Name)


def _common_material_label(objects, prop_name):
    """
    "(none)" if no object has this material set, the shared material's own
    Name if every object agrees, else "(multiple)" -- same convention
    TaskPanelTypeEditor uses for a mixed-selection combo box.
    """
    names = set()
    for obj in objects:
        material = getattr(obj, prop_name, None)
        names.add(material.Name if material is not None and getattr(material, "Name", "") else "")
    if len(names) == 1:
        name = names.pop()
        return name if name else translate("HVAC_EditMaterial", "(none)")
    return translate("HVAC_EditMaterial", "(multiple)")


def _layer_label(layer_id):
    return layer_id.replace("_", " ").capitalize()


def layer_visibility_entries(net):
    """
    [(property name, label), ...] for the display switches a network has:
    one ShowLayer_<Role> per construction layer role, then ShowFeatures.
    Shared by the Layer Visibility panel and its toolbar dropdown.
    """
    entries = []
    for role in ALL_LAYER_ROLES:
        prop_name = "ShowLayer_" + role_property_suffix(role)
        if prop_name in net.PropertiesList:
            entries.append((prop_name, _layer_label(role)))
    if "ShowFeatures" in net.PropertiesList:
        entries.append(("ShowFeatures", translate("HVAC_LayerVisibility", "Construction features (flanges, ...)")))
    return entries


def set_layer_visibility(net, prop_name, value):
    """Set one display switch; only writes on a change (each write re-renders the network)."""
    if bool(getattr(net, prop_name, True)) != bool(value):
        setattr(net, prop_name, bool(value))


class TaskPanelLayerVisibility:
    """
    Task panel with the active network's display switches: one checkbox per
    construction layer role and one for construction features. Display only,
    applied at once (no recompute), so the panel only has a Close button.
    """

    def __init__(self, network_obj):
        self.network_obj = network_obj

        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(translate("HVAC_LayerVisibility", "Layer Visibility"))
        layout = QtWidgets.QVBoxLayout(self.form)

        layout.addWidget(QtWidgets.QLabel(
            translate("HVAC_LayerVisibility", "Network: {}").format(network_obj.Label)
        ))
        note = QtWidgets.QLabel(
            translate("HVAC_LayerVisibility", "Show layers and features (display only, applied at once):")
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        self.checks = {}
        for prop_name, label in layer_visibility_entries(network_obj):
            check = QtWidgets.QCheckBox(label)
            check.setChecked(bool(getattr(network_obj, prop_name, True)))
            check.toggled.connect(
                lambda checked, prop_name=prop_name: set_layer_visibility(self.network_obj, prop_name, checked)
            )
            layout.addWidget(check)
            self.checks[prop_name] = check

        buttons = QtWidgets.QHBoxLayout()
        show_all = QtWidgets.QPushButton(translate("HVAC_LayerVisibility", "Show All"))
        show_all.clicked.connect(lambda: [check.setChecked(True) for check in self.checks.values()])
        buttons.addWidget(show_all)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addStretch(1)

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Close

    def accept(self):
        return True

    def reject(self):
        return True


class TaskPanelEditMaterial:
    """
    Task panel to assign native FreeCAD materials to selected duct
    segment(s)/component(s) -- one row per construction layer id present on
    the selection (union across a mixed selection of different types; see
    CommandEditMaterial), instead of two hardcoded casing/insulation rows.
    """

    def __init__(self, objects, apply_callback=None):
        self.objects = [o for o in (objects or []) if o is not None]
        self.apply_callback = apply_callback

        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(translate("HVAC_EditMaterial", "Edit Material"))

        layout = QtWidgets.QVBoxLayout(self.form)
        layout.addWidget(QtWidgets.QLabel(
            translate("HVAC_EditMaterial", "Selected objects: {}").format(len(self.objects))
        ))

        layer_ids = []
        for obj in self.objects:
            for layer_id in getattr(obj, "ConstructionLayerIds", []) or []:
                if layer_id not in layer_ids:
                    layer_ids.append(layer_id)

        self.rows = {}
        for layer_id in layer_ids:
            label = _layer_label(layer_id)
            layout.addWidget(QtWidgets.QLabel(
                translate("HVAC_EditMaterial", "{} material:").format(label)
            ))
            row = MaterialPickerRow(
                translate("HVAC_EditMaterial", "Select {} Material").format(label),
                _common_material_label(self.objects, _construction_schema.material_property_name(layer_id)),
            )
            layout.addWidget(row)
            self.rows[layer_id] = row

    def accept(self):
        materials = {layer_id: row.material for layer_id, row in self.rows.items() if row.touched}

        if materials and self.apply_callback:
            QtCore.QTimer.singleShot(0, lambda: self.apply_callback(self.objects, materials))
        return True

    def reject(self):
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

        layout.addWidget(self._makeSeparator())

        layout.addWidget(QtWidgets.QLabel(
            translate("HVAC_NetworkTypeDefaults", "Default materials by role:")
        ))
        self.role_material_rows = {}
        for role in ALL_LAYER_ROLES:
            prop_name = "DefaultMaterial_" + role_property_suffix(role)
            label = _layer_label(role)
            layout.addWidget(QtWidgets.QLabel(
                translate("HVAC_NetworkTypeDefaults", "{}:").format(label)
            ))
            row = MaterialPickerRow(
                translate("HVAC_NetworkTypeDefaults", "Select {} Material").format(label),
                _common_material_label([network_obj], prop_name),
            )
            layout.addWidget(row)
            self.role_material_rows[role] = row

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
                default_materials_by_role={
                    role: row.material for role, row in self.role_material_rows.items() if row.touched
                },
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

        # Per-port values (Stage 3): one row per port, one column per
        # per-port property of the current type. Only for a single selected
        # object whose type has such properties.
        self.port_group = QtWidgets.QGroupBox(translate("HVAC_EditType", "Per-port values"))
        port_layout = QtWidgets.QVBoxLayout(self.port_group)
        self.port_note = QtWidgets.QLabel()
        self.port_note.setWordWrap(True)
        port_layout.addWidget(self.port_note)
        self.port_table = QtWidgets.QTableWidget()
        port_layout.addWidget(self.port_table)
        layout.addWidget(self.port_group)
        self._port_columns = []
        self._port_rows = []

        self._populateLibraries()
        self._loadFromSelection()
        self._buildPortTable()

        self.library_combo.currentIndexChanged.connect(self._refreshTypes)
        self.type_combo.currentIndexChanged.connect(self._syncPortTableEnabled)

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
            # For segments, keep it simple: show every segment type in
            # the library, not just ones matching this segment's own
            # current family/profile -- unlike a junction's family
            # (a topological fact the classifier computes), a segment's
            # straight/curved family is closer to "which backend draws
            # this same duct run", so a user may deliberately want to
            # switch between them. list_types() already ranks by
            # kind/priority (best-suited first, same as automatic
            # selection); layer a preference for whichever types match
            # this segment's own current Family/Profile on top of that,
            # without narrowing the list any candidates drop out of.
            family = getattr(ref, "Family", "")
            profile = getattr(ref, "Profile", "")
            type_defs = lib.list_types(category="segment")
            if family or profile:
                type_defs = sorted(
                    type_defs,
                    key=lambda t: (
                        0 if (family and family in t.family) else (1 if family else 0),
                        0 if (profile and t.profiles and profile in t.profiles) else (1 if profile else 0),
                    ),
                )

        else:
            # For a junction's Primary/Inline DuctComponent, Family is a
            # junction-level classifier concept (not the component's own --
            # see Component.py), so resolve it off the parent junction via
            # ParentJunctionName. A component's own Profile can collapse
            # several distinct connected-port profiles into a single
            # "Mixed" label (see HVACLibraryService.match_profile_from_ports),
            # which can never correctly filter a type by plain membership
            # (no type declares a literal "Mixed" profile) -- pull the
            # parent junction's own connected_ports instead, same as
            # automatic selection does, so list_types() can check each
            # port's real profile individually.
            family = getattr(ref, "Family", "")
            parent = None
            if hvaclib.isDuctComponent(ref):
                parent_name = getattr(ref, "ParentJunctionName", "")
                parent = ref.Document.getObject(parent_name) if parent_name else None
                if not family:
                    family = getattr(parent, "Family", "") if parent is not None else ""

            # The junction's flow classification goes along too, so the list
            # only offers types that fit how air passes this node: the
            # transition that matches how the two ducts line up, entries
            # where air comes in and exits where it leaves, and so on.
            connected_ports = None
            classification = None
            if parent is not None:
                try:
                    analysis = json.loads(getattr(parent, "AnalysisJson", "") or "{}")
                except Exception:
                    analysis = {}
                connected_ports = list(analysis.get("connected_ports", []) or [])
                classification = {
                    "flow_class": analysis.get("flow_class", ""),
                    "qualifiers": dict(analysis.get("qualifiers", {}) or {}),
                    "derived_values": dict(analysis.get("derived_values", {}) or {}),
                }

            type_defs = lib.list_types(
                category="junction",
                family=family if family else None,
                connected_ports=connected_ports,
                include_placeholders=False,
                classification=classification,
            )

        for tdef in type_defs:
            self.type_combo.addItem(tdef.label, tdef.id)

    def _portObject(self):
        return self.objects[0] if len(self.objects) == 1 else None

    def _portLabels(self, obj):
        """{edge_key: duct number or label} for the object's ports."""
        net = hvaclib.getOwnerNetwork(obj)
        if net is None or getattr(net, "Proxy", None) is None:
            return {}
        labels = {}
        for key, seg in net.Proxy.collectSegmentObjects().items():
            labels[key] = str(getattr(seg, "Number", "") or getattr(seg, "Label", "") or key)
        return labels

    def _buildPortTable(self):
        from ..core import _port_properties

        self._port_columns, self._port_rows = [], []
        obj = self._portObject()
        type_def = None
        if obj is not None and getattr(obj, "LibraryId", "") and getattr(obj, "TypeId", ""):
            reg = hvaclib.HVACLibraryService.get_hvac_library_registry()
            type_def = reg.resolve_type(obj.LibraryId, obj.TypeId)
        if type_def is not None:
            self._port_columns, self._port_rows = _port_properties.port_table(obj, type_def, self._portLabels(obj))
        if not self._port_columns or not self._port_rows:
            self.port_group.setVisible(False)
            return
        self._port_type_def = type_def
        table = self.port_table
        table.clear()
        table.setColumnCount(len(self._port_columns))
        table.setRowCount(len(self._port_rows))
        table.setHorizontalHeaderLabels([c["name"] for c in self._port_columns])
        table.setVerticalHeaderLabels([r["label"] for r in self._port_rows])
        for col, column in enumerate(self._port_columns):
            header = table.horizontalHeaderItem(col)
            if header is not None:
                header.setToolTip(column["description"])
        for row, port_row in enumerate(self._port_rows):
            for col, column in enumerate(self._port_columns):
                value = port_row["values"][column["name"]]
                item = QtWidgets.QTableWidgetItem()
                if column["prop_type"] == "App::PropertyBool":
                    item.setFlags(QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled)
                    item.setCheckState(QtCore.Qt.Checked if value else QtCore.Qt.Unchecked)
                else:
                    item.setText("" if value is None else str(value))
                table.setItem(row, col, item)
        table.resizeColumnsToContents()
        self.port_group.setVisible(True)
        self._syncPortTableEnabled()

    def _portTableApplies(self):
        """The table edits the object's current type; it doesn't apply once another type is picked."""
        obj = self._portObject()
        return (
            obj is not None
            and bool(self._port_columns)
            and self.library_combo.currentData() == getattr(obj, "LibraryId", "")
            and self.type_combo.currentData() == getattr(obj, "TypeId", "")
        )

    def _syncPortTableEnabled(self, *_args):
        if not self._port_columns:
            return
        applies = self._portTableApplies()
        self.port_table.setEnabled(applies)
        self.port_note.setText(
            translate("HVAC_EditType", "One value per connected duct.")
            if applies
            else translate("HVAC_EditType", "These values belong to the current type; they are not applied when the type changes.")
        )

    def _applyPortTable(self):
        """Write the table back; False (with a message) when a cell does not parse."""
        from ..core import _port_properties

        edits = {}
        for row, port_row in enumerate(self._port_rows):
            for col, column in enumerate(self._port_columns):
                item = self.port_table.item(row, col)
                if item is None:
                    continue
                if column["prop_type"] == "App::PropertyBool":
                    raw = item.checkState() == QtCore.Qt.Checked
                else:
                    raw = item.text()
                try:
                    value = _port_properties.parse_port_value(column["prop_type"], raw)
                except ValueError as e:
                    QtWidgets.QMessageBox.warning(
                        self.form,
                        translate("HVAC_EditType", "Per-port values"),
                        "{} / {}: {}".format(port_row["label"], column["name"], e),
                    )
                    return False
                edits.setdefault(port_row["edge_key"], {})[column["name"]] = value
        obj = self._portObject()
        doc = obj.Document
        doc.openTransaction("Edit per-port values")
        try:
            changed = _port_properties.apply_port_table(obj, self._port_type_def, edits)
        finally:
            doc.commitTransaction()
        if changed:
            obj.touch()
            doc.recompute()
        return True

    def accept(self):
        library_id = self.library_combo.currentData()
        type_id = self.type_combo.currentData()

        if self._portTableApplies() and not self._applyPortTable():
            return False

        if self.apply_callback:
            _runWithPropertyViewDetached(
                lambda: self.apply_callback(self.objects, library_id=library_id, type_id=type_id)
            )
        return True

    def reject(self):
        return True


def _runWithPropertyViewDetached(func):
    """
    Run func with the selection cleared, then select the same objects again.

    func may remove type properties from several selected objects. FreeCAD's
    property view (1.1) breaks on that: after one object is selected and a
    second is added, a row shared by both stays bound to the first object's
    property. Once that property is removed, the row throws "Property 'X'
    not found" on the next update or repaint. Clearing the selection first,
    and waiting for the property view's rebuild timer, removes the old rows.
    """
    selection = list(Gui.Selection.getSelection())
    Gui.Selection.clearSelection()
    rebuild_ms = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/View").GetUnsigned("PropertyViewTimer", 100)

    def run():
        try:
            func()
        finally:
            for obj in selection:
                # An object func deleted raises on access; leave it out.
                with contextlib.suppress(ReferenceError, RuntimeError):
                    if obj.Document is not None and obj.Document.getObject(obj.Name) is obj:
                        Gui.Selection.addSelection(obj)

    QtCore.QTimer.singleShot(int(rebuild_ms) + 50, run)


class TaskPanelEditInlineComponents:
    """
    Task panel for managing a junction's Inline devices (dampers,
    silencers, ...) in one place, replacing the previous separate Add/
    Remove Inline Component commands: a list of what's already attached
    (selecting an entry highlights it in the 3D view), a Delete button for
    it, and an "Add inline component" section (pick which real edge to
    attach a new one to and which type -- the old Add Inline Component
    panel's own content) that highlights the currently-picked port with a
    semi-transparent plane so a user can see which physical connection
    "Attach to edge" refers to.

    Add/remove act immediately through add_callback/remove_callback rather
    than being deferred to accept() -- the list has to reflect each change
    right away so the panel can stay open across several edits.
    """

    def __init__(self, junction, add_callback=None, remove_callback=None):
        self.junction = junction
        self.add_callback = add_callback
        self.remove_callback = remove_callback
        self._highlight_root = None
        self._components = []

        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(translate("HVAC_EditInlineComponents", "Edit Inline Components"))

        layout = QtWidgets.QVBoxLayout(self.form)
        layout.addWidget(QtWidgets.QLabel(
            translate("HVAC_EditInlineComponents", "Junction: {}").format(junction.Label)
        ))

        layout.addWidget(QtWidgets.QLabel(
            translate("HVAC_EditInlineComponents", "Existing inline components:")
        ))
        self.component_list = QtWidgets.QListWidget()
        self.component_list.currentRowChanged.connect(self._onSelectComponent)
        layout.addWidget(self.component_list)

        self.delete_button = QtWidgets.QPushButton(
            translate("HVAC_EditInlineComponents", "Delete Selected")
        )
        self.delete_button.clicked.connect(self._deleteSelected)
        layout.addWidget(self.delete_button)

        separator = QtWidgets.QFrame()
        separator.setFrameShape(QtWidgets.QFrame.HLine)
        layout.addWidget(separator)

        layout.addWidget(QtWidgets.QLabel(
            translate("HVAC_EditInlineComponents", "Add inline component:")
        ))

        try:
            analysis = json.loads(getattr(junction, "AnalysisJson", "") or "{}")
        except Exception:
            analysis = {}
        self.ports = list(analysis.get("connected_ports", []) or [])

        layout.addWidget(QtWidgets.QLabel(translate("HVAC_EditInlineComponents", "Attach to edge:")))
        self.edge_combo = QtWidgets.QComboBox()
        for port in self.ports:
            self.edge_combo.addItem(self._portLabel(port))
        layout.addWidget(self.edge_combo)
        # Degree 1: nothing to choose, but still shown for clarity.
        self.edge_combo.setEnabled(len(self.ports) > 1)

        layout.addWidget(QtWidgets.QLabel(translate("HVAC_EditInlineComponents", "Type:")))
        self.type_combo = QtWidgets.QComboBox()
        layout.addWidget(self.type_combo)

        self.add_button = QtWidgets.QPushButton(translate("HVAC_EditInlineComponents", "Add"))
        self.add_button.clicked.connect(self._addComponent)
        layout.addWidget(self.add_button)

        self._refreshTypes()
        self.edge_combo.currentIndexChanged.connect(self._refreshTypes)
        self.edge_combo.currentIndexChanged.connect(self._highlightCurrentPort)

        self._refreshComponentList()
        self._highlightCurrentPort()

    # ------------------------------------------------------------------
    # Existing components list
    # ------------------------------------------------------------------

    def _refreshComponentList(self):
        self.component_list.blockSignals(True)
        self.component_list.clear()
        # Sorted by documentation Number (see core/Numbering.py) -- this
        # already matches getInlineComponents()' own AttachedEdgeKey/
        # PortSequence order once the network has been renumbered, since
        # HVAC_RenumberNetwork numbers Inline components in that same
        # order; never-renumbered components (blank Number) keep their
        # original relative order.
        self._components = sorted(
            self.junction.Proxy.getInlineComponents(),
            key=lambda c: getattr(c, "Number", "") or "",
        )
        for component in self._components:
            self.component_list.addItem(self._componentLabel(component))
        self.component_list.blockSignals(False)
        Gui.Selection.clearSelection()

    @classmethod
    def _componentLabel(cls, component):
        number = getattr(component, "Number", "") or ""
        label = "{}".format(cls._typeLabel(component))
        return "{} — {}".format(number, label) if number else label

    @staticmethod
    def _typeLabel(component):
        library_id = getattr(component, "LibraryId", "")
        type_id = getattr(component, "TypeId", "")
        reg = hvaclib.HVACLibraryService.get_hvac_library_registry()
        lib = reg.get_library(library_id) if library_id else None
        tdef = lib.get_type(type_id) if lib is not None else None
        return tdef.label if tdef is not None else (type_id or translate("HVAC_EditInlineComponents", "(no type)"))

    def _onSelectComponent(self, row):
        Gui.Selection.clearSelection()
        if row is None or row < 0 or row >= len(self._components):
            return
        component = self._components[row]
        Gui.Selection.addSelection(component.Document.Name, component.Name)

    def _deleteSelected(self):
        row = self.component_list.currentRow()
        if row is None or row < 0 or row >= len(self._components):
            return
        component = self._components[row]
        if self.remove_callback:
            self.remove_callback(component)
        self._refreshComponentList()

    # ------------------------------------------------------------------
    # Add section
    # ------------------------------------------------------------------

    @staticmethod
    def _portLabel(port):
        """Size (inlet/outlet) -- direction vector -- e.g. '300 x 250 mm
        (outlet) -- (1.00, 0.00, 0.00)'. Leads with what a user actually
        recognizes a duct run by, not the internal edge_key."""
        section_params = port.get("section_params", {}) or {}
        if port.get("profile") == "Circular":
            size = "{:.0f} mm dia".format(section_params.get("Diameter", 0.0) or 0.0)
        else:
            size = "{:.0f} x {:.0f} mm".format(
                section_params.get("Width", 0.0) or 0.0, section_params.get("Height", 0.0) or 0.0,
            )
        role = translate("HVAC_EditInlineComponents", "inlet") if port.get("flow_into_junction") else translate("HVAC_EditInlineComponents", "outlet")
        direction = port.get("direction") or (0.0, 0.0, 0.0)
        direction = [0.0 if abs(x) < 0.05 else x for x in direction]  # round small values to 0.0 to avoid noise
        return "{} ({}) -- ({:.1f}, {:.1f}, {:.1f})".format(size, role, direction[0], direction[1], direction[2])

    def _currentPort(self):
        idx = self.edge_combo.currentIndex()
        if idx < 0 or idx >= len(self.ports):
            return None
        return self.ports[idx]

    def _refreshTypes(self):
        self.type_combo.clear()
        junction = self.junction
        primary = junction.Proxy.getPrimaryComponent()
        net = hvaclib.getOwnerNetwork(junction)
        library_id = getattr(primary, "LibraryId", "") or (net.Proxy.getDefaultLibraryId() if net is not None else "")
        self._library_id = library_id

        port = self._currentPort()
        profile = port.get("profile", "") if port else ""
        # Always "through": an Inline device is always a physically
        # two-port device evaluated against its own attached leg, no
        # matter what the parent junction's real topology is.
        types = hvaclib.HVACLibraryService.list_inline_types(library_id, topology="through", profile=profile)
        self._types = types
        for tdef in types:
            self.type_combo.addItem(tdef.label, tdef.id)

    def _translatedPort(self, port):
        """
        Highlighting a port's raw AnalysisJson position would always land
        on the junction's shared pre-fitting anchor, not the physical duct
        wall / existing inline device chain a new component would actually
        attach to -- see hvaclib.translated_port_position().
        """
        return hvaclib.translated_port_position(self.junction, port)

    def _highlightCurrentPort(self):
        """Show a semi-transparent plane over the port picked in "Attach to
        edge", sized ~2x its own duct section and centered on where a new
        device would actually attach, so a user can see which physical
        connection it refers to before adding one there."""
        self._clearHighlight()
        port = self._currentPort()
        if port is None:
            return
        net = hvaclib.getOwnerNetwork(self.junction)
        vobj = getattr(net, "ViewObject", None) if net is not None else None
        if vobj is None:
            return
        try:
            self._highlight_root = buildPortHighlightCoinNode(self._translatedPort(port))
            vobj.RootNode.addChild(self._highlight_root)
        except Exception:
            self._highlight_root = None

    def _clearHighlight(self):
        if self._highlight_root is None:
            return
        try:
            net = hvaclib.getOwnerNetwork(self.junction)
            vobj = getattr(net, "ViewObject", None) if net is not None else None
            if vobj is not None:
                vobj.RootNode.removeChild(self._highlight_root)
        except Exception:
            pass
        self._highlight_root = None

    def _addComponent(self):
        port = self._currentPort()
        type_id = self.type_combo.currentData()
        if port is None or not type_id:
            return

        edge_key = port.get("edge_key", "")
        library_id = getattr(self, "_library_id", "")
        if edge_key and self.add_callback:
            self.add_callback(self.junction, edge_key, library_id, type_id)
        self._refreshComponentList()

    def accept(self):
        self._clearHighlight()
        return True

    def reject(self):
        self._clearHighlight()
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


def _spreadsheet_cell(col, row):
    """0-based (col, row) -> a Spreadsheet::Sheet cell address, e.g. (0, 0) -> "A1", (27, 1) -> "AB2"."""
    letters = ""
    n = col
    while True:
        letters = chr(ord('A') + (n % 26)) + letters
        n = n // 26 - 1
        if n < 0:
            break
    return "{}{}".format(letters, row + 1)


def _resolveSelectableObjects(obj):
    """
    A DuctJunction has no Shape of its own and can't be highlighted in the
    3D view -- retarget to every one of its DuctComponent children: the
    Primary fitting AND any Inline devices (dampers, etc.) chained onto
    its own edges, so a junction's whole fitting geometry gets selected,
    not just its Primary.
    """
    if obj is None:
        return []
    if hvaclib.isDuctJunction(obj):
        proxy = getattr(obj, "Proxy", None)
        components = list(proxy.getComponents()) if proxy is not None else []
        return components if components else [obj]
    return [obj]


def _network_elements(network_obj):
    """Every segment, junction and component of a network (what a results warning may name)."""
    proxy = getattr(network_obj, "Proxy", None)
    if proxy is None:
        return []
    objects = list(proxy.collectSegmentObjects().values()) + list(proxy.collectJunctionObjects().values())
    for components in proxy.collectComponentObjects().values():
        objects.extend(components)
    return objects


def _select_objects(objs):
    """Replace the 3D selection with `objs` (a junction selects its fittings, see _resolveSelectableObjects)."""
    Gui.Selection.clearSelection()
    for obj in objs:
        for target in _resolveSelectableObjects(obj):
            try:
                Gui.Selection.addSelection(target.Document.Name, target.Name)
            except Exception:
                pass


def _build_warnings_box(title, warnings, network_obj):
    """
    A "Warnings" group whose element references (duct, junction and fitting
    numbers or labels) are links: clicking one selects that object in the
    3D view and the tree. One label per warning, so each wraps on its own.
    """
    import html

    from ..core import _analysis_adapter

    index = _analysis_adapter.network_element_index(_network_elements(network_obj))
    by_name = {obj.Name: obj for obj in index.values()}

    box = QtWidgets.QGroupBox(title)
    layout = QtWidgets.QVBoxLayout(box)
    for warning in warnings:
        # Step 1: escape the plain text and wrap each named element in a link carrying its object name.
        parts = []
        for piece, obj in _analysis_adapter.link_spans(warning, index):
            text = html.escape(piece)
            parts.append('<a href="{}">{}</a>'.format(html.escape(obj.Name), text) if obj is not None else text)
        # Step 2: a rich-text label that hands link clicks to us instead of opening a browser.
        label = QtWidgets.QLabel("&#8226; " + "".join(parts))
        label.setWordWrap(True)
        label.setTextFormat(QtCore.Qt.RichText)
        label.setTextInteractionFlags(QtCore.Qt.LinksAccessibleByMouse | QtCore.Qt.TextSelectableByMouse)
        label.setOpenExternalLinks(False)
        label.linkActivated.connect(lambda name, objs=by_name: _select_objects([objs[name]] if name in objs else []))
        layout.addWidget(label)
    return box


class _ResultsSelectionSync:
    """
    Two-way sync between one or more results tables' row selection and
    Gui.Selection, for the lifetime of a TaskPanelAirflowResults/
    TaskPanelSizeDucts panel: selecting a row selects that row's object in
    the 3D view, AND selecting a matching object in the 3D view (or tree)
    selects its row back -- across every table registered via addTable()
    (e.g. Calculate Airflow's segment AND junction tables at once).

    `_updating` guards against the two directions bouncing off each other
    forever: a table-driven Gui.Selection change would otherwise trigger
    this same class's own Gui.Selection observer, which would try to
    re-apply the very same table selection it just came from.
    """

    def __init__(self):
        self._tables = []  # [(QTableWidget, [obj, obj, ...]), ...]
        self._updating = False
        Gui.Selection.addObserver(self)

    def addTable(self, table, objs):
        """
        Row-based (not per-cell) selection, so clicking any cell picks the
        whole row's object -- `objs[row]` is that row's own object.
        """
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._tables.append((table, objs))
        table.itemSelectionChanged.connect(lambda t=table, o=objs: self._onTableSelectionChanged(t, o))

    def clearTables(self):
        """Drop every registered table -- call before rebuilding results (e.g. a re-run), since
        the old table widgets are about to be deleted and must not be referenced afterwards."""
        self._tables = []

    def stop(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception:
            pass
        self._tables = []

    def _onTableSelectionChanged(self, table, objs):
        if self._updating:
            return
        self._updating = True
        try:
            Gui.Selection.clearSelection()
            rows = {index.row() for index in table.selectedIndexes()}
            for row in rows:
                if 0 <= row < len(objs):
                    for target in _resolveSelectableObjects(objs[row]):
                        try:
                            Gui.Selection.addSelection(target.Document.Name, target.Name)
                        except Exception:
                            pass
        finally:
            self._updating = False

    def _syncTablesFromSelection(self):
        if self._updating:
            return
        self._updating = True
        try:
            selected = {
                (sel.Object.Document.Name, sel.Object.Name)
                for sel in Gui.Selection.getSelectionEx()
                if sel.Object is not None
            }
            for table, objs in self._tables:
                table.blockSignals(True)
                try:
                    table.clearSelection()
                    for row, obj in enumerate(objs):
                        targets = _resolveSelectableObjects(obj)
                        if any((t.Document.Name, t.Name) in selected for t in targets):
                            table.selectRow(row)
                finally:
                    table.blockSignals(False)
        finally:
            self._updating = False

    # ------------------------------------------------------------------
    # Gui.Selection observer protocol -- react to any selection change by
    # just re-reading the current selection fresh, rather than tracking
    # each method's own specific (doc, obj, sub, ...) args individually.
    # ------------------------------------------------------------------

    def addSelection(self, doc, obj, sub, pnt):
        self._syncTablesFromSelection()

    def removeSelection(self, doc, obj, sub):
        self._syncTablesFromSelection()

    def setSelection(self, doc):
        self._syncTablesFromSelection()

    def clearSelection(self, doc):
        self._syncTablesFromSelection()


def _sorted_by_number(items):
    """
    Stable-sort SegmentResult/JunctionResult/SegmentSizeResult items (or
    anything with a .obj) by that object's documentation Number (see
    core/Numbering.py, HVAC_RenumberNetwork). Never-renumbered objects
    (blank Number) sort first and keep their original relative order --
    returns a new list, the caller's own result list/tuple is untouched.
    """
    return sorted(items, key=lambda item: getattr(item.obj, "Number", "") or "")


def _setHeaderLabelsWithTooltips(table, headers):
    """
    headers: [(caption, tooltip), ...] -- caption is the short column
    header actually shown (a symbol + unit for a physical quantity, to
    keep result tables narrow); tooltip is the full descriptive name,
    shown on hovering the header cell so the abbreviation stays
    unambiguous. Used by every results table in this module (Calculate
    Airflow's segment/junction/fittings tables and Size Ducts' own table).
    """
    table.setHorizontalHeaderLabels([caption for caption, _ in headers])
    for col, (_, tooltip) in enumerate(headers):
        item = table.horizontalHeaderItem(col)
        if item is not None:
            item.setToolTip(tooltip)


class TaskPanelAirflowResults:
    """Read-only report panel showing the results of an airflow/pressure-drop calculation."""

    # (caption, tooltip) -- caption is the compact symbol+unit actually
    # shown in the header; tooltip is the full name, on hover (see
    # _setHeaderLabelsWithTooltips).
    SEGMENT_HEADERS = [
        ("#", "Number"), ("Segment", "Segment"), ("Q (L/s)", "Flow Rate"),
        ("V (m/s)", "Velocity"), ("ΔPf (Pa)", "Friction Loss"),
        ("ΔPd (Pa)", "Fitting (Dynamic) Loss"), ("ΔPt (Pa)", "Total Loss"),
        ("Ps (Pa)", "Static Pressure"),
    ]
    JUNCTION_HEADERS = [
        ("#", "Number"), ("Junction", "Junction"), ("Q (L/s)", "Total Flow Rate"),
        ("Ps (Pa)", "Static Pressure"), ("Src", "Source (flow leaves the system here)"),
        ("⚠", "Warning"),
    ]
    FITTING_HEADERS = [
        ("#", "Number"), ("Fitting", "Fitting"), ("Role", "Role (Primary / Inline)"),
        ("Path", "Flow Path (from → to)"), ("Q (L/s)", "Flow Rate"), ("V (m/s)", "Velocity"),
        ("K", "Loss Coefficient (K)"), ("ΔPd (Pa)", "Fitting (Dynamic) Loss"),
        ("Ps (Pa)", "Static Pressure"), ("Status", "Loss Calculation Status"),
    ]

    def __init__(self, network_obj, result):
        self.network_obj = network_obj

        # Terminal design-flow-rate arrow overlay, active for this panel's
        # whole lifetime -- see Observer.py:TerminalFlowRateObserver.
        self.flow_arrow_observer = TerminalFlowRateObserver(network_obj)
        self.flow_arrow_observer.start()

        # Two-way row <-> 3D-selection sync across every segment/junction
        # table this panel builds (one pair per sub-network tab).
        self.selection_sync = _ResultsSelectionSync()

        # Colored plane/overlay result visualization, active for this
        # panel's whole lifetime -- see Observer.py:AirflowResultObserver.
        # Off by default (both Enable checkboxes start unchecked).
        self.airflow_result_observer = AirflowResultObserver(
            network_obj, result, terminal_observer=self.flow_arrow_observer,
        )
        self.airflow_result_observer.start()

        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(translate("HVAC_CalculateAirflow", "Airflow Calculation Results"))
        self.layout = QtWidgets.QVBoxLayout(self.form)

        self.layout.addWidget(self._buildVisualizationControls())

        self.results_container = QtWidgets.QWidget()
        self.results_layout = QtWidgets.QVBoxLayout(self.results_container)
        self.results_layout.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(self.results_container)

        self.run_button = QtWidgets.QPushButton(
            translate("HVAC_CalculateAirflow", "Run Revised Calculation")
        )
        self.run_button.clicked.connect(self._runRevisedCalculation)
        self.layout.addWidget(self.run_button)

        self.export_button = QtWidgets.QPushButton(translate("HVAC_CalculateAirflow", "Export to Spreadsheet"))
        self.export_button.clicked.connect(self._exportToSpreadsheets)
        self.layout.addWidget(self.export_button)

        self._showResults(result)

    def _buildVisualizationControls(self):
        """
        "Enable" checkbox + "Color by" dropdown for each of the two result
        overlays AirflowResultObserver can draw -- see its own docstring.
        Text values on the overlays are always shown regardless of which
        dropdown entry is picked; only the overlay's own color follows it.
        """
        group = QtWidgets.QGroupBox(translate("HVAC_CalculateAirflow", "Result Visualization"))
        grid = QtWidgets.QGridLayout(group)

        self.junction_viz_checkbox = QtWidgets.QCheckBox(translate("HVAC_CalculateAirflow", "Junction Ports"))
        grid.addWidget(self.junction_viz_checkbox, 0, 0)
        grid.addWidget(QtWidgets.QLabel(translate("HVAC_CalculateAirflow", "Color by:")), 0, 1)
        self.junction_color_combo = QtWidgets.QComboBox()
        self.junction_color_combo.addItem(translate("HVAC_CalculateAirflow", "Flow Rate"), "flow_rate")
        self.junction_color_combo.addItem(translate("HVAC_CalculateAirflow", "Static Pressure"), "static_pressure")
        grid.addWidget(self.junction_color_combo, 0, 2)

        self.segment_viz_checkbox = QtWidgets.QCheckBox(translate("HVAC_CalculateAirflow", "Segments"))
        grid.addWidget(self.segment_viz_checkbox, 1, 0)
        grid.addWidget(QtWidgets.QLabel(translate("HVAC_CalculateAirflow", "Color by:")), 1, 1)
        self.segment_color_combo = QtWidgets.QComboBox()
        self.segment_color_combo.addItem(translate("HVAC_CalculateAirflow", "Velocity"), "velocity")
        self.segment_color_combo.addItem(translate("HVAC_CalculateAirflow", "Friction Drop"), "friction_drop")
        self.segment_color_combo.addItem(translate("HVAC_CalculateAirflow", "Pressure Loss"), "pressure_loss")
        grid.addWidget(self.segment_color_combo, 1, 2)

        self.junction_viz_checkbox.toggled.connect(self.airflow_result_observer.setJunctionEnabled)
        self.junction_color_combo.currentIndexChanged.connect(
            lambda: self.airflow_result_observer.setJunctionColorBy(self.junction_color_combo.currentData())
        )
        self.segment_viz_checkbox.toggled.connect(self.airflow_result_observer.setSegmentEnabled)
        self.segment_color_combo.currentIndexChanged.connect(
            lambda: self.airflow_result_observer.setSegmentColorBy(self.segment_color_combo.currentData())
        )

        return group

    def _clearResults(self):
        while self.results_layout.count():
            item = self.results_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _showResults(self, result):
        self.result = result
        self._clearResults()
        self.selection_sync.clearTables()
        self.airflow_result_observer.setResult(result)

        if result.warnings:
            # Element references in each warning are links that select the element.
            warn_box = _build_warnings_box(
                translate("HVAC_CalculateAirflow", "Warnings"), result.warnings, self.network_obj
            )
            self.results_layout.addWidget(warn_box)

        if not result.components:
            empty_label = QtWidgets.QLabel(
                translate("HVAC_CalculateAirflow", "No sub-network could be solved. See warnings above.")
            )
            empty_label.setWordWrap(True)
            self.results_layout.addWidget(empty_label)
        elif len(result.components) == 1:
            self.results_layout.addWidget(self._buildComponentWidget(result.components[0]))
        else:
            tabs = QtWidgets.QTabWidget()
            for i, comp in enumerate(result.components):
                tabs.addTab(self._buildComponentWidget(comp), "{} {}".format(
                    translate("HVAC_CalculateAirflow", "Sub-network"), i + 1
                ))
            self.results_layout.addWidget(tabs)

        self.export_button.setEnabled(bool(result.components))

    def _runRevisedCalculation(self):
        from ..core.AirflowSolver import AirflowSolver

        try:
            result = AirflowSolver(self.network_obj).solve()
        except Exception as e:
            FreeCAD.Console.PrintWarning(
                "HVAC - CalculateAirflow - Error solving network '{}': {}\n".format(self.network_obj.Label, e)
            )
            FreeCAD.Console.PrintMessage(traceback.format_exc())
            return

        doc = getattr(self.network_obj, "Document", None)
        if doc is not None:
            doc.recompute()

        self._showResults(result)

    def _buildComponentWidget(self, comp):
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)

        summary = QtWidgets.QLabel(
            translate(
                "HVAC_CalculateAirflow",
                "Balancing terminal: {ref}\n"
                "Critical terminal: {crit}\n"
                "Required fan/AHU total pressure: {pa:.1f} Pa"
            ).format(
                ref=comp.reference_terminal_key,
                crit=comp.critical_terminal_key,
                pa=comp.critical_pressure_pa,
            )
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)

        segments = _sorted_by_number(comp.segments)
        seg_table = QtWidgets.QTableWidget(len(segments), len(self.SEGMENT_HEADERS))
        _setHeaderLabelsWithTooltips(seg_table, self.SEGMENT_HEADERS)
        seg_table.verticalHeader().setVisible(False)
        seg_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        for row, seg in enumerate(segments):
            values = [
                getattr(seg.obj, "Number", "") or "",
                seg.obj.Label,
                "{:.2f}".format(seg.flow_lps),
                "{:.2f}".format(seg.velocity_ms),
                "{:.2f}".format(seg.friction_loss_pa),
                "{:.2f}".format(seg.fitting_loss_pa),
                "{:.2f}".format(seg.total_loss_pa),
                "{:.1f}".format(seg.cumulative_pressure_pa),
            ]
            for col, value in enumerate(values):
                seg_table.setItem(row, col, QtWidgets.QTableWidgetItem(value))
        seg_table.resizeColumnsToContents()
        self.selection_sync.addTable(seg_table, [seg.obj for seg in segments])
        layout.addWidget(QtWidgets.QLabel(translate("HVAC_CalculateAirflow", "Segments")))
        layout.addWidget(seg_table)

        junctions = _sorted_by_number(comp.junctions)
        junc_table = QtWidgets.QTableWidget(len(junctions), len(self.JUNCTION_HEADERS))
        _setHeaderLabelsWithTooltips(junc_table, self.JUNCTION_HEADERS)
        junc_table.verticalHeader().setVisible(False)
        junc_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        for row, junc in enumerate(junctions):
            values = [
                getattr(junc.obj, "Number", "") or "",
                junc.obj.Label,
                "{:.2f}".format(junc.total_flow_lps),
                "{:.1f}".format(junc.static_pressure_pa),
                translate("HVAC_CalculateAirflow", "Yes") if junc.is_source else "",
                junc.warning,
            ]
            for col, value in enumerate(values):
                junc_table.setItem(row, col, QtWidgets.QTableWidgetItem(value))
        junc_table.resizeColumnsToContents()
        self.selection_sync.addTable(junc_table, [junc.obj for junc in junctions])
        layout.addWidget(QtWidgets.QLabel(translate("HVAC_CalculateAirflow", "Junctions")))
        layout.addWidget(junc_table)

        # One row per applicable directed loss path/reference leg -- a
        # multiport fitting (tee/wye/cross) gets one row per path it
        # actually has a K for, each with its own K/ΔP, rather than one
        # misleading combined scalar per fitting (see
        # core/AirflowSolver.ComponentPortRow / core/_component_results.py).
        # This is the same generic path-based shape for a diverging
        # fitting (paths run common-inlet -> each outlet), a converging
        # one (paths run each inlet -> common-outlet), and a plain 1-port
        # or 2-port component (a single row) -- no per-family branching
        # needed here to tell them apart.
        fittings = sorted(
            comp.component_ports,
            key=lambda row: (getattr(row.component_obj, "Number", "") or "", row.edge_key),
        )
        fit_table = QtWidgets.QTableWidget(len(fittings), len(self.FITTING_HEADERS))
        _setHeaderLabelsWithTooltips(fit_table, self.FITTING_HEADERS)
        fit_table.verticalHeader().setVisible(False)
        fit_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        for row, fit in enumerate(fittings):
            values = [
                getattr(fit.component_obj, "Number", "") or "",
                fit.component_obj.Label,
                fit.component_role,
                fit.path_label,
                "{:.2f}".format(fit.flow_lps),
                "{:.2f}".format(fit.velocity_ms),
                "{:.2f}".format(fit.loss_coefficient) if fit.loss_coefficient is not None else "-",
                "{:.2f}".format(fit.pressure_drop_pa),
                "{:.1f}".format(fit.static_pressure_pa) if fit.static_pressure_pa is not None else "-",
                fit.status.capitalize() if fit.status else "-",
            ]
            for col, value in enumerate(values):
                fit_table.setItem(row, col, QtWidgets.QTableWidgetItem(value))
        fit_table.resizeColumnsToContents()
        self.selection_sync.addTable(fit_table, [fit.component_obj for fit in fittings])
        layout.addWidget(QtWidgets.QLabel(translate("HVAC_CalculateAirflow", "Fittings")))
        layout.addWidget(fit_table)

        return widget

    def _exportToSpreadsheets(self):
        """
        Write every sub-network's segment/junction results into two
        Spreadsheet::Sheet document objects (one row per segment/junction,
        same columns as the on-screen tables) -- lets a user take the
        numbers into a report without retyping them. A "Sub-network"
        column is added only when there's more than one component, mirroring
        when the on-screen view itself splits into per-sub-network tabs.
        """
        doc = getattr(self.network_obj, "Document", None)
        if doc is None:
            return

        multi = len(self.result.components) > 1
        # The spreadsheet has no header-hover tooltip and no column-width
        # pressure the on-screen table has -- use each column's full name
        # (the on-screen tooltip text) directly as its header here instead
        # of the abbreviated symbol+unit caption.
        segment_headers = [tooltip for _, tooltip in self.SEGMENT_HEADERS]
        junction_headers = [tooltip for _, tooltip in self.JUNCTION_HEADERS]
        if multi:
            segment_headers = [translate("HVAC_CalculateAirflow", "Sub-network")] + segment_headers
            junction_headers = [translate("HVAC_CalculateAirflow", "Sub-network")] + junction_headers

        segment_rows = []
        junction_rows = []
        for i, comp in enumerate(self.result.components):
            sub_network_label = "{} {}".format(translate("HVAC_CalculateAirflow", "Sub-network"), i + 1)

            for seg in _sorted_by_number(comp.segments):
                row = [
                    getattr(seg.obj, "Number", "") or "",
                    seg.obj.Label,
                    "{:.2f}".format(seg.flow_lps),
                    "{:.2f}".format(seg.velocity_ms),
                    "{:.2f}".format(seg.friction_loss_pa),
                    "{:.2f}".format(seg.fitting_loss_pa),
                    "{:.2f}".format(seg.total_loss_pa),
                    "{:.1f}".format(seg.cumulative_pressure_pa),
                ]
                segment_rows.append([sub_network_label] + row if multi else row)

            for junc in _sorted_by_number(comp.junctions):
                row = [
                    getattr(junc.obj, "Number", "") or "",
                    junc.obj.Label,
                    "{:.2f}".format(junc.total_flow_lps),
                    "{:.1f}".format(junc.static_pressure_pa),
                    translate("HVAC_CalculateAirflow", "Yes") if junc.is_source else "",
                    junc.warning,
                ]
                junction_rows.append([sub_network_label] + row if multi else row)

        seg_sheet = self._writeSheet(
            doc, "AirflowSegments",
            translate("HVAC_CalculateAirflow", "Airflow - Segments"),
            segment_headers, segment_rows,
        )
        junc_sheet = self._writeSheet(
            doc, "AirflowJunctions",
            translate("HVAC_CalculateAirflow", "Airflow - Junctions"),
            junction_headers, junction_rows,
        )
        doc.recompute()

        FreeCAD.Console.PrintMessage(
            "HVAC - Exported airflow results to '{}' and '{}'.\n".format(seg_sheet.Label, junc_sheet.Label)
        )
        # Export closes the dialog directly (not via accept()/reject()), so
        # every overlay/sync helper must be torn down here too.
        self.flow_arrow_observer.stop()
        self.selection_sync.stop()
        self.airflow_result_observer.stop()
        Gui.Control.closeDialog()

    @staticmethod
    def _writeSheet(doc, base_name, label, headers, rows):
        sheet = doc.addObject("Spreadsheet::Sheet", doc.getUniqueObjectName(base_name))
        sheet.Label = label
        for col, header in enumerate(headers):
            sheet.set(_spreadsheet_cell(col, 0), str(header))
        for row_index, row in enumerate(rows, start=1):
            for col, value in enumerate(row):
                sheet.set(_spreadsheet_cell(col, row_index), str(value))
        return sheet

    def accept(self):
        self.flow_arrow_observer.stop()
        self.selection_sync.stop()
        self.airflow_result_observer.stop()
        return True

    def reject(self):
        self.flow_arrow_observer.stop()
        self.selection_sync.stop()
        self.airflow_result_observer.stop()
        return True


class TaskPanelSizeDucts:
    """
    Combined duct-sizing task panel: an editable "Sizing Parameters"
    section (the network's own SizingMethod/TargetVelocity/etc -- the same
    "HVAC Duct Sizing" group properties otherwise only reachable through
    the raw property editor) with a "Run Duct Sizing" button, followed by
    the results/warnings section built fresh each time that button is
    clicked. OK applies the last computed proposed sizes; Cancel discards
    them (parameter edits already written to the network by a Run are
    kept either way, same as editing them directly in the property editor
    would be).
    """

    # (caption, tooltip) -- see _setHeaderLabelsWithTooltips.
    HEADERS = [
        ("#", "Number"), ("Segment", "Segment"), ("Profile", "Profile"),
        ("Current", "Current Size"), ("Proposed", "Proposed Size"),
        ("V (m/s)", "Velocity"), ("R (Pa/m)", "Friction Rate"),
        ("Bal.", "Balanced (Static Regain)"),
    ]
    BALANCING_HEADERS = [
        ("Junction", "Junction"), ("Branch", "Branch"),
        ("Required ΔP (Pa)", "Additional pressure drop still required after sizing"),
        ("Required K", "Loss coefficient a balancing device here would need"),
    ]

    SIZING_METHODS = [
        ("ConstantVelocity", "Constant Velocity"),
        ("ConstantFrictionRate", "Constant Friction Rate"),
        ("StaticRegain", "Static Regain"),
        ("PressureBalancedStaticRegain", "Pressure-Balanced Static Regain"),
    ]
    SIZE_CHANGE_POLICIES = [
        ("AtStraightJunctions", "At straight-through junctions"),
        ("AtInlineNodesOnly", "At in-line nodes only"),
        ("EverySegment", "Every segment"),
    ]
    RECTANGULAR_SIZING_MODES = [
        ("FixedAspectRatio", "Fixed Aspect Ratio"),
        ("FixedHeight", "Fixed Height"),
        ("FixedWidth", "Fixed Width"),
    ]
    FRICTION_MODELS = [
        ("DarcyAltshulTsal", "Darcy-Weisbach (Altshul-Tsal)"),
        ("DarcyColebrook", "Darcy-Weisbach (Colebrook)"),
        ("Table", "Friction chart (CSV)"),
        ("Expression", "Expression"),
    ]

    def __init__(self, network_obj):
        self.network_obj = network_obj
        self.sizer = None
        self.result = None

        # Terminal design-flow-rate arrow overlay, active for this panel's
        # whole lifetime -- see Observer.py:TerminalFlowRateObserver.
        self.flow_arrow_observer = TerminalFlowRateObserver(network_obj)
        self.flow_arrow_observer.start()

        # Two-way row <-> 3D-selection sync for the results table.
        self.selection_sync = _ResultsSelectionSync()

        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(translate("HVAC_SizeDucts", "Size Ducts"))
        self.layout = QtWidgets.QVBoxLayout(self.form)

        self.layout.addWidget(QtWidgets.QLabel(
            translate("HVAC_SizeDucts", "Network: {}").format(network_obj.Label)
        ))

        self.layout.addWidget(self._buildParametersGroup())

        self.run_button = QtWidgets.QPushButton(translate("HVAC_SizeDucts", "Run Duct Sizing"))
        self.run_button.clicked.connect(self._runSizing)
        self.layout.addWidget(self.run_button)

        # Populated by _showResults() each time Run is clicked -- empty
        # until the first run.
        self.results_container = QtWidgets.QWidget()
        self.results_layout = QtWidgets.QVBoxLayout(self.results_container)
        self.results_layout.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(self.results_container)

        self._loadFromNetwork()
        self.sizing_method_combo.currentIndexChanged.connect(self._refreshParameterVisibility)
        self.rectangular_sizing_mode_combo.currentIndexChanged.connect(self._refreshParameterVisibility)
        self.friction_model_combo.currentIndexChanged.connect(self._refreshParameterVisibility)
        self._refreshParameterVisibility()

    def _buildParametersGroup(self):
        group = QtWidgets.QGroupBox(translate("HVAC_SizeDucts", "Sizing Parameters"))
        grid = QtWidgets.QGridLayout(group)
        row = 0

        grid.addWidget(QtWidgets.QLabel(translate("HVAC_SizeDucts", "Sizing method:")), row, 0)
        self.sizing_method_combo = QtWidgets.QComboBox()
        for value, label in self.SIZING_METHODS:
            self.sizing_method_combo.addItem(translate("HVAC_SizeDucts", label), value)
        grid.addWidget(self.sizing_method_combo, row, 1)
        row += 1

        self.target_velocity_label = QtWidgets.QLabel(translate("HVAC_SizeDucts", "Target velocity:"))
        grid.addWidget(self.target_velocity_label, row, 0)
        self.target_velocity = QtWidgets.QDoubleSpinBox()
        self.target_velocity.setDecimals(2)
        self.target_velocity.setRange(0.0, 1e6)
        self.target_velocity.setSingleStep(0.5)
        self.target_velocity.setSuffix(" m/s")
        grid.addWidget(self.target_velocity, row, 1)
        row += 1

        self.target_friction_rate_label = QtWidgets.QLabel(translate("HVAC_SizeDucts", "Target friction rate:"))
        grid.addWidget(self.target_friction_rate_label, row, 0)
        self.target_friction_rate = QtWidgets.QDoubleSpinBox()
        self.target_friction_rate.setDecimals(3)
        self.target_friction_rate.setRange(0.0, 1e6)
        self.target_friction_rate.setSingleStep(0.1)
        self.target_friction_rate.setSuffix(" Pa/m")
        grid.addWidget(self.target_friction_rate, row, 1)
        row += 1

        self.static_regain_factor_label = QtWidgets.QLabel(translate("HVAC_SizeDucts", "Static regain factor:"))
        grid.addWidget(self.static_regain_factor_label, row, 0)
        self.static_regain_factor = QtWidgets.QDoubleSpinBox()
        self.static_regain_factor.setDecimals(2)
        self.static_regain_factor.setRange(0.0, 1.0)
        self.static_regain_factor.setSingleStep(0.05)
        grid.addWidget(self.static_regain_factor, row, 1)
        row += 1

        self.minimum_velocity_label = QtWidgets.QLabel(translate("HVAC_SizeDucts", "Minimum velocity:"))
        grid.addWidget(self.minimum_velocity_label, row, 0)
        self.minimum_velocity = QtWidgets.QDoubleSpinBox()
        self.minimum_velocity.setDecimals(2)
        self.minimum_velocity.setRange(0.0, 1e6)
        self.minimum_velocity.setSingleStep(0.5)
        self.minimum_velocity.setSuffix(" m/s")
        grid.addWidget(self.minimum_velocity, row, 1)
        row += 1

        # Where a duct may change size; the tooltip spells out each choice.
        grid.addWidget(QtWidgets.QLabel(translate("HVAC_SizeDucts", "Size changes:")), row, 0)
        self.size_change_policy_combo = QtWidgets.QComboBox()
        for value, label in self.SIZE_CHANGE_POLICIES:
            self.size_change_policy_combo.addItem(translate("HVAC_SizeDucts", label), value)
        self.size_change_policy_combo.setToolTip(
            translate(
                "HVAC_SizeDucts",
                "At straight-through junctions: a duct may change size wherever air passes straight through a "
                "junction (straight, transition and offset nodes, and the run of a tee or cross); it keeps its "
                "size through bends.\nAt in-line nodes only: as above, but a tee or cross run keeps one size.\n"
                "Every segment: each segment is sized for its own flow.\n"
                "A junction's AllowSizeChange property can pin it to one size.",
            )
        )
        grid.addWidget(self.size_change_policy_combo, row, 1)
        row += 1

        grid.addWidget(QtWidgets.QLabel(translate("HVAC_SizeDucts", "Rectangular sizing mode:")), row, 0)
        self.rectangular_sizing_mode_combo = QtWidgets.QComboBox()
        for value, label in self.RECTANGULAR_SIZING_MODES:
            self.rectangular_sizing_mode_combo.addItem(translate("HVAC_SizeDucts", label), value)
        grid.addWidget(self.rectangular_sizing_mode_combo, row, 1)
        row += 1

        self.target_aspect_ratio_label = QtWidgets.QLabel(translate("HVAC_SizeDucts", "Target aspect ratio:"))
        grid.addWidget(self.target_aspect_ratio_label, row, 0)
        self.target_aspect_ratio = QtWidgets.QDoubleSpinBox()
        self.target_aspect_ratio.setDecimals(2)
        self.target_aspect_ratio.setRange(0.1, 100.0)
        self.target_aspect_ratio.setSingleStep(0.1)
        grid.addWidget(self.target_aspect_ratio, row, 1)
        row += 1

        grid.addWidget(QtWidgets.QLabel(translate("HVAC_SizeDucts", "Size rounding increment:")), row, 0)
        self.size_rounding_increment = QtWidgets.QDoubleSpinBox()
        self.size_rounding_increment.setDecimals(1)
        self.size_rounding_increment.setRange(0.1, 1e6)
        self.size_rounding_increment.setSingleStep(5.0)
        self.size_rounding_increment.setSuffix(" mm")
        grid.addWidget(self.size_rounding_increment, row, 1)
        row += 1

        # The network's friction model (also used by Calculate Airflow): a formula, a chart file or an expression.
        grid.addWidget(QtWidgets.QLabel(translate("HVAC_SizeDucts", "Friction model:")), row, 0)
        self.friction_model_combo = QtWidgets.QComboBox()
        for value, label in self.FRICTION_MODELS:
            self.friction_model_combo.addItem(translate("HVAC_SizeDucts", label), value)
        grid.addWidget(self.friction_model_combo, row, 1)
        row += 1

        self.friction_table_label = QtWidgets.QLabel(translate("HVAC_SizeDucts", "Friction chart (CSV):"))
        grid.addWidget(self.friction_table_label, row, 0)
        self.friction_table_row = QtWidgets.QWidget()
        table_layout = QtWidgets.QHBoxLayout(self.friction_table_row)
        table_layout.setContentsMargins(0, 0, 0, 0)
        self.friction_table_file = QtWidgets.QLineEdit()
        self.friction_table_file.setToolTip(
            translate(
                "HVAC_SizeDucts",
                "A header row with diameter_mm, velocity_ms (or flow_lps) and pa_per_m, then one row per chart point",
            )
        )
        browse = QtWidgets.QPushButton(translate("HVAC_SizeDucts", "Browse..."))
        browse.clicked.connect(self._browseFrictionTable)
        table_layout.addWidget(self.friction_table_file)
        table_layout.addWidget(browse)
        grid.addWidget(self.friction_table_row, row, 1)
        row += 1

        self.friction_expression_label = QtWidgets.QLabel(translate("HVAC_SizeDucts", "Friction expression:"))
        grid.addWidget(self.friction_expression_label, row, 0)
        self.friction_expression = QtWidgets.QLineEdit()
        self.friction_expression.setToolTip(
            translate(
                "HVAC_SizeDucts",
                "Friction rate in Pa/m in Q (m3/s), V (m/s), Dh (m), A (m2), eps (m), rho (kg/m3), nu (m2/s), Re; "
                "+ - * / **, sqrt, log, log10, exp, abs, min, max",
            )
        )
        grid.addWidget(self.friction_expression, row, 1)

        return group

    def _browseFrictionTable(self):
        path, _filter = QtWidgets.QFileDialog.getOpenFileName(
            None,
            translate("HVAC_SizeDucts", "Friction chart"),
            self.friction_table_file.text(),
            translate("HVAC_SizeDucts", "CSV files (*.csv);;All files (*)"),
        )
        if path:
            self.friction_table_file.setText(path)

    def _loadFromNetwork(self):
        net = self.network_obj

        method = str(getattr(net, "SizingMethod", "ConstantVelocity") or "ConstantVelocity")
        idx = self.sizing_method_combo.findData(method)
        self.sizing_method_combo.setCurrentIndex(idx if idx >= 0 else 0)

        self.target_velocity.setValue(float(getattr(net, "TargetVelocity", 5.0) or 5.0))
        self.target_friction_rate.setValue(float(getattr(net, "TargetFrictionRate", 1.0) or 1.0))
        self.static_regain_factor.setValue(float(getattr(net, "StaticRegainFactor", 0.75) or 0.75))
        self.minimum_velocity.setValue(float(getattr(net, "MinimumVelocity", 2.5) or 2.5))

        policy = str(getattr(net, "SizeChangePolicy", "AtStraightJunctions") or "AtStraightJunctions")
        idx = self.size_change_policy_combo.findData(policy)
        self.size_change_policy_combo.setCurrentIndex(idx if idx >= 0 else 0)

        mode = str(getattr(net, "RectangularSizingMode", "FixedAspectRatio") or "FixedAspectRatio")
        idx = self.rectangular_sizing_mode_combo.findData(mode)
        self.rectangular_sizing_mode_combo.setCurrentIndex(idx if idx >= 0 else 0)

        self.target_aspect_ratio.setValue(float(getattr(net, "TargetAspectRatio", 2.0) or 2.0))
        self.size_rounding_increment.setValue(float(getattr(net, "SizeRoundingIncrement", 10.0) or 10.0))

        model = str(getattr(net, "FrictionModel", "DarcyAltshulTsal") or "DarcyAltshulTsal")
        idx = self.friction_model_combo.findData(model)
        self.friction_model_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.friction_table_file.setText(str(getattr(net, "FrictionTableFile", "") or ""))
        self.friction_expression.setText(str(getattr(net, "FrictionExpression", "") or ""))

    def _refreshParameterVisibility(self):
        """Only show the parameters relevant to the currently-picked SizingMethod/RectangularSizingMode."""
        method = self.sizing_method_combo.currentData()
        regain_family = ("StaticRegain", "PressureBalancedStaticRegain")
        for widget in (self.target_velocity_label, self.target_velocity):
            widget.setVisible(method == "ConstantVelocity" or method in regain_family)
        for widget in (self.target_friction_rate_label, self.target_friction_rate):
            widget.setVisible(method == "ConstantFrictionRate")
        for widget in (self.static_regain_factor_label, self.static_regain_factor):
            widget.setVisible(method in regain_family)
        for widget in (self.minimum_velocity_label, self.minimum_velocity):
            widget.setVisible(method in regain_family)

        show_aspect_ratio = self.rectangular_sizing_mode_combo.currentData() == "FixedAspectRatio"
        for widget in (self.target_aspect_ratio_label, self.target_aspect_ratio):
            widget.setVisible(show_aspect_ratio)

        friction = self.friction_model_combo.currentData()
        for widget in (self.friction_table_label, self.friction_table_row):
            widget.setVisible(friction == "Table")
        for widget in (self.friction_expression_label, self.friction_expression):
            widget.setVisible(friction == "Expression")

    def _applyParametersToNetwork(self):
        net = self.network_obj
        net.SizingMethod = self.sizing_method_combo.currentData()
        net.TargetVelocity = self.target_velocity.value()
        net.TargetFrictionRate = self.target_friction_rate.value()
        net.StaticRegainFactor = self.static_regain_factor.value()
        net.MinimumVelocity = self.minimum_velocity.value()
        if "SizeChangePolicy" in net.PropertiesList:
            net.SizeChangePolicy = self.size_change_policy_combo.currentData()
        net.RectangularSizingMode = self.rectangular_sizing_mode_combo.currentData()
        net.TargetAspectRatio = self.target_aspect_ratio.value()
        net.SizeRoundingIncrement = self.size_rounding_increment.value()
        if "FrictionModel" in net.PropertiesList:
            net.FrictionModel = self.friction_model_combo.currentData()
            net.FrictionTableFile = self.friction_table_file.text().strip()
            net.FrictionExpression = self.friction_expression.text().strip()

    def _runSizing(self):
        from ..core.DuctSizer import DuctSizer

        self._applyParametersToNetwork()

        sizer = DuctSizer(self.network_obj)
        try:
            result = sizer.solve()
        except Exception as e:
            FreeCAD.Console.PrintWarning(
                "HVAC - SizeDucts - Error sizing network '{}': {}\n".format(self.network_obj.Label, e)
            )
            FreeCAD.Console.PrintMessage(traceback.format_exc())
            return

        self.sizer = sizer
        self.result = result
        self._showResults(result)

    def _clearResults(self):
        while self.results_layout.count():
            item = self.results_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _showResults(self, result):
        self._clearResults()
        self.selection_sync.clearTables()

        if result.warnings:
            # Element references in each warning are links that select the element.
            warn_box = _build_warnings_box(translate("HVAC_SizeDucts", "Warnings"), result.warnings, self.network_obj)
            self.results_layout.addWidget(warn_box)

        info = QtWidgets.QLabel(
            translate(
                "HVAC_SizeDucts",
                "Review the proposed duct sizes below, then click OK to apply them to the "
                "segments, or Cancel to discard."
            )
        )
        info.setWordWrap(True)
        self.results_layout.addWidget(info)

        segments = _sorted_by_number(result.segments)
        table = QtWidgets.QTableWidget(len(segments), len(self.HEADERS))
        _setHeaderLabelsWithTooltips(table, self.HEADERS)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        for row, sres in enumerate(segments):
            current = self._formatSize(sres.profile, sres.old_diameter_mm, sres.old_width_mm, sres.old_height_mm)
            proposed = self._formatSize(sres.profile, sres.new_diameter_mm, sres.new_width_mm, sres.new_height_mm)
            if not sres.changed:
                proposed = translate("HVAC_SizeDucts", "(unchanged)")
            values = [
                getattr(sres.obj, "Number", "") or "",
                sres.obj.Label,
                sres.profile,
                current,
                proposed,
                "{:.2f}".format(sres.velocity_ms),
                "{:.3f}".format(sres.friction_rate_pa_per_m),
                "" if sres.regain_balanced else translate("HVAC_SizeDucts", "No (see warnings)"),
            ]
            for col, value in enumerate(values):
                table.setItem(row, col, QtWidgets.QTableWidgetItem(value))
        table.resizeColumnsToContents()
        self.selection_sync.addTable(table, [sres.obj for sres in segments])
        self.results_layout.addWidget(table)

        # Only ever non-empty for PressureBalancedStaticRegain, when some
        # branch's pressure deficit couldn't be closed by sizing alone --
        # reporting only (see core.DuctSizer.BalancingRequirementRow): this
        # never inserts a damper, sets a custom K, or changes topology/
        # geometry, it just shows the additional ΔP/K a real balancing
        # device would need at that junction/branch.
        if result.balancing_requirements:
            self.results_layout.addWidget(
                QtWidgets.QLabel(translate("HVAC_SizeDucts", "Balancing Requirements"))
            )
            bal_table = QtWidgets.QTableWidget(len(result.balancing_requirements), len(self.BALANCING_HEADERS))
            _setHeaderLabelsWithTooltips(bal_table, self.BALANCING_HEADERS)
            bal_table.verticalHeader().setVisible(False)
            bal_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
            for row, req in enumerate(result.balancing_requirements):
                values = [
                    self._objectLabel(req.junction_obj, req.junction_key),
                    self._objectLabel(req.branch_obj, req.branch_key),
                    "{:.1f}".format(req.pressure_deficit_pa),
                    "{:.2f}".format(req.required_k),
                ]
                for col, value in enumerate(values):
                    bal_table.setItem(row, col, QtWidgets.QTableWidgetItem(value))
            bal_table.resizeColumnsToContents()
            self.selection_sync.addTable(
                bal_table, [req.junction_obj for req in result.balancing_requirements]
            )
            self.results_layout.addWidget(bal_table)

    @staticmethod
    def _objectLabel(obj, fallback_key):
        """Number, then Label, then the raw graph key -- same resolution the segment-sizing
        table above already uses for a real object, for whichever of junction_obj/branch_obj
        actually resolved (see BalancingRequirementRow's own docstring on why either may be None)."""
        if obj is None:
            return fallback_key
        return getattr(obj, "Number", "") or getattr(obj, "Label", "") or fallback_key

    def _formatSize(self, profile, diameter_mm, width_mm, height_mm):
        if profile == "Circular":
            return "{:.0f} mm dia".format(diameter_mm)
        return "{:.0f} x {:.0f} mm".format(width_mm, height_mm)

    def accept(self):
        self.flow_arrow_observer.stop()
        self.selection_sync.stop()
        if self.sizer is not None and self.result is not None:
            changed_count = self.sizer.apply(self.result)
            if changed_count and getattr(self.network_obj, "Document", None):
                self.network_obj.Document.recompute()
        return True

    def reject(self):
        self.flow_arrow_observer.stop()
        self.selection_sync.stop()
        return True


# =================================================
# Port containers: custom fittings and equipment
# =================================================


def selected_planar_faces():
    """
    [(body, face_name), ...] for every face picked in the 3D view, with the
    selection resolved through any App::Part / link to the body that owns
    the face. Used by the port panel (TaskPanelPortContainer).
    """
    faces = []
    for sel in Gui.Selection.getSelectionEx("", 0) or []:
        owner = sel.Object
        for sub in sel.SubElementNames or []:
            face_name = sub.split(".")[-1]
            if not face_name.startswith("Face"):
                continue
            body = owner
            if "." in sub:
                resolved = owner.getSubObject(sub, retType=1)
                body = resolved if resolved is not None else owner
            faces.append((body, face_name))
    return faces


def _length_spin_box(value=0.0):
    box = QtWidgets.QDoubleSpinBox()
    box.setRange(-1.0e6, 1.0e6)
    box.setDecimals(1)
    box.setSingleStep(10.0)
    box.setSuffix(" mm")
    box.setValue(float(value))
    return box


class TaskPanelAddEquipment:
    """
    Add a library equipment model (an air handling unit, a fan, ...) to the
    document as HVAC equipment: pick the library, then the model, set its
    sizes and where it goes; OK builds it with its ports
    (Equipment.create_from_model). The fields are made from the model's own
    property list. Only libraries with at least one equipment model are
    offered; the active network's default library is picked first.
    """

    def __init__(self, doc, models):
        self.doc = doc
        self.models = list(models)
        self.created = None
        self._editors = {}
        self._shown = []

        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(translate("HVAC_AddEquipment", "Add Equipment"))
        layout = QtWidgets.QVBoxLayout(self.form)

        layout.addWidget(QtWidgets.QLabel(translate("HVAC_AddEquipment", "Library:")))
        self.library_combo = QtWidgets.QComboBox()
        layout.addWidget(self.library_combo)
        layout.addWidget(QtWidgets.QLabel(translate("HVAC_AddEquipment", "Model:")))
        self.model_combo = QtWidgets.QComboBox()
        layout.addWidget(self.model_combo)
        self.description = QtWidgets.QLabel()
        self.description.setWordWrap(True)
        layout.addWidget(self.description)

        self.fields_box = QtWidgets.QGroupBox(translate("HVAC_AddEquipment", "Sizes"))
        self.fields_form = QtWidgets.QFormLayout(self.fields_box)
        layout.addWidget(self.fields_box)

        place_box = QtWidgets.QGroupBox(translate("HVAC_AddEquipment", "Position of the unit's centre"))
        place_form = QtWidgets.QFormLayout(place_box)
        self.position = []
        for axis in ("X", "Y", "Z"):
            spin = _length_spin_box()
            spin.setSuffix(" mm")
            place_form.addRow(axis + ":", spin)
            self.position.append(spin)
        layout.addWidget(place_box)

        self.message = QtWidgets.QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        layout.addStretch(1)

        self._populateLibraries()
        self.library_combo.currentIndexChanged.connect(self._refreshModels)
        self.model_combo.currentIndexChanged.connect(self._showModel)
        self._refreshModels()

    def _populateLibraries(self):
        """The libraries that have equipment models, in registry order, starting on the active network's default."""
        with_models = {model.library_id for model in self.models}
        labels = {}
        try:
            for lib in hvaclib.HVACLibraryService.get_hvac_library_registry().list_libraries():
                labels[lib.id] = lib.label
        except Exception:
            pass
        ordered = [lib_id for lib_id in labels if lib_id in with_models]
        ordered += sorted(with_models - set(ordered))
        self.library_combo.clear()
        for lib_id in ordered:
            self.library_combo.addItem(labels.get(lib_id) or lib_id, lib_id)
        try:
            net = hvaclib.activeHVACNetwork()
        except Exception:
            net = None
        index = self.library_combo.findData(getattr(net, "DefaultLibraryId", "") if net is not None else "")
        if index >= 0:
            self.library_combo.setCurrentIndex(index)

    def _refreshModels(self):
        """List the picked library's models, keeping the picked model's id when the new library has it too."""
        current = self._model()
        library_id = self.library_combo.currentData()
        self._shown = [model for model in self.models if model.library_id == library_id]
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for model in self._shown:
            self.model_combo.addItem(model.label, model.id)
        index = self.model_combo.findData(current.id) if current is not None else -1
        self.model_combo.setCurrentIndex(max(index, 0) if self._shown else -1)
        self.model_combo.blockSignals(False)
        self._showModel()

    def _model(self):
        index = self.model_combo.currentIndex()
        return self._shown[index] if 0 <= index < len(self._shown) else None

    def _showModel(self):
        """Rebuild the size fields for the picked model."""
        while self.fields_form.rowCount():
            self.fields_form.removeRow(0)
        self._editors = {}
        model = self._model()
        self.message.setText("")
        if model is None:
            self.description.setText(translate("HVAC_AddEquipment", "No equipment model in the loaded libraries."))
            return
        self.description.setText(model.description)
        for prop in model.properties:
            if prop.type == "bool":
                editor = QtWidgets.QCheckBox()
                editor.setChecked(bool(prop.default))
            elif prop.type == "choice":
                editor = QtWidgets.QComboBox()
                editor.addItems(prop.options)
                editor.setCurrentIndex(max(prop.options.index(str(prop.default)), 0))
            else:
                editor = QtWidgets.QDoubleSpinBox()
                editor.setRange(prop.minimum, 1.0e6)
                editor.setDecimals(1)
                editor.setSingleStep(50.0 if prop.type == "length" else 10.0)
                editor.setSuffix({"length": " mm", "pressure": " Pa"}.get(prop.type, ""))
                editor.setValue(float(prop.default))
            if prop.description:
                editor.setToolTip(prop.description)
            self.fields_form.addRow(prop.label + ":", editor)
            self._editors[prop.name] = editor

    def values(self):
        """{property name: value} as set in the fields."""
        values = {}
        for name, editor in self._editors.items():
            if isinstance(editor, QtWidgets.QCheckBox):
                values[name] = editor.isChecked()
            elif isinstance(editor, QtWidgets.QComboBox):
                values[name] = editor.currentText()
            else:
                values[name] = editor.value()
        return values

    def accept(self):
        from ..core import Equipment

        model = self._model()
        if model is None:
            return True
        self.doc.openTransaction("Add Equipment")
        try:
            position = tuple(spin.value() for spin in self.position)
            self.created = Equipment.create_from_model(self.doc, model, self.values(), position)
        except Exception as e:
            self.doc.abortTransaction()
            # Stay open, so the sizes can be corrected.
            self.message.setText(translate("HVAC_AddEquipment", "Not added: {}").format(e))
            return False
        self.doc.commitTransaction()
        self.doc.recompute()
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, self.created.Name)
        FreeCAD.Console.PrintMessage("HVAC - Added equipment '{}'\n".format(self.created.Label))
        return True

    def reject(self):
        return True


class TaskPanelPortContainer:
    """
    Create and edit the ports of an App::Part: an HVAC equipment's ports
    (kind "equipment", grouped by what each port does) or a custom fitting's
    (kind "fitting"). The same panel opens again later to edit them.

    - The tree lists the ports. Picking one selects its marker in the 3D
      view, and picking a marker in the 3D view picks it in the tree.
    - One "Port" box follows the 3D selection: a port marker selected ->
      edit it (name, function, X/Y from the face centre; Apply / Remove);
      a planar face of the model selected -> a new port on that face (Add
      Port); nothing usable selected -> a hint. For equipment, picking a
      group header in the tree picks the function of the next new port.
    - Equipment: its internal pressure drop. Custom fitting: the junctions
      it fits (same number of ducts as ports, and the ports line up with the
      ducts; an end node counts for a one-port fitting), listed and coloured
      orange in the 3D view while the panel is open (their own colours come
      back on close; pre-selection and selection highlight them as usual);
      picking one in the list selects its fittings in the 3D view and the
      other way round. "Use This Fitting There" moves the fitting onto it.
    - Port markers are shown while the panel is open and hidden when it
      closes. Each equipment port also gets a snap point at its centre
      (_custom_fitting.ensure_snap_point), which stays visible, so a duct
      can be drawn to end exactly on the port.

    Ducts drawn to end on the ports attach without any further step: an
    equipment port is connected to its duct end, and the ends on a custom
    fitting's ports become one junction using the fitting where it is
    (DuctNetwork.autoAttach).
    """

    MODE_NONE = "none"
    MODE_ADD = "add"
    MODE_EDIT = "edit"

    # Candidate junction highlight; FreeCAD draws the selection in green and
    # pre-selection in yellow, so neither is used here.
    COLOR_CANDIDATE = (1.0, 0.5, 0.0)

    def __init__(self, container, kind="equipment"):
        from ..core import Equipment, _custom_fitting

        self.container = container
        self.kind = kind
        self.doc = container.Document
        self._custom_fitting = _custom_fitting
        self._equipment = Equipment
        self._syncing = False
        self._mode = self.MODE_NONE
        self._marker = None
        self._face = None
        self._highlight_saved = {}
        self.junction_list = None

        self.form = QtWidgets.QWidget()
        title = "Equipment" if kind == "equipment" else "Custom Fitting"
        self.form.setWindowTitle(translate("HVAC_PortContainer", title) + ": " + container.Label)
        layout = QtWidgets.QVBoxLayout(self.form)

        # Step 1: the port list.
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(
            [translate("HVAC_PortContainer", text) for text in ("Port", "Profile", "Size", "X", "Y")]
        )
        self.tree.itemSelectionChanged.connect(self._onTreeSelection)
        layout.addWidget(self.tree)

        # Step 2: one box for the port in hand, a new one or an existing one.
        self.port_box = QtWidgets.QGroupBox(translate("HVAC_PortContainer", "Port"))
        port_form = QtWidgets.QFormLayout(self.port_box)
        self.state_label = QtWidgets.QLabel()
        self.state_label.setWordWrap(True)
        port_form.addRow(self.state_label)
        self.function_combo = self._functionCombo()
        if self.function_combo is not None:
            port_form.addRow(translate("HVAC_PortContainer", "Function:"), self.function_combo)
        self.name_edit = QtWidgets.QLineEdit()
        self.name_label = QtWidgets.QLabel(translate("HVAC_PortContainer", "Name:"))
        port_form.addRow(self.name_label, self.name_edit)
        self.x_spin = _length_spin_box()
        self.y_spin = _length_spin_box()
        port_form.addRow(translate("HVAC_PortContainer", "Offset X from face centre:"), self.x_spin)
        port_form.addRow(translate("HVAC_PortContainer", "Offset Y from face centre:"), self.y_spin)
        buttons = QtWidgets.QHBoxLayout()
        self.add_button = QtWidgets.QPushButton(translate("HVAC_PortContainer", "Add Port"))
        self.add_button.clicked.connect(self._addPort)
        self.apply_button = QtWidgets.QPushButton(translate("HVAC_PortContainer", "Apply"))
        self.apply_button.clicked.connect(self._applyEdit)
        self.remove_button = QtWidgets.QPushButton(translate("HVAC_PortContainer", "Remove"))
        self.remove_button.clicked.connect(self._removePort)
        for button in (self.add_button, self.apply_button, self.remove_button):
            buttons.addWidget(button)
        port_form.addRow(buttons)
        self._port_inputs = [self.name_edit, self.x_spin, self.y_spin] + (
            [self.function_combo] if self.function_combo is not None else []
        )
        layout.addWidget(self.port_box)

        # Step 3: the container's own options.
        if kind == "equipment":
            options = QtWidgets.QGroupBox(translate("HVAC_PortContainer", "Equipment"))
            options_form = QtWidgets.QFormLayout(options)
            self.pressure_drop = QtWidgets.QDoubleSpinBox()
            self.pressure_drop.setRange(0.0, 1.0e5)
            self.pressure_drop.setDecimals(1)
            self.pressure_drop.setSuffix(" Pa")
            self.pressure_drop.setValue(float(getattr(container, "InternalPressureDrop", 0.0) or 0.0))
            self.pressure_drop.setToolTip(
                translate("HVAC_PortContainer", "Pressure drop inside the unit (coils, filters, casing)")
            )
            self.pressure_drop.valueChanged.connect(self._setPressureDrop)
            options_form.addRow(translate("HVAC_PortContainer", "Internal pressure drop:"), self.pressure_drop)
            hint = QtWidgets.QLabel(
                translate(
                    "HVAC_PortContainer",
                    "Draw the duct base geometry so a duct ends on a port: the network connects it to the port "
                    "automatically.",
                )
            )
            hint.setWordWrap(True)
            options_form.addRow(hint)
            layout.addWidget(options)
        else:
            options = QtWidgets.QGroupBox(translate("HVAC_PortContainer", "Use in a network"))
            options_layout = QtWidgets.QVBoxLayout(options)
            hint = QtWidgets.QLabel(
                translate(
                    "HVAC_PortContainer",
                    "Draw the duct base geometry so the ducts end on the ports: their ends become one junction "
                    "that uses this fitting where it is. Or move it onto an existing junction it fits (shown in "
                    "orange in the 3D view):",
                )
            )
            hint.setWordWrap(True)
            options_layout.addWidget(hint)
            self.junction_list = QtWidgets.QListWidget()
            self.junction_list.setMinimumHeight(90)
            self.junction_list.itemSelectionChanged.connect(self._onJunctionListSelection)
            options_layout.addWidget(self.junction_list)
            self.use_button = QtWidgets.QPushButton(translate("HVAC_PortContainer", "Use This Fitting There"))
            self.use_button.clicked.connect(self._useAtJunction)
            options_layout.addWidget(self.use_button)
            layout.addWidget(options)

        # Markers are shown while the panel is open (hidden again on close);
        # equipment ports get their snap points (ports made before had none).
        for marker in self._ports():
            self._custom_fitting.show_port(marker)
            if kind == "equipment":
                self._custom_fitting.ensure_snap_point(marker)
        self._refresh()
        self._syncFromSelection()
        Gui.Selection.addObserver(self)

    # -- helpers ------------------------------------------------------------

    def _functionCombo(self):
        if self.kind != "equipment":
            return None
        combo = QtWidgets.QComboBox()
        for value, label in self.FUNCTION_LABELS:
            combo.addItem(translate("HVAC_PortContainer", label), value)
        return combo

    FUNCTION_LABELS = [
        ("SupplyOutlet", "Supply outlet"),
        ("ReturnInlet", "Return inlet"),
        ("OutdoorAirInlet", "Outdoor air inlet"),
        ("ExhaustOutlet", "Exhaust outlet"),
    ]
    GROUP_LABELS = {
        "SupplyOutlet": "Supply outlets",
        "ReturnInlet": "Return inlets",
        "OutdoorAirInlet": "Outdoor air inlets",
        "ExhaustOutlet": "Exhaust outlets",
    }

    def _ports(self):
        return self._custom_fitting.container_ports(self.container)

    def _treeMarker(self):
        items = self.tree.selectedItems()
        if not items:
            return None
        name = items[0].data(0, QtCore.Qt.UserRole)
        return self.doc.getObject(name) if name else None

    def _selectedObjects(self):
        """Every object picked in the 3D view or the tree, resolved through App::Parts / links to the picked one."""
        objects = []
        for sel in Gui.Selection.getSelectionEx("", 0) or []:
            owner = sel.Object
            for sub in sel.SubElementNames or [""]:
                obj = owner.getSubObject(sub, retType=1) if sub else owner
                objects.append(obj if obj is not None else owner)
        return objects

    def _selectedPortMarker(self):
        """The port marker of this container picked in the 3D view (an axis or plane of the marker counts)."""
        ports = {marker.Name: marker for marker in self._ports()}
        for obj in self._selectedObjects():
            if obj.Name in ports:
                return ports[obj.Name]
            by_point = self._custom_fitting.port_of_snap_point(obj, ports.values())
            if by_point is not None:
                return by_point
            # A marker's own axis, plane or origin: the marker lists it in OriginFeatures. (Not any InList
            # entry: the body a marker is attached to has the marker in its InList too.)
            for candidate in getattr(obj, "InList", []) or []:
                if candidate.Name in ports and obj in (getattr(candidate, "OriginFeatures", []) or []):
                    return ports[candidate.Name]
        return None

    def _selectedJunction(self):
        """The junction picked in the 3D view: the junction itself, or one of its fittings."""
        from ..utils import hvaclib

        for obj in self._selectedObjects():
            if hvaclib.isDuctJunction(obj):
                return obj
            if hvaclib.isDuctComponent(obj):
                junction = self.doc.getObject(getattr(obj, "ParentJunctionName", "") or "")
                if junction is not None:
                    return junction
        return None

    def _refresh(self, select_name=None):
        """Rebuild the tree from the container's markers (grouped by function for equipment)."""
        self.tree.blockSignals(True)
        self.tree.clear()
        groups = {}
        if self.kind == "equipment":
            for value, _label in self.FUNCTION_LABELS:
                item = QtWidgets.QTreeWidgetItem([translate("HVAC_PortContainer", self.GROUP_LABELS[value])])
                item.setData(1, QtCore.Qt.UserRole, value)
                self.tree.addTopLevelItem(item)
                groups[value] = item
        else:
            groups[""] = QtWidgets.QTreeWidgetItem([translate("HVAC_PortContainer", "Ports")])
            self.tree.addTopLevelItem(groups[""])
        selected = None
        for marker in self._ports():
            key = str(getattr(marker, "EquipmentPortFunction", "SupplyOutlet")) if self.kind == "equipment" else ""
            parent = groups.get(key) or next(iter(groups.values()))
            item = QtWidgets.QTreeWidgetItem(
                [
                    str(getattr(marker, "PortName", "") or marker.Label),
                    str(getattr(marker, "PortProfile", "")),
                    self._custom_fitting.port_size_text(marker),
                    "{:.1f}".format(float(getattr(marker, "PortOffsetX", 0.0) or 0.0)),
                    "{:.1f}".format(float(getattr(marker, "PortOffsetY", 0.0) or 0.0)),
                ]
            )
            item.setData(0, QtCore.Qt.UserRole, marker.Name)
            parent.addChild(item)
            if marker.Name == select_name:
                selected = item
        self.tree.expandAll()
        for column in range(self.tree.columnCount()):
            self.tree.resizeColumnToContents(column)
        if selected is not None:
            selected.setSelected(True)
        self.tree.blockSignals(False)
        if self.kind == "fitting":
            self._refreshJunctions()

    def _selectTreeMarker(self, marker):
        """Pick `marker`'s row in the tree (None: no port row), without acting on it."""
        self.tree.blockSignals(True)
        try:
            iterator = QtWidgets.QTreeWidgetItemIterator(self.tree)
            while iterator.value():
                item = iterator.value()
                name = item.data(0, QtCore.Qt.UserRole)
                if name:
                    item.setSelected(marker is not None and name == marker.Name)
                elif marker is not None:
                    item.setSelected(False)
                iterator += 1
        finally:
            self.tree.blockSignals(False)

    # -- the Port box -------------------------------------------------------

    def _syncFromSelection(self):
        """Put the Port box (and the tree and junction list) in step with the 3D selection."""
        if self._syncing:
            return
        self._syncing = True
        try:
            marker = self._selectedPortMarker()
            faces = [] if marker is not None else selected_planar_faces()
            if marker is not None:
                self._selectTreeMarker(marker)
                if self._mode != self.MODE_EDIT or self._marker is None or self._marker.Name != marker.Name:
                    self._setMode(self.MODE_EDIT, marker=marker)
            elif faces:
                self._selectTreeMarker(None)
                face = (faces[0][0].Name, faces[0][1])
                if self._mode != self.MODE_ADD or self._face != face:
                    self._setMode(self.MODE_ADD, face=face, body=faces[0][0])
            else:
                self._selectTreeMarker(None)
                self._setMode(self.MODE_NONE)
            if self.junction_list is not None:
                self._selectJunctionRow(self._selectedJunction())
        finally:
            self._syncing = False

    def _setMode(self, mode, marker=None, face=None, body=None):
        self._mode = mode
        self._marker = marker if mode == self.MODE_EDIT else None
        self._face = face if mode == self.MODE_ADD else None
        for widget in self._port_inputs:
            widget.setEnabled(mode != self.MODE_NONE)
        self.add_button.setVisible(mode == self.MODE_ADD)
        self.apply_button.setVisible(mode == self.MODE_EDIT)
        self.remove_button.setVisible(mode == self.MODE_EDIT)
        if mode == self.MODE_EDIT:
            label = str(getattr(marker, "PortName", "") or marker.Label)
            self.state_label.setText(
                translate("HVAC_PortContainer", "Port {} ({} {})").format(
                    label, getattr(marker, "PortProfile", ""), self._custom_fitting.port_size_text(marker)
                )
            )
            self.name_label.setText(translate("HVAC_PortContainer", "Name:"))
            self.name_edit.setText(str(getattr(marker, "PortName", "") or ""))
            self.x_spin.setValue(float(getattr(marker, "PortOffsetX", 0.0) or 0.0))
            self.y_spin.setValue(float(getattr(marker, "PortOffsetY", 0.0) or 0.0))
            if self.function_combo is not None:
                index = self.function_combo.findData(str(getattr(marker, "EquipmentPortFunction", "SupplyOutlet")))
                self.function_combo.setCurrentIndex(max(index, 0))
        elif mode == self.MODE_ADD:
            self.state_label.setText(
                translate("HVAC_PortContainer", "New port on face {}").format(body.Label + "." + face[1])
            )
            self.name_label.setText(translate("HVAC_PortContainer", "Name (optional):"))
            self.name_edit.clear()
            self.x_spin.setValue(0.0)
            self.y_spin.setValue(0.0)
        else:
            self.state_label.setText(
                translate(
                    "HVAC_PortContainer",
                    "Pick a planar end face of the model in the 3D view to add a port, or a port in the list "
                    "(or its marker in the 3D view) to edit it.",
                )
            )

    # -- the junction list (custom fitting) ----------------------------------

    def _candidateJunctions(self):
        """Every junction in the document this fitting can be put on (see _custom_fitting.fit_problem)."""
        from ..utils import hvaclib

        found = []
        for obj in self.doc.Objects:
            if not hvaclib.isDuctJunction(obj):
                continue
            try:
                primary = obj.Proxy.getPrimaryComponent()
            except Exception:
                primary = None
            if primary is None or "GeometrySource" not in primary.PropertiesList:
                continue
            if not self._custom_fitting.fit_problem(self.container, primary):
                found.append(obj)
        return found

    def _refreshJunctions(self):
        """List the junctions this fitting fits and highlight them in the 3D view."""
        candidates = self._candidateJunctions()
        self.junction_list.blockSignals(True)
        self.junction_list.clear()
        for junction in candidates:
            number = getattr(junction, "Number", "") or ""
            item = QtWidgets.QListWidgetItem(" ".join(filter(None, (str(number), junction.Label))))
            item.setData(QtCore.Qt.UserRole, junction.Name)
            self.junction_list.addItem(item)
        if not candidates:
            item = QtWidgets.QListWidgetItem(translate("HVAC_PortContainer", "No junction in the document fits"))
            item.setFlags(QtCore.Qt.NoItemFlags)
            self.junction_list.addItem(item)
        self.junction_list.blockSignals(False)
        self.use_button.setEnabled(False)
        self._drawHighlights(candidates)

    def _selectJunctionRow(self, junction):
        self.junction_list.blockSignals(True)
        try:
            for row in range(self.junction_list.count()):
                item = self.junction_list.item(row)
                item.setSelected(junction is not None and item.data(QtCore.Qt.UserRole) == junction.Name)
        finally:
            self.junction_list.blockSignals(False)
        self.use_button.setEnabled(bool(self.junction_list.selectedItems()))

    def _listedJunction(self):
        items = self.junction_list.selectedItems() if self.junction_list is not None else []
        return self.doc.getObject(items[0].data(QtCore.Qt.UserRole) or "") if items else None

    def _onJunctionListSelection(self):
        """Select the listed junction's fittings in the 3D view."""
        junction = self._listedJunction()
        self.use_button.setEnabled(junction is not None)
        if junction is None or self._syncing:
            return
        self._syncing = True
        try:
            Gui.Selection.clearSelection()
            components = []
            try:
                components = list(junction.Proxy.getComponents() or [])
            except Exception:
                components = []
            for obj in components or [junction]:
                Gui.Selection.addSelection(self.doc.Name, obj.Name)
            self._selectTreeMarker(None)
            self._setMode(self.MODE_NONE)
        finally:
            self._syncing = False

    def _drawHighlights(self, candidates):
        """
        Colour every candidate junction's fittings orange: faces, lines and
        points of the fitting itself (a custom fitting's link through its
        override material), so FreeCAD's own pre-selection and selection
        highlight still show on them. The colours they had are kept and put
        back by _clearHighlights().
        """
        self._clearHighlights()
        for junction in candidates:
            try:
                components = list(junction.Proxy.getComponents() or [])
            except Exception:
                components = []
            for obj in components:
                target = obj
                shape = getattr(obj, "Shape", None)
                if shape is None or shape.isNull():
                    target = self._custom_fitting.owned_link(obj) or obj
                self._paint(target)

    def _orangeMaterial(self):
        material = FreeCAD.Material()
        material.DiffuseColor = self.COLOR_CANDIDATE
        material.AmbientColor = tuple(0.5 * c for c in self.COLOR_CANDIDATE)
        material.EmissiveColor = tuple(0.25 * c for c in self.COLOR_CANDIDATE)
        return material

    def _paint(self, obj):
        """Colour one object's view orange, keeping what it had in self._highlight_saved."""
        view = getattr(obj, "ViewObject", None)
        if view is None or obj.Name in self._highlight_saved:
            return
        saved = {}
        try:
            properties = view.PropertiesList
            if "ShapeAppearance" in properties:
                saved["ShapeAppearance"] = view.ShapeAppearance
                view.ShapeAppearance = [self._orangeMaterial()] * max(1, len(view.ShapeAppearance))
            elif "OverrideMaterial" in properties and "ShapeMaterial" in properties:  # App::Link
                saved["OverrideMaterial"] = view.OverrideMaterial
                saved["ShapeMaterial"] = view.ShapeMaterial
                view.ShapeMaterial = self._orangeMaterial()
                view.OverrideMaterial = True
            for name in ("LineColor", "PointColor"):
                if name in properties:
                    saved[name] = getattr(view, name)
                    setattr(view, name, self.COLOR_CANDIDATE)
        except Exception as e:
            FreeCAD.Console.PrintWarning("HVAC - could not highlight '{}': {}\n".format(obj.Label, e))
        self._highlight_saved[obj.Name] = saved

    def _clearHighlights(self):
        """Put back the colours the highlighted fittings had."""
        saved_all, self._highlight_saved = self._highlight_saved, {}
        for name, saved in saved_all.items():
            obj = self.doc.getObject(name)
            view = getattr(obj, "ViewObject", None) if obj is not None else None
            if view is None:
                continue
            # The override flag last, so a link never shows its override material unset.
            for prop in sorted(saved, key=lambda key: key == "OverrideMaterial"):
                try:
                    setattr(view, prop, saved[prop])
                except Exception:
                    pass

    # -- selection observer (FreeCAD calls these) ------------------------------

    def addSelection(self, doc, obj, sub, pnt):
        self._syncFromSelection()

    def removeSelection(self, doc, obj, sub):
        self._syncFromSelection()

    def setSelection(self, doc):
        self._syncFromSelection()

    def clearSelection(self, doc):
        self._syncFromSelection()

    # -- actions ------------------------------------------------------------

    def _onTreeSelection(self):
        items = self.tree.selectedItems()
        # Picking a group header for equipment picks the kind of port the next "Add Port" makes.
        if items and items[0].parent() is None:
            if self.function_combo is not None and self._mode != self.MODE_EDIT:
                index = self.function_combo.findData(items[0].data(1, QtCore.Qt.UserRole))
                if index >= 0:
                    self.function_combo.setCurrentIndex(index)
            return
        marker = self._treeMarker()
        if marker is not None:
            # The selection observer then switches the Port box to this port.
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(self.doc.Name, marker.Name)

    def _addPort(self):
        faces = selected_planar_faces()
        if not faces:
            return
        body, face_name = faces[0]
        self.doc.openTransaction("Add HVAC Port")
        try:
            marker = self._custom_fitting.add_port(
                body,
                face_name,
                container=self.container,
                name=self.name_edit.text().strip(),
                offset_x=self.x_spin.value(),
                offset_y=self.y_spin.value(),
            )
            if self.kind == "equipment":
                self._equipment.ensure_equipment_port(marker, self.function_combo.currentData())
                self._custom_fitting.ensure_snap_point(marker)
        except Exception as e:
            self.doc.abortTransaction()
            FreeCAD.Console.PrintWarning("HVAC - Add port on {}.{}: {}\n".format(body.Label, face_name, e))
            return
        self.doc.commitTransaction()
        self.doc.recompute()
        self._refresh(select_name=marker.Name)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, marker.Name)

    def _applyEdit(self):
        marker = self._marker
        if marker is None:
            return
        self.doc.openTransaction("Edit HVAC Port")
        try:
            marker.PortName = self.name_edit.text().strip()
            if self.function_combo is not None:
                self._equipment.ensure_equipment_port(marker, self.function_combo.currentData())
            self._custom_fitting.set_port_offset(marker, self.x_spin.value(), self.y_spin.value())
            if self.kind == "equipment":
                self._custom_fitting.ensure_snap_point(marker)
        finally:
            self.doc.commitTransaction()
        self.doc.recompute()
        self._refresh(select_name=marker.Name)
        self._setMode(self.MODE_EDIT, marker=marker)

    def _removePort(self):
        marker = self._marker
        if marker is None:
            return
        Gui.Selection.clearSelection()
        self.doc.openTransaction("Remove HVAC Port")
        try:
            self._custom_fitting.remove_port(marker)
        finally:
            self.doc.commitTransaction()
        self.doc.recompute()
        self._refresh()
        self._setMode(self.MODE_NONE)

    def _setPressureDrop(self, value):
        if "InternalPressureDrop" in self.container.PropertiesList:
            self.container.InternalPressureDrop = float(value)

    def _useAtJunction(self):
        """Make the picked junction's Primary fitting take this container's geometry."""
        junction = self._listedJunction()
        if junction is None:
            return
        primary = junction.Proxy.getPrimaryComponent()
        if primary is None or "GeometrySource" not in primary.PropertiesList:
            FreeCAD.Console.PrintWarning("HVAC - '{}' has no fitting to replace\n".format(junction.Label))
            return
        self.doc.openTransaction("Use Custom Fitting")
        try:
            primary.CustomFitting = self.container
            if "CustomPlacement" in primary.PropertiesList:
                primary.CustomPlacement = self._custom_fitting.PLACEMENT_FIT
            primary.GeometrySource = "Custom"
        finally:
            self.doc.commitTransaction()
        self.doc.recompute()
        self._refreshJunctions()
        FreeCAD.Console.PrintMessage(
            "HVAC - '{}' now uses custom fitting '{}'\n".format(junction.Label, self.container.Label)
        )

    # -- task dialog -----------------------------------------------------------

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Close

    def _stop(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception:
            pass
        self._clearHighlights()
        for marker in self._ports():
            self._custom_fitting.hide_port(marker)

    def accept(self):
        self._stop()
        return True

    def reject(self):
        self._stop()
        return True
