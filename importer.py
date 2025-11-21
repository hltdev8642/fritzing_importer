import bpy
from bpy.props import StringProperty, BoolProperty, FloatProperty
from bpy_extras.io_utils import ImportHelper
import os
import tempfile
import zipfile
from .lib import fzp_parser

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

def _duplicate_object(obj, collection=None):
    try:
        new_obj = obj.copy()
        if obj.data:
            new_obj.data = obj.data.copy()
        # Clear animation data
        try:
            new_obj.animation_data_clear()
        except Exception:
            pass
        # Link to collection
        if collection is None:
            collection = bpy.context.collection
        collection.objects.link(new_obj)
        return new_obj
    except Exception as e:
        print(f"Duplicating object failed: {e}")
        return None

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
    return (lx, ly, lz), rot

def import_fzp_from_zip(filepath, context, convert_to_mesh=False, join=False, use_placement=True, placement_scale=0.001):
    if not zipfile.is_zipfile(filepath):
        raise RuntimeError("Not a zip archive")
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
    svgs_map = {}
    for src, dest in extracted_svgs.items():
        new_objs = _get_new_objects_after_call(_import_svg_from_file, dest)
        if new_objs:
            key = os.path.basename(src).lower()
            svgs_map[key] = new_objs
            if convert_to_mesh:
                _convert_objects_to_mesh(new_objs, join=join)
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
                    for module in root.findall('.//module'):
                        fileattr = module.get('file') or module.get('url')
                        if not fileattr:
                            continue
                        name = os.path.basename(fileattr).lower()
                        transform = _get_transform_from_module(module)
                        if transform is None:
                            continue
                        (mx, my, mz), rot = transform
                        mx *= placement_scale
                        my *= placement_scale
                        mz *= placement_scale
                        # find base objects matching model or svg name
                        base_list = models_map.get(name) or svgs_map.get(name)
                        if not base_list:
                            continue
                        placed_objs = []
                        for base in base_list:
                            dup = _duplicate_object(base, collection=context.collection)
                            if dup:
                                placed_objs.append(dup)
                                _apply_transform_to_object(dup, loc=(mx, my, mz), rot_z=rot)
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

def import_fzp_file(filepath, context, convert_to_mesh=False, join=False, use_placement=True, placement_scale=0.001):
    # plain xml fzp file - typically references images / models by relative path
    if not os.path.exists(filepath):
        raise RuntimeError("File not found")
    with open(filepath, 'r', encoding='utf-8') as f:
        data = f.read()
    root = _parse_fzp_xml(data)
    if root is None:
        return
    # locate any referenced models or svgs in same folder
    basedir = os.path.dirname(filepath)
    models_map = {}
    svgs_map = {}
    for elem in root.findall('.//module'):
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
            # apply placement for this module
            if use_placement:
                transform = _get_transform_from_module(elem)
                if transform is not None:
                    (mx, my, mz), rot = transform
                    mx *= placement_scale
                    my *= placement_scale
                    mz *= placement_scale
                    base_list = models_map.get(os.path.basename(fileattr).lower()) or svgs_map.get(os.path.basename(fileattr).lower())
                    if base_list:
                        placed_objs = []
                        for base in base_list:
                            dup = _duplicate_object(base, collection=context.collection)
                            if dup:
                                placed_objs.append(dup)
                                _apply_transform_to_object(dup, loc=(mx, my, mz), rot_z=rot)
                        if join and placed_objs:
                            bpy.ops.object.select_all(action='DESELECT')
                            for o in placed_objs:
                                o.select_set(True)
                            bpy.context.view_layer.objects.active = placed_objs[0]
                            try:
                                bpy.ops.object.join()
                            except Exception as e:
                                print(f"Join failed for placed objects: {e}")

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

    def execute(self, context):
        path = self.filepath
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext == '.fzpz':
                import_fzp_from_zip(path, context, convert_to_mesh=self.convert_to_mesh, join=self.join_meshes, use_placement=self.use_placement, placement_scale=self.placement_scale)
            elif ext == '.fzp':
                import_fzp_file(path, context, convert_to_mesh=self.convert_to_mesh, join=self.join_meshes, use_placement=self.use_placement, placement_scale=self.placement_scale)
            elif ext == '.svg':
                new_objs = _get_new_objects_after_call(_import_svg_from_file, path)
                if self.convert_to_mesh and new_objs:
                    _convert_objects_to_mesh(new_objs, join=self.join_meshes)
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

def menu_func_import(self, context):
    self.layout.operator(ImportFritzingPart.bl_idname, text="Fritzing Part (.fzpz/.fzp/.svg)")

def register_menu():
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)

def unregister_menu():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
