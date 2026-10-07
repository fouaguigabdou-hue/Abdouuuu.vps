# ABDOUUU TEAM VPS — Railway Edition

لوحة تحكم لتجربة وتشغيل مواقع HTML وبوتات Python/Node على Railway.

## النشر على Railway

1. ارفع المشروع إلى GitHub (المجلد كاملًا).
2. في Railway اختر **New Project → Deploy from GitHub Repo**.
3. أضف متغيرًا باسم `PANEL_TOKEN` وضع رمزًا قويًا وطويلًا.
4. أضف Volume دائمًا (Persistent Volume) واربطه بالمسار `/data` حتى لا تضيع البوتات والمواقع وقاعدة البيانات عند إعادة النشر.
5. أنشئ Domain من إعدادات Railway وافتحه في المتصفح.

الملف `railway.json` يضبط أمر التشغيل تلقائيًا.

## رفع البوتات

ZIP Python:
- `main.py` أو `bot.py` أو `app.py`
- و`requirements.txt` اختياري

ZIP Node:
- `package.json` مع `scripts.start`، أو
- `index.js` / `bot.js` / `main.js`

بعد الرفع اضغط Start. البوتات تحصل على اتصال الإنترنت من Railway، لذلك Telegram/Discord APIs تعمل ما دام البوت نفسه صحيحًا.

## المواقع

ZIP يحتوي `index.html`، ثم سيظهر الموقع على:
`/site/<ID>/`

## مهم

هذه النسخة لا تعتمد على Docker Socket. البوتات تُشغّل كعمليات داخل خدمة Railway. لذلك هي مناسبة للتجربة والاستخدام الشخصي، لكنها ليست عزلًا أمنيًا بمستوى منصة استضافة متعددة المستخدمين.

يجب عدم وضع `PANEL_TOKEN` داخل الكود أو GitHub.
