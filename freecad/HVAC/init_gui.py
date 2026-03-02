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
import freecad.HVAC.hvaclib as hvaclib

from PySide.QtCore import QT_TRANSLATE_NOOP
translate = FreeCAD.Qt.translate

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
        import freecad.HVAC.Ducts

        self.toolbar_commands = ['CreateDucts',
                                'ModifyDucts',
                                'DeleteDucts',
                                ]

        self.submenu_commands = ['CreateDucts',
                                 'ModifyDucts',
                                 'DeleteDucts',
                                 ]

        self.contextmenu_commands = ['CreateDucts',
                                    'ModifyDucts',
                                    'DeleteDucts',
                                    ]

        self.appendMenu(QT_TRANSLATE_NOOP("Workbench", "HVAC tools"), self.submenu_commands)
        self.appendToolbar(QT_TRANSLATE_NOOP("Workbench", "HVAC tools"), self.toolbar_commands)

    def Activated(self):
        """This function is executed whenever the workbench is activated"""
        FreeCAD.Console.PrintMessage(translate(
                                     "InitGui","HVAC Workbench loaded") + "\n")
        return

    def Deactivated(self):
        """This function is executed whenever the workbench is deactivated"""
        return

    def ContextMenu(self, recipient):
        """This function is executed whenever the user right-clicks on screen"""
        self.appendContextMenu(QT_TRANSLATE_NOOP("Workbench", "HVAC tools"), self.toolbar_commands)

    def GetClassName(self):
        # This function is mandatory if this is a full Python workbench
        # This is not a template,
        # the returned string should be exactly "Gui::PythonWorkbench"
        return "Gui::PythonWorkbench"

Gui.addWorkbench(HVAC())

#https://wiki.freecadweb.org/Workbench_creation
#https://wiki.freecad.org/Translating_an_external_workbench
