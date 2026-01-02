# Metafor Bundler Documentation

## Overview

The Metafor bundler is a build system that transforms a Metafor project (containing PTML files, Python modules, and assets) into a distributable Python wheel package. It handles compilation, asset management, dependency resolution, and PyScript configuration.

## Architecture

The bundler orchestrates multiple build phases:

1. **Setup Parsing** - Extracts project metadata from `setup.py`
2. **File Discovery** - Walks the source directory to find all files
3. **Asset Processing** - Copies static assets to the build directory
4. **PTML Compilation** - Compiles PTML files to Python (parallel execution)
5. **Framework Integration** - Copies Metafor framework files
6. **Wheel Creation** - Packages everything into a Python wheel
7. **Configuration Update** - Updates `pyscript.toml` with packages and files
8. **Caching** - Tracks file changes to optimize rebuilds

## File Structure

```
metafor/bundler.py
├── BuildCache          # File change tracking
└── MetaforBundler      # Main bundler class
```

## Build Process

### Phase 1: Setup Parsing (`_parse_setup_py`)

The bundler parses `setup.py` to extract project metadata:

**Extracted Fields:**
- `name` - Package name
- `version` - Package version
- `packages` - Python packages (discovered automatically)
- `py_modules` - Top-level Python modules
- `install_requires` - Dependencies
- `package_data` - Additional data files
- `include_package_data` - Include package data flag

**Process:**
1. Parse `setup.py` using AST
2. Find `setup()` function call
3. Extract keyword arguments
4. Store in `self.setup_config`

**Example:**
```python
# setup.py
setup(
    name="my_app",
    version="1.0.0",
    install_requires=["requests"]
)
```

Parsed into:
```python
{
    'name': 'my_app',
    'version': '1.0.0',
    'install_requires': ['requests']
}
```

### Phase 2: Directory Setup

Creates necessary output directories:

- `build/` - Main build output directory
- `build/public/` - Wheel output directory
- `build/_wheel_staging/` - Temporary staging for wheel creation
- `.metafor/cache.json` - Build cache file

### Phase 3: File Discovery and Processing

The bundler walks the source directory and processes each file:

**File Categories:**

1. **Special Files** (copied to build root):
   - `index.html` - Entry HTML file
   - `pyscript.toml` - PyScript configuration
   - `main.py` - Application entry point

2. **Code Files** (processed and sent to wheel staging):
   - `*.ptml` - Compiled to `*.py` using MetaforCompiler
   - `*.py` - Copied as-is (except test files)

3. **Asset Files** (copied to build directory):
   - CSS, images, fonts, etc.
   - Tracked for `pyscript.toml` [files] section

**Processing Logic:**

```python
for file in source_directory:
    if file == 'index.html' or file == 'pyscript.toml' or file == 'main.py':
        # Copy to build root
        copy_to_build_root(file)
    elif file.endswith('.ptml'):
        # Add to PTML compilation queue
        ptml_tasks.append((file, target_dir))
    elif file.endswith('.py'):
        # Copy to wheel staging
        copy_to_wheel_staging(file)
    else:
        # Copy asset to build directory
        copy_asset_to_build(file)
        track_for_pyscript_toml(file)
```

**Directory Exclusion:**
- Hidden directories (starting with `.`)
- `build/` directory
- `public/` directory

### Phase 4: Build Cache

The bundler uses a hash-based cache to avoid recompiling unchanged files:

**Cache Structure:**
```json
{
    "path/to/file.ptml": "md5_hash",
    "path/to/asset.css": "md5_hash"
}
```

**Cache Operations:**
- `is_changed(file_path)` - Checks if file hash changed
- `update_cache(file_path)` - Updates hash after processing
- `save()` - Persists cache to `.metafor/cache.json`

**Benefits:**
- Skip compilation of unchanged PTML files
- Skip copying of unchanged assets
- Faster incremental builds

### Phase 5: PTML Compilation (`_compile_ptml_task`)

PTML files are compiled in parallel using `ProcessPoolExecutor`:

**Process:**
1. Read PTML source file
2. Create `MetaforCompiler` instance
3. Compile PTML to Python code
4. Write compiled `.py` file to wheel staging
5. Update cache

**Parallel Execution:**
```python
with ProcessPoolExecutor() as executor:
    futures = [executor.submit(compile_task, task) for task in ptml_tasks]
    for future in as_completed(futures):
        result = future.result()
        cache.update(result)
```

**Error Handling:**
- Compilation errors stop the build
- Error messages include file path and details

### Phase 6: Framework Integration (`_copy_framework`)

Copies the Metafor framework to wheel staging:

**Process:**
1. Locate framework directory (from `framework_dir` parameter)
2. Copy entire framework tree to `_wheel_staging/metafor/`
3. Exclude `__pycache__`, `*.pyc`, and hidden files

**Purpose:**
- Ensures runtime framework is included in wheel
- Framework is bundled with application code

### Phase 7: Wheel Creation (`_create_wheel`)

Packages everything into a Python wheel file:

#### 7.1 Package Discovery

Discovers packages and modules in staging directory:

**Package Detection:**
- Directories with `__init__.py` are packages
- Top-level `.py` files are modules

**Process:**
```python
for directory in staging_dir:
    if "__init__.py" in directory:
        package_name = directory_path.replace("/", ".")
        packages.append(package_name)
    elif file.endswith(".py"):
        module_name = file[:-3]
        py_modules.append(module_name)
```

#### 7.2 Bytecode Compilation (Optional)

If `use_pyc=True`, compiles Python files to `.pyc`:

**Process:**
1. Walk staging directory
2. For each `.py` file:
   - Compile to `.pyc` using `py_compile`
   - Remove original `.py` file
3. Update `package_data` to include `*.pyc` files

**Benefits:**
- Faster import times
- Smaller distribution (if optimized)
- Source code protection

#### 7.3 Setup.py Generation

Generates a `setup.py` in staging directory:

**Generated Setup Arguments:**
- `name` - From `setup_config` or default "metafor_app"
- `version` - From `setup_config` or default "0.1.0"
- `packages` - Discovered packages
- `py_modules` - Discovered modules
- `install_requires` - From `setup_config`
- `package_data` - Includes `*.pyc` or `*.py` patterns
- `include_package_data` - Always `True`

**Example Generated Setup:**
```python
from setuptools import setup

setup(
    name='my_app',
    version='1.0.0',
    packages=['app', 'app.pages'],
    py_modules=['main'],
    install_requires=['requests'],
    package_data={'': ['*.pyc']},
    include_package_data=True
)
```

#### 7.4 Wheel Building

Executes `setuptools` to create wheel:

**Command:**
```bash
python setup.py bdist_wheel --dist-dir public/
```

**Environment:**
- Preserves `PYTHONPATH` from current environment
- Adds `sys.path` to ensure dependencies are found

**Post-Processing:**
- If using `.pyc`, manually adds top-level `.pyc` files to wheel
- Uses `zipfile` to patch wheel if needed

**Output:**
- Wheel file: `{name}-{version}-py3-none-any.whl`
- Location: `build/public/`

### Phase 8: PyScript Configuration Update (`_update_pyscript_toml`)

Updates `pyscript.toml` with build artifacts:

#### 8.1 Package Section

**Process:**
1. Read existing packages from source `pyscript.toml`
2. Combine:
   - Generated wheel path: `./public/{name}-{version}-py3-none-any.whl`
   - Dependencies from `install_requires`
   - User-defined packages
3. Update or create `packages = [...]` section

**Example:**
```toml
packages = [
    "./public/my_app-1.0.0-py3-none-any.whl",
    "requests",
    "other-user-package"
]
```

#### 8.2 Files Section

**Process:**
1. Read existing files from source `pyscript.toml`
2. Merge:
   - Generated asset files (from build directory)
   - User-defined files (takes precedence)
3. Update or create `[files]` section

**File Mapping:**
- VFS path: `assets/logo.svg`
- Real path: `./assets/logo.svg`

**Example:**
```toml
[files]
"assets/logo.svg" = "./assets/logo.svg"
"assets/app.css" = "./assets/app.css"
```

#### 8.3 Update Strategy

**Line-by-Line Processing:**
- Preserves existing structure
- Updates `packages` and `[files]` sections
- Adds missing sections if needed
- Maintains comments and formatting where possible

### Phase 9: Cleanup

**Actions:**
1. Remove staging directory (`_wheel_staging`)
2. Save build cache
3. Print build completion message

## Build Cache System

### Cache File Location

`.metafor/cache.json` in source directory

### Cache Structure

```json
{
    "app/components/counter.ptml": "a1b2c3d4e5f6...",
    "app/assets/logo.svg": "f6e5d4c3b2a1...",
    "app/main.py": "1234567890ab..."
}
```

### Cache Operations

**Check if Changed:**
```python
if cache.is_changed(file_path):
    # Process file
    process_file(file_path)
    cache.update_cache(file_path)
```

**Hash Calculation:**
- Uses MD5 hash of file contents
- Binary read for consistency

**Cache Persistence:**
- Loaded at bundler initialization
- Saved after build completion
- Survives build restarts

## Parallel Compilation

### Process Pool Executor

Uses `concurrent.futures.ProcessPoolExecutor` for parallel PTML compilation:

**Benefits:**
- Multiple CPU cores utilized
- Faster compilation of large projects
- Independent process isolation

**Limitations:**
- Each task runs in separate process
- No shared state between tasks
- Process startup overhead

### Task Structure

```python
task = (file_path, target_dir)
# file_path: Path to .ptml file
# target_dir: Directory for compiled .py file
```

### Error Handling

- Exceptions in compilation stop the build
- Error messages include file path
- Failed tasks don't update cache

## Wheel Structure

### Generated Wheel Contents

```
my_app-1.0.0-py3-none-any.whl
├── my_app/
│   ├── __init__.pyc
│   ├── main.pyc
│   └── pages/
│       ├── __init__.pyc
│       └── dashboard.pyc
└── metafor/
    ├── __init__.pyc
    ├── core.pyc
    ├── dom.pyc
    └── ...
```

### Package Discovery

**Packages:**
- Directories with `__init__.py` (or `__init__.pyc`)
- Nested packages supported
- Path structure preserved

**Modules:**
- Top-level `.py` files (not in packages)
- Compiled to `.pyc` if `use_pyc=True`

## Configuration Files

### setup.py

**Required Fields:**
- `name` - Package name
- `version` - Package version

**Optional Fields:**
- `packages` - Auto-discovered if not specified
- `py_modules` - Auto-discovered if not specified
- `install_requires` - Dependencies list
- `package_data` - Additional data files

### pyscript.toml

**Sections:**
- `packages` - Python packages/wheels to load
- `[files]` - Virtual file system mappings

**Auto-Generated:**
- Wheel path added to packages
- Asset files added to [files]

## Build Output Structure

```
build/
├── index.html              # Copied from source
├── main.py                 # Copied from source
├── pyscript.toml           # Updated with packages/files
├── assets/                 # Copied assets
│   ├── logo.svg
│   └── app.css
└── public/                 # Wheel output
    └── my_app-1.0.0-py3-none-any.whl
```

## Usage

### Basic Usage

```python
from metafor.bundler import MetaforBundler

bundler = MetaforBundler(
    src_dir=".",
    out_dir="build",
    pyscript_toml="pyscript.toml",
    framework_dir="/path/to/metafor",
    use_pyc=True
)

bundler.build()
```

### Parameters

- `src_dir` - Source directory (default: ".")
- `out_dir` - Output directory (default: "build")
- `pyscript_toml` - Path to pyscript.toml (optional)
- `framework_dir` - Path to Metafor framework (optional)
- `use_pyc` - Compile to bytecode (default: True)

### CLI Integration

```bash
metafor build
```

Uses `metafor_cli/builder.py` which:
1. Locates framework directory
2. Creates bundler instance
3. Executes build

## Error Handling

### Compilation Errors

- PTML syntax errors stop build
- Error messages include file path and line numbers
- Stack traces preserved

### File System Errors

- Missing directories created automatically
- Permission errors reported clearly
- File not found errors handled gracefully

### Wheel Creation Errors

- `setuptools` errors reported
- Missing dependencies flagged
- Wheel patching failures logged

## Optimization Features

### Incremental Builds

- Cache-based change detection
- Only recompiles changed files
- Faster rebuild times

### Parallel Compilation

- Multi-core utilization
- Independent task execution
- Process isolation

### Bytecode Compilation

- Faster import times
- Source code protection
- Smaller distributions (if optimized)

## Limitations

1. **Process Isolation**: Parallel compilation uses separate processes (no shared state)
2. **Cache Invalidation**: Manual cache clearing required for some edge cases
3. **Dependency Resolution**: Doesn't install dependencies, only lists them
4. **Platform Specific**: Wheel format is platform-specific (py3-none-any is universal)

## Future Enhancements

Potential improvements:
- Watch mode for development
- Source maps for debugging
- Dependency installation
- Multiple output formats
- Plugin system for custom processing
- Build profiles (dev/prod)

