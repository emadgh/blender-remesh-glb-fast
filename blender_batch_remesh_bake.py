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
from mathutils.bvhtree import BVHTree


CHANNELS = {
    "basecolor": ("Base Color", (0.8, 0.8, 0.8, 1.0)),
    "roughness": ("Roughness", (0.5, 0.5, 0.5, 1.0)),
    "metallic": ("Metallic", (0.0, 0.0, 0.0, 1.0)),
    "emission": ("Emission Color", (0.0, 0.0, 0.0, 1.0)),
    "alpha": ("Alpha", (1.0, 1.0, 1.0, 1.0)),
}
MAP_OPTIONS = ("basecolor", "metallic", "normal", "roughness", "ao", "emission", "height")


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
    p.add_argument("--maps", nargs="*", choices=MAP_OPTIONS,
                   default=["basecolor", "metallic", "normal"],
                   help="Texture maps to export; --maps alone exports no textures")
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


def object_space_dimensions(source):
    """Return mesh bounds in object space, matching Blender's voxel-size units."""
    bounds = source.bound_box
    use_bounds = len(bounds) == 8 and not all(
        all(component == -1.0 for component in point) for point in bounds
    )
    points = bounds if use_bounds else source.data.vertices
    minima = [float("inf")] * 3
    maxima = [float("-inf")] * 3
    for point in points:
        coordinates = point if use_bounds else point.co
        for axis in range(3):
            value = coordinates[axis]
            minima[axis] = min(minima[axis], value)
            maxima[axis] = max(maxima[axis], value)
    return [maxima[axis] - minima[axis] for axis in range(3)]


def remesh(source, a):
    low = source.copy()
    low.data = source.data.copy()
    bpy.context.collection.objects.link(low)
    low.name = source.name + "_remesh"
    activate(low)
    # Voxel remesh drops all UV and material assignments. Originals stay intact for baking.
    # Voxel size is in object space, so apply scale only to this disposable copy
    # before measuring its bounds. The imported source object remains unchanged.
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    bpy.context.view_layer.update()
    local_dimension = max(object_space_dimensions(low))
    # Keep world dimensions separate for bake extrusion.
    dimension = max(source.dimensions)
    if local_dimension <= 0 or dimension <= 0:
        raise ValueError("Zero-size mesh")
    voxel_size = max(local_dimension * a.voxel_size, 0.000001)
    low.data.remesh_voxel_size = voxel_size
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
    return low, dimension, voxel_size, local_dimension


def bake_height(source, low, img, extrusion):
    """Project high-poly geometry onto low-poly UV texels along low normals.

    Encode signed world-space offset as 0.5 + offset / (2 * ray range).
    Use evaluated meshes in world space so parent/rotation/scale agree.
    """
    radius = max(extrusion, max(source.dimensions) * 0.02, 1e-6)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    high_eval = source.evaluated_get(depsgraph)
    low_eval = low.evaluated_get(depsgraph)
    high_mesh = high_eval.to_mesh()
    low_mesh = low_eval.to_mesh()
    try:
        high_mesh.calc_loop_triangles()
        low_mesh.calc_loop_triangles()
        high_points = [high_eval.matrix_world @ vertex.co for vertex in high_mesh.vertices]
        bvh = BVHTree.FromPolygons(high_points,
                                  [tuple(t.vertices) for t in high_mesh.loop_triangles],
                                  all_triangles=True)
        uv_layer = low_mesh.uv_layers.active
        if uv_layer is None:
            raise ValueError("Height bake requires a UV map on the low-poly mesh")
        width, height = img.size
        pixels = array('f', [0.5, 0.5, 0.5, 1.0]) * (width * height)
        covered = bytearray(width * height)
        world = low_eval.matrix_world
        normal_matrix = world.to_3x3().inverted().transposed()
        hits = missed = 0
        minimum = maximum = 0.0
        for triangle in low_mesh.loop_triangles:
            uvs = [uv_layer.data[i].uv for i in triangle.loops]
            ax, ay = uvs[0].x * width, uvs[0].y * height
            bx, by = uvs[1].x * width, uvs[1].y * height
            cx, cy = uvs[2].x * width, uvs[2].y * height
            denominator = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
            if abs(denominator) < 1e-12:
                continue
            vertices = [low_mesh.vertices[i] for i in triangle.vertices]
            points = [world @ vertex.co for vertex in vertices]
            normals = [(normal_matrix @ vertex.normal).normalized() for vertex in vertices]
            smooth = low_mesh.polygons[triangle.polygon_index].use_smooth
            face_normal = (points[1] - points[0]).cross(points[2] - points[0]).normalized()
            for y in range(max(0, int(min(ay, by, cy))), min(height, int(max(ay, by, cy)) + 1)):
                for x in range(max(0, int(min(ax, bx, cx))), min(width, int(max(ax, bx, cx)) + 1)):
                    px, py = x + 0.5, y + 0.5
                    a = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / denominator
                    b = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / denominator
                    c = 1.0 - a - b
                    if min(a, b, c) < -1e-7:
                        continue
                    index = y * width + x
                    if covered[index]:
                        continue
                    position = points[0] * a + points[1] * b + points[2] * c
                    normal = ((normals[0] * a + normals[1] * b + normals[2] * c).normalized()
                              if smooth else face_normal)
                    if normal.length_squared < 1e-12:
                        missed += 1
                        continue
                    offsets = []
                    for sign in (1.0, -1.0):
                        location, _, _, _ = bvh.ray_cast(position + normal * (radius * sign),
                                                         normal * -sign, radius * 2)
                        if location is not None:
                            offsets.append((location - position).dot(normal))
                    if not offsets:
                        missed += 1
                        continue
                    offset = min(offsets, key=abs)
                    value = max(0.0, min(1.0, 0.5 + offset / (2 * radius)))
                    pixels[index * 4:index * 4 + 4] = array('f', [value, value, value, 1.0])
                    covered[index] = 1
                    hits += 1
                    minimum, maximum = min(minimum, offset), max(maximum, offset)
        if not hits:
            raise ValueError("Height bake found no source surface; increase cage extrusion")
        # Extend island colors into empty texels to prevent filtering seams.
        frontier = [i for i, value in enumerate(covered) if value]
        for _ in range(8):
            following = []
            for index in frontier:
                x, y = index % width, index // width
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < width and 0 <= ny < height:
                        neighbor = ny * width + nx
                        if not covered[neighbor]:
                            pixels[neighbor * 4:neighbor * 4 + 4] = pixels[index * 4:index * 4 + 4]
                            covered[neighbor] = 1
                            following.append(neighbor)
            frontier = following
        img.pixels.foreach_set(pixels)
        print(f"HEIGHT: {hits} projected texels, {missed} missed, range +/-{radius:g}", flush=True)
        if missed:
            print("WARNING: Height projection missed texels; consider increasing cage extrusion", flush=True)
        return {"method": "high_to_low_geometry", "neutral": 0.5,
                "world_space_range": radius, "min_offset": minimum, "max_offset": maximum,
                "projected_texels": hits, "missed_texels": missed}
    finally:
        high_eval.to_mesh_clear()
        low_eval.to_mesh_clear()


def bake_map(source, low, originals, channel, img, extrusion):
    if channel == "height":
        return bake_height(source, low, img, extrusion)
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

    if "basecolor" in imgs:
        base = tex("basecolor")
        tree.links.new(base.outputs["Color"], bsdf.inputs["Base Color"])
    if transparent and "basecolor" in imgs:
        tree.links.new(base.outputs["Alpha"], bsdf.inputs["Alpha"])
        mat.surface_render_method = "DITHERED"
    # Keep grayscale maps directly connected to the Principled inputs. This
    # lets FBX export preserve their texture links as individual material maps.
    for key, socket in (("roughness", "Roughness"), ("metallic", "Metallic"),
                        ("emission", "Emission Color")):
        if key in imgs:
            tree.links.new(tex(key).outputs["Color"], bsdf.inputs[socket])
    if "normal" in imgs:
        normal = tex("normal")
        normal_map = tree.nodes.new("ShaderNodeNormalMap")
        tree.links.new(normal.outputs["Color"], normal_map.inputs["Color"])
        tree.links.new(normal_map.outputs["Normal"], bsdf.inputs["Normal"])
    bsdf.inputs["Emission Strength"].default_value = 1.0 if "emission" in imgs else 0.0
    return mat


def pack_unity_channels(imgs, size, transparent):
    count = size * size
    def values(key, default=0.0):
        if key not in imgs:
            return array('f', [default, default, default, 1.0]) * count
        data = array('f', [0.0]) * (count * 4)
        imgs[key].pixels.foreach_get(data)
        return data
    base = values("basecolor")
    alpha = values("alpha") if transparent else None
    coverage = values("coverage") if transparent else None
    rough = values("roughness", 0.5)
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
    if "basecolor" in imgs:
        imgs["basecolor"].pixels.foreach_set(base)
    ao = values("ao", 1.0)
    unity_mask = image("unity_metallic_smoothness", size, (0, 1, 0, 0.5), True)
    pixels = array('f', [0.0]) * (count * 4)
    for i in range(count):
        j = i * 4
        pixels[j] = metal[j]
        pixels[j + 1] = ao[j]
        pixels[j + 2] = 0.0
        pixels[j + 3] = 1.0 - rough[j]
    unity_mask.pixels.foreach_set(pixels)
    if any(key in imgs for key in ("metallic", "roughness", "ao")):
        imgs["unity_metallic_smoothness"] = unity_mask
    else:
        bpy.data.images.remove(unity_mask)
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
        selected_maps = set(a.maps)
        transparent = "basecolor" in selected_maps and any(material_has_transparency(mat) for mat in originals)
        # Unassigned material slots still need a source material during channel baking.
        if not originals:
            blank = bpy.data.materials.new("default")
            blank.diffuse_color = (0.8, 0.8, 0.8, 1)
            originals = [blank]
            source.data.materials.append(blank)
        low, dimension, voxel_size, local_dimension = remesh(source, a)
        bake_mat = bpy.data.materials.new("Bake Target")
        bake_mat.use_nodes = True
        bake_tex = bake_mat.node_tree.nodes.new("ShaderNodeTexImage")
        bake_tex.name = "BAKE_TARGET"
        low.data.materials.append(bake_mat)
        safe_name = source.name.replace('/', '_').replace(chr(92), '_')
        prefix = f"{index:03d}_{safe_name}"
        imgs = {}
        height_report = None
        bake_keys = [key for key in MAP_OPTIONS if key in selected_maps]
        # Unity stores smoothness in Metallic alpha. Keep source roughness even
        # when the user doesn't request a separate roughness texture.
        if ("metallic" in selected_maps or "ao" in selected_maps) and "roughness" not in bake_keys:
            bake_keys.append("roughness")
        if transparent:
            bake_keys.append("alpha")
        for key in bake_keys:
            fill = CHANNELS[key][1] if key in CHANNELS else ((1, 1, 1, 1) if key == "ao" else ((0.5, 0.5, 0.5, 1) if key == "height" else (0.5, 0.5, 1, 1)))
            img = image(prefix + "_" + key, a.texture_size, fill,
                        key not in ("basecolor", "emission"),
                        alpha=(transparent or key != "basecolor"))
            bake_result = bake_map(source, low, originals, key, img, dimension * a.cage_extrusion)
            if key == "height":
                height_report = bake_result
            imgs[key] = img
        if transparent:
            coverage = image(prefix + "_coverage", a.texture_size, (0, 0, 0, 0), True)
            bake_coverage(source, low, coverage, dimension * a.cage_extrusion)
            imgs["coverage"] = coverage
        pack_unity_channels(imgs, a.texture_size, transparent)
        export_keys = selected_maps | {"unity_metallic_smoothness"}
        if "roughness" in selected_maps:
            smoothness = image(prefix + "_smoothness", a.texture_size, (0.5, 0.5, 0.5, 1), True)
            pixels = array('f', [0.0]) * (a.texture_size * a.texture_size * 4)
            imgs["roughness"].pixels.foreach_get(pixels)
            for j in range(0, len(pixels), 4):
                value = 1.0 - pixels[j]
                pixels[j:j + 4] = array('f', [value, value, value, 1.0])
            smoothness.pixels.foreach_set(pixels)
            imgs["smoothness"] = smoothness
            export_keys.add("smoothness")
        for key in export_keys:
            if key in imgs:
                save_image(imgs[key], out / f"{prefix}_{key}.png")
        # Internal roughness used for packing must not become an unselected
        # external FBX texture reference.
        if "roughness" not in selected_maps and "roughness" in imgs:
            bpy.data.images.remove(imgs.pop("roughness"))
        low.data.materials.clear()
        low.data.materials.append(material_from_images(imgs, transparent))
        lows.append(low)
        report["objects"].append({"name": source.name,
                                  "source_vertices": len(source.data.vertices),
                                  "source_faces": len(source.data.polygons),
                                  "output_vertices": len(low.data.vertices),
                                  "output_faces": len(low.data.polygons),
                                  "voxel_size_object_space": voxel_size,
                                  "local_longest_dimension": local_dimension,
                                  "texture_prefix": prefix,
                                  "exported_maps": sorted(key for key in export_keys if key in imgs),
                                  "height_bake": height_report,
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
