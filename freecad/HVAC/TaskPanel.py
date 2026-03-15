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
        return hvaclib.obj_is_sketch(obj) or hvaclib.obj_is_wire(obj)

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

        # AutoType
        self.auto_check = QtWidgets.QCheckBox(translate("HVAC_EditType", "Auto select type"))
        layout.addWidget(self.auto_check)

        # Library
        layout.addWidget(QtWidgets.QLabel(translate("HVAC_EditType", "Library:")))
        self.library_combo = QtWidgets.QComboBox()
        layout.addWidget(self.library_combo)

        # Type
        layout.addWidget(QtWidgets.QLabel(translate("HVAC_EditType", "Type:")))
        self.type_combo = QtWidgets.QComboBox()
        layout.addWidget(self.type_combo)

        # Suggested type info
        self.suggested_label = QtWidgets.QLabel("")
        layout.addWidget(self.suggested_label)

        self._populateLibraries()
        self._loadFromSelection()

        self.library_combo.currentIndexChanged.connect(self._refreshTypes)
        self.auto_check.toggled.connect(self._updateEnabledState)

    def _populateLibraries(self):
        self.library_combo.clear()
        reg = hvaclib.get_hvac_library_registry()
        for lib in reg.list_libraries():
            self.library_combo.addItem(lib.label, lib.id)

    def _commonLibraryId(self):
        vals = {getattr(o, "LibraryId", "") for o in self.objects}
        return vals.pop() if len(vals) == 1 else ""

    def _commonTypeId(self):
        vals = {getattr(o, "TypeId", "") for o in self.objects}
        return vals.pop() if len(vals) == 1 else ""

    def _commonAutoType(self):
        vals = {bool(getattr(o, "AutoType", True)) for o in self.objects}
        return vals.pop() if len(vals) == 1 else True

    def _commonSuggestedType(self):
        suggested = set()
        for obj in self.objects:
            family = getattr(obj, "Family", "")
            if hvaclib.isDuctSegment(obj):
                profile = getattr(obj, "Profile", "")
                type_id = ""
                if profile == "circular":
                    type_id = "circular_straight"
                else:
                    type_id = "rectangular_straight"
            else:
                type_id = hvaclib.default_junction_type_id(family)
            suggested.add(type_id)
        return suggested.pop() if len(suggested) == 1 else ""

    def _loadFromSelection(self):
        library_id = self._commonLibraryId()
        auto_type = self._commonAutoType()

        if library_id:
            idx = self.library_combo.findData(library_id)
            if idx >= 0:
                self.library_combo.setCurrentIndex(idx)

        self.auto_check.setChecked(auto_type)
        self._refreshTypes()

        type_id = self._commonTypeId()
        if type_id:
            idx = self.type_combo.findData(type_id)
            if idx >= 0:
                self.type_combo.setCurrentIndex(idx)

        suggested = self._commonSuggestedType()
        if suggested:
            self.suggested_label.setText(
                translate("HVAC_EditType", "Suggested type: {}").format(suggested)
            )
        else:
            self.suggested_label.setText(
                translate("HVAC_EditType", "Suggested type: <mixed>")
            )

        self._updateEnabledState()

    def _refreshTypes(self):
        self.type_combo.clear()
        if not self.objects:
            return

        library_id = self.library_combo.currentData()
        if not library_id:
            return

        reg = hvaclib.get_hvac_library_registry()
        lib = reg.get_library(library_id)
        if lib is None:
            return

        ref = self.objects[0]
        category = "segment" if hvaclib.isDuctSegment(ref) else "junction"
        family = getattr(ref, "Family", "")
        profile = getattr(ref, "Profile", "")

        type_defs = lib.list_types(
            category=category,
            family=family if family else None,
            profile=profile if profile else None,
        )

        for tdef in type_defs:
            self.type_combo.addItem(tdef.label, tdef.id)

    def _updateEnabledState(self):
        manual = not self.auto_check.isChecked()
        self.type_combo.setEnabled(manual)

    def accept(self):
        library_id = self.library_combo.currentData()
        type_id = self.type_combo.currentData()
        auto_type = self.auto_check.isChecked()

        if self.apply_callback:
            QtCore.QTimer.singleShot(
                0,
                lambda: self.apply_callback(
                    self.objects,
                    library_id=library_id,
                    type_id=type_id,
                    auto_type=auto_type,
                )
            )
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

        self.segment_auto_check = QtWidgets.QCheckBox(
            translate("HVAC_NetworkTypeDefaults", "Segments use automatic type selection by default")
        )
        layout.addWidget(self.segment_auto_check)

        note = QtWidgets.QLabel(
            translate(
                "HVAC_NetworkTypeDefaults",
                "Junction types are not selected here. They continue to follow parser/classifier output unless manually overridden."
            )
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        self._populateLibraries()
        self._loadFromNetwork()

        self.library_combo.currentIndexChanged.connect(self._refreshProfiles)

    def _populateLibraries(self):
        reg = hvaclib.get_hvac_library_registry()

        self.library_combo.clear()
        for lib in reg.list_libraries():
            self.library_combo.addItem(lib.label, lib.id)

    def _refreshProfiles(self):
        library_id = self.library_combo.currentData()
        self.profile_combo.clear()

        if not library_id:
            return

        profiles = hvaclib.segment_profiles_for_library(library_id)
        for profile in profiles:
            self.profile_combo.addItem(profile, profile)

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

        self.segment_auto_check.setChecked(
            bool(getattr(self.network_obj, "DefaultSegmentAutoType", True))
        )

    def accept(self):
        if self.apply_callback:
            self.apply_callback(
                self.network_obj,
                library_id=self.library_combo.currentData(),
                segment_profile=self.profile_combo.currentData(),
                default_segment_auto=self.segment_auto_check.isChecked(),
            )
        return True

    def reject(self):
        return True
