# Fritzing Part Importer for Blender

This Blender addon imports Fritzing part packages (.fzpz), part XML (.fzp), and related SVGs into Blender. It extracts 3D models (OBJ/STL) from `.fzpz` zip archives and imports them into the current Blender scene, and also imports SVGs as curves.

Installation

- Copy the `fritzing_importer` folder into your Blender `scripts/addons/` or use the `Install` option in Blender's Add-ons preferences.

- Then enable the `Fritzing Part Importer` addon.

Running Tests (non-Blender environment)

- The pure-Python parsing helpers can be tested without Blender. If you have `pytest` available, run:

```bash
pytest tests/test_fzp_parser.py
```

Note: The addon code that uses `bpy` requires running inside Blender's Python. The test above validates only the ZIP/XML parsing code.

Usage

- From the 3D Viewport UI, open the `N` sidebar and find the `Fritzing` tab. Click the `Import Fritzing Part` button or go to `File > Import > Fritzing Part (.fzpz/.fzp/.svg)` and select a `.fzpz`, `.fzp` or `.svg` file.

Additional Options

- `Convert to Mesh`: When enabled, imported curves and SVGs will be converted into mesh objects automatically.
- `Join Meshes`: When enabled, imported meshes will be joined into a single object after import and conversion.
- `Extrusion Depth`: Thickness to add to imported meshes (0.0 = no extrusion). Adds a Solidify modifier to give 2D SVGs depth in the Z-axis.- `Perform Boolean Cut`: When enabled, applies boolean difference operations to cut overlapping placed parts, ensuring all parts are visible by removing intersections.
Placement Options

- `Use Placement`: When enabled, placement metadata from `.fzp` files will be applied to imported objects.
- `Placement Scale`: Conversion factor between Fritzing placement units and Blender units (default `0.001`, which treats Fritzing units as millimeters and converts to meters).

Duplication behavior

- If a `.fzp` module references the same file multiple times (same model used more than once), the importer will duplicate the base object for each module and apply placement transforms to each duplicate.

Assembly and Pins

- `Create Pins`: When enabled, the importer will create pin markers for module pins defined in the `.fzp` metadata and attach them to the placed module duplicates.
- `Pin Size` and `Pin as Mesh`: Control the pin marker type and visual size. Pin markers default to empties (SPHERE display) and can be created as small sphere meshes.

- Notes

- Only simple automatic import is implemented. The add-on tries to import `.obj/.stl` models and `.svg` files contained in `.fzpz` packages and .fzp referencing files.
- It sets `context.scene['fritzing_part']` to the part's title if found inside the `.fzp` XML metadata.
- Blender must have the standard OBJ/STL/SVG importers enabled; enable the `io_scene_obj`, `io_mesh_stl`, and `io_curve_svg` add-ons if needed.

- Limitations and Future Work

- This is a minimal implementation: no automatic assembly or placement based on metadata
- Parsing of offsets, transforms, or multiple modules isn't fully implemented
- 3D model positioning and material import could be improved

Contributing

- Feel free to submit improvements, better parsing of .fzp metadata, and support for model placement.
