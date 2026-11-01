"""Convert GLB files to Unity-friendly FBX files without changing mesh topology or UVs.

The importer keeps the original scene, mesh data, UVs, materials, armatures and
animations. Images used by node-based materials are written as external PNG
files next to the FBX, then exported with relative texture references.

Run from Blender:
    blender -b --python blender_batch_glb_to_fbx.py -- \
        --input model.glb --output C:/exports
"""

import argparse
import json
import re
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Matrix, Vector


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tga", ".bmp", ".tif", ".tiff", ".exr", ".hdr", ".webp"}
BLENDER_FORMATS = {
    ".png": "PNG",
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".tga": "TARGA",
    ".bmp": "BMP",
    ".tif": "TIFF",
    ".tiff": "TIFF",
    ".exr": "OPEN_EXR",
    ".hdr": "HDR",
    ".webp": "WEBP",
}


def parse_args():
    raw = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="A GLB file or a folder containing GLB files")
    parser.add_argument("--output", required=True, type=Path, help="Output folder")
    parser.add_argument("--recursive", action="store_true", help="Search input subfolders")
    parser.add_argument("--no-animation", action="store_true", help="Do not export animation data")
    parser.add_argument(
        "--texture-format",
        choices=("png", "original"),
        default="png",
        help="Texture output format; PNG is the safest option for Unity",
    )
    args = parser.parse_args(raw)
    args.input = args.input.resolve()
    args.output = args.output.resolve()
    return args


def safe_stem(value):
    value = Path(value).stem or "texture"
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return value or "texture"


def unique_texture_path(folder, image, extension):
    source_name = image.name or "texture"
    if source_name.lower().endswith(extension):
        base = Path(source_name).stem
    else:
        base = safe_stem(source_name)
    base = safe_stem(base)
    candidate = folder / f"{base}{extension}"
    number = 2
    while candidate.exists():
        candidate = folder / f"{base}_{number}{extension}"
        number += 1
    return candidate


def material_images():
    """Return images referenced by material image nodes, preserving order."""
    result = []
    seen = set()
    for material in bpy.data.materials:
        if not material.use_nodes or not material.node_tree:
            continue
        for node in material.node_tree.nodes:
            if node.type != "TEX_IMAGE" or not node.image:
                continue
            key = node.image.as_pointer()
            if key not in seen:
                seen.add(key)
                result.append(node.image)
    return result


def source_extension(image):
    filepath = str(getattr(image, "filepath", ""))
    suffix = Path(filepath).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return suffix
    name_suffix = Path(image.name or "").suffix.lower()
    if name_suffix in IMAGE_EXTENSIONS:
        return name_suffix
    return ".png"


def save_external_images(folder, texture_format):
    """Write material images and leave their paths external for FBX export."""
    folder.mkdir(parents=True, exist_ok=True)
    records = []
    for image in material_images():
        original_filepath = str(getattr(image, "filepath", ""))
        extension = ".png" if texture_format == "png" else source_extension(image)
        target = unique_texture_path(folder, image, extension)

        # Saving through Blender works for both packed GLB images and images
        # that were already external. It also converts uncommon embedded image
        # formats to a Unity-friendly PNG when requested.
        if texture_format == "png":
            image.file_format = "PNG"
        else:
            image.file_format = BLENDER_FORMATS.get(extension, "PNG")
        image.save(filepath=str(target))
        # Do not unpack the GLB image: that can write beside the input file.
        # Point the datablock at the saved copy so FBX uses the output texture.
        image.filepath = str(target)
        records.append({
            "name": image.name,
            "file": target.name,
            "source": original_filepath,
        })
        print(f"TEXTURE {target.name}", flush=True)
    return records


def imported_objects():
    """Select renderable GLB objects while retaining hierarchy helpers."""
    allowed = {"MESH", "ARMATURE", "EMPTY"}
    return [obj for obj in bpy.context.scene.objects if obj.type in allowed]


def base_color_uv(material):
    """Find the UV map driving the visible base-color image, if explicit."""
    if not material or not material.use_nodes:
        return None
    tree = material.node_tree
    for shader in (node for node in tree.nodes if node.type == 'BSDF_PRINCIPLED'):
        color = shader.inputs.get('Base Color')
        if not color or not color.is_linked:
            continue
        texture = color.links[0].from_node
        if texture.type != 'TEX_IMAGE':
            continue
        vector = texture.inputs.get('Vector')
        if not vector or not vector.is_linked:
            continue
        mapping = vector.links[0].from_node
        if mapping.type == 'MAPPING':
            vector = mapping.inputs.get('Vector')
            if not vector or not vector.is_linked:
                continue
            mapping = vector.links[0].from_node
        if mapping.type == 'UVMAP':
            return mapping.uv_map
    return None


def base_color_transform(material):
    """Return the static glTF texture transform feeding Base Color."""
    if not material or not material.use_nodes:
        return None
    for shader in (node for node in material.node_tree.nodes if node.type == 'BSDF_PRINCIPLED'):
        color = shader.inputs.get('Base Color')
        if not color or not color.is_linked:
            continue
        texture = color.links[0].from_node
        if texture.type != 'TEX_IMAGE' or not texture.inputs['Vector'].is_linked:
            continue
        mapping = texture.inputs['Vector'].links[0].from_node
        if mapping.type != 'MAPPING' or mapping.vector_type != 'POINT':
            continue
        location = tuple(mapping.inputs['Location'].default_value)
        rotation = tuple(mapping.inputs['Rotation'].default_value)
        scale = tuple(mapping.inputs['Scale'].default_value)
        if any(mapping.inputs[key].is_linked for key in ('Location', 'Rotation', 'Scale')):
            raise ValueError(f'Animated/linked Base Color texture transform in {material.name} cannot be baked into static UVs')
        matrix = (Matrix.Translation(Vector(location)) @
                  Matrix.Rotation(rotation[2], 4, 'Z') @
                  Matrix.Diagonal(Vector((scale[0], scale[1], 1, 1))))
        return matrix
    return None


def keep_one_texture_uv(obj):
    """Keep only the base-color UV; Unity FBX materials sample UV channel 0."""
    layers = obj.data.uv_layers
    names = [layer.name for layer in layers]
    requested = {name for material in obj.data.materials
                 if (name := base_color_uv(material)) and name in names}
    used = set()
    for material in obj.data.materials:
        if not material or not material.use_nodes:
            continue
        for texture in (node for node in material.node_tree.nodes if node.type == 'TEX_IMAGE'):
            vector = texture.inputs.get('Vector')
            if vector and vector.is_linked and vector.links[0].from_node.type == 'UVMAP':
                name = vector.links[0].from_node.uv_map
                if name in names:
                    used.add(name)
    if len(requested) > 1:
        raise ValueError(f'Conflicting base-color UV sets on {obj.name}: {sorted(requested)}. A single UV cannot represent both.')
    warning = None
    if len(used) > 1:
        warning = (f'Multiple texture UV sets on {obj.name}: {sorted(used)}. '
                   'The output uses Base Color UV for every texture; other maps may need rebaking.')
    if not names:
        return warning, None
    chosen = next(iter(requested)) if requested else names[0]
    transforms = [base_color_transform(material) for material in obj.data.materials
                  if material and material.use_nodes]
    matrices = [matrix if matrix is not None else Matrix.Identity(4) for matrix in transforms]
    if matrices and any(any(abs(matrices[0][row][col] - matrix[row][col]) > 1e-6
                            for row in range(4) for col in range(4)) for matrix in matrices[1:]):
        raise ValueError(f'Conflicting Base Color texture transforms on {obj.name}; cannot use one UV for all materials')
    # If there was no explicit base-color UV, glTF uses TEXCOORD_0.
    for layer in list(layers):
        if layer.name != chosen:
            layers.remove(layer)
    layers.active = layers[0]
    layers.active_index = 0
    if transforms and transforms[0] is not None:
        matrix = transforms[0]
        for loop in layers[0].data:
            transformed = matrix @ Vector((loop.uv.x, loop.uv.y, 0, 1))
            loop.uv = transformed.x, transformed.y
        print(f'UV transform baked into {obj.name}: {chosen}', flush=True)
    print(f'UV0 {obj.name}: {chosen} (one UV layer)', flush=True)
    return warning, chosen


def export_file(source_path, args):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source_path))
    objects = imported_objects()
    if not objects or not any(obj.type == "MESH" for obj in objects):
        raise ValueError("No mesh in GLB")

    # Mesh data may be shared between objects; make UV selection local to each.
    warnings = []
    uv_selection = {}
    for obj in objects:
        if obj.type == 'MESH':
            if obj.data.users > 1:
                obj.data = obj.data.copy()
            warning, selected_uv = keep_one_texture_uv(obj)
            uv_selection[obj.name] = selected_uv
            if warning:
                warnings.append(warning)
                print(f'WARNING {warning}', flush=True)

    output_dir = args.output / source_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    fbx_path = output_dir / f"{source_path.stem}.fbx"
    texture_records = save_external_images(output_dir, args.texture_format)

    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = next((obj for obj in objects if obj.type == "MESH"), objects[0])

    # Relative paths are resolved by the FBX exporter against the FBX output
    # directory. Images are stored in that same directory, so Unity can find
    # them beside the FBX without embedded texture blobs.
    bpy.ops.export_scene.fbx(
        filepath=str(fbx_path),
        use_selection=True,
        object_types={"EMPTY", "MESH", "ARMATURE"},
        path_mode="RELATIVE",
        embed_textures=False,
        # Export the imported mesh data directly: don't evaluate modifiers,
        # subdivide or triangulate it again during FBX export.
        use_mesh_modifiers=False,
        use_mesh_modifiers_render=False,
        use_subsurf=False,
        use_triangles=False,
        bake_space_transform=False,
        bake_anim=not args.no_animation,
        bake_anim_use_all_actions=True,
        bake_anim_use_nla_strips=True,
        bake_anim_simplify_factor=0.0,
        add_leaf_bones=False,
        apply_unit_scale=True,
        axis_forward="-Z",
        axis_up="Y",
    )

    report = {
        "source": str(source_path),
        "fbx": str(fbx_path),
        "textures": texture_records,
        "objects": [{"name": obj.name, "type": obj.type} for obj in objects],
        "animation_exported": not args.no_animation,
        "warnings": warnings,
        "uv0_by_object": uv_selection,
    }
    (output_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"FBX {fbx_path}", flush=True)


def main():
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.input.is_file():
        files = [args.input]
    else:
        pattern = args.input.rglob("*.glb") if args.recursive else args.input.glob("*.glb")
        files = sorted(pattern)
    if not files:
        raise SystemExit("No GLB files found")

    failures = []
    for source_path in files:
        print(f"PROCESS {source_path}", flush=True)
        try:
            export_file(source_path, args)
            print(f"DONE {source_path}", flush=True)
        except Exception as exc:
            failures.append({"file": str(source_path), "error": str(exc)})
            traceback.print_exc()

    if failures:
        (args.output / "failures.json").write_text(json.dumps(failures, indent=2), encoding="utf-8")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
