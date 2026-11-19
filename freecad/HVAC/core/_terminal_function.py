# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Terminal function (ROADMAP 6.5): what an open duct end does in its system.

Each network is one system (`DuctNetwork.SystemType`). Each end junction
has `TerminalFunction`; `Auto` (the default) resolves from the system: the
balancing terminal (FlowBoundary `Auto`, where the system meets its fan or
equipment) is the `Source`, every other terminal plays the system's own
role. The resolved value goes into the node's qualifiers as
`terminal_function`, so type constraints and loss variants can read it, and
the flow solver checks the drawn air direction against it.

Whether the Source pushes air into the ducts or draws it out normally
follows the system (a supply fan pushes, every other system's fan draws).
A network connected to equipment follows the equipment port instead
(source_feeds_air): a duct from an AHU's exhaust outlet to outside is an
Exhaust network that the equipment pushes into, and its open ends are
Discharge terminals.

Plain Python, no FreeCAD.
"""

SYSTEM_TYPES = ("Supply", "Return", "Exhaust", "OutdoorAir")
TERMINAL_FUNCTIONS = ("Auto", "Supply", "Return", "Exhaust", "OutdoorAir", "Discharge", "Source")

# What a terminal of each system is, when not set: a supply outlet, a return
# inlet, an exhaust inlet, an outdoor-air intake.
_SYSTEM_TERMINAL = {"Supply": "Supply", "Return": "Return", "Exhaust": "Exhaust", "OutdoorAir": "OutdoorAir"}

# Which way air passes a terminal of each function, as the end node's
# flow_class: "exit" = air leaves the ducts there, "entry" = it comes in.
_FLOW_CLASS = {
    "Supply": "exit",  # into the room
    "Return": "entry",  # from the room, back to the equipment
    "Exhaust": "entry",  # from the room, to be thrown away
    "OutdoorAir": "entry",  # from outside
    "Discharge": "exit",  # out of the building
}


# Equipment port functions that push air into the network connected to them,
# and those that draw it out (core/Equipment.py's PORT_FUNCTIONS).
_PUSHING_PORTS = ("SupplyOutlet", "ExhaustOutlet")
_DRAWING_PORTS = ("ReturnInlet", "OutdoorAirInlet")


def source_feeds_air(system_type, equipment_port_functions=()):
    """
    True when the network's Source pushes air into its ducts, False when it
    draws air out of them. The functions of the equipment ports connected to
    the network decide when there are any (an outlet pushes, an inlet
    draws); otherwise a supply system is fed and every other drained.
    """
    functions = [str(function or "") for function in equipment_port_functions]
    if any(function in _PUSHING_PORTS for function in functions):
        return True
    if any(function in _DRAWING_PORTS for function in functions):
        return False
    return str(system_type or "Supply") == "Supply"


def _feeds(system_type, feeds):
    return source_feeds_air(system_type) if feeds is None else bool(feeds)


def system_terminal(system_type, feeds=None):
    """
    What a terminal of this system is when not set: a supply outlet, a
    return inlet, an exhaust inlet, an outdoor-air intake -- or, where the
    Source pushes air into anything but a supply system, a Discharge outlet.
    """
    system_type = str(system_type or "Supply")
    if _feeds(system_type, feeds) and system_type != "Supply":
        return "Discharge"
    return _SYSTEM_TERMINAL.get(system_type, "Supply")


def resolve(system_type, setting, flow_boundary, flow_class="", feeds=None):
    """
    The terminal function of an end node: its own setting, or (Auto) what
    its system and drawn direction imply. In a supply system the terminal
    where air comes into the ducts is the Source (the equipment feeds it)
    and every other terminal a supply outlet; in the other systems the
    terminal where air leaves the ducts is the Source (it goes to the fan)
    and the others are the system's inlets. With no known direction, a
    FlowBoundary Auto terminal (the balancing one) is the Source.

    `feeds` (see source_feeds_air) overrides which way the Source moves air;
    None means the system's usual way.
    """
    setting = str(setting or "Auto")
    if setting != "Auto":
        return setting
    system_type = str(system_type or "Supply")
    terminal = system_terminal(system_type, feeds)
    if flow_class in ("entry", "exit"):
        return "Source" if flow_class == expected_flow_class("Source", system_type, feeds) else terminal
    return "Source" if str(flow_boundary or "Auto") == "Auto" else terminal


def balancing_warning(label, function, system_type, flow_boundary):
    """
    A warning when the balancing terminal (FlowBoundary Auto, where the
    fan or equipment is) is not the system's Source, e.g. a supply
    network's equipment end drawn as an outlet; else "".
    """
    if str(flow_boundary or "") != "Auto" or function in ("", "Source"):
        return ""
    return (
        "Terminal '{}' balances the {} system (FlowBoundary Auto) but is drawn as a {} terminal; "
        "the equipment end should be drawn the other way (Edit Duct Directions)".format(label, system_type, function)
    )


def expected_flow_class(function, system_type, feeds=None):
    """
    The end-node flow_class a terminal of this function should have:
    "entry" or "exit". A `Source` feeds a supply system (air comes in from
    the equipment) and drains every other system (air goes to the fan),
    unless `feeds` says otherwise (see source_feeds_air).
    """
    if function == "Source":
        return "entry" if _feeds(system_type, feeds) else "exit"
    return _FLOW_CLASS.get(function, "")


def direction_warning(label, function, system_type, flow_class, feeds=None):
    """
    A readable warning when an end node is drawn the wrong way for its
    function, else "". Unknown directions are not judged.
    """
    expected = expected_flow_class(function, system_type, feeds)
    if not expected or flow_class not in ("entry", "exit") or flow_class == expected:
        return ""
    drawn = "an inlet" if flow_class == "entry" else "an outlet"
    wanted = "an inlet" if expected == "entry" else "an outlet"
    return (
        "Terminal '{}' ({} in a {} system) is drawn as {} of the duct system but should be {}; "
        "reverse its duct with Edit Duct Directions, or change its TerminalFunction".format(
            label, function, system_type, drawn, wanted
        )
    )
