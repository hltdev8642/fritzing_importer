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
