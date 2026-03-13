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
