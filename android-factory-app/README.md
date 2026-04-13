Factory Approval Android App

Purpose
- Lightweight Android wrapper app for the Render-hosted payment approval website.
- Opens: https://paymentapproval.onrender.com

Open In Android Studio
1. Open Android Studio.
2. Select Open and choose folder: android-factory-app
3. Let Gradle sync complete.

Generate Debug APK
1. In Android Studio, click Build.
2. Click Build Bundle(s) / APK(s).
3. Click Build APK(s).
4. APK output path:
   app/build/outputs/apk/debug/app-debug.apk

Generate Release APK
1. In Android Studio, click Build.
2. Click Generate Signed Bundle / APK.
3. Choose APK and create/select keystore.
4. Use release build type.

Share To Factory Users
- Share the signed release APK file with factory users.
- Users may need to allow installation from unknown sources.

Important
- Keep website URL HTTPS.
- Login and session are handled by the server.
- File upload from the bill input is supported through Android file picker.
