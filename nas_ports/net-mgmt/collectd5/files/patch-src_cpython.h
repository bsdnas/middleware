--- src/cpython.h.orig	2024-10-23 10:00:28 UTC
+++ src/cpython.h
@@ -26,7 +26,7 @@
 
 /* Some python versions don't include this by default. */
 
-#include <longintrepr.h>
+#include <Python.h>
 
 /* These two macros are basically Py_BEGIN_ALLOW_THREADS and
  * Py_BEGIN_ALLOW_THREADS
