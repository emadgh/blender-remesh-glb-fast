# GLB Remesh to FBX for Unity URP

Windows GUI for batch remeshing GLB files with Blender 4.3+. Drop GLB files into the window, choose the output folder and settings, then run. The tool exports FBX only and writes its material textures beside each FBX.

## Quick start

1. Keep `Launch RemeshBake.vbs`, `RemeshBake.ps1`, and `blender_batch_remesh_bake.py` together.
2. Double-click `Launch RemeshBake.vbs`.
3. Drop one or more `.glb` files into the window, choose output and options, and click **Remesh + Export FBX**.

The GUI uses the default Blender 4.3 install path when available; select `blender.exe` manually otherwise. See [README-fa.md](README-fa.md) for Persian instructions and processing limitations.

## Output textures

Each remeshed mesh gets its own UV map and texture set:

- `*_basecolor.png` — Base Color and source Alpha when the input material is actually transparent.
- `*_normal.png` — tangent-space normal map.
- `*_metallic.png`, `*_roughness.png`, and `*_emission.png` — individual PBR maps linked to the FBX material.
- `*_ao.png` — baked ambient occlusion.
- `*_unity_metallic_smoothness.png` — packed for URP Lit: R=Metallic, G=Occlusion, B=unused, A=Smoothness (1 − Roughness).

Set the packed Unity map's **sRGB (Color Texture)** option off when importing. Assign it to the URP Lit Metallic and Occlusion map inputs; Unity reads the appropriate channels. The FBX retains a PBR material with direct links to Base Color, Metallic, Roughness, Normal, and Emission textures. AO is provided separately and in the Unity packed map. Unity may import the FBX material under a different shader; use **Universal Render Pipeline/Lit** if the project does not automatically upgrade it.

## Run from command line

```powershell
blender -b --python blender_batch_remesh_bake.py -- --input "C:\models" --output "C:\baked" --texture-size 2048
```

Use `--recursive` to include subfolders. See `--help` for all remesh options.
