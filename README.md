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

Each remeshed mesh gets its own UV map and texture set:

- `*_basecolor.png` — Base Color and source Alpha when the input material is actually transparent.
- `*_normal.png` — tangent-space normal map.
- `*_metallic.png`, `*_roughness.png`, and `*_emission.png` — individual PBR maps linked to the FBX material.
- `*_ao.png` — baked ambient occlusion.
- `*_unity_metallic_smoothness.png` — packed for URP Lit: R=Metallic, G=Occlusion, B=unused, A=Smoothness (1 − Roughness).

Set the packed Unity map's **sRGB (Color Texture)** option off when importing. Assign it to the URP Lit Metallic and Occlusion map inputs; Unity reads the appropriate channels. The FBX retains a PBR material with direct links to Base Color, Metallic, Roughness, Normal, and Emission textures. AO is provided separately and in the Unity packed map. Unity may import the FBX material under a different shader; use **Universal Render Pipeline/Lit** if the project does not automatically upgrade it.

## Run Remesh + Bake from command line

```powershell
blender -b --python blender_batch_remesh_bake.py -- --input "C:\models" --output "C:\baked" --texture-size 2048
```

Use `--recursive` to include subfolders. See `--help` for all remesh options.
