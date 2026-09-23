"""Batch GLB remesh, UV unwrap, PBR bake and FBX export for Unity URP. Blender 4.3+.

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


def image(name, size, fill, noncolor=False, alpha=True):
    img = bpy.data.images.new(name, width=size, height=size, alpha=alpha)
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
    # Bake the Principled emission's effective value, including Strength.
    # Ignoring a zero strength turns the default white Emission Color into a
    # full-white emissive map and makes the exported model look white.
    if channel == "emission" and shader:
        strength = shader.inputs.get("Emission Strength")
        if strength:
            if strength.is_linked:
                tree.links.new(strength.links[0].from_socket, emit.inputs["Strength"])
            else:
                emit.inputs["Strength"].default_value = strength.default_value
    tree.links.new(emit.outputs["Emission"], output.inputs["Surface"])
    return mat


def material_has_transparency(mat):
    shader = principal(mat)
    alpha = shader.inputs.get("Alpha") if shader else None
    if not alpha:
        return False
    if alpha.is_linked:
        return True
    return float(alpha.default_value) < 0.999


def bake_coverage(source, low, img, extrusion):
    """Bake a white surface mask so empty atlas pixels stay fully opaque."""
    original_slots = list(source.data.materials)
    mask_mat = bpy.data.materials.new("__BakeCoverage")
    mask_mat.use_nodes = True
    tree = mask_mat.node_tree
    tree.nodes.clear()
    out = tree.nodes.new("ShaderNodeOutputMaterial")
    emit = tree.nodes.new("ShaderNodeEmission")
    emit.inputs["Color"].default_value = (1, 1, 1, 1)
    tree.links.new(emit.outputs["Emission"], out.inputs["Surface"])
    source.data.materials.clear()
    for _ in (original_slots or [None]):
        source.data.materials.append(mask_mat)
    tex = low.active_material.node_tree.nodes.get("BAKE_TARGET")
    tex.image = img
    low.active_material.node_tree.nodes.active = tex
    activate(source, low, active=low)
    try:
        bpy.ops.object.bake(type="EMIT", use_selected_to_active=True,
                            cage_extrusion=extrusion, margin=8, use_clear=True)
    finally:
        source.data.materials.clear()
        for original in original_slots:
            source.data.materials.append(original)
        bpy.data.materials.remove(mask_mat)


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


def material_from_images(imgs, transparent):
    mat = bpy.data.materials.new("Baked URP Lit")
    mat.use_nodes = True
    # Blender 4.3 defaults new materials to HASHED transparency. Explicitly
    # mark opaque inputs as opaque so FBX/Unity does not import them translucent.
    mat.blend_method = "BLEND" if transparent else "OPAQUE"
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
    if transparent:
        tree.links.new(base.outputs["Alpha"], bsdf.inputs["Alpha"])
        mat.surface_render_method = "DITHERED"
    # Keep grayscale maps directly connected to the Principled inputs. This
    # lets FBX export preserve their texture links as individual material maps.
    rough = tex("roughness")
    tree.links.new(rough.outputs["Color"], bsdf.inputs["Roughness"])
    metal = tex("metallic")
    tree.links.new(metal.outputs["Color"], bsdf.inputs["Metallic"])
    normal = tex("normal")
    normal_map = tree.nodes.new("ShaderNodeNormalMap")
    tree.links.new(normal.outputs["Color"], normal_map.inputs["Color"])
    tree.links.new(normal_map.outputs["Normal"], bsdf.inputs["Normal"])
    emission = tex("emission")
    tree.links.new(emission.outputs["Color"], bsdf.inputs["Emission Color"])
    bsdf.inputs["Emission Strength"].default_value = 1.0
    return mat


def pack_unity_channels(imgs, size, transparent):
    count = size * size
    def values(key):
        data = array('f', [0.0]) * (count * 4)
        imgs[key].pixels.foreach_get(data)
        return data
    base = values("basecolor")
    alpha = values("alpha") if transparent else None
    coverage = values("coverage") if transparent else None
    rough = values("roughness")
    metal = values("metallic")
    for i in range(count):
        j = i * 4
        if transparent:
            # Bake margin fills texels around UV islands; for all remaining
            # empty atlas pixels use alpha=1 so the whole material is not
            # classified as transparent by glTF/FBX importers.
            base[j + 3] = alpha[j] if coverage[j] > 0.5 else 1.0
        else:
            base[j + 3] = 1.0
    imgs["basecolor"].pixels.foreach_set(base)
    ao = values("ao")
    unity_mask = image("unity_metallic_smoothness", size, (0, 1, 0, 0.5), True)
    pixels = array('f', [0.0]) * (count * 4)
    for i in range(count):
        j = i * 4
        pixels[j] = metal[j]
        pixels[j + 1] = ao[j]
        pixels[j + 2] = 0.0
        pixels[j + 3] = 1.0 - rough[j]
    unity_mask.pixels.foreach_set(pixels)
    imgs["unity_metallic_smoothness"] = unity_mask
    if transparent:
        for key in ("alpha", "coverage"):
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
        transparent = any(material_has_transparency(mat) for mat in originals)
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
        bake_keys = ["basecolor", "roughness", "metallic", "emission", "ao", "normal"]
        if transparent:
            bake_keys.append("alpha")
        for key in bake_keys:
            fill = CHANNELS[key][1] if key in CHANNELS else ((1, 1, 1, 1) if key == "ao" else (0.5, 0.5, 1, 1))
            img = image(prefix + "_" + key, a.texture_size, fill,
                        key not in ("basecolor", "emission"),
                        alpha=(transparent or key != "basecolor"))
            bake_map(source, low, originals, key, img, dimension * a.cage_extrusion)
            imgs[key] = img
            if key != "coverage":
                save_image(img, out / f"{prefix}_{key}.png")
        if transparent:
            coverage = image(prefix + "_coverage", a.texture_size, (0, 0, 0, 0), True)
            bake_coverage(source, low, coverage, dimension * a.cage_extrusion)
            imgs["coverage"] = coverage
        pack_unity_channels(imgs, a.texture_size, transparent)
        # Re-save base color after alpha was made opaque outside UV islands.
        save_image(imgs["basecolor"], out / f"{prefix}_basecolor.png")
        save_image(imgs["unity_metallic_smoothness"],
                   out / f"{prefix}_unity_metallic_smoothness.png")
        low.data.materials.clear()
        low.data.materials.append(material_from_images(imgs, transparent))
        lows.append(low)
        report["objects"].append({"name": source.name, "source_faces": len(source.data.polygons),
                                  "output_faces": len(low.data.polygons), "texture_prefix": prefix,
                                  "transparent": transparent})
    activate(*lows)
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
