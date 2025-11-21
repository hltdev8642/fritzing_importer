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

def test_parse_position_string():
    from ..lib import fzp_parser
    assert fzp_parser.parse_position_string('12.0, 34.5') == (12.0, 34.5, 0.0)
    assert fzp_parser.parse_position_string('1,2,3') == (1.0, 2.0, 3.0)
    assert fzp_parser.parse_position_string(None) is None
