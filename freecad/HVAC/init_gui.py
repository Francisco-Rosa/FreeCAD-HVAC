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

__title__ = "Gui initialization module for HVAC Workbench."
__author__ = "Francisco Rosa, Manu Varkey"

import FreeCAD
import FreeCADGui as Gui
from PySide.QtCore import QT_TRANSLATE_NOOP, QTimer
translate = FreeCAD.Qt.translate

from .utils import hvaclib
from .utils import materials as hvac_materials

Gui.addLanguagePath(hvaclib.get_language_base_path())
Gui.updateLocale()

# Register this addon's native material cards and Hydraulic model with
# FreeCAD's Material subsystem so both appear in the normal editor.
hvac_materials.register_material_resources()


class HVAC(Gui.Workbench):
    """The HVAC Workbench."""

    MenuText = translate("InitGui", "HVAC")
    ToolTip = translate("InitGui",
                        "Workbench for HVAC analysis and configuration.")
    Icon = hvaclib.get_icon_path("Logo.svg")

    def Initialize(self):
        """This function is executed when the workbench is first activated.
        It is executed once in a FreeCAD session followed by the Activated function.
        """
        # import here all the needed files that create your FreeCAD commands
        from .ui import Command
        
        self.watchers = []

        # Groups: network (create, edit, defaults, renumber, analysis);
        # routing; base geometry; component editing; display and selection.
        commands = ['HVAC_CreateDuctNetwork',
                    'HVAC_ActivateDuctNetwork',
                    'HVAC_ModifyDuctNetwork',
                    'HVAC_EditNetworkTypeDefaults',
                    'HVAC_RenumberNetwork',
                    'HVAC_CalculateAirflow',
                    'HVAC_SizeDucts',
                    "Separator",
                    'HVAC_CreateSketch',
                    'HVAC_CreateLine',
                    'HVAC_CreateSpline',
                    'HVAC_CreateVirtualJunction',
                    'HVAC_AddEquipment',
                    "Separator",
                    'HVAC_EditBaseObject',
                    'HVAC_EditDuctDirections',
                    # 'HVAC_ReverseGeometryDirection',
                    "Separator",
                    'HVAC_CreateEquipment',
                    'HVAC_CreateCustomFitting',
                    "Separator",
                    'HVAC_EditType',
                    'HVAC_EditPlacement',
                    'HVAC_EditInlineComponents',
                    'HVAC_EditPorts',
                    'HVAC_EditMaterial',
                    'HVAC_ResetTypesToDefaults',
                    "Separator",
                    'HVAC_LayerVisibility',
                    'HVAC_SelectAllSegments',
                    'HVAC_SelectAllComponents'
                    ]
        self.toolbar_commands = list(commands)
        self.submenu_commands = list(commands)
        self.contextmenu_commands = list(commands)

        self.appendMenu(QT_TRANSLATE_NOOP("Workbench", "HVAC"), self.submenu_commands)
        self.appendToolbar(QT_TRANSLATE_NOOP("Workbench", "HVAC"), self.toolbar_commands)

        # Document observers are registered once here (Initialize() only
        # ever runs once per session), not in Activated()/Deactivated().
        # Entering Sketch or Draft Wire edit mode switches the active
        # workbench away from HVAC as a side effect (FreeCAD auto-switches
        # to the Sketcher workbench for Sketch edits; CommandEditBaseObject
        # explicitly does so for Draft Wire edits) -- that would fire
        # Deactivated() and tear the observers down right before FreeCAD's
        # own slotInEdit signal fires, so document-observer lifetime can't
        # be tied to workbench activation.
        self.setObservers()

    def Activated(self):
        """This function is executed whenever the workbench is activated"""
        FreeCAD.Console.PrintMessage(translate("InitGui","HVAC - Workbench loaded") + "\n")
        self.refreshWatchers()
        FreeCAD.Console.PrintMessage(translate("InitGui","HVAC - Workbench - Watchers set") + "\n")
        # The Layer Visibility toolbar button drops down its switches; FreeCAD
        # builds the toolbar buttons during activation, so attach afterwards.
        from PySide import QtCore
        QtCore.QTimer.singleShot(0, self.attachToolbarDropdowns)
        return

    def attachToolbarDropdowns(self):
        from .ui import Toolbar
        from .ui.Command import populate_layer_visibility_menu
        try:
            Toolbar.attach_dropdown('HVAC_LayerVisibility', populate_layer_visibility_menu)
        except Exception as e:
            FreeCAD.Console.PrintWarning("HVAC - toolbar drop-down not attached: {}\n".format(e))

    def Deactivated(self):
        """This function is executed whenever the workbench is deactivated"""
        # Only task watchers are workbench-activation-scoped -- the document,
        # gui-edit and selection observers registered in setObservers() are
        # session-scoped, see the comment in Initialize().
        try:
            Gui.Control.clearTaskWatcher()
        except Exception:
            pass
        self.watchers = []
        return

    def ContextMenu(self, recipient):
        """This function is executed whenever the user right-clicks on screen"""
        self.appendContextMenu(QT_TRANSLATE_NOOP("Workbench", "HVAC"), self.contextmenu_commands)

    def refreshWatchers(self):
        try:
            Gui.Control.clearTaskWatcher()
        except Exception:
            pass
        self.setWatchers()
        
    def setWatchers(self):
        
        def is_network_active():
            doc = FreeCAD.ActiveDocument
            active_network = hvaclib.activeHVACNetwork()
            return active_network and active_network.Document == doc
        
        def is_object_selected():
            sel_base = Gui.Selection.getSelectionEx()[0] if Gui.Selection.getSelectionEx() else None
            sel_geo = sel_base.Object if sel_base else None
            return sel_geo is not None

        class HVACCreateWatcher:
            """Shows 'Create HVAC Network' when no Duct Network exists in the document."""

            def __init__(self):
                self.commands = ["HVAC_CreateDuctNetwork"]
                self.title = translate("HVAC", "Start")

            def shouldShow(self):
                hvac_networks = hvaclib.allHVACNetworks()
                if hvac_networks:
                    return False
                else:
                    return True

        class HVACActivateWatcher:
            """Shows 'Activate HVAC Network' when an HVAC Network exists but is not active."""

            def __init__(self):
                self.commands = ["HVAC_ActivateDuctNetwork"]
                self.title = translate("HVAC", "Start")

            def shouldShow(self):
                doc = FreeCAD.ActiveDocument
                hvac_networks = hvaclib.allHVACNetworks()
                hvac_network = hvaclib.activeHVACNetwork()
                return hvac_networks and (hvac_network is None or hvac_network.Document != doc)

        class HVACEditWatcher:
            """Shows 'Edit Network' when an HVAC Network is active."""

            def __init__(self):
                super().__init__()
                self.commands = ["HVAC_ModifyDuctNetwork",
                                "HVAC_EditNetworkTypeDefaults",
                                "HVAC_RenumberNetwork",
                                "HVAC_CalculateAirflow",
                                "HVAC_SizeDucts",
                                "HVAC_LayerVisibility",
                                "HVAC_SelectAllSegments",
                                "HVAC_SelectAllComponents"]
                self.title = translate("HVAC", "Network")
                
            def shouldShow(self):
                # Show if there is an active document and no object is selected
                return is_network_active() and not is_object_selected()
                
        class HVACRoutingWatcher:
            """Shows 'Routing Tools' when an HVAC Network is active."""

            def __init__(self):
                super().__init__()
                self.commands = ['HVAC_CreateSketch',
                                 'HVAC_CreateLine',
                                 'HVAC_CreateSpline',
                                 'HVAC_CreateVirtualJunction',
                                 'HVAC_AddEquipment',
                                 'HVAC_EditBaseObject',
                                 'HVAC_EditDuctDirections']
                self.title = translate("HVAC", "Routing Tools")
                
            def shouldShow(self):
                # Show if there is an active document
                return is_network_active()
        
        class HVACEditObjectWatcher:
            """Shows 'Edit Object' when an object is selected."""

            def __init__(self):
                super().__init__()
                self.commands = ['HVAC_EditType',
                                 'HVAC_EditPlacement',
                                 'HVAC_EditInlineComponents',
                                 'HVAC_EditPorts',
                                 'HVAC_EditMaterial',
                                 'HVAC_ResetTypesToDefaults']
                self.title = translate("HVAC", "Edit Tools")
                
            def shouldShow(self):
                # Show if there is an active document and an object is selected
                return is_network_active() and is_object_selected()
                

        class HVACModelWatcher:
            """
            Shows Create Custom Equipment / Custom Fitting when a modelled part
            or solid that is neither yet is selected (the ports of one that is
            are edited with Edit Ports, among the Edit Tools).
            """

            def __init__(self):
                self.commands = ['HVAC_CreateEquipment',
                                 'HVAC_CreateCustomFitting']
                self.title = translate("HVAC", "Equipment and Custom Fittings")

            def shouldShow(self):
                from .ui.Command import _is_port_container, _selected_part
                if FreeCAD.ActiveDocument is None:
                    return False
                part = _selected_part()
                return part is not None and not _is_port_container(part)

        self.watchers = [
            HVACCreateWatcher(),
            HVACActivateWatcher(),
            HVACEditWatcher(),
            HVACRoutingWatcher(),
            HVACEditObjectWatcher(),
            HVACModelWatcher(),
        ]
        Gui.Control.addTaskWatcher(self.watchers)
        
    def setObservers(self):
        from .ui.Observer import DuctNetworkChangeObserver, DuctNetworkGuiEditObserver, DuctNetworkSelectionObserver

        # App document observer: property/document/undo-redo handling.
        self.hvac_change_observer = DuctNetworkChangeObserver()
        FreeCAD.addDocumentObserver(self.hvac_change_observer)

        # Gui document observer: edit-mode enter/exit events (slotInEdit/
        # slotResetEdit), registered separately since these are Gui-level
        # callbacks, not App-level ones -- see DuctNetworkGuiEditObserver.
        self.hvac_gui_edit_observer = DuctNetworkGuiEditObserver(self.hvac_change_observer)
        Gui.addDocumentObserver(self.hvac_gui_edit_observer)

        # Gui selection observer: redirects sub-element (edge/face/vertex)
        # selection AND pre-selection (hover) up to the parent
        # DuctComponent/DuctSegment object, so selection-driven UI never
        # sees a bare sub-name.
        self.hvac_selection_observer = DuctNetworkSelectionObserver()
        Gui.Selection.addObserver(self.hvac_selection_observer)

        # One-time bootstrap: pick up an edit session already in progress
        # right as these observers are first registered (no slotInEdit
        # fires for an edit that started before this observer existed) --
        # not a recurring poll, see
        # DuctNetworkChangeObserver._checkEditedBaseObject().
        QTimer.singleShot(0, self.hvac_change_observer._checkEditedBaseObject)

    def GetClassName(self):
        # This function is mandatory if this is a full Python workbench
        # This is not a template,
        # the returned string should be exactly "Gui::PythonWorkbench"
        return "Gui::PythonWorkbench"

Gui.addWorkbench(HVAC())

#https://wiki.freecadweb.org/Workbench_creation
#https://wiki.freecad.org/Translating_an_external_workbench
