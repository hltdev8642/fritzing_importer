import zipfile
import os
import tempfile
import xml.etree.ElementTree as ET

def parse_fzp_xml_string(text):
    try:
        root = ET.fromstring(text)
        return root
    except ET.ParseError:
        return None

def list_zip_contents(filepath):
    if not zipfile.is_zipfile(filepath):
        raise RuntimeError("Not a zip file")
    with zipfile.ZipFile(filepath, 'r') as z:
        return z.namelist()

def extract_files_by_extensions(filepath, extensions):
    if not zipfile.is_zipfile(filepath):
        raise RuntimeError("Not a zip file")
    extracted = {}
    tempdir = tempfile.mkdtemp(prefix='fritzing_')
    with zipfile.ZipFile(filepath, 'r') as z:
        for name in z.namelist():
            if any(name.lower().endswith(ext) for ext in extensions):
                dest = os.path.join(tempdir, os.path.basename(name))
                with z.open(name) as src, open(dest, 'wb') as dst:
                    dst.write(src.read())
                extracted[name] = dest
    return extracted

def parse_position_string(pos_str):
    # Parse a comma separated string 'x,y[,z]' to floats
    if pos_str is None:
        return None
    try:
        parts = [p.strip() for p in pos_str.split(',')]
        nums = [float(p) for p in parts if p != '']
        if len(nums) == 2:
            return (nums[0], nums[1], 0.0)
        if len(nums) >= 3:
            return (nums[0], nums[1], nums[2])
        return None
    except Exception:
        return None

def parse_transform_string(transform_str):
    """Parse an SVG 'transform' attribute into translate, rotate, scale components.

    Returns a dict: {'translate': (x, y), 'rotate': angle_degrees or None, 'scale': float or None}
    Supports 'translate(x[,y])', 'rotate(angle)' and 'scale(s[,sy])'.
    If multiple transforms present, they are composed in order; this function returns the cumulative translate, rotate, scale
    by performing a simplified composition (translation accumulates, rotation overrides to last rotate value, scale multiplies).
    """
    if not transform_str:
        return {'translate': None, 'rotate': None, 'scale': None}
    import re
    trans = None
    rotate = None
    scale = None
    # find all function calls
    pattern = re.compile(r'(translate|rotate|scale)\s*\(([^)]+)\)')
    for m in pattern.finditer(transform_str):
        fn = m.group(1)
        args = m.group(2)
        parts = re.split('[,\s]+', args.strip())
        parts = [p for p in parts if p != '']
        try:
            if fn == 'translate':
                x = float(parts[0]) if len(parts) >= 1 else 0.0
                y = float(parts[1]) if len(parts) >= 2 else 0.0
                if trans is None:
                    trans = (x, y)
                else:
                    trans = (trans[0] + x, trans[1] + y)
            elif fn == 'rotate':
                # only take the rotation angle (cx,cy ignored)
                angle = float(parts[0]) if len(parts) >= 1 else 0.0
                rotate = angle
            elif fn == 'scale':
                sx = float(parts[0]) if len(parts) >= 1 else 1.0
                sy = float(parts[1]) if len(parts) >= 2 else sx
                if scale is None:
                    scale = sx
                else:
                    scale = scale * sx
        except Exception:
            continue
    return {'translate': trans, 'rotate': rotate, 'scale': scale}

def extract_modules_and_pins_from_fzp_string(xml_text):
    """Parse Fritzing .fzp XML text and return a list of modules with their pins.

    Returns a list of dicts: { 'module_id': str, 'file': str, 'pins': [ { 'id': str, 'position': (x,y,z), 'rotation': float }, ... ] }
    """
    root = parse_fzp_xml_string(xml_text)
    if root is None:
        return []
    modules = []
    for module in root.findall('.//module'):
        mfile = module.get('file') or module.get('url') or ''
        mid = module.get('id') or module.get('name') or mfile
        pins = []
        # look for common pin elements
        for pin_elem in module.findall('.//pin') + module.findall('.//pad') + module.findall('.//connector'):
            pid = pin_elem.get('id') or pin_elem.get('name') or pin_elem.get('index') or pin_elem.get('label') or ''
            x = pin_elem.get('x') or pin_elem.get('cx')
            y = pin_elem.get('y') or pin_elem.get('cy')
            z = pin_elem.get('z')
            pos_attr = pin_elem.get('position')
            transform_str = pin_elem.get('transform')
            if (x is None or y is None) and pos_attr:
                pos = parse_position_string(pos_attr)
                if pos:
                    x, y, z = pos[0], pos[1], pos[2]
            # fallback: nested <position> elements
            if (x is None or y is None):
                for c in pin_elem:
                    if c.tag.lower().endswith('position'):
                        px = c.get('x') or c.get('cx')
                        py = c.get('y') or c.get('cy')
                        if px and py:
                            x = x or px
                            y = y or py
                            z = z or c.get('z')
            try:
                fx = float(x) if x is not None else None
                fy = float(y) if y is not None else None
                fz = float(z) if z is not None else 0.0
            except Exception:
                fx, fy, fz = None, None, 0.0
            # apply transform attribute if present (translate/rotate/scale)
            if transform_str and (fx is not None and fy is not None):
                t = parse_transform_string(transform_str)
                trans = t.get('translate')
                if trans:
                    fx += trans[0]
                    fy += trans[1]
            # rotation
            rot = pin_elem.get('rotation') or pin_elem.get('angle')
            try:
                r = float(rot) if rot is not None else None
            except Exception:
                r = None
            if fx is not None and fy is not None:
                pins.append({ 'id': pid, 'position': (fx, fy, fz), 'rotation': r })
        modules.append({ 'module_id': mid, 'file': mfile, 'pins': pins })
    return modules
