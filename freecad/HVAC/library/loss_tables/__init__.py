# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Digitised fitting-loss tables from the SMACNA "Duct Design Tables and
Charts" chapter (Tables 14-9 to 14-18), one module per table group.

Every table is a `table.LossTable` registered in `table.ALL_TABLES` under
the source's own id ("14-10B", ...). Values are kept exactly as printed,
including the few that look like misprints. Nothing in this package imports
FreeCAD.
"""
