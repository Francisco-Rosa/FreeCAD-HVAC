# FreeCAD-HVAC

FreeCAD-HVAC is a FreeCAD workbench for creating and managing HVAC duct networks. The current implementation focuses on a basic but usable duct-network workflow built around route geometry, automatic connectivity parsing, and library-driven generation of duct segments and fittings.

## User workflow

The intended workflow is:

1. Create a **Duct Network**
2. Add base routing geometry using sketches or line-based objects
3. Let the parser extract connectivity from that geometry
4. Automatically generate duct segments and junctions/fittings.
5. Modify duct/ fitting parameters directly on the generated segments and junctions/fittings.
6. For editing routing the base geometry can be edited as needed and the generated segments and junctions/fittings are synchronised automatically.

This approach keeps the modeling process parametric and reduces the need to rebuild duct geometry manually after every layout change.

Duct segments and fittings are generated from a library of reusable
definitions rather than being hard-coded. Three libraries ship today:
`builtin_basic` (minimal generic types), `smacna` (SMACNA-based sheet-metal
types, meant for day-to-day modeling), and `samples` (reference-only
examples). New fitting types, profiles, and parameters can be added as
library data without touching the core addon: see
[Writing an HVAC library](docs/library-guide.md).

Once a network is modeled, built-in tools can calculate airflow pressure
drop across it and propose duct sizes (constant velocity, constant friction
rate, or static regain).

Each generated segment/fitting can also carry a casing and an insulation
material, assigned from FreeCAD's own native material database (built-in
materials, this addon's own SMACNA-relevant cards, other addons', or
user-defined) — there is no separate HVAC material list.

## Screenshots
<img width="1418" height="815" alt="Screenshot from 2026-03-27 03-37-15" src="https://github.com/user-attachments/assets/70b94757-0161-4c5d-b9fd-5b85a57cfde7" />
<img width="1418" height="815" alt="Screenshot from 2026-03-27 03-35-18" src="https://github.com/user-attachments/assets/052a4662-84c8-417a-a198-d021a9b4eba3" />
<img width="1418" height="815" alt="Screenshot from 2026-03-27 03-36-14" src="https://github.com/user-attachments/assets/6fafb9ee-c38f-48df-a6a3-4a32c91a7a1e" />

## Design goals

- [x] Duct routing module (may use the same module or reuse components for piping also).
- [ ] Detailing of ducts and fittings for rectangular/ circular/ oval ducts.
- [ ] Add BIM data
- [ ] Standard library of commonly used air side HVAC components like Diffusers, grills, registers, dampers, intake and exhaust accessories, VAV units, AHUs etc.
- [x] Pressure drop calculation based on terminal flow rates and static pressure calculation for nodes.
- [x] Automatic sizing module based on constant friction drop, constant velocity, static regain methods.
- [ ] Add additional duct classes (custom profile ducts) and detailing like insulation, duct supports, flanges etc.
- [ ] Add support for defining piping.

## Status

Basic duct creation functionality is now reasonably in place. The project already supports the main framework required for:

- defining duct routes
- parsing connectivity
- generating duct segments
- generating junction/fitting objects
- organizing library-based element definitions
- calculating airflow pressure drop across a network
- automatic duct sizing by constant velocity, constant friction rate, or static regain
- assigning casing/insulation materials from FreeCAD's native material database

This provides a solid base for further development, including richer fitting logic, validation tools, and future analysis capabilities.

### Known geometry limitations

The `builtin_basic` `branch_wye_radius` fitting is experimental and its
geometry generation is incomplete. It can build circular, rectangular, and
oval wyes across a broad range of sizes and radii, but some combinations of
profile dimensions, branch angles, and radii may still fail in Open CASCADE's
sweep or boolean operations. The generator may increase an undersized radius
or move the main split plane to keep the layout geometrically feasible. When a
build fails, the generated component retains the previous geometry and reports
the current failure in its read-only `GeometryError` property and the FreeCAD
Report view. With a wall thickness (the hollow build) it currently fails on
round and rectangular ducts, so automatic selection uses `branch_wye_mitered`
for a wye and the radius wye is a manual choice.

## For developers

For how the addon is put together internally (module responsibilities,
sync/execute flow, the airflow/sizing solvers, the library type-selection
system) see [`ARCHITECTURE.md`](ARCHITECTURE.md). Coding/testing rules for
this repository are in [`AGENTS.md`](AGENTS.md).
