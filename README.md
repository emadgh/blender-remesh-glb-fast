# Blender Remesh + Bake

Windows GUI for batch remeshing GLB files with Blender 4.3+. Drag and drop GLB files, select the output folder and settings, then run. Blender runs in the background.

## Quick start

1. Keep `Launch RemeshBake.vbs`, `RemeshBake.ps1`, and `blender_batch_remesh_bake.py` together.
2. Double-click `Launch RemeshBake.vbs`.
3. Drop one or more `.glb` files into the window, choose output and options, and click **Remesh + Bake**.

The GUI uses the default Blender 4.3 install path when available; select `blender.exe` manually otherwise. See [README-fa.md](README-fa.md) for Persian instructions and processing limitations.

## Texture output

- **GLB:** baked images are packed and embedded in the `.glb`. GLB-only runs do not create PNG sidecar files.
- **FBX:** writes PNG textures beside the FBX because FBX references external texture files.
- **Both:** embeds textures in GLB and writes the PNG files needed by FBX.

The GLB includes Base Color with Alpha, an ORM image (R=AO, G=Roughness, B=Metallic), tangent Normal, and Emission. Each mesh gets its own UV map and baked texture set.

Run the processor directly:

```powershell
blender -b --python blender_batch_remesh_bake.py -- --input "C:\models" --output "C:\baked" --format glb --texture-size 2048
```

Default output format is `glb`. Other options include `fbx` and `both`. See the command help with `blender -b --python blender_batch_remesh_bake.py -- --help`.
