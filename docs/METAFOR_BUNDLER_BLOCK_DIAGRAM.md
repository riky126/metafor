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
                    │  • Create build/_wheel_    │
                    │    staging/                │
                    │  • Load .metafor/cache.json│
                    └───────────┬────────────────┘
                                │
                                ▼
                    ┌───────────────────────────┐
                    │  Phase 3: Framework Copy   │
                    │  (_copy_framework)         │
                    │                            │
                    │  • Copy metafor/ to        │
                    │    _wheel_staging/         │
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
        │  │          Copy to _wheel_staging/                │   │
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
        │         ProcessPoolExecutor (Parallel)                 │
        │                                                         │
        │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
        │  │ Worker 1     │  │ Worker 2     │  │ Worker 3     │ │
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
                    │  _wheel_staging/           │
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
                    │  Phase 6: Wheel Creation    │
                    │  (_create_wheel)            │
                    └───────────┬────────────────┘
                                │
                                ▼
        ┌───────────────────────────────────────────────────────┐
        │              WHEEL CREATION PIPELINE                    │
        │                                                         │
        │  ┌─────────────────────────────────────────────────┐   │
        │  │  Step 6.1: Package Discovery                    │   │
        │  │  • Walk _wheel_staging/                        │   │
        │  │  • Find packages (dirs with __init__.py)       │   │
        │  │  • Find modules (top-level .py files)         │   │
        │  │                                                │   │
        │  │  Result:                                       │   │
        │  │    packages = ['app', 'app.components', ...]  │   │
        │  │    py_modules = ['main']                       │   │
        │  └──────────────────┬────────────────────────────┘   │
        │                      │                                 │
        │                      ▼                                 │
        │  ┌─────────────────────────────────────────────────┐   │
        │  │  Step 6.2: Bytecode Compilation                 │   │
        │  │  (if use_pyc=True)                             │   │
        │  │  • For each .py file:                          │   │
        │  │    - py_compile.compile()                     │   │
        │  │    - Generate .pyc                            │   │
        │  │    - Remove .py                               │   │
        │  │                                                │   │
        │  │  Result: All .py → .pyc                        │   │
        │  └──────────────────┬────────────────────────────┘   │
        │                      │                                 │
        │                      ▼                                 │
        │  ┌─────────────────────────────────────────────────┐   │
        │  │  Step 6.3: Generate setup.py                      │   │
        │  │  • Merge setup_config with discovered packages  │   │
        │  │  • Add package_data patterns                    │   │
        │  │  • Write setup.py to staging                    │   │
        │  │                                                │   │
        │  │  Generated:                                     │   │
        │  │    setup(                                      │   │
        │  │      name='my_app',                            │   │
        │  │      version='1.0.0',                           │   │
        │  │      packages=[...],                           │   │
        │  │      py_modules=[...],                         │   │
        │  │      package_data={'': ['*.pyc']},            │   │
        │  │      ...                                       │   │
        │  │    )                                           │   │
        │  └──────────────────┬────────────────────────────┘   │
        │                      │                                 │
        │                      ▼                                 │
        │  ┌─────────────────────────────────────────────────┐   │
        │  │  Step 6.4: Build Wheel                           │   │
        │  │  • Run: python setup.py bdist_wheel             │   │
        │  │    --dist-dir public/                           │   │
        │  │  • Output: *.whl file                           │   │
        │  │                                                │   │
        │  │  Result:                                       │   │
        │  │    my_app-1.0.0-py3-none-any.whl              │   │
        │  └──────────────────┬────────────────────────────┘   │
        │                      │                                 │
        │                      ▼                                 │
        │  ┌─────────────────────────────────────────────────┐   │
        │  │  Step 6.5: Post-Process Wheel                     │   │
        │  │  (if use_pyc=True)                               │   │
        │  │  • Open wheel as zipfile                         │   │
        │  │  • Add top-level .pyc files                      │   │
        │  │  • Close and save                                │   │
        │  └─────────────────────────────────────────────────┘   │
        └───────────────────────────┬───────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────┐
                    │  Phase 7: Cleanup          │
                    │                            │
                    │  • Remove _wheel_staging/  │
                    │  • Save cache              │
                    └───────────┬────────────────┘
                                │
                                ▼
                    ┌───────────────────────────┐
                    │  Phase 8: Update Config     │
                    │  (_update_pyscript_toml)    │
                    └───────────┬────────────────┘
                                │
                                ▼
        ┌───────────────────────────────────────────────────────┐
        │         PYSCRIPT.TOML UPDATE PROCESS                  │
        │                                                         │
        │  ┌─────────────────────────────────────────────────┐   │
        │  │  Step 8.1: Read Source Config                     │   │
        │  │  • Parse source pyscript.toml                    │   │
        │  │  • Extract user_packages                          │   │
        │  │  • Extract user_files                             │   │
        │  └──────────────────┬───────────────────────────────┘   │
        │                      │                                   │
        │                      ▼                                   │
        │  ┌─────────────────────────────────────────────────┐   │
        │  │  Step 8.2: Merge Packages                         │   │
        │  │  • Add wheel path                                │   │
        │  │  • Add install_requires                          │   │
        │  │  • Add user_packages                             │   │
        │  │  • Deduplicate                                   │   │
        │  │                                                │   │
        │  │  Result:                                        │   │
        │  │    all_packages = [                             │   │
        │  │      "./public/my_app-1.0.0-...whl",           │   │
        │  │      "requests",                                │   │
        │  │      ...                                        │   │
        │  │    ]                                            │   │
        │  └──────────────────┬───────────────────────────────┘   │
        │                      │                                   │
        │                      ▼                                   │
        │  ┌─────────────────────────────────────────────────┐   │
        │  │  Step 8.3: Merge Files                            │   │
        │  │  • Add generated asset files                      │   │
        │  │  • Merge with user_files                         │   │
        │  │  • User files take precedence                    │   │
        │  │                                                │   │
        │  │  Result:                                        │   │
        │  │    merged_files = {                             │   │
        │  │      "assets/logo.svg": "./assets/logo.svg",   │   │
        │  │      "assets/app.css": "./assets/app.css",     │   │
        │  │      ...                                        │   │
        │  │    }                                            │   │
        │  └──────────────────┬───────────────────────────────┘   │
        │                      │                                   │
        │                      ▼                                   │
        │  ┌─────────────────────────────────────────────────┐   │
        │  │  Step 8.4: Update File                            │   │
        │  │  • Replace packages = [...]                      │   │
        │  │  • Replace [files] section                      │   │
        │  │  • Preserve other content                        │   │
        │  └─────────────────────────────────────────────────┘   │
        └───────────────────────────┬───────────────────────────┘
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
                    │  │ │   ├── logo.svg   │   │
                    │  │ │   └── app.css    │   │
                    │  │ └── public/        │   │
                    │  │     └── my_app-    │   │
                    │  │       1.0.0-        │   │
                    │  │       py3-none-     │   │
                    │  │       any.whl       │   │
                    │  └─────────────────────┘   │
                    └───────────────────────────┘
```

## Detailed PTML Compilation Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    PTML Compilation Queue                    │
│  ┌───────────────────────────────────────────────────────┐ │
│  │ [                                                       │ │
│  │   (app/components/counter.ptml,                         │ │
│  │    staging/app/components/),                           │ │
│  │   (app/pages/dashboard.ptml,                            │ │
│  │    staging/app/pages/),                                 │ │
│  │   ...                                                   │ │
│  │ ]                                                       │ │
│  └───────────────────────────────────────────────────────┘ │
└───────────────────────────────┬───────────────────────────────┘
                                │
                                ▼
        ┌───────────────────────────────────────────────────┐
        │         ProcessPoolExecutor                         │
        │         (Parallel Execution)                        │
        │                                                      │
        │  ┌──────────────┐  ┌──────────────┐  ┌────────────┐ │
        │  │ Process 1    │  │ Process 2    │  │ Process 3  │ │
        │  │              │  │              │  │            │ │
        │  │ counter.ptml │  │ dashboard.   │  │ ...        │ │
        │  │      │       │  │   ptml       │  │            │ │
        │  │      ▼       │  │      │       │  │            │ │
        │  │ Read file    │  │      ▼       │  │            │ │
        │  │      │       │  │ Read file    │  │            │ │
        │  │      ▼       │  │      │       │  │            │ │
        │  │ Metafor      │  │      ▼       │  │            │ │
        │  │ Compiler     │  │ Metafor      │  │            │ │
        │  │ .compile()   │  │ Compiler     │  │            │ │
        │  │      │       │  │ .compile()   │  │            │ │
        │  │      ▼       │  │      │       │  │            │ │
        │  │ Python code  │  │      ▼       │  │            │ │
        │  │      │       │  │ Python code  │  │            │ │
        │  │      ▼       │  │      │       │  │            │ │
        │  │ Write        │  │      ▼       │  │            │ │
        │  │ counter.py   │  │ Write        │  │            │ │
        │  │ to staging   │  │ dashboard.py │  │            │ │
        │  │      │       │  │ to staging   │  │            │ │
        │  │      ▼       │  │      │       │  │            │ │
        │  │ Return path  │  │      ▼       │  │            │ │
        │  │              │  │ Return path  │  │            │ │
        │  └──────────────┘  └──────────────┘  └────────────┘ │
        └───────────────────────────┬──────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────┐
                    │  Update Cache               │
                    │  • For each completed task  │
                    │  • Update cache with hash    │
                    └─────────────────────────────┘
```

## Build Cache System Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    File Processing                            │
│                                                               │
│   For each file in source directory:                          │
│   ┌───────────────────────────────────────────────────────┐  │
│   │  1. Calculate MD5 Hash                                   │  │
│   │     hasher = hashlib.md5()                             │  │
│   │     hasher.update(file_contents)                       │  │
│   │     current_hash = hasher.hexdigest()                   │  │
│   └───────────────────┬─────────────────────────────────────┘  │
│                       │                                        │
│                       ▼                                        │
│   ┌───────────────────────────────────────────────────────┐  │
│   │  2. Check Cache                                         │  │
│   │     cached_hash = cache.get(file_path)                 │  │
│   │     if current_hash != cached_hash:                     │  │
│   │         changed = True                                  │  │
│   │     else:                                               │  │
│   │         changed = False                                 │  │
│   └───────────────────┬─────────────────────────────────────┘  │
│                       │                                        │
│                       ▼                                        │
│   ┌───────────────────────────────────────────────────────┐  │
│   │  3. Process if Changed                                   │  │
│   │     if changed:                                          │  │
│   │         process_file(file_path)                        │  │
│   │         cache.update_cache(file_path)                   │  │
│   │     else:                                               │  │
│   │         skip_file(file_path)  # Use cached result      │  │
│   └─────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                            │
                            │
                            ▼
        ┌───────────────────────────────────────────────┐
        │   Cache File: .metafor/cache.json              │
        │   ┌─────────────────────────────────────────┐ │
        │   │ {                                       │ │
        │   │   "app/counter.ptml": "abc123...",     │ │
        │   │   "assets/logo.svg": "def456...",      │ │
        │   │   "app/main.py": "ghi789...",          │ │
        │   │   ...                                   │ │
        │   }                                         │ │
        │   └─────────────────────────────────────────┘ │
        └───────────────────────────────────────────────┘
```

## Wheel Creation Detailed Steps

```
┌─────────────────────────────────────────────────────────────┐
│              _wheel_staging/ Directory                      │
│  ┌───────────────────────────────────────────────────────┐ │
│  │ app/                                                   │ │
│  │   ├── __init__.py                                      │ │
│  │   ├── components/                                      │ │
│  │   │   ├── __init__.py                                  │ │
│  │   │   └── counter.py                                   │ │
│  │   └── pages/                                           │ │
│  │       ├── __init__.py                                  │ │
│  │       └── dashboard.py                                 │ │
│  │ main.py                                                │ │
│  │ metafor/                                               │ │
│  │   └── (framework files)                                │ │
│  └───────────────────────────────────────────────────────┘ │
└───────────────────────────────┬───────────────────────────────┘
                                │
                                ▼
        ┌───────────────────────────────────────────────────┐
        │  Step 1: Package Discovery                          │
        │  (Walk staging directory)                          │
        │                                                      │
        │  Packages found:                                    │
        │    • app (has __init__.py)                         │
        │    • app.components (has __init__.py)              │
        │    • app.pages (has __init__.py)                   │
        │    • metafor (has __init__.py)                     │
        │                                                      │
        │  Modules found:                                     │
        │    • main (top-level .py)                          │
        └───────────────────────┬────────────────────────────┘
                                │
                                ▼
        ┌───────────────────────────────────────────────────┐
        │  Step 2: Bytecode Compilation                        │
        │  (if use_pyc=True)                                   │
        │                                                      │
        │  For each .py file:                                 │
        │    py_compile.compile(file.py, file.pyc)           │
        │    os.remove(file.py)                               │
        │                                                      │
        │  Result:                                            │
        │    app/__init__.pyc                                 │
        │    app/components/counter.pyc                       │
        │    app/pages/dashboard.pyc                          │
        │    main.pyc                                         │
        │    metafor/__init__.pyc                             │
        │    ...                                              │
        └───────────────────────┬────────────────────────────┘
                                │
                                ▼
        ┌───────────────────────────────────────────────────┐
        │  Step 3: Generate setup.py                           │
        │                                                      │
        │  setup_args = {                                     │
        │    'name': 'my_app',                                │
        │    'version': '1.0.0',                              │
        │    'packages': ['app', 'app.components', ...],     │
        │    'py_modules': ['main'],                          │
        │    'install_requires': ['requests'],                │
        │    'package_data': {'': ['*.pyc']},                │
        │    'include_package_data': True                      │
        │  }                                                  │
        │                                                      │
        │  Write setup.py to staging/                         │
        └───────────────────────┬────────────────────────────┘
                                │
                                ▼
        ┌───────────────────────────────────────────────────┐
        │  Step 4: Build Wheel                                  │
        │                                                      │
        │  Command:                                           │
        │    python setup.py bdist_wheel                     │
        │      --dist-dir public/                             │
        │                                                      │
        │  Environment:                                        │
        │    • Preserve PYTHONPATH                            │
        │    • Add sys.path                                   │
        │                                                      │
        │  Output:                                            │
        │    public/my_app-1.0.0-py3-none-any.whl            │
        └───────────────────────┬────────────────────────────┘
                                │
                                ▼
        ┌───────────────────────────────────────────────────┐
        │  Step 5: Post-Process (if use_pyc)                  │
        │                                                      │
        │  • Open wheel as zipfile                            │
        │  • Add top-level .pyc files                         │
        │  • Close and save                                    │
        └─────────────────────────────────────────────────────┘
```

## PyScript TOML Update Process

```
┌─────────────────────────────────────────────────────────────┐
│              Source pyscript.toml                           │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ packages = ["requests"]                                │  │
│  │                                                         │  │
│  │ [files]                                                │  │
│  │ "custom/file.txt" = "./custom/file.txt"               │  │
│  └───────────────────────────────────────────────────────┘  │
└───────────────────────────────┬───────────────────────────────┘
                                │
                                ▼
        ┌───────────────────────────────────────────────────┐
        │  Step 1: Read Source Config                         │
        │  (tomllib.load)                                      │
        │                                                      │
        │  user_packages = ["requests"]                       │
        │  user_files = {"custom/file.txt": "./custom/..."}  │
        └───────────────────────┬────────────────────────────┘
                                │
                                ▼
        ┌───────────────────────────────────────────────────┐
        │  Step 2: Merge Packages                             │
        │                                                      │
        │  all_packages = [                                   │
        │    "./public/my_app-1.0.0-py3-none-any.whl",      │
        │    "requests",  # from install_requires            │
        │    "requests"   # from user_packages (deduped)     │
        │  ]                                                  │
        └───────────────────────┬────────────────────────────┘
                                │
                                ▼
        ┌───────────────────────────────────────────────────┐
        │  Step 3: Merge Files                                 │
        │                                                      │
        │  merged_files = {                                   │
        │    "assets/logo.svg": "./assets/logo.svg",         │
        │    "assets/app.css": "./assets/app.css",           │
        │    "custom/file.txt": "./custom/file.txt"          │
        │  }                                                  │
        └───────────────────────┬────────────────────────────┘
                                │
                                ▼
        ┌───────────────────────────────────────────────────┐
        │  Step 4: Update File (Line-by-Line)                 │
        │                                                      │
        │  • Replace packages = [...]                         │
        │  • Replace [files] section                          │
        │  • Preserve other content                           │
        └───────────────────────┬────────────────────────────┘
                                │
                                ▼
        ┌───────────────────────────────────────────────────┐
        │         Updated pyscript.toml                       │
        │  ┌───────────────────────────────────────────────┐ │
        │  │ packages = [                                   │ │
        │  │     "./public/my_app-1.0.0-py3-none-any.whl", │ │
        │  │     "requests"                                 │ │
        │  │ ]                                              │ │
        │  │                                                 │ │
        │  │ [files]                                         │ │
        │  │ "assets/logo.svg" = "./assets/logo.svg"       │ │
        │  │ "assets/app.css" = "./assets/app.css"          │ │
        │  │ "custom/file.txt" = "./custom/file.txt"        │ │
        │  └───────────────────────────────────────────────┘ │
        └─────────────────────────────────────────────────────┘
```

## Data Flow Summary

```
Source Files
    │
    ├─► Setup Parsing ──► setup_config
    │
    ├─► File Discovery ──► File Categories
    │                        │
    │                        ├─► Special Files ──► build/
    │                        │
    │                        ├─► PTML Files ──► Compilation Queue
    │                        │                    │
    │                        │                    └─► Parallel Compile ──► _wheel_staging/
    │                        │
    │                        ├─► Python Files ──► _wheel_staging/
    │                        │
    │                        └─► Assets ──► build/ + generated_files
    │
    ├─► Framework Copy ──► _wheel_staging/metafor/
    │
    └─► Cache Check ──► Skip if unchanged

_wheel_staging/
    │
    └─► Wheel Creation
         │
         ├─► Package Discovery
         ├─► Bytecode Compilation (optional)
         ├─► Generate setup.py
         ├─► Build wheel
         └─► Post-process wheel

build/
    │
    └─► Update pyscript.toml
         │
         ├─► Merge packages
         └─► Merge files

Final Output:
    • build/public/*.whl
    • build/pyscript.toml (updated)
    • build/assets/ (copied)
    • build/index.html, main.py (copied)
```

