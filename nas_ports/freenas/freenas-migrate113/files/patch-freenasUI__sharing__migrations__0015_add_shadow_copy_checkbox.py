--- freenasUI/sharing/migrations/0015_add_shadow_copy_checkbox.py.orig	2024-10-22 20:18:42.234537703 +0200
+++ freenasUI/sharing/migrations/0015_add_shadow_copy_checkbox.py	2024-10-22 20:18:50.182709880 +0200
@@ -23,8 +23,4 @@
         migrations.RunPython(
             migrate_shadowcopies
         ),
-        migrations.RemoveField(
-            model_name='cifs_share',
-            name='cifs_storage_task_id',
-        ),
     ]
