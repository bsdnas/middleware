--- freenasUI/middleware/notifier.py.orig	2024-10-22 19:11:43.479479553 +0200
+++ freenasUI/middleware/notifier.py	2024-10-22 19:11:48.479587871 +0200
@@ -35,7 +35,7 @@
 """
 
 
-from middlewared.plugins.system.product import SystemService
+from middlewared.plugins.system import SystemService
 from middlewared.plugins.pwenc import encrypt, decrypt
 
 
