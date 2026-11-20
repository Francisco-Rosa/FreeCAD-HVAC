import os

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs

from freecad.HVAC.library.Library import HVACLibraryRegistry

LIBRARIES_ROOT = os.path.join(os.path.dirname(__file__), "..", "freecad", "HVAC", "libraries")


def _load_registry():
    reg = HVACLibraryRegistry()
    reg.set_search_paths([LIBRARIES_ROOT])
    reg.ensure_loaded()
    return reg


def test_all_shipped_libraries_parse_without_error():
    reg = _load_registry()
    lib_ids = set(reg._libraries.keys())
    assert lib_ids == {"builtin_basic", "smacna", "samples", "fcstd_ducts"}


def test_smacna_segments_use_the_shared_segment_generator():
    # Same builder as builtin_basic: straight and curved, one generator module.
    reg = _load_registry()
    smacna = reg._libraries["smacna"]
    for type_id in ("circular_straight", "oval_straight", "rectangular_straight", "circular_generic", "circular_flex"):
        type_def = smacna.get_type(type_id)
        assert type_def is not None, type_id
        assert type_def.geometry.backend == "generator"
        assert type_def.generator_module == "shared:segments"


def test_circular_and_oval_straight_flanges_default_off():
    reg = _load_registry()
    smacna = reg._libraries["smacna"]
    for type_id in ("circular_straight", "oval_straight"):
        type_def = smacna.get_type(type_id)
        flags = {
            p.name: p.default
            for p in type_def.properties
            if p.name.startswith("ShowFlange")
        }
        assert flags == {"ShowFlange1": False, "ShowFlange2": False}


def test_rectangular_straight_flanges_default_on():
    reg = _load_registry()
    type_def = reg._libraries["smacna"].get_type("rectangular_straight")
    flags = {p.name: p.default for p in type_def.properties if p.name.startswith("ShowFlange")}
    assert flags == {"ShowFlange1": True, "ShowFlange2": True}


def test_smacna_default_construction_includes_insulation():
    reg = _load_registry()
    layers = {layer.id: layer for layer in reg._libraries["smacna"].default_construction}
    assert set(layers) == {"shape", "insulation"}
    assert layers["insulation"].roles == ["thermal_insulation"]
    assert layers["insulation"].default_material_role == "thermal_insulation"


def test_all_smacna_casing_types_declare_insulation():
    reg = _load_registry()
    smacna = reg._libraries["smacna"]
    for type_def in smacna.types_by_id.values():
        layer_ids = {layer.id for layer in type_def.construction}
        if "casing" not in layer_ids:
            continue
        properties = {prop.name: prop for prop in type_def.properties}
        assert "insulation" in layer_ids, type_def.id
        assert properties["InsulationThickness"].group == "Dimensions", type_def.id


def test_through_elbow_rectangular_uses_partscript_backend():
    reg = _load_registry()
    type_def = reg._libraries["smacna"].get_type("through_elbow_rectangular")
    assert type_def is not None
    assert type_def.profiles == ["Rectangular"]
    assert type_def.geometry.backend == "partscript"
    assert os.path.isfile(os.path.join(reg._libraries["smacna"].root_path, type_def.geometry.file))

    by_name = {p.name: p for p in type_def.properties}
    input_names = {
        "CenterlineRadius", "Thickness", "FlangeHeight", "FlangeThickness",
        "ShowFlange1", "ShowFlange2", "InsulationThickness", "LinerThickness", "SplitterVanes",
    }
    assert input_names == set(by_name.keys())

    for name in input_names:
        assert by_name[name].editor_mode == 0, name


def test_circular_acoustic_straight_is_a_samples_three_layer_construction():
    reg = _load_registry()
    smacna = reg._libraries["smacna"]
    samples = reg._libraries["samples"]
    assert smacna.get_type("circular_acoustic_straight") is None

    type_def = samples.get_type("circular_acoustic_straight")
    assert type_def is not None
    assert type_def.geometry.backend == "partscript"
    assert os.path.isfile(os.path.join(samples.root_path, type_def.geometry.file))

    by_id = {ldef.id: ldef for ldef in type_def.construction}
    assert set(by_id.keys()) == {"liner", "absorber", "jacket"}
    assert by_id["liner"].roles == ["flow_surface", "acoustic_liner"]
    assert by_id["absorber"].roles == ["acoustic_absorber"]
    assert by_id["jacket"].roles == ["outer_jacket", "structural_shell"]
    # Every layer's material default is explicit -- never left to fall back
    # on roles[0], since "flow_surface" (liner's own first-listed role)
    # isn't a material-bearing role the way "acoustic_liner" is.
    assert by_id["liner"].default_material_role == "acoustic_liner"
    assert by_id["absorber"].default_material_role == "acoustic_absorber"
    assert by_id["jacket"].default_material_role == "outer_jacket"

    assert type_def.selection.priority == 50


def test_samples_library_holds_all_sample_models():
    reg = _load_registry()
    samples = reg._libraries["samples"]

    rect = samples.get_type("rectangular_straight")
    assert rect is not None
    assert rect.generator_module == "segments"
    assert rect.generator_function == "build_rectangular_straight_fcstd"
    assert os.path.isfile(os.path.join(samples.root_path, "models", "rectangular_straight.FCStd"))

    acoustic = samples.get_type("circular_acoustic_straight")
    assert acoustic is not None
    assert acoustic.geometry.backend == "partscript"
    assert os.path.isfile(os.path.join(samples.root_path, acoustic.geometry.file))

    diffuser = samples.get_type("end_diffuser_static")
    assert diffuser is not None
    assert diffuser.geometry.backend == "static"
    assert os.path.isfile(os.path.join(samples.root_path, diffuser.geometry.descriptor))


def test_every_shipped_type_has_a_role_bearing_material_construction():
    reg = _load_registry()
    for library in reg.list_libraries():
        for type_def in library.types_by_id.values():
            assert type_def.construction, "{}:{}".format(library.id, type_def.id)
            assert all(layer.roles for layer in type_def.construction), (
                library.id, type_def.id
            )


def test_every_declared_layer_thickness_property_is_in_dimensions_group():
    reg = _load_registry()
    for library in reg.list_libraries():
        for type_def in library.types_by_id.values():
            properties = {p.name: p for p in type_def.properties}
            for layer in type_def.construction:
                if layer.thickness_property:
                    assert properties[layer.thickness_property].group == "Dimensions", (
                        library.id, type_def.id, layer.thickness_property
                    )
