"""Blender integration check of OBJ transforms and the existing bake pipeline.

Uses a copying remesher stub so the test needs no user interaction.
Run: blender -b --python tests/external_roundtrip_blender.py
"""
import importlib.util
from pathlib import Path
import shutil
import tempfile
import sys
from types import SimpleNamespace

import bpy
from mathutils import Vector

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pipeline', root / 'blender_batch_remesh_bake.py')
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)

def copy_obj(executable, incoming, outgoing, quads):
    assert quads == 100
    shutil.copyfile(incoming, outgoing)

if '--real' not in sys.argv:
    pipeline.run_remesher = copy_obj
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add()
source = bpy.context.object
source.location = (4, -2, 3)
source.rotation_euler = (0.3, 0.2, 0.7)
source.scale = (2, 0.8, 1.2)
bpy.context.view_layer.update()
world_vertices = [source.matrix_world @ vertex.co for vertex in source.data.vertices]
settings = SimpleNamespace(remesher='external', external_remesher=root / 'autoremesher/autoremesher.exe',
                           target_quads=100, voxel_size=0.01, decimate_ratio=1,
                           cage_extrusion=0.02, texture_size=16, samples=1)
low, dimension, voxel, local_dimension = pipeline.remesh(source, settings)
bpy.context.view_layer.update()
if '--real' not in sys.argv:
    for vertex in low.data.vertices:
        world = low.matrix_world @ vertex.co
        assert min((world - expected).length for expected in world_vertices) < 0.0001
assert voxel is None
assert len(low.data.uv_layers) == 1
assert len(source.data.vertices) == 8
with tempfile.TemporaryDirectory(prefix='external_bake_test_') as temporary:
    temporary = Path(temporary)
    pipeline.activate(source)
    glb = temporary / 'sample.glb'
    bpy.ops.export_scene.gltf(filepath=str(glb), export_format='GLB', use_selection=True)
    settings.output = temporary / 'output'
    pipeline.process_file(glb, settings)
    assert (settings.output / 'sample/sample_remeshed.fbx').is_file()
    assert len(list((settings.output / 'sample').glob('*.png'))) == 7
print('PASS: OBJ world coordinates, UV unwrap, texture bake and FBX export')
