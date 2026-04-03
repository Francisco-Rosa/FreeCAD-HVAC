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
from PySide.QtCore import QT_TRANSLATE_NOOP
translate = FreeCAD.Qt.translate

from . import hvaclib

Gui.addLanguagePath(hvaclib.get_language_base_path())
Gui.updateLocale()


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
        from . import Command
        
        self.watchers = []
        self.observers = []
        
        self.toolbar_commands = ['HVAC_CreateDuctNetwork',
                                'HVAC_ActivateDuctNetwork',
                                'HVAC_ModifyDuctNetwork',
                                'HVAC_EditNetworkTypeDefaults',
                                "Separator",
                                'HVAC_CreateSketch',
                                'HVAC_CreateLine',
                                'HVAC_CreateSpline',
                                'HVAC_EditBaseObject',
                                'HVAC_CreateVirtualJunction',
                                "Separator",
                                'HVAC_EditType',
                                'HVAC_EditPlacement',
                                'HVAC_ResetTypesToDefaults'
                                ]

        self.submenu_commands = ['HVAC_CreateDuctNetwork',
                                'HVAC_ActivateDuctNetwork',
                                'HVAC_ModifyDuctNetwork',
                                'HVAC_EditNetworkTypeDefaults',
                                "Separator",
                                'HVAC_CreateSketch',
                                'HVAC_CreateLine',
                                'HVAC_CreateSpline',
                                'HVAC_EditBaseObject',
                                'HVAC_CreateVirtualJunction',
                                "Separator",
                                'HVAC_EditType',
                                'HVAC_EditPlacement',
                                'HVAC_ResetTypesToDefaults'
                                ]

        self.contextmenu_commands = ['HVAC_CreateDuctNetwork',
                                'HVAC_ActivateDuctNetwork',
                                'HVAC_ModifyDuctNetwork',
                                'HVAC_EditNetworkTypeDefaults',
                                "Separator",
                                'HVAC_CreateSketch',
                                'HVAC_CreateLine',
                                'HVAC_CreateSpline',
                                'HVAC_EditBaseObject',
                                'HVAC_CreateVirtualJunction',
                                "Separator",
                                'HVAC_EditType',
                                'HVAC_EditPlacement',
                                'HVAC_ResetTypesToDefaults'
                                ]

        self.appendMenu(QT_TRANSLATE_NOOP("Workbench", "HVAC"), self.submenu_commands)
        self.appendToolbar(QT_TRANSLATE_NOOP("Workbench", "HVAC"), self.toolbar_commands)

    def Activated(self):
        """This function is executed whenever the workbench is activated"""
        FreeCAD.Console.PrintMessage(translate("InitGui","HVAC - Workbench loaded") + "\n")
        self.refreshWatchers()
        self.setObservers()
        FreeCAD.Console.PrintMessage(translate("InitGui","HVAC - Workbench - Watchers set") + "\n")
        return

    def Deactivated(self):
        """This function is executed whenever the workbench is deactivated"""
        try:
            Gui.Control.clearTaskWatcher()
            for obs in self.observers:
                Gui.Selection.rmvObserver(obj)
        except Exception:
            pass
        self.watchers = []
        self.observers = []
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
                                "HVAC_EditNetworkTypeDefaults"]
                self.title = translate("HVAC", "Network")
                
            def shouldShow(self):
                # Show if there is an active document and no object is selected
                return is_network_active()
                
        class HVACRoutingWatcher:
            """Shows 'Routing Tools' when an HVAC Network is active."""

            def __init__(self):
                super().__init__()
                self.commands = ['HVAC_CreateSketch',
                                 'HVAC_CreateLine',
                                 'HVAC_CreateSpline',
                                 'HVAC_EditBaseObject',
                                 'HVAC_CreateVirtualJunction']
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
                                 'HVAC_ResetTypesToDefaults']
                self.title = translate("HVAC", "Edit Tools")
                
            def shouldShow(self):
                # Show if there is an active document and an object is selected
                return is_network_active() and is_object_selected()
                

        self.watchers = [
            HVACCreateWatcher(),
            HVACActivateWatcher(),
            HVACEditWatcher(),
            HVACRoutingWatcher(),
            HVACEditObjectWatcher(),
        ]
        Gui.Control.addTaskWatcher(self.watchers)
        
    def setObservers(self):
        # Observer for watching duct network changes
        from .Observer import DuctNetworkChangeObserver
        hvac_change_observer = DuctNetworkChangeObserver()
        
        self.observers = [hvac_change_observer]
        for obs in self.observers:
            FreeCAD.addDocumentObserver(obs)

    def GetClassName(self):
        # This function is mandatory if this is a full Python workbench
        # This is not a template,
        # the returned string should be exactly "Gui::PythonWorkbench"
        return "Gui::PythonWorkbench"

Gui.addWorkbench(HVAC())

#https://wiki.freecadweb.org/Workbench_creation
#https://wiki.freecad.org/Translating_an_external_workbench
