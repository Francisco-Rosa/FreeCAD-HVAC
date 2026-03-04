# -*- coding: utf-8 -*-
#***************************************************************************
#*                                                                         *
#*   Copyright (c) 2026 Francisco Rosa                                     *
#*                                                                         *
#*   Portions of code based on kbwbe's A2Plus Workbench                    *
#*                                                                         *
#*   This program is free software; you can redistribute it and/or modify  *
#*   it under the terms of the GNU Lesser General Public License (LGPL)    *
#*   as published by the Free Software Foundation; either version 2 of     *
#*   the License, or (at your option) any later version.                   *
#*   for detail see the LICENCE text file.                                 *
#*                                                                         *
#*   This program is distributed in the hope that it will be useful,       *
#*   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
#*   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
#*   GNU Library General Public License for more details.                  *
#*                                                                         *
#*   You should have received a copy of the GNU Library General Public     *
#*   License along with this program; if not, write to the Free Software   *
#*   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
#*   USA                                                                   *
#*                                                                         *
#***************************************************************************

import os, platform
import FreeCAD
import FreeCADGui as Gui
from PySide import QtGui
translate = FreeCAD.Qt.translate
preferences = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/HVAC")

WORKBENCH_STATE = 'DEFAULT'
DUCT_NETWORK_CONTEXT_KEY = "hvac_ductnetwork"

path_hvac = os.path.dirname(__file__)

#------------------------------------------------------------------------------
# State management
#------------------------------------------------------------------------------
def activeHVACNetwork():
    doc = Gui.ActiveDocument

    if doc is None or doc.ActiveView is None:
        return None
    active_network = doc.ActiveView.getActiveObject(DUCT_NETWORK_CONTEXT_KEY)
    
    if active_network:
        return active_network

def allHVACNetworks():
    from freecad.HVAC.DuctNetwork import DuctNetwork
    doc = Gui.ActiveDocument

    hvac_networks = None
    if doc is None:
        return None
    if hasattr(doc.Document, "Objects"):
        hvac_networks = [n for n in doc.Document.Objects if hasattr(n, "Proxy") and isinstance(n.Proxy, DuctNetwork)]
    
    return hvac_networks
    
def selectedHVACNetworks():
    from freecad.HVAC.DuctNetwork import DuctNetwork
    objs = Gui.Selection.getSelection()
    if objs:
        filtered = [o for o in objs if hasattr(o, "Proxy") and isinstance(o.Proxy, DuctNetwork)]
        return filtered
    return None
    
def refreshState():
    QtGui.QApplication.processEvents()

#------------------------------------------------------------------------------
# Detect the operating system...
#------------------------------------------------------------------------------
tmp = platform.system()
tmp = tmp.upper()
tmp = tmp.split(' ')

OPERATING_SYSTEM = 'UNKNOWN'
if "WINDOWS" in tmp:
    OPERATING_SYSTEM = "WINDOWS"
elif "LINUX" in tmp:
    OPERATING_SYSTEM = "LINUX"
else:
    OPERATING_SYSTEM = "OTHER"

#------------------------------------------------------------------------------
# Return paths...
#------------------------------------------------------------------------------

def get_module_path():
    """Function returns HVAC module path."""
    s_path = os.path.dirname(os.path.abspath(__file__))
    return s_path

def get_file_path(file_name):
    """Function returns HVAC module path."""
    s_path = os.path.join(get_module_path(), file_name)
    return s_path

def get_language_base_path():
    """Function return path for localization files."""
    s_path = os.path.join(get_module_path(), "translations")
    return s_path

def get_icon_base_path():
    """Function return path for icon files."""
    s_path = os.path.join(get_module_path(), "icons")
    return s_path

def get_icon_path(icon_name: str):
    """Function returns path for icon file."""
    s_path = os.path.join(get_icon_base_path(), icon_name)
    return s_path

#------------------------------------------------------------------------------
# Miscellaneous
#------------------------------------------------------------------------------

def get_version():
    """
    Function return A2Plus version for storing in assembly file
    """

    hvac_path = get_module_path()
    try:
        metadata = FreeCAD.Metadata(os.path.join(hvac_path, 'package.xml'))
        return metadata.Version
    except:
        tx = ' ?? '
        return tx
