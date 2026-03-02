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

"""This module implements HVAC duct design."""

import os
import FreeCAD
import FreeCADGui as Gui
import freecad.HVAC.DuctsDialog as DuctsDialog

from PySide.QtCore import QT_TRANSLATE_NOOP
translate = FreeCAD.Qt.translate

#=================================================
# A. Main classes
#=================================================

class Ducts:

    """Visualize and configure HVAC ducts in FreeCAD's 3D view."""

    def __init__(self,obj):
        obj.Proxy = self
        self.setProperties(obj)

    def setProperties(self,obj):
        """Gives the object properties to HVAC ducts."""
        pass


class DuctsViewProvider:

    """A View Provider for the HVAC ducts object"""

    def __init__(self, obj):
        obj.Proxy = self

    def getIcon(self):
        __dir__ = os.path.dirname(__file__)
        return __dir__ + '/icons/DuctsIcon.svg'


class CreateDucts:

    """Create HVAC ducts."""

    def QT_TRANSLATE_NOOP(self, text):
        return text

    def GetResources(self):
        __dir__ = os.path.dirname(__file__)
        return {'Pixmap': __dir__ + '/icons/CreateDuctsIcon.svg',
                'MenuText': QT_TRANSLATE_NOOP('CreateDucts', 'Create HVAC ducts'),
                'ToolTip': QT_TRANSLATE_NOOP('CreateDucts', 'Instructions')}

    def IsActive(self):
        if Gui.ActiveDocument:
            return True
        else:
            return False

    def Activated(self):
        activated_create_ducts(self)


class ModifyDucts:

    """Modify HVAC ducts."""

    def QT_TRANSLATE_NOOP(self, text):
        return text

    def GetResources(self):
        __dir__ = os.path.dirname(__file__)
        return {'Pixmap': __dir__ + '/icons/ModifyDuctsIcon.svg',
                'MenuText': QT_TRANSLATE_NOOP('ModifyDucts', 'Modify HVAC ducts'),
                'ToolTip': QT_TRANSLATE_NOOP('ModifyDucts',  'Instructions')}

    def IsActive(self):
        if Gui.ActiveDocument:
            try:
                FreeCAD.ActiveDocument.findObjects(Name = "Ducts")[0].Name
                return True
            except:
                pass
        else:
            return False

    def Activated(self):
        activated_modify_ducts(self)

class DeleteDucts:

    """Delete a selected Sun Analysis."""

    def QT_TRANSLATE_NOOP(self, text):
        return text

    def GetResources(self):
        __dir__ = os.path.dirname(__file__)
        return {'Pixmap': __dir__ + '/icons/DeleteDuctsIcon.svg',
                'MenuText': QT_TRANSLATE_NOOP('DeleteDucts', 'Delete HVAC ducts'),
                'ToolTip': QT_TRANSLATE_NOOP('DeleteDucts', 'Instructions')}

    def IsActive(self):
        if Gui.ActiveDocument:
            try:
                FreeCAD.ActiveDocument.findObjects(Name = "Ducts")[0].Name
                return True
            except:
                pass
        else:
            return False

    def Activated(self):
        activated_delete_ducts(self)

def activated_create_ducts(self):
    """Create the Ducts"""
    folder = FreeCAD.ActiveDocument.addObject(
             'App::DocumentObjectGroupPython',
             'Ducts')
    Ducts(folder)
    DuctsViewProvider(folder.ViewObject)
    print("Ducts created!")
    DuctsDialog.open_ducts_configuration()
    FreeCAD.ActiveDocument.recompute()

def activated_modify_ducts(self):
    """Modify the HVAC duct object selected"""
    pass

def activated_delete_ducts(self):
    """Delete the HVAC duct object selected"""
    pass


#=================================================
# B. General functions
#=================================================



#=================================================
# C. Commands
#=================================================

if FreeCAD.GuiUp:
    FreeCAD.Gui.addCommand('CreateDucts', CreateDucts())
    FreeCAD.Gui.addCommand('ModifyDucts', ModifyDucts())
    FreeCAD.Gui.addCommand('DeleteDucts', DeleteDucts())
