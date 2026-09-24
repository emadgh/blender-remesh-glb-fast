# کانورتور مستقل GLB به FBX برای Unity

این ابزار مستقل از Remesh/Bake است و مدل را مستقیماً از GLB به FBX تبدیل می‌کند.

- Remesh، Decimate، UV unwrap و Bake انجام نمی‌شود.
- مش، UV، متریال نودی، اسکلت و انیمیشن‌های واردشده تا حد ممکن حفظ می‌شوند.
- تکسچرهای استفاده‌شده توسط متریال از حالت packed خارج و در همان پوشهٔ FBX ذخیره می‌شوند.
- لینک تکسچرها در FBX به‌صورت relative و کنار فایل FBX باقی می‌ماند؛ گزینهٔ PNG برای Unity پیشنهاد می‌شود.

## اجرا

فایل `Launch GLB to FBX.vbs` را دوبار کلیک کنید، سپس فایل‌های GLB را بکشید و رها کنید، پوشهٔ خروجی و `blender.exe` را انتخاب کنید و **Convert GLB → FBX** را بزنید.

برای هر فایل، خروجی در یک زیرپوشهٔ هم‌نام ساخته می‌شود:

```text
output/
└── model/
    ├── model.fbx
    ├── texture.png
    └── report.json
```

در Unity معمولاً کافی است `model.fbx` را همراه با فایل‌های PNG وارد پروژه کنید. اگر Unity متریال FBX را خودکار درست نساخت، متریال را روی `Universal Render Pipeline/Lit` بگذارید و لینک‌های نقشه‌ها را بررسی کنید؛ FBX فرمت کاملاً یکسانی برای همهٔ نودهای Blender نیست.

## خط فرمان

```powershell
blender -b --python blender_batch_glb_to_fbx.py -- --input "C:\models\model.glb" --output "C:\exports"
```

گزینه‌های مفید:

- `--texture-format original` پسوند اصلی تکسچر را تا حد امکان نگه می‌دارد.
- `--no-animation` انیمیشن‌ها را صادر نمی‌کند.
- `--recursive` هنگام دادن یک پوشه، زیرپوشه‌ها را هم جست‌وجو می‌کند.

نکته: GLB ممکن است از shaderهای اختصاصی glTF مثل transmission، clearcoat یا sheen استفاده کند. ساختار متریال وارد می‌شود، اما پشتیبانی FBX و Unity از این ویژگی‌ها به اندازهٔ glTF کامل نیست.
