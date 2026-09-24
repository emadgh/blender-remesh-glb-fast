# تبدیل GLB به FBX برای Unity URP

رابط ویندوزی برای remesh و bake دسته‌ای فایل‌های GLB با Blender 4.3 یا جدیدتر. فایل‌ها را در پنجره بکشید، پوشهٔ مقصد و تنظیمات را انتخاب کنید و اجرا را بزنید. خروجی هر مدل فقط FBX است و تکسچرها در پوشهٔ همان FBX ذخیره می‌شوند.

## شروع سریع

1. فایل‌های `Launch RemeshBake.vbs`، `RemeshBake.ps1` و `blender_batch_remesh_bake.py` را کنار هم نگه دارید.
2. `Launch RemeshBake.vbs` را دوبار کلیک کنید.
3. فایل‌های `.glb` را داخل پنجره رها کنید، مقصد و تنظیمات را انتخاب کنید و **Remesh + Export FBX** را بزنید.

اگر Blender در مسیر پیش‌فرض نسخهٔ 4.3 نصب باشد خودکار پیدا می‌شود؛ در غیر این صورت مسیر `blender.exe` را دستی انتخاب کنید.

## کانورت مستقیم بدون Remesh

اگر فقط تبدیل GLB به FBX می‌خواهید، فایل مستقل `Launch GLB to FBX.vbs` را اجرا کنید. این ابزار Remesh، Decimate و Bake انجام نمی‌دهد؛ متریال و UV ورودی را حفظ می‌کند و تکسچرهای استفاده‌شده را کنار FBX آنپک کرده و با لینک نسبی صادر می‌کند. راهنمای کامل در [README-glb-to-fbx-fa.md](README-glb-to-fbx-fa.md) است.

## فایل‌های خروجی تکسچر

برای هر مش یک UV جدید و این نقشه‌ها ساخته می‌شود:

- `*_basecolor.png` — رنگ پایه و آلفای اصلی، فقط اگر متریال ورودی واقعاً شفاف باشد.
- `*_normal.png` — نرمال tangent-space.
- `*_metallic.png`، `*_roughness.png` و `*_emission.png` — نقشه‌های PBR که به متریال FBX وصل می‌شوند.
- `*_ao.png` — Ambient Occlusion bakeشده.
- `*_unity_metallic_smoothness.png` — پک مخصوص URP Lit: کانال R فلزی، G انسداد محیطی، B استفاده‌نشده و A صافی (`1 − Roughness`).

در Unity برای تکسچر پک‌شده گزینهٔ **sRGB (Color Texture)** را خاموش کنید و آن را به ورودی‌های Metallic و Occlusion متریال URP Lit بدهید. متریال داخل FBX به نقشه‌های Base Color، Metallic، Roughness، Normal و Emission وصل است. اگر Unity متریال FBX را خودکار به URP تبدیل نکرد، Shader آن را روی **Universal Render Pipeline/Lit** بگذارید.

## اجرا از خط فرمان

```powershell
blender -b --python blender_batch_remesh_bake.py -- --input "C:\models" --output "C:\baked" --texture-size 2048
```

برای جست‌وجوی زیرپوشه‌ها `--recursive` را اضافه کنید. گزینه‌های remesh با `--help` نمایش داده می‌شوند.

**محدودیت‌ها:** voxel remesh برای مدل‌های بسته و سطحی مناسب‌تر است و ممکن است ورقه‌های خیلی نازک، قطعات ریز یا حفره‌ها را تغییر دهد. ریگ، انیمیشن و shape key منتقل نمی‌شوند. نقشهٔ AO از هندسه bake می‌شود؛ نقشهٔ AO ورودی عیناً کپی نمی‌شود. متریال‌های اختصاصی مثل clearcoat و transmission در این نسخه بازسازی نمی‌شوند.
