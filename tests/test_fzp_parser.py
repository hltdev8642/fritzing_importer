import os
from ..lib import fzp_parser

def test_parse_simple_fzp_xml():
    xml = '<module><title>Test Part</title></module>'
    root = fzp_parser.parse_fzp_xml_string(xml)
    assert root is not None
    assert root.find('title').text == 'Test Part'

def test_list_zip_contents(tmp_path):
    # create a small zip file
    zfile = tmp_path / "test.fzpz"
    import zipfile
    with zipfile.ZipFile(zfile, 'w') as z:
        z.writestr('part.fzp', '<module><title>zip part</title></module>')
        z.writestr('model.obj', '# OBJ content')
    items = fzp_parser.list_zip_contents(str(zfile))
    assert 'part.fzp' in items
    assert 'model.obj' in items
