# Metafor Bundler Block Diagram

## Complete Build Flow: Source Project → Distributable Wheel

```
┌─────────────────────────────────────────────────────────────────────┐
│                         SOURCE PROJECT                               │
│  ┌───────────────────────────────────────────────────────────────┐   │
│  │ app/                                                          │   │
│  │   ├── components/counter.ptml                                │   │
│  │   ├── pages/dashboard.ptml                                    │   │
│  │   └── main.py                                                 │   │
│  │ assets/logo.svg                                               │   │
│  │ setup.py                                                      │   │
│  │ pyscript.toml                                                  │   │
│  │ index.html                                                     │   │
│  └───────────────────────────────────────────────────────────────┘   │
└──────────────────────────────┬──────────────────────────────────────┘
                                │
                                ▼
                    ┌───────────────────────────┐
                    │  Phase 1: Setup Parsing   │
                    │  (_parse_setup_py)         │
                    │                            │
                    │  • Parse setup.py (AST)    │
                    │  • Extract metadata        │
                    │  • Store in setup_config    │
                    └───────────┬────────────────┘
                                │
                                ▼
                    ┌───────────────────────────┐
                    │  setup_config = {         │
                    │    'name': 'my_app',      │
                    │    'version': '1.0.0',    │
                    │    'install_requires': [] │
                    │  }                        │
                    └───────────┬────────────────┘
                                │
                                ▼
                    ┌───────────────────────────┐
                    │  Phase 2: Directory Setup  │
                    │                            │
                    │  • Create build/           │
                    │  • Create build/public/    │
                    │  • Create build/_staging_/ │
                    │  • Load .metafor/cache.json│
                    └───────────┬────────────────┘
                                │
                                ▼
                    ┌───────────────────────────┐
                    │  Phase 3: Framework Copy   │
                    │  (_copy_framework)         │
                    │                            │
                    │  • Copy metafor/ to        │
                    │    build/_staging_/        │
                    │  • Exclude __pycache__     │
                    └───────────┬────────────────┘
                                │
                                ▼
                    ┌───────────────────────────┐
                    │  Phase 4: File Discovery    │
                    │  (os.walk source_dir)       │
                    │                            │
                    │  Walk source tree and       │
                    │  categorize files           │
                    └───────────┬────────────────┘
                                │
                                ▼
        ┌───────────────────────────────────────────────────────┐
        │              FILE PROCESSING DECISION TREE             │
        │                                                         │
        │  For each file found:                                   │
        │                                                         │
        │  ┌─────────────────────────────────────────────────┐   │
        │  │  Special File?                                  │   │
        │  │  (index.html, pyscript.toml, main.py)          │   │
        │  │    └─► Copy to build/                          │   │
        │  │        Update cache                            │   │
        │  │                                                 │   │
        │  │  PTML File? (*.ptml)                            │   │
        │  │    └─► Check cache                              │   │
        │  │        If changed:                              │   │
        │  │          Add to ptml_tasks queue                │   │
        │  │                                                 │   │
        │  │  Python File? (*.py, not test_*)               │   │
        │  │    └─► Check cache                              │   │
        │  │        If changed:                              │   │
        │  │          Copy to build/_staging_/               │   │
        │  │          Update cache                            │   │
        │  │                                                 │   │
        │  │  Asset File? (css, svg, images, etc.)          │   │
        │  │    └─► Check cache                              │   │
        │  │        If changed:                              │   │
        │  │          Copy to build/                         │   │
        │  │          Track in generated_files               │   │
        │  │          Update cache                            │   │
        │  └─────────────────────────────────────────────────┘   │
        └───────────────────────────┬───────────────────────────┘
                                      │
                                      ▼
                    ┌───────────────────────────┐
                    │  Build Cache System        │
                    │  (BuildCache)              │
                    │                            │
                    │  • Calculate MD5 hash       │
                    │  • Compare with cache      │
                    │  • Skip if unchanged        │
                    │  • Update after processing  │
                    └───────────┬────────────────┘
                                │
                                ▼
                    ┌───────────────────────────┐
                    │  Phase 5: PTML Compilation  │
                    │  (Parallel Execution)       │
                    │                            │
                    │  ptml_tasks = [            │
                    │    (file1.ptml, target1),  │
                    │    (file2.ptml, target2),  │
                    │    ...                     │
                    │  ]                         │
                    └───────────┬────────────────┘
                                │
                                ▼
        ┌───────────────────────────────────────────────────────┐
        │         ThreadPoolExecutor (Parallel)                  │
        │                                                         │
        │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
        │  │ Thread 1     │  │ Thread 2     │  │ Thread 3     │ │
        │  │              │  │              │  │              │ │
        │  │ Read PTML    │  │ Read PTML    │  │ Read PTML    │ │
        │  │      │       │  │      │       │  │      │       │ │
        │  │      ▼       │  │      ▼       │  │      ▼       │ │
        │  │ Compiler     │  │ Compiler     │  │ Compiler     │ │
        │  │ .compile()   │  │ .compile()   │  │ .compile()   │ │
        │  │      │       │  │      │       │  │      │       │ │
        │  │      ▼       │  │      ▼       │  │      ▼       │ │
        │  │ Write .py    │  │ Write .py    │  │ Write .py    │ │
        │  │ to staging   │  │ to staging   │  │ to staging   │ │
        │  └──────────────┘  └──────────────┘  └──────────────┘ │
        └───────────────────────────┬───────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────┐
                    │  _staging/                 │
                    │  ┌─────────────────────┐ │
                    │  │ app/                  │ │
                    │  │   ├── components/     │ │
                    │  │   │   └── counter.py  │ │
                    │  │   └── pages/          │ │
                    │  │       └── dashboard.py│ │
                    │  │ main.py               │ │
                    │  │ metafor/              │ │
                    │  │   └── (framework)     │ │
                    │  └─────────────────────┘ │
                    └───────────┬────────────────┘
                                │
                                ▼
                    ┌───────────────────────────┐
                    │  Phase 6: Optimization      │
                    │  (if use_pyc=True)          │
                    │                            │
                    │  • compileall.compile_dir  │
                    │  • Staging -> .pyc         │
                    └───────────┬────────────────┘
                                │
                                ▼
                    ┌───────────────────────────┐
                    │  Phase 7: Wheel Packing     │
                    │  (_pack_wheel)              │
                    │  IN-MEMORY PROCESSING       │
                    └───────────┬────────────────┘
                                │
                                ▼
        ┌───────────────────────────────────────────────────────┐
        │              WHEEL CREATION PIPELINE                    │
        │                                                         │
        │  ┌─────────────────────────────────────────────────┐   │
        │  │  Streaming Zip Writes                           │   │
        │  │  • Walk _staging/                              │   │
        │  │  • Stream .pyc (or .py) to .whl                │   │
        │  │  • Calculate SHA-256 on the fly                │   │
        │  └──────────────────┬───────────────────────────────┘  │
        │                      │                                 │
        │                      ▼                                 │
        │  ┌─────────────────────────────────────────────────┐   │
        │  │  In-Memory Metadata Generation                  │   │
        │  │  • Generate METADATA string                     │   │
        │  │  • Generate WHEEL string                        │   │
        │  │  • Build RECORD list (files + hashes)           │   │
        │  └──────────────────┬───────────────────────────────┘  │
        │                      │                                 │
        │                      ▼                                 │
        │  ┌─────────────────────────────────────────────────┐   │
        │  │  Finalizing Wheel                               │   │
        │  │  • Write METADATA to zip                        │   │
        │  │  • Write WHEEL to zip                           │   │
        │  │  • Write RECORD to zip                          │   │
        │  └─────────────────────────────────────────────────┘   │
        └───────────────────────────┬───────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────┐
                    │  Phase 8: Cleanup          │
                    │                            │
                    │  • Save cache              │
                    │  • (Staging preserved for  │
                    │     incremental builds)    │
                    └───────────┬────────────────┘
                                │
                                ▼
                    ┌───────────────────────────┐
                    │  Phase 9: Update Config     │
                    │  (_update_pyscript_toml)    │
                    └───────────┬────────────────┘
                                │
                                ▼
        ┌───────────────────────────────────────────────────────┐
        │         PYSCRIPT.TOML UPDATE PROCESS                  │
        │                                                         │
        │  Step 1: Parse Source Config                          │
        │    Using `tomllib`                                    │
        │                                                         │
        │  Step 2: Inject Wheel                                 │
        │    Add generated wheel path to `packages` list        │
        │                                                         │
        │  Step 3: Inject Assets                                │
        │    Add generated asset mappings to `[files]`          │
        │                                                         │
        │  Step 4: Write Config                                 │
        │    Update `build/pyscript.toml`                       │
        └───────────────────────────────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────┐
                    │      BUILD OUTPUT           │
                    │  ┌─────────────────────┐   │
                    │  │ build/              │   │
                    │  │ ├── index.html     │   │
                    │  │ ├── main.py        │   │
                    │  │ ├── pyscript.toml  │   │
                    │  │ ├── assets/        │   │
                    │  │ └── public/        │   │
                    │  │     └── my_app-    │   │
                    │  │       1.0.0-        │   │
                    │  │       py3-none-     │   │
                    │  │       any.whl       │   │
                    │  └─────────────────────┘   │
                    └───────────────────────────┘
```

## Key Architectural Changes

1.  **In-Memory Wheel Packing**: Replaces `setup.py bdist_wheel` with a direct ZipFile stream (`_pack_wheel`). This is significantly faster and avoids disk I/O for intermediate metadata files.
2.  **Thread-based Concurrency**: Uses `ThreadPoolExecutor` for PTML compilation instead of `ProcessPoolExecutor` to reduce overhead and avoid zombie processes.
3.  **Optimization**: Uses `compileall` to generate `.pyc` files directly in the staging area, which are then packed into the wheel.
4.  **Incremental Staging**: The `_staging_` directory is preserved between builds to allow incremental updates, only pruning files that were deleted from the source.
