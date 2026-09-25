# تبدیل GLB به FBX برای Unity

رابط ویندوزی برای تبدیل فایل‌های GLB به FBX با Blender 4.3 یا جدیدتر. حالت پیش‌فرض مش و UV اصلی را حفظ می‌کند و تکسچرها را کنار FBX می‌نویسد. حالت اختیاری **Remesh + Bake** عمداً مش را تغییر می‌دهد و UV جدیدی برای تکسچرهای bakeشده می‌سازد.

## شروع سریع

1. فایل‌های `Launch RemeshBake.vbs`، `RemeshBake.ps1`، `blender_batch_glb_to_fbx.py` و `blender_batch_remesh_bake.py` را کنار هم نگه دارید.
2. `Launch RemeshBake.vbs` را دوبار کلیک کنید.
3. فایل‌های `.glb` را داخل پنجره رها کنید، پوشهٔ مقصد را انتخاب کنید و **Convert GLB → FBX (preserve mesh + UV)** را بزنید.

برای تبدیل مستقیم، گزینهٔ **Preserve original mesh, UV and materials** را روشن بگذارید. فقط وقتی remesh و UV تازه می‌خواهید آن را خاموش کنید؛ در آن حالت تعداد و شکل وجه‌ها و مختصات UV مثل ورودی باقی نمی‌مانند.

در حالت Remesh + Bake، اندازهٔ voxel درصدی از بزرگ‌ترین بُعد bounds محلی مش است. این مقدار رزولوشن مکانی را تعیین می‌کند، نه تعداد رأس هدف؛ بنابراین دو مدل هم‌اندازه با جزئیات سطح یا توپولوژی متفاوت ممکن است تعداد رأس خروجی متفاوتی داشته باشند. **Decimate (%)** هم فقط نسبت کاهش هر مش را تعیین می‌کند و تعداد مشترک نمی‌سازد. در `report.json` تعداد رأس ورودی و خروجی و voxel استفاده‌شده ثبت می‌شود.

اگر Blender در مسیر پیش‌فرض نسخهٔ 4.3 نصب باشد خودکار پیدا می‌شود؛ در غیر این صورت مسیر `blender.exe` را دستی انتخاب کنید.

## کانورت مستقیم بدون Remesh

اگر فقط تبدیل GLB به FBX می‌خواهید، فایل مستقل `Launch GLB to FBX.vbs` را اجرا کنید. این ابزار Remesh، Decimate و Bake انجام نمی‌دهد؛ متریال و UV ورودی را حفظ می‌کند و تکسچرهای استفاده‌شده را کنار FBX آنپک کرده و با لینک نسبی صادر می‌کند. راهنمای کامل در [README-glb-to-fbx-fa.md](README-glb-to-fbx-fa.md) است.

## تکسچرهای خروجی حالت Remesh + Bake

برای هر مش یک UV جدید و این نقشه‌ها ساخته می‌شود:

- `*_basecolor.png` — رنگ پایه و آلفای اصلی، فقط اگر متریال ورودی واقعاً شفاف باشد.
- `*_normal.png` — نرمال tangent-space.
- `*_metallic.png`، `*_roughness.png` و `*_emission.png` — نقشه‌های PBR که به متریال FBX وصل می‌شوند.
- `*_ao.png` — Ambient Occlusion bakeشده.
- `*_unity_metallic_smoothness.png` — پک مخصوص URP Lit: کانال R فلزی، G انسداد محیطی، B استفاده‌نشده و A صافی (`1 − Roughness`).

در Unity برای تکسچر پک‌شده گزینهٔ **sRGB (Color Texture)** را خاموش کنید و آن را به ورودی‌های Metallic و Occlusion متریال URP Lit بدهید. متریال داخل FBX به نقشه‌های Base Color، Metallic، Roughness، Normal و Emission وصل است. اگر Unity متریال FBX را خودکار به URP تبدیل نکرد، Shader آن را روی **Universal Render Pipeline/Lit** بگذارید.

## اجرای Remesh + Bake از خط فرمان

```powershell
blender -b --python blender_batch_remesh_bake.py -- --input "C:\models" --output "C:\baked" --texture-size 2048
```

برای جست‌وجوی زیرپوشه‌ها `--recursive` را اضافه کنید. گزینه‌های remesh با `--help` نمایش داده می‌شوند.

**محدودیت‌ها:** voxel remesh برای مدل‌های بسته و سطحی مناسب‌تر است و ممکن است ورقه‌های خیلی نازک، قطعات ریز یا حفره‌ها را تغییر دهد. ریگ، انیمیشن و shape key منتقل نمی‌شوند. نقشهٔ AO از هندسه bake می‌شود؛ نقشهٔ AO ورودی عیناً کپی نمی‌شود. متریال‌های اختصاصی مثل clearcoat و transmission در این نسخه بازسازی نمی‌شوند.
