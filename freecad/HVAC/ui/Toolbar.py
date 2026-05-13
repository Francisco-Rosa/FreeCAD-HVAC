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
from PySide import QtWidgets, QtCore, QtGui
from PySide.QtWidgets import QToolBar
from PySide.QtCore import QT_TRANSLATE_NOOP


#------------------------------------------------------------------------------
# Toolbars
#------------------------------------------------------------------------------

FloatingBaseEditToolbar = ("HVAC_BaseEditTempToolbar", ["HVAC_ReverseGeometryDirection"])

#------------------------------------------------------------------------------
# Convenience toolbar utilities
#------------------------------------------------------------------------------

def create_toolbar(toolbar_struct):
    toolbar_name, commands = toolbar_struct
    mw = Gui.getMainWindow()
    toolbar = mw.findChild(QToolBar, toolbar_name)

    if toolbar:
        return None

    toolbar = QToolBar(toolbar_name, mw)
    toolbar.setObjectName(toolbar_name)

    for cmd_name in commands:
        if cmd_name == "Separator":
            toolbar.addSeparator()
        else:
            cmd = Gui.Command.get(cmd_name)
            if cmd:
                info = cmd.getInfo()
                action = QtGui.QAction(toolbar)
                name = info.get("name", cmd_name)
                menutext = info.get("menuText", cmd_name)
                tooltip = info.get("toolTip", cmd_name)
                accel    = info.get("accel", "")
                if accel:
                    tooltip_ext = (
                        f'<b>{menutext} ({accel})</b>'
                        f'<p style="margin:6px 0">{tooltip}</p>'
                        f'<p style="margin:6px 0"><i>{name}</i></p>'
                    )
                else:
                    tooltip_ext = (
                        f'<b>{menutext}</b>'
                        f'<p style="margin:6px 0">{tooltip}</p>'
                        f'<p style="margin:6px 0"><i>{name}</i></p>'
                    )
                action.setText(menutext)
                action.setToolTip(tooltip_ext)

                pixmap = info.get("pixmap", "")
                if pixmap:
                    action.setIcon(QtGui.QIcon(pixmap))

                action.triggered.connect(
                    lambda checked=False, name=cmd_name: Gui.runCommand(name)
                )
                toolbar.addAction(action)

    mw.addToolBar(toolbar)
    toolbar.setVisible(False)
    return toolbar

def show_toolbar(toolbar_struct):
    toolbar_name, _ = toolbar_struct
    mw = Gui.getMainWindow()
    toolbar = mw.findChild(QToolBar, toolbar_name)
    if toolbar:
        toolbar.setVisible(True)

def hide_toolbar(toolbar_struct):
    toolbar_name, _ = toolbar_struct
    mw = Gui.getMainWindow()
    toolbar = mw.findChild(QToolBar, toolbar_name)
    if toolbar:
        toolbar.setVisible(False)
