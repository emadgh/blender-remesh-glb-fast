# GLB to FBX for Unity

Windows GUI for converting GLB files to FBX with Blender 4.3+. The default mode preserves the imported mesh and UV maps, and writes material textures beside each FBX. Optional **Remesh + Bake** mode changes the mesh and creates a new UV map for its baked textures.

## Quick start

1. Keep `Launch RemeshBake.vbs`, `RemeshBake.ps1`, `blender_batch_glb_to_fbx.py`, and `blender_batch_remesh_bake.py` together.
2. Double-click `Launch RemeshBake.vbs`.
3. Drop one or more `.glb` files into the window, choose an output folder, and click **Convert GLB → FBX (preserve mesh + UV)**.

Leave **Preserve original mesh, UV and materials** checked for a direct conversion. Uncheck it only when you want voxel remeshing, a newly generated UV map, and baked textures; that mode intentionally changes mesh topology and UVs.

In Remesh + Bake mode, voxel size is a percentage of the longest mesh-local bound. It controls spatial resolution, not a target vertex count, so equally sized objects can still have different output counts when their surface detail or topology differs. **Decimate (%)** keeps a fraction of each object's remeshed geometry; it also does not set a shared count. Each `report.json` records source/output vertex counts and the voxel size used.

The GUI uses the default Blender 4.3 install path when available; select `blender.exe` manually otherwise. See [README-fa.md](README-fa.md) for Persian instructions and processing limitations.

## Standalone direct converter

For a dedicated window that always converts without remesh or baking, use `Launch GLB to FBX.vbs`. It preserves the imported mesh/UV structure, writes material images beside each FBX, and exports relative texture links. See [README-glb-to-fbx-fa.md](README-glb-to-fbx-fa.md).

## Remesh + Bake output textures

Choose the maps using the texture checkboxes. **Diffuse / Base Color, Metallic and Normal** are checked by default. **Roughness / Smoothness, AO, Emission and Height / Displacement** start unchecked. Unchecking all maps exports geometry without texture files. These controls apply to Remesh + Bake; Preserve mode keeps the original textures.

Each remeshed mesh gets its own UV map and selected textures:

- `*_basecolor.png` — Base Color and source Alpha when the input material is actually transparent.
- `*_normal.png` — tangent-space normal map.
- `*_metallic.png`, `*_roughness.png`, and `*_emission.png` — individual PBR maps linked to the FBX material.
- `*_ao.png` — baked ambient occlusion.
- `*_smoothness.png` — inverse roughness, exported with the Roughness / Smoothness option.
- `*_height.png` — geometric height baked from the high-poly source onto the low-poly UVs. No source height texture is required. Projection follows low-poly surface normals in world space: gray 0.5 means no offset, brighter means outward, darker means inward. The signed offset is encoded as `0.5 + offset / (2 * range)`. Range is the greater of cage extrusion and 2% of source bounds. Missed projections are logged; zero hits fail the bake rather than exporting a placeholder. Eight pixels of island padding reduce filtering seams. `report.json` records the range, offsets and hit/miss counts. This CPU projection can take longer at large texture resolutions.
- `*_unity_metallic_smoothness.png` — packed for URP Lit: R=Metallic, G=Occlusion, B=unused, A=Smoothness (1 − Roughness).

URP Lit supports metallic. Set the packed Unity map's **sRGB (Color Texture)** option off when importing. Assign it to Metallic, choose **Metallic Alpha** as the smoothness source and set the smoothness multiplier to 1. If AO is selected, assign the same packed map to Occlusion. Source roughness is baked internally for packing even when its separate export is unchecked; absent AO uses white. Import Normal as **Normal map**. Height goes into **Height Map** for parallax, not mesh vertex displacement. Height and AO need manual assignment; FBX does not automatically configure a URP Lit material. Use **Universal Render Pipeline/Lit** with the Metallic workflow.

## Run Remesh + Bake from command line

```powershell
blender -b --python blender_batch_remesh_bake.py -- --input "C:\models" --output "C:\baked" --texture-size 2048
```

Use `--maps basecolor metallic normal ao emission` to select maps, or `--maps` alone for no textures. Defaults are basecolor, metallic and normal. Use `--recursive` to include subfolders. See `--help` for all remesh options.
