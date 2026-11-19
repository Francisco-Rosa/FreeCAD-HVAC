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

"""
IFC export of duct networks (ROADMAP design 6.8).

- `mapping.py` (pure): which IFC class, predefined type, covering and system
  type an HVAC object exports as, and its property sets.
- `plan.py` (pure): ports, port connections, systems, type objects and
  coverings worked out from plain network data.
- `collect.py` (FreeCAD): reads networks into the plain data `plan.py` takes.
- `writer.py` (ifcopenshell): adds the plan to a file the BIM exporter wrote.
- `export.py` (FreeCAD): the whole export, run by the HVAC_ExportIFC command.
"""
