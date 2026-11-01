"""Run with blender -b --python tests/preserve_uv_roundtrip_blender.py."""
import importlib.util
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import bpy
from mathutils import Vector

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('converter', root / 'blender_batch_glb_to_fbx.py')
converter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(converter)

def snapshot():
    return {
        obj.name: {
            'loops': len(obj.data.loops),
            'uvs': {uv.name: [tuple(round(v, 5) for v in loop.uv) for loop in uv.data]
                    for uv in obj.data.uv_layers},
            'active': obj.data.uv_layers.active.name if obj.data.uv_layers.active else None,
        }
        for obj in bpy.context.scene.objects if obj.type == 'MESH'
    }

with tempfile.TemporaryDirectory(prefix='uv_roundtrip_') as folder:
    folder = Path(folder)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cube_add()
    cube = bpy.context.object
    cube.name = 'UvCube'
    uv0 = cube.data.uv_layers.active
    uv0.name = 'BaseUV'
    uv1 = cube.data.uv_layers.new(name='DetailUV')
    for index, loop in enumerate(uv0.data):
        loop.uv = ((index % 5) / 5, ((index * 3) % 7) / 7)
    for index, loop in enumerate(uv1.data):
        loop.uv = (((index + 1) % 7) / 7, ((index * 2) % 9) / 9)
    cube.data.uv_layers.active = uv0
    image = bpy.data.images.new('ColorGrid', width=2, height=2, alpha=True)
    image.pixels = [1, 0, 0, 1, 0, 1, 0, 1, 0, 0, 1, 1, 1, 1, 1, 1]
    image.pack()
    material = bpy.data.materials.new('WithUV')
    material.use_nodes = True
    cube.data.materials.append(material)
    tex = material.node_tree.nodes.new('ShaderNodeTexImage')
    tex.image = image
    uv_node = material.node_tree.nodes.new('ShaderNodeUVMap')
    uv_node.uv_map = 'DetailUV'
    material.node_tree.links.new(uv_node.outputs['UV'], tex.inputs['Vector'])
    material.node_tree.links.new(tex.outputs['Color'], material.node_tree.nodes.get('Principled BSDF').inputs['Base Color'])
    glb = folder / 'sample.glb'
    bpy.ops.export_scene.gltf(filepath=str(glb), export_format='GLB')

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(glb))
    imported = snapshot()
    source_images = [(image.name, [round(value, 5) for value in image.pixels[:]])
                     for image in bpy.data.images if image.type == 'IMAGE' and image.size[0] > 0]
    converter.export_file(glb, SimpleNamespace(output=folder / 'fbx', texture_format='png', no_animation=True))
    saved_image = bpy.data.images.load(str(folder / 'fbx/sample/ColorGrid.png'))
    saved_pixels = [round(value, 5) for value in saved_image.pixels[:]]
    print('SOURCE_IMAGES', source_images)
    print('SAVED_PIXELS', saved_pixels)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(folder / 'fbx/sample/sample.fbx'))
    roundtrip = snapshot()
    print('GLB_UV', json.dumps(imported, sort_keys=True))
    print('FBX_UV', json.dumps(roundtrip, sort_keys=True))
    assert set(imported) == set(roundtrip)
    for name in imported:
        assert imported[name]['loops'] == roundtrip[name]['loops']
        assert len(roundtrip[name]['uvs']) == 1
        assert roundtrip[name]['uvs']['UVMap.001'] == imported[name]['uvs']['UVMap.001']
        assert roundtrip[name]['active'] == 'UVMap.001'
    report = json.loads((folder / 'fbx/sample/report.json').read_text())
    assert not report['warnings']
    assert report['uv0_by_object'] == {'UvCube': 'UVMap.001'}
    assert any(pixels == saved_pixels for _, pixels in source_images)

    # A GLB that already has one UV must keep precisely that one.
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cube_add()
    single = bpy.context.object
    for index, loop in enumerate(single.data.uv_layers[0].data):
        loop.uv = ((index % 7) / 70, (index % 11) / 110)
    image2 = bpy.data.images.new('SmallUVTexture', width=2, height=2)
    image2.pack()
    mat2 = bpy.data.materials.new('ScaledTexture')
    mat2.use_nodes = True
    single.data.materials.append(mat2)
    tex2 = mat2.node_tree.nodes.new('ShaderNodeTexImage')
    tex2.image = image2
    map2 = mat2.node_tree.nodes.new('ShaderNodeMapping')
    map2.inputs['Scale'].default_value = (10, 10, 1)
    uv2 = mat2.node_tree.nodes.new('ShaderNodeUVMap')
    uv2.uv_map = single.data.uv_layers[0].name
    mat2.node_tree.links.new(uv2.outputs['UV'], map2.inputs['Vector'])
    mat2.node_tree.links.new(map2.outputs['Vector'], tex2.inputs['Vector'])
    mat2.node_tree.links.new(tex2.outputs['Color'], mat2.node_tree.nodes.get('Principled BSDF').inputs['Base Color'])
    one_glb = folder / 'single.glb'
    bpy.ops.export_scene.gltf(filepath=str(one_glb), export_format='GLB')
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(one_glb))
    one_imported = snapshot()
    source_material = next(mat for mat in bpy.data.materials if mat.name == 'ScaledTexture')
    source_matrix = converter.base_color_transform(source_material)
    assert source_matrix is not None
    converter.export_file(one_glb, SimpleNamespace(output=folder / 'fbx', texture_format='png', no_animation=True))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(folder / 'fbx/single/single.fbx'))
    one_roundtrip = snapshot()
    for material in bpy.data.materials:
        assert converter.base_color_transform(material) is None
    assert len(next(iter(one_roundtrip.values()))['uvs']) == 1
    original_uv = next(iter(next(iter(one_imported.values()))['uvs'].values()))
    converted_uv = next(iter(next(iter(one_roundtrip.values()))['uvs'].values()))
    for before, after in zip(original_uv, converted_uv):
        expected = source_matrix @ Vector((before[0], before[1], 0, 1))
        assert abs(expected.x - after[0]) < 1e-4
        assert abs(expected.y - after[1]) < 1e-4
print('PASS: FBX has one UV and bakes the GLB texture transform into its coordinates')
