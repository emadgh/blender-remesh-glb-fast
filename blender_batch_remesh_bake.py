"""Batch GLB remesh, UV unwrap, PBR bake and export. Blender 4.3+.

Run: blender -b --python blender_batch_remesh_bake.py -- --input DIR --output DIR
"""
import argparse
from array import array
import json
import sys
import traceback
from pathlib import Path

import bpy


CHANNELS = {
    "basecolor": ("Base Color", (0.8, 0.8, 0.8, 1.0)),
    "roughness": ("Roughness", (0.5, 0.5, 0.5, 1.0)),
    "metallic": ("Metallic", (0.0, 0.0, 0.0, 1.0)),
    "emission": ("Emission Color", (0.0, 0.0, 0.0, 1.0)),
    "alpha": ("Alpha", (1.0, 1.0, 1.0, 1.0)),
}


def args():
    raw = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", required=True, type=Path, help="GLB file or folder")
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--format", choices=("glb", "fbx", "both"), default="glb")
    p.add_argument("--texture-size", type=int, default=1024)
    p.add_argument("--voxel-size", type=float, default=0.005,
                   help="Fraction of each object's longest local dimension")
    p.add_argument("--decimate-ratio", type=float, default=1.0)
    p.add_argument("--cage-extrusion", type=float, default=0.02,
                   help="Fraction of each object's longest local dimension")
    p.add_argument("--samples", type=int, default=16)
    p.add_argument("--recursive", action="store_true")
    a = p.parse_args(raw)
    a.input = a.input.resolve()
    a.output = a.output.resolve()
    if a.texture_size < 16 or not 0 < a.voxel_size < 1 or not 0 < a.decimate_ratio <= 1:
        p.error("Invalid texture size, voxel size or decimate ratio")
    return a


def activate(*objects, active=None):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = active or objects[-1]


def image(name, size, fill, noncolor=False):
    img = bpy.data.images.new(name, width=size, height=size, alpha=True)
    img.generated_color = fill
    if noncolor:
        img.colorspace_settings.name = "Non-Color"
    return img


def save_image(img, path):
    img.filepath_raw = str(path)
    img.file_format = "PNG"
    img.save()


def principal(mat):
    if not mat or not mat.use_nodes:
        return None
    return next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)


def emission_copy(original, channel):
    """Copy source graph and route one Principled input to emission output."""
    label, default = CHANNELS[channel]
    mat = original.copy() if original else bpy.data.materials.new("default_source")
    mat.use_nodes = True
    tree = mat.node_tree
    shader = principal(mat)
    output = next((n for n in tree.nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output), None)
    if output is None:
        output = tree.nodes.new("ShaderNodeOutputMaterial")
    emit = tree.nodes.new("ShaderNodeEmission")
    if shader and label in shader.inputs:
        socket = shader.inputs[label]
        if socket.is_linked:
            tree.links.new(socket.links[0].from_socket, emit.inputs["Color"])
        else:
            value = socket.default_value
            if isinstance(value, (int, float)):
                emit.inputs["Color"].default_value = (value, value, value, 1)
            else:
                emit.inputs["Color"].default_value = value
    else:
        emit.inputs["Color"].default_value = default
    tree.links.new(emit.outputs["Emission"], output.inputs["Surface"])
    return mat


def remesh(source, a):
    low = source.copy()
    low.data = source.data.copy()
    bpy.context.collection.objects.link(low)
    low.name = source.name + "_remesh"
    activate(low)
    # Voxel remesh drops all UV and material assignments. Originals stay intact for baking.
    dimension = max(source.dimensions)
    if dimension <= 0:
        raise ValueError("Zero-size mesh")
    low.data.remesh_voxel_size = max(dimension * a.voxel_size, 0.000001)
    bpy.ops.object.voxel_remesh()
    if not low.data.polygons:
        raise ValueError("Voxel remesh produced an empty mesh; reduce --voxel-size")
    if a.decimate_ratio < 1:
        mod = low.modifiers.new("Reduce", "DECIMATE")
        mod.ratio = a.decimate_ratio
        bpy.ops.object.modifier_apply(modifier=mod.name)
    low.data.materials.clear()
    for uv in list(low.data.uv_layers):
        low.data.uv_layers.remove(uv)
    low.data.uv_layers.new(name="BakedUV")
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(island_margin=0.01)
    bpy.ops.object.mode_set(mode="OBJECT")
    return low, dimension


def bake_map(source, low, originals, channel, img, extrusion):
    temporary = []
    if channel in CHANNELS:
        for original in originals:
            temporary.append(emission_copy(original, channel))
        source.data.materials.clear()
        for mat in temporary:
            source.data.materials.append(mat)
    mat = low.active_material
    tex = mat.node_tree.nodes.get("BAKE_TARGET")
    tex.image = img
    mat.node_tree.nodes.active = tex
    activate(source, low, active=low)
    try:
        bpy.ops.object.bake(type="EMIT" if channel in CHANNELS else channel.upper(),
                            use_selected_to_active=True, cage_extrusion=extrusion,
                            margin=8, use_clear=True)
    finally:
        if channel in CHANNELS:
            source.data.materials.clear()
            for original in originals:
                source.data.materials.append(original)
            for copy in temporary:
                bpy.data.materials.remove(copy)


def material_from_images(imgs):
    mat = bpy.data.materials.new("Baked PBR")
    mat.use_nodes = True
    tree = mat.node_tree
    tree.nodes.clear()
    out = tree.nodes.new("ShaderNodeOutputMaterial")
    bsdf = tree.nodes.new("ShaderNodeBsdfPrincipled")
    tree.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    def tex(key):
        node = tree.nodes.new("ShaderNodeTexImage")
        node.image = imgs[key]
        node.label = key
        return node

    base = tex("basecolor")
    tree.links.new(base.outputs["Color"], bsdf.inputs["Base Color"])
    tree.links.new(base.outputs["Alpha"], bsdf.inputs["Alpha"])
    pixels = imgs["basecolor"].pixels
    if any(pixels[i] < 0.999 for i in range(3, len(pixels), 4)):
        mat.surface_render_method = "DITHERED"
    orm = tex("orm")
    separate = tree.nodes.new("ShaderNodeSeparateColor")
    tree.links.new(orm.outputs["Color"], separate.inputs["Color"])
    tree.links.new(separate.outputs["Green"], bsdf.inputs["Roughness"])
    tree.links.new(separate.outputs["Blue"], bsdf.inputs["Metallic"])
    normal = tex("normal")
    normal_map = tree.nodes.new("ShaderNodeNormalMap")
    tree.links.new(normal.outputs["Color"], normal_map.inputs["Color"])
    tree.links.new(normal_map.outputs["Normal"], bsdf.inputs["Normal"])
    emission = tex("emission")
    tree.links.new(emission.outputs["Color"], bsdf.inputs["Emission Color"])
    bsdf.inputs["Emission Strength"].default_value = 1.0
    # Exporter recognizes the unconnected glTF Material Output group's Occlusion input.
    group = bpy.data.node_groups.get("glTF Material Output")
    if group is None:
        group = bpy.data.node_groups.new("glTF Material Output", "ShaderNodeTree")
        group.interface.new_socket(name="Occlusion", in_out="INPUT", socket_type="NodeSocketColor")
    hook = tree.nodes.new("ShaderNodeGroup")
    hook.node_tree = group
    tree.links.new(orm.outputs["Color"], hook.inputs["Occlusion"])
    return mat


def pack_channels(imgs, size):
    count = size * size
    def values(key):
        data = array('f', [0.0]) * (count * 4)
        imgs[key].pixels.foreach_get(data)
        return data
    base = values("basecolor")
    alpha = values("alpha")
    ao = values("ao")
    rough = values("roughness")
    metal = values("metallic")
    for i in range(count):
        j = i * 4
        base[j + 3] = alpha[j]
    imgs["basecolor"].pixels.foreach_set(base)
    orm = image("orm", size, (1, 0.5, 0, 1), True)
    pixels = array('f', [0.0]) * (count * 4)
    for i in range(count):
        j = i * 4
        pixels[j] = ao[j]
        pixels[j + 1] = rough[j]
        pixels[j + 2] = metal[j]
        pixels[j + 3] = 1.0
    orm.pixels.foreach_set(pixels)
    imgs["orm"] = orm
    for key in ("alpha", "ao", "roughness", "metallic"):
        bpy.data.images.remove(imgs.pop(key))


def process_file(path, a):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(path))
    sources = [o for o in bpy.context.scene.objects if o.type == "MESH" and o.data.polygons]
    if not sources:
        raise ValueError("No mesh in GLB")
    bpy.context.scene.render.engine = "CYCLES"
    bpy.context.scene.cycles.samples = a.samples
    out = a.output / path.stem
    out.mkdir(parents=True, exist_ok=True)
    lows = []
    report = {"source": str(path), "objects": []}
    for index, source in enumerate(sources):
        if source.data.users > 1:
            source.data = source.data.copy()
        originals = [m if m else bpy.data.materials.new("empty_slot") for m in source.data.materials]
        # Unassigned material slots still need a source material during channel baking.
        if not originals:
            blank = bpy.data.materials.new("default")
            blank.diffuse_color = (0.8, 0.8, 0.8, 1)
            originals = [blank]
            source.data.materials.append(blank)
        low, dimension = remesh(source, a)
        bake_mat = bpy.data.materials.new("Bake Target")
        bake_mat.use_nodes = True
        bake_tex = bake_mat.node_tree.nodes.new("ShaderNodeTexImage")
        bake_tex.name = "BAKE_TARGET"
        low.data.materials.append(bake_mat)
        safe_name = source.name.replace('/', '_').replace(chr(92), '_')
        prefix = f"{index:03d}_{safe_name}"
        imgs = {}
        for key in (*CHANNELS, "ao", "normal"):
            fill = CHANNELS[key][1] if key in CHANNELS else ((1, 1, 1, 1) if key == "ao" else (0.5, 0.5, 1, 1))
            img = image(prefix + "_" + key, a.texture_size, fill, key not in ("basecolor", "emission"))
            bake_map(source, low, originals, key, img, dimension * a.cage_extrusion)
            imgs[key] = img
            # GLB is self-contained; sidecar PNGs are only needed by FBX workflows.
            if a.format in ("fbx", "both"):
                save_image(img, out / f"{prefix}_{key}.png")
        pack_channels(imgs, a.texture_size)
        if a.format in ("fbx", "both"):
            save_image(imgs["basecolor"], out / f"{prefix}_basecolor.png")
            save_image(imgs["orm"], out / f"{prefix}_orm.png")
        low.data.materials.clear()
        low.data.materials.append(material_from_images(imgs))
        lows.append(low)
        report["objects"].append({"name": source.name, "source_faces": len(source.data.polygons),
                                  "output_faces": len(low.data.polygons), "texture_prefix": prefix})
    activate(*lows)
    if a.format in ("glb", "both"):
        # Pack image datablocks before export so the GLB exporter always reads
        # their pixels from Blender and writes them into the GLB BIN chunk.
        for img in bpy.data.images:
            if img.source == "GENERATED" and not img.packed_file:
                img.pack()
        bpy.ops.export_scene.gltf(filepath=str(out / (path.stem + "_remeshed.glb")),
                                  export_format="GLB", use_selection=True,
                                  export_animations=False, export_image_format="AUTO")
    if a.format in ("fbx", "both"):
        bpy.ops.export_scene.fbx(filepath=str(out / (path.stem + "_remeshed.fbx")),
                                 use_selection=True, path_mode="RELATIVE", embed_textures=False,
                                 bake_anim=False)
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


def main():
    a = args()
    a.output.mkdir(parents=True, exist_ok=True)
    files = ([a.input] if a.input.is_file() else
             sorted(a.input.rglob("*.glb") if a.recursive else a.input.glob("*.glb")))
    if not files:
        raise SystemExit("No GLB files found")
    failures = []
    for path in files:
        print("PROCESS", path, flush=True)
        try:
            process_file(path, a)
            print("DONE", path, flush=True)
        except Exception as exc:
            failures.append({"file": str(path), "error": str(exc)})
            traceback.print_exc()
    if failures:
        (a.output / "failures.json").write_text(json.dumps(failures, indent=2), encoding="utf-8")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
