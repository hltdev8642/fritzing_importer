import bpy
from bpy.props import StringProperty, BoolProperty, FloatProperty
from bpy_extras.io_utils import ImportHelper
import os
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from .lib import fzp_parser

_ADDON_ID = __package__ if __package__ else 'fritzing_importer'

def _debug(msg):
    try:
        prefs = bpy.context.preferences.addons[_ADDON_ID].preferences
        if getattr(prefs, 'enable_debug', False):
            print(f"[FritzingImport DEBUG] {msg}")
    except Exception:
        pass

def _import_obj_from_file(filepath):
    try:
        return bpy.ops.import_scene.obj(filepath=filepath)
    except Exception as e:
        print(f"OBJ import failed: {e}")
    return {'CANCELLED'}

def _import_stl_from_file(filepath):
    try:
        return bpy.ops.import_mesh.stl(filepath=filepath)
    except Exception as e:
        print(f"STL import failed: {e}")
    return {'CANCELLED'}

def _import_svg_from_file(filepath):
    try:
        return bpy.ops.import_curve.svg(filepath=filepath)
    except Exception as e:
        print(f"SVG import failed: {e}")
    return {'CANCELLED'}

def _get_new_objects_after_call(callable_fn, *args, **kwargs):
    before = set(o.name for o in bpy.data.objects)
    callable_fn(*args, **kwargs)
    after = set(o.name for o in bpy.data.objects)
    new_names = after - before
    return [bpy.data.objects[n] for n in new_names]

def _convert_objects_to_mesh(objects, join=False):
    # Convert curve-like objects to meshes
    imported_meshes = []
    # Store original selection
    prev_active = bpy.context.view_layer.objects.active
    prev_selected = [o for o in bpy.context.selected_objects]
    # Ensure Object Mode
    try:
        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
    except Exception:
        pass
    # Convert each object individually
    for obj in objects:
        if obj.type in {'CURVE', 'FONT', 'SURFACE', 'META'}:
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            try:
                bpy.ops.object.convert(target='MESH')
            except Exception as e:
                print(f"Conversion to mesh failed for {obj.name}: {e}")
        # after conversion or if already a mesh, collect
    # Restore selection
    bpy.ops.object.select_all(action='DESELECT')
    for o in prev_selected:
        o.select_set(True)
    bpy.context.view_layer.objects.active = prev_active
    # If join requested, join new mesh objects
    if join:
        mesh_objs = [o for o in objects if o.type in {'MESH', 'CURVE', 'FONT', 'SURFACE', 'META'}]
        # Convert curve objects that weren't converted by op above
        mesh_objs = [o for o in bpy.context.view_layer.objects if o.name in [x.name for x in objects] and o.type == 'MESH']
        if len(mesh_objs) > 1:
            bpy.ops.object.select_all(action='DESELECT')
            for o in mesh_objs:
                o.select_set(True)
            bpy.context.view_layer.objects.active = mesh_objs[0]
            try:
                bpy.ops.object.join()
            except Exception as e:
                print(f"Join meshes failed: {e}")

def _apply_transform_to_object(obj, loc=None, rot_z=None, scale=None):
    # Apply location, rotation (around Z), and uniform scale
    try:
        if loc is not None:
            obj.location.x = loc[0]
            obj.location.y = loc[1]
            if len(loc) > 2:
                obj.location.z = loc[2]
        if rot_z is not None:
            # ensure Euler
            obj.rotation_mode = 'XYZ'
            import math
            obj.rotation_euler[2] = math.radians(rot_z)
        if scale is not None:
            obj.scale = (scale, scale, scale)
    except Exception as e:
        print(f"Applying transform failed on {obj.name}: {e}")

def _apply_extrusion_to_objects(objects, depth, bevel_depth=0.0):
    # Add solidify (and optional bevel) modifiers to mesh objects
    if depth is None or depth <= 0:
        return
    for obj in objects:
        if obj is None:
            continue
        if obj.type != 'MESH':
            continue
        try:
            _debug(f"Adding Solidify modifier to {obj.name} (thickness={depth})")
            mod = obj.modifiers.new(name="Solidify", type='SOLIDIFY')
            mod.thickness = depth
            mod.offset = 0.00
            if bevel_depth and bevel_depth > 0:
                _debug(f"Adding Bevel modifier to {obj.name} (width={bevel_depth})")
                bevel_mod = obj.modifiers.new(name="Bevel", type='BEVEL')
                bevel_mod.width = bevel_depth
                bevel_mod.segments = 4
                bevel_mod.profile = 0.5
        except Exception as e:
            print(f"Failed to add extrusion modifiers to {obj.name}: {e}")

def _apply_boolean_cut(placed_objects):
    # Sort by Z location ascending (lower Z first, assuming "below")
    placed_objects.sort(key=lambda o: o.location.z)
    mesh_objects = [o for o in placed_objects if o.type == 'MESH']
    if len(mesh_objects) < 2:
        return
    try:
        for i, obj in enumerate(mesh_objects[1:], 1):  # start from second
            _debug(f"Boolean cut iteration {i}: target={obj.name}, cutters={[c.name for c in mesh_objects[:i]]}")
            cutters = mesh_objects[:i]
            if not cutters:
                continue
            # Duplicate cutters
            bpy.ops.object.select_all(action='DESELECT')
            for c in cutters:
                c.select_set(True)
            bpy.ops.object.duplicate()
            duplicated_cutters = [o for o in bpy.context.selected_objects if o != obj]
            if len(duplicated_cutters) > 1:
                bpy.context.view_layer.objects.active = duplicated_cutters[0]
                bpy.ops.object.join()
            cutter = bpy.context.active_object
            # Apply boolean difference to obj
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            mod = obj.modifiers.new(name="Boolean", type='BOOLEAN')
            mod.operation = 'DIFFERENCE'
            mod.object = cutter
            bpy.ops.object.modifier_apply(modifier="Boolean")
            # Delete cutter
            bpy.ops.object.select_all(action='DESELECT')
            cutter.select_set(True)
            bpy.ops.object.delete()
            _debug(f"Boolean cut applied to {obj.name}; cutter deleted")
    except Exception as e:
        print(f"Boolean cut failed: {e}")

def _create_pin_marker(location=(0,0,0), name='pin', size=0.002, as_mesh=False, collection=None):
    # Create an empty or small sphere mesh to represent a pin
    try:
        if collection is None:
            collection = bpy.context.collection
        if not as_mesh:
            e = bpy.data.objects.new(name, None)
            e.empty_display_type = 'SPHERE'
            e.empty_display_size = size
            e.location = location
            collection.objects.link(e)
            return e
        # create a UV sphere mesh
        mesh = bpy.data.meshes.new(f"{name}_mesh")
        bm = None
        try:
            import bmesh
            bm = bmesh.new()
            bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=8, diameter=size)
            bm.to_mesh(mesh)
        finally:
            if bm:
                bm.free()
        obj = bpy.data.objects.new(name, mesh)
        obj.location = location
        collection.objects.link(obj)
        return obj
    except Exception as e:
        print(f"Failed to create pin marker: {e}")
        return None

class FritzingImporterPreferences(bpy.types.AddonPreferences):
    bl_idname = _ADDON_ID
    enable_debug: BoolProperty(
        name="Enable Debug Output",
        description="When enabled, the addon prints debug messages to the terminal",
        default=False,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, 'enable_debug')

def _create_pins_for_module(module_elem, placed_objects, context, create_pins=False, pin_size=0.002, pin_as_mesh=False, placement_scale=0.001):
    if not create_pins:
        return
    # module_elem may be an Element; use tostring to parse pins via the fzp_parser testable function
    try:
        xml_text = ET.tostring(module_elem, encoding='unicode')
    except Exception:
        return
    modules = fzp_parser.extract_modules_and_pins_from_fzp_string(xml_text)
    if not modules:
        return
    pins = modules[0].get('pins', [])
    for pin in pins:
            px, py, pz = pin['position']
            local_loc = (px * placement_scale, py * placement_scale, pz * placement_scale)
            for o in placed_objects:
                # create marker with default location, then parent and set local location
                marker = _create_pin_marker(location=(0,0,0), name=f"{o.name}_pin_{pin.get('id','')}", size=pin_size, as_mesh=pin_as_mesh, collection=context.collection)
                if marker:
                    try:
                        marker.parent = o
                        marker.location = local_loc
                        rot_value = pin.get('rotation') or pin.get('angle')
                        if rot_value is not None:
                            try:
                                import math
                                marker.rotation_mode = 'XYZ'
                                marker.rotation_euler[2] = math.radians(rot_value)
                            except Exception:
                                pass
                    except Exception:
                        pass

def _parse_fzp_xml(text):
    return fzp_parser.parse_fzp_xml_string(text)

def _get_transform_from_module(module_elem):
    # Checks for common attributes in Fritzing .fzp module elements: x/y/z, rotation, position, transform
    x = module_elem.get('x') or module_elem.get('cx')
    y = module_elem.get('y') or module_elem.get('cy')
    z = module_elem.get('z')
    rotation = module_elem.get('rotation') or module_elem.get('angle')
    # check nested <position> or attribute 'position'
    pos_attr = module_elem.get('position')
    transform_attr = module_elem.get('transform')
    if not (x and y) and pos_attr:
        # try to parse like "12.3,45.6"
        try:
            parts = pos_attr.split(',')
            if len(parts) >= 2:
                x = parts[0].strip()
                y = parts[1].strip()
                if len(parts) >= 3:
                    z = parts[2].strip()
        except Exception:
            pass
    if x is None or y is None:
        # try to find nested elements with coordinates
        for child in module_elem:
            if child.tag.lower().endswith('position'):
                try:
                    cx = child.get('x') or child.get('cx')
                    cy = child.get('y') or child.get('cy')
                    if cx and cy:
                        x = x or cx
                        y = y or cy
                except Exception:
                    pass
    # convert to floats
    try:
        lx = float(x) if x is not None else None
        ly = float(y) if y is not None else None
        lz = float(z) if z is not None else 0.0
    except Exception:
        lx, ly, lz = None, None, 0.0
    try:
        rot = float(rotation) if rotation is not None else None
    except Exception:
        rot = None
    if lx is None or ly is None:
        return None
    # If module has a transform attribute, apply translation/rotation from it
    if transform_attr:
        t = fzp_parser.parse_transform_string(transform_attr)
        trans = t.get('translate')
        if trans and (lx is not None and ly is not None):
            lx += trans[0]
            ly += trans[1]
        rot_from_transform = t.get('rotate')
        if rot_from_transform is not None:
            rot = rot_from_transform
    return (lx, ly, lz), rot

def import_fzp_from_zip(filepath, context, convert_to_mesh=False, join=False, use_placement=True, placement_scale=0.001, create_pins=False, pin_size=0.002, pin_as_mesh=False, extrusion_depth=0.0, bevel_depth=0.0, perform_boolean_cut=False, z_step=0.01, z_step_in_blender_units=False, min_z_step=1e-5):
    if not zipfile.is_zipfile(filepath):
        raise RuntimeError("Not a zip archive")
    _debug(f"import_fzp_from_zip: filepath={filepath} convert_to_mesh={convert_to_mesh} join={join} placement_scale={placement_scale} extrusion_depth={extrusion_depth} bevel={bevel_depth} z_step={z_step} z_step_blender={z_step_in_blender_units} min_z_step={min_z_step}")
    # Use the fzp_parser helpers
    extracted_models = fzp_parser.extract_files_by_extensions(filepath, ['.obj', '.stl'])
    extracted_svgs = fzp_parser.extract_files_by_extensions(filepath, ['.svg'])
    fzp_files = [n for n in fzp_parser.list_zip_contents(filepath) if n.lower().endswith('.fzp')]
    models_map = {}
    for src, dest in extracted_models.items():
        new_objs = []
        if dest.lower().endswith('.obj'):
            new_objs = _get_new_objects_after_call(_import_obj_from_file, dest)
        elif dest.lower().endswith('.stl'):
            new_objs = _get_new_objects_after_call(_import_stl_from_file, dest)
        if new_objs:
            key = os.path.basename(src).lower()
            models_map[key] = new_objs
            if convert_to_mesh:
                _convert_objects_to_mesh(new_objs, join=join)
                _apply_extrusion_to_objects(new_objs, extrusion_depth, bevel_depth)
    svgs_map = {}
    for src, dest in extracted_svgs.items():
        new_objs = _get_new_objects_after_call(_import_svg_from_file, dest)
        if new_objs:
            key = os.path.basename(src).lower()
            svgs_map[key] = new_objs
            if convert_to_mesh:
                _convert_objects_to_mesh(new_objs, join=join)
                _apply_extrusion_to_objects(new_objs, extrusion_depth, bevel_depth)
    # Get metadata for fzp files
    for fzp in fzp_files:
        with zipfile.ZipFile(filepath, 'r') as z:
            with z.open(fzp) as f:
                data = f.read().decode('utf-8')
                root = _parse_fzp_xml(data)
                if root is None:
                    continue
                title = root.findtext('title') or os.path.basename(fzp)
                context.scene['fritzing_part'] = title
                # apply placement metadata for each module if requested
                if use_placement:
                    placed_all = []
                    for idx, module in enumerate(root.findall('.//module')):
                        fileattr = module.get('file') or module.get('url')
                        if not fileattr:
                            continue
                        name = os.path.basename(fileattr).lower()
                        _debug(f"Module[{idx}] name={name} fileattr={fileattr}")
                        transform = _get_transform_from_module(module)
                        if transform is None:
                            continue
                        (mx, my, mz), rot = transform
                        mx *= placement_scale
                        my *= placement_scale
                        mz *= placement_scale
                        # calculate per-step value (either blender units or fritzing units scaled by placement_scale)
                        step_val = z_step if z_step_in_blender_units else (z_step * placement_scale)
                        if min_z_step and step_val < min_z_step:
                            step_val = min_z_step
                        mz += idx * step_val
                        # find base objects matching model or svg name
                        base_list = models_map.get(name) or svgs_map.get(name)
                        if not base_list:
                            continue
                        placed_objs = []
                        for base_idx, base in enumerate(base_list):
                            dup = _duplicate_object(base, collection=context.collection)
                            if dup:
                                placed_objs.append(dup)
                                step_val = z_step if z_step_in_blender_units else (z_step * placement_scale)
                                if min_z_step and step_val < min_z_step:
                                    step_val = min_z_step
                                final_mz = mz + (base_idx * step_val)
                                _debug(f"Placing base {base_idx} of module {name} at z={final_mz}")
                                _apply_transform_to_object(dup, loc=(mx, my, final_mz), rot_z=rot)
                                # optionally create pins for this module
                                _create_pins_for_module(module, [dup], context, create_pins=create_pins, pin_size=pin_size, pin_as_mesh=pin_as_mesh, placement_scale=placement_scale)
                        # If join requested, optionally join placed_objs
                        if join and placed_objs:
                            bpy.ops.object.select_all(action='DESELECT')
                            for o in placed_objs:
                                o.select_set(True)
                            bpy.context.view_layer.objects.active = placed_objs[0]
                            try:
                                bpy.ops.object.join()
                            except Exception as e:
                                print(f"Join failed for placed objects: {e}")
                            # after joining, placed_objs[0] remains as the joined object; we may want to create pins relative to that
                            if create_pins:
                                # create pins relative to joined object using the module element
                                                _create_pins_for_module(module, [bpy.context.view_layer.objects.active], context, create_pins=create_pins, pin_size=pin_size, pin_as_mesh=pin_as_mesh, placement_scale=placement_scale)
                            placed_all.append(bpy.context.view_layer.objects.active)
                        else:
                            placed_all.extend(placed_objs)
                    # After all placements, apply boolean cut if requested
                    if perform_boolean_cut:
                        _apply_boolean_cut(placed_all)

def import_fzp_file(filepath, context, convert_to_mesh=False, join=False, use_placement=True, placement_scale=0.001, create_pins=False, pin_size=0.002, pin_as_mesh=False, extrusion_depth=0.0, bevel_depth=0.0, perform_boolean_cut=False, z_step=0.01, z_step_in_blender_units=False, min_z_step=1e-5):
    # plain xml fzp file - typically references images / models by relative path
    if not os.path.exists(filepath):
        raise RuntimeError("File not found")
    _debug(f"import_fzp_file: filepath={filepath} convert_to_mesh={convert_to_mesh} join={join} placement_scale={placement_scale} extrusion_depth={extrusion_depth} bevel={bevel_depth} z_step={z_step} z_step_blender={z_step_in_blender_units} min_z_step={min_z_step}")
    with open(filepath, 'r', encoding='utf-8') as f:
        data = f.read()
    root = _parse_fzp_xml(data)
    if root is None:
        return
    # locate any referenced models or svgs in same folder
    basedir = os.path.dirname(filepath)
    models_map = {}
    svgs_map = {}
    placed_all = []
    for idx, elem in enumerate(root.findall('.//module')):
        fileattr = elem.get('file') or elem.get('url')
        if not fileattr:
            continue
        target = os.path.join(basedir, fileattr)
        if os.path.exists(target):
            new_objs = []
            if target.lower().endswith('.obj'):
                new_objs = _get_new_objects_after_call(_import_obj_from_file, target)
            elif target.lower().endswith('.stl'):
                new_objs = _get_new_objects_after_call(_import_stl_from_file, target)
            elif target.lower().endswith('.svg'):
                new_objs = _get_new_objects_after_call(_import_svg_from_file, target)
            if new_objs:
                key = os.path.basename(fileattr).lower()
                if target.lower().endswith(('.obj', '.stl')):
                    models_map[key] = new_objs
                elif target.lower().endswith('.svg'):
                    svgs_map[key] = new_objs
                if convert_to_mesh and new_objs:
                    _convert_objects_to_mesh(new_objs, join=join)
                    _apply_extrusion_to_objects(new_objs, extrusion_depth, bevel_depth)
            # apply placement for this module
            if use_placement:
                transform = _get_transform_from_module(elem)
                if transform is not None:
                    (mx, my, mz), rot = transform
                    mx *= placement_scale
                    my *= placement_scale
                    mz *= placement_scale
                    # compute step_val (scaled by placement_scale unless z_step_in_blender_units)
                    step_val = z_step if z_step_in_blender_units else (z_step * placement_scale)
                    if min_z_step and step_val < min_z_step:
                        step_val = min_z_step
                    mz += idx * step_val
                    base_list = models_map.get(os.path.basename(fileattr).lower()) or svgs_map.get(os.path.basename(fileattr).lower())
                    if base_list:
                        placed_objs = []
                        for base_idx, base in enumerate(base_list):
                            dup = _duplicate_object(base, collection=context.collection)
                            if dup:
                                placed_objs.append(dup)
                                final_mz = mz + (base_idx * step_val)
                                _apply_transform_to_object(dup, loc=(mx, my, final_mz), rot_z=rot)
                                # create pins for this module duplicate
                                _create_pins_for_module(elem, [dup], context, create_pins=create_pins, pin_size=pin_size, pin_as_mesh=pin_as_mesh, placement_scale=placement_scale)
                        if join and placed_objs:
                            bpy.ops.object.select_all(action='DESELECT')
                            for o in placed_objs:
                                o.select_set(True)
                            bpy.context.view_layer.objects.active = placed_objs[0]
                            try:
                                bpy.ops.object.join()
                            except Exception as e:
                                print(f"Join failed for placed objects: {e}")
                            if create_pins:
                                _create_pins_for_module(elem, [bpy.context.view_layer.objects.active], context, create_pins=create_pins, pin_size=pin_size, pin_as_mesh=pin_as_mesh, placement_scale=placement_scale)
                            placed_all.append(bpy.context.view_layer.objects.active)
                        else:
                            placed_all.extend(placed_objs)
    # After all placements, apply boolean cut if requested
    if perform_boolean_cut:
        _apply_boolean_cut(placed_all)

class ImportFritzingPart(bpy.types.Operator, ImportHelper):
    bl_idname = "import_scene.fritzing_part"
    bl_label = "Import Fritzing Part (.fzpz/.fzp/.svg)"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".fzpz"
    filter_glob: StringProperty(default='*.fzpz;*.fzp;*.svg', options={'HIDDEN'})
    convert_to_mesh: BoolProperty(
        name="Convert to Mesh",
        description="Convert imported curves/SVGs to mesh objects",
        default=True,
    )
    join_meshes: BoolProperty(
        name="Join Meshes",
        description="Join imported meshes into a single object after conversion",
        default=False,
    )
    use_placement: BoolProperty(
        name="Use Placement",
        description="Apply placement metadata from .fzp files to position imported objects",
        default=True,
    )
    placement_scale: FloatProperty(
        name="Placement Scale",
        description="Scale conversion factor for placement coordinates (Fritzing units to Blender units)",
        default=0.001,
        min=0.0,
    )
    create_pins: BoolProperty(
        name="Create Pins",
        description="Create pin markers (empties or small meshes) for module pins",
        default=True,
    )
    pin_size: FloatProperty(
        name="Pin Size",
        description="Size of pin marker in Blender units when instantiating pins",
        default=0.002,
        min=0.0,
    )
    pin_as_mesh: BoolProperty(
        name="Pin as Mesh",
        description="Create pins as small sphere meshes instead of empties",
        default=False,
    )
    extrusion_depth: FloatProperty(
        name="Extrusion Depth",
        description="Thickness to add to imported meshes (0.0 = no extrusion)",
        default=0.0,
        min=0.0,
        max=10.0,
    )
    bevel_depth: FloatProperty(
        name="Bevel Depth",
        description="Bevel width to add to extruded meshes (0.0 = no bevel)",
        default=0.0,
        min=0.0,
        max=1.0,
    )
    perform_boolean_cut: BoolProperty(
        name="Perform Boolean Cut",
        description="Apply boolean difference operations to cut overlapping parts for visibility",
        default=False,
    )
    z_step: FloatProperty(
        name="Z Step",
        description="Incremental Z offset applied per module in import order (in Fritzing units; scaled by Placement Scale)",
        default=0.01,
        min=0.0,
    )
    z_step_in_blender_units: BoolProperty(
        name="Z Step in Blender Units",
        description="If set, Z Step is treated as Blender units directly instead of scaling by Placement Scale",
        default=False,
    )
    min_z_step: FloatProperty(
        name="Minimum Z Step",
        description="Minimum per-step Z offset in Blender units; ensures tiny offsets are bumped to a visible minimum",
        default=1e-5,
        min=0.0,
    )
    # Backwards-compat alias for the operator-level convenience; not used for the addon-pref toggle

    def execute(self, context):
        path = self.filepath
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext == '.fzpz':
                import_fzp_from_zip(path, context, convert_to_mesh=self.convert_to_mesh, join=self.join_meshes, use_placement=self.use_placement, placement_scale=self.placement_scale, create_pins=self.create_pins, pin_size=self.pin_size, pin_as_mesh=self.pin_as_mesh, extrusion_depth=self.extrusion_depth, bevel_depth=self.bevel_depth, perform_boolean_cut=self.perform_boolean_cut, z_step=self.z_step, z_step_in_blender_units=self.z_step_in_blender_units, min_z_step=self.min_z_step)
            elif ext == '.fzp':
                import_fzp_file(path, context, convert_to_mesh=self.convert_to_mesh, join=self.join_meshes, use_placement=self.use_placement, placement_scale=self.placement_scale, create_pins=self.create_pins, pin_size=self.pin_size, pin_as_mesh=self.pin_as_mesh, extrusion_depth=self.extrusion_depth, bevel_depth=self.bevel_depth, perform_boolean_cut=self.perform_boolean_cut, z_step=self.z_step, z_step_in_blender_units=self.z_step_in_blender_units, min_z_step=self.min_z_step)
            elif ext == '.svg':
                new_objs = _get_new_objects_after_call(_import_svg_from_file, path)
                if self.convert_to_mesh and new_objs:
                    _convert_objects_to_mesh(new_objs, join=self.join_meshes)
                    _apply_extrusion_to_objects(new_objs, self.extrusion_depth, self.bevel_depth)
                    # calculate step value based on units selection and min threshold
                    step_val = self.z_step if self.z_step_in_blender_units else (self.z_step * self.placement_scale)
                    if self.min_z_step and step_val < self.min_z_step:
                        step_val = self.min_z_step
                    # apply z-step ordering for standalone SVG imports per path/object
                    for idx, o in enumerate(new_objs):
                        try:
                            _debug(f"SVG import: placing object {o.name} at z offset {idx * step_val}")
                            o.location.z += idx * step_val
                        except Exception:
                            pass
            else:
                self.report({'WARNING'}, f"Unsupported extension: {ext}")
                return {'CANCELLED'}
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        self.report({'INFO'}, "Fritzing part import complete")
        return {'FINISHED'}

class FritzingImporterPanel(bpy.types.Panel):
    bl_label = "Fritzing Importer"
    bl_idname = "VIEW3D_PT_fritzing_importer"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Fritzing'

    def draw(self, context):
        layout = self.layout
        op = layout.operator(ImportFritzingPart.bl_idname, text="Import Fritzing Part (.fzpz/.fzp/.svg)")
        layout.prop(op, 'convert_to_mesh')
        layout.prop(op, 'join_meshes')
        layout.prop(op, 'use_placement')
        layout.prop(op, 'placement_scale')
        layout.prop(op, 'create_pins')
        layout.prop(op, 'pin_size')
        layout.prop(op, 'pin_as_mesh')
        layout.prop(op, 'extrusion_depth')
        layout.prop(op, 'bevel_depth')
        layout.prop(op, 'perform_boolean_cut')
        layout.prop(op, 'z_step')
        layout.prop(op, 'z_step_in_blender_units')
        layout.prop(op, 'min_z_step')

def menu_func_import(self, context):
    self.layout.operator(ImportFritzingPart.bl_idname, text="Fritzing Part (.fzpz/.fzp/.svg)")

def register_menu():
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)

def unregister_menu():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
