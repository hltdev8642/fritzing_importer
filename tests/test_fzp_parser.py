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

def test_extract_modules_and_pins_from_fzp_string():
    xml = '''
        <module id="M1" file="res/part.obj">
            <pin id="1" x="10" y="20" />
            <pin id="2" position="30,40" />
        </module>
        <module id="M2" file="res/board.obj">
            <pad id="A" x="1.5" y="2.5" />
        </module>
        '''
    result = fzp_parser.extract_modules_and_pins_from_fzp_string(xml)
    assert len(result) == 2
    assert any(m['module_id'] == 'M1' and len(m['pins']) == 2 for m in result)
    assert any(m['module_id'] == 'M2' and len(m['pins']) == 1 for m in result)

def test_pin_rotation_parsing():
    xml = '''
        <module id="M3" file="res/part.obj">
            <pin id="1" x="0" y="0" rotation="90" />
        </module>
        '''
    result = fzp_parser.extract_modules_and_pins_from_fzp_string(xml)
    assert len(result) == 1
    pins = result[0]['pins']
    assert pins[0]['rotation'] == 90.0

def test_parse_transform_string():
    from ..lib import fzp_parser
    t = fzp_parser.parse_transform_string('translate(10,20) rotate(30) scale(2)')
    assert t['translate'] == (10.0, 20.0)
    assert t['rotate'] == 30.0
    assert t['scale'] == 2.0
    # multiple translates accumulate
    t2 = fzp_parser.parse_transform_string('translate(1,2) translate(3,4)')
    assert t2['translate'] == (4.0, 6.0)
