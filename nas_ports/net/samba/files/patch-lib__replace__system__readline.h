diff --git lib/replace/system/readline.h lib/replace/system/readline.h
index 29379626e0..84cc66af04 100644
--- lib/replace/system/readline.h
+++ lib/replace/system/readline.h
@@ -46,9 +46,7 @@
 #endif
 
 #ifdef HAVE_NEW_LIBREADLINE
-#ifdef HAVE_CPPFUNCTION
-#  define RL_COMPLETION_CAST (CPPFunction *)
-#elif defined(HAVE_RL_COMPLETION_T)
+#if defined(HAVE_RL_COMPLETION_T)
 #  define RL_COMPLETION_CAST (rl_completion_t *)
 #else
 #  define RL_COMPLETION_CAST
