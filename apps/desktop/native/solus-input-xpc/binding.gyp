{
  # Solus.app main's XPC client for the drive agent (sol-drive.md §2.1).
  # The interface and signing constants come from the agent's own header.
  "targets": [
    {
      "target_name": "solus_input_xpc",
      "sources": ["src/addon.mm"],
      "include_dirs": ["../solus-input/Sources/SolusInputShared/include"],
      "defines": ["NAPI_VERSION=8"],
      "conditions": [
        ["OS=='mac'", {
          "xcode_settings": {
            "CLANG_ENABLE_OBJC_ARC": "YES",
            "CLANG_CXX_LANGUAGE_STANDARD": "c++17",
            "MACOSX_DEPLOYMENT_TARGET": "14.0",
            "GCC_TREAT_WARNINGS_AS_ERRORS": "YES",
            "WARNING_CFLAGS": ["-Wall", "-Wextra", "-Wno-unused-parameter"],
            "OTHER_LDFLAGS": ["-framework", "Foundation", "-framework", "Security"]
          }
        }]
      ]
    }
  ]
}
