import bpy
from bpy.props import StringProperty
from bpy_extras.io_utils import ImportHelper
import os
import tempfile
import zipfile
from .lib import fzp_parser

def _import_obj_from_file(filepath):
    try:
        bpy.ops.import_scene.obj(filepath=filepath)
        return True
    except Exception as e:
        print(f"OBJ import failed: {e}")
    return False

def _import_stl_from_file(filepath):
    try:
        bpy.ops.import_mesh.stl(filepath=filepath)
        return True
    except Exception as e:
        print(f"STL import failed: {e}")
    return False

def _import_svg_from_file(filepath):
    try:
        bpy.ops.import_curve.svg(filepath=filepath)
        return True
    except Exception as e:
        print(f"SVG import failed: {e}")
    return False

def _parse_fzp_xml(text):
    return fzp_parser.parse_fzp_xml_string(text)

def import_fzp_from_zip(filepath, context):
    if not zipfile.is_zipfile(filepath):
        raise RuntimeError("Not a zip archive")
    # Use the fzp_parser helpers
    extracted_models = fzp_parser.extract_files_by_extensions(filepath, ['.obj', '.stl'])
    extracted_svgs = fzp_parser.extract_files_by_extensions(filepath, ['.svg'])
    fzp_files = [n for n in fzp_parser.list_zip_contents(filepath) if n.lower().endswith('.fzp')]
    for src, dest in extracted_models.items():
        if dest.lower().endswith('.obj'):
            _import_obj_from_file(dest)
        elif dest.lower().endswith('.stl'):
            _import_stl_from_file(dest)
    for src, dest in extracted_svgs.items():
        _import_svg_from_file(dest)
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

def import_fzp_file(filepath, context):
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
    for elem in root.findall('.//module'):
        fileattr = elem.get('file') or elem.get('url')
        if not fileattr:
            continue
        target = os.path.join(basedir, fileattr)
        if os.path.exists(target):
            if target.lower().endswith('.obj'):
                _import_obj_from_file(target)
            elif target.lower().endswith('.stl'):
                _import_stl_from_file(target)
            elif target.lower().endswith('.svg'):
                _import_svg_from_file(target)

class ImportFritzingPart(bpy.types.Operator, ImportHelper):
    bl_idname = "import_scene.fritzing_part"
    bl_label = "Import Fritzing Part (.fzpz/.fzp/.svg)"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".fzpz"
    filter_glob: StringProperty(default='*.fzpz;*.fzp;*.svg', options={'HIDDEN'})

    def execute(self, context):
        path = self.filepath
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext == '.fzpz':
                import_fzp_from_zip(path, context)
            elif ext == '.fzp':
                import_fzp_file(path, context)
            elif ext == '.svg':
                _import_svg_from_file(path)
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
        layout.operator(ImportFritzingPart.bl_idname, text="Import Fritzing Part (.fzpz/.fzp/.svg)")

def menu_func_import(self, context):
    self.layout.operator(ImportFritzingPart.bl_idname, text="Fritzing Part (.fzpz/.fzp/.svg)")

def register_menu():
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)

def unregister_menu():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
