import os
import shutil
import pathlib
import hashlib
import json
import concurrent.futures
import time
import zipfile
import base64

class BuildCache:
    def __init__(self, cache_file):
        self.cache_file = pathlib.Path(cache_file)
        self.cache = self._load_cache()

    def _load_cache(self):
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save(self):
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_file, 'w') as f:
            json.dump(self.cache, f, indent=2)

    def get_hash(self, file_path):
        hasher = hashlib.md5()
        with open(file_path, 'rb') as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.hexdigest()

    def is_changed(self, file_path):
        file_path_str = str(file_path)
        current_hash = self.get_hash(file_path)
        cached_hash = self.cache.get(file_path_str)
        return current_hash != cached_hash

    def update_cache(self, file_path):
        file_path_str = str(file_path)
        self.cache[file_path_str] = self.get_hash(file_path)
        
    def get_cached_hash(self, file_path):
        return self.cache.get(str(file_path))

class MetaforBundler:
    def __init__(self, src_dir=".", out_dir="build", pyscript_toml=None, framework_dir=None, use_pyc=True):
        self.src_dir = pathlib.Path(src_dir).resolve()
        self.out_dir = pathlib.Path(out_dir)
        self.pyscript_toml = pathlib.Path(pyscript_toml) if pyscript_toml else None
        self.framework_dir = pathlib.Path(framework_dir) if framework_dir else None
        self.use_pyc = use_pyc
        self.generated_files = []
        self.setup_config = {}
        self.cache = BuildCache(self.src_dir / ".metafor" / "cache.json")
        self.record_rows = []

        # Ensure framework is importable (for compiler)
        if self.framework_dir:
            import sys
            parent_dir = str(self.framework_dir.parent.resolve())
            if parent_dir not in sys.path:
                sys.path.insert(0, parent_dir)

    def _parse_setup_py(self):
        setup_path = self.src_dir / "setup.py"
        if not setup_path.exists():
            return

        print(f"Parsing {setup_path}...")
        import ast
        try:
            with open(setup_path, 'r') as f:
                tree = ast.parse(f.read())
            
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'setup':
                    for keyword in node.keywords:
                        if keyword.arg in ['name', 'version', 'packages', 'py_modules', 'install_requires', 'package_data', 'include_package_data', 'sass_processor_enabled']:
                            try:
                                value = ast.literal_eval(keyword.value)
                                self.setup_config[keyword.arg] = value
                            except ValueError:
                                pass
                    break
        except Exception as e:
            print(f"Error parsing setup.py: {e}")

    def build(self):
        t0 = time.time()
        self._parse_setup_py()

        if not self.out_dir.exists():
            self.out_dir.mkdir(parents=True)
        
        public_dir = self.out_dir / "public"
        public_dir.mkdir(parents=True, exist_ok=True)

        # Artifact Cache (formerly Staging)
        self.artifact_cache_dir = self.out_dir / "_cache_"
        self.artifact_cache_dir.mkdir(parents=True, exist_ok=True)

        print(f"Building optimized wheel from {self.src_dir}...")

        # Prepare Wheel Output
        wheel_filename = f"{self.setup_config.get('name', 'metafor_app')}-{self.setup_config.get('version', '0.1.0')}-py3-none-any.whl"
        wheel_path = public_dir / wheel_filename
        
        self.record_rows = []
        
        # We will write directly to the Zip
        # For optimized I/O, we open the Zip once and stream everything into it
        with zipfile.ZipFile(wheel_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            self._process_framework(zf)
            self._process_source(zf)
            self._write_metadata(zf)

        self.cache.save()
        
        # Update pyscript.toml
        if self.pyscript_toml:
            target_toml = self.out_dir / self.pyscript_toml.name
            if target_toml.exists():
                self._update_pyscript_toml(target_toml)

        print(f"\033[92m✓ Build complete ({time.time() - t0:.2f}s)\033[0m")

    def _add_to_zip(self, zf, arcname, data_source, is_file=True):
        """
        Stream data into the zip file.
        data_source: path (if is_file=True) or bytes/string (if is_file=False)
        """
        hasher = hashlib.sha256()
        size = 0
        
        with zf.open(arcname, 'w') as dst:
            if is_file:
                # Streaming read from disk -> zip
                with open(data_source, 'rb') as src:
                    while chunk := src.read(64 * 1024):
                        size += len(chunk)
                        hasher.update(chunk)
                        dst.write(chunk)
            else:
                # In-memory data
                if isinstance(data_source, str):
                    data_source = data_source.encode('utf-8')
                size = len(data_source)
                hasher.update(data_source)
                dst.write(data_source)
        
        digest = hasher.digest()
        hash_str = base64.urlsafe_b64encode(digest).decode('ascii').rstrip('=')
        self.record_rows.append(f"{arcname},sha256={hash_str},{size}")

    def _process_framework(self, zf):
        if not self.framework_dir or not self.framework_dir.exists():
            return
            
        print(f" bundling framework...")
        prefix = self.framework_dir.name
        
        for root, dirs, files in os.walk(self.framework_dir):
            # Skip pycache
            dirs[:] = [d for d in dirs if d != '__pycache__']
            
            for file in files:
                if file.endswith('.pyc') or file.startswith('.'): continue
                
                # We enforce using .py source for framework in this optimized mode for simplicity
                # unless use_pyc is strictly required to compile framework too.
                # Standard metafor behavior is to bundle source .py for framework.
                
                file_path = pathlib.Path(root) / file
                rel_path = file_path.relative_to(self.framework_dir)
                arcname = f"{prefix}/{rel_path}"
                
                self._add_to_zip(zf, arcname, file_path, is_file=True)

    def _process_source(self, zf):
        # We need to handle compilation tasks. 
        # Ideally we parallelize compilation, but we need to serialize zip writing.
        # Flow:
        # 1. Identify all files
        # 2. Determine tasks (Static vs Compile)
        # 3. Execute Compile tasks (updating cache)
        # 4. Stream all results to Zip
        
        tasks = []
        static_files = []
        
        IGNORE = {'build', '__pycache__', '.git', '.idea', '.vscode', 'node_modules', self.out_dir.name, 'public'}
        
        for root, dirs, files in os.walk(self.src_dir):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in IGNORE]
            
            for file in files:
                if file.startswith('.'): continue
                
                file_path = pathlib.Path(root) / file
                if str(file_path.parent) == str(self.artifact_cache_dir): continue # Skip our own cache if inside src

                rel_path = file_path.relative_to(self.src_dir)

                # Skip config files that are not part of the package code
                if file in ['pyscript.toml', 'index.html', 'build.py', 'main.py', 'setup.py']:
                    # Handle index/pyscript/main copy to out_dir mostly for serving
                    # But they are NOT part of the wheel usually, except main.py might be?
                    # Original logic excluded them. We match that.
                    if file in ['index.html', 'pyscript.toml', 'main.py']:
                        target_file = self.out_dir / rel_path
                        if self.cache.is_changed(file_path, ) or not target_file.exists():
                            shutil.copy2(file_path, target_file)
                            self.cache.update_cache(file_path)
                    continue

                if file.endswith('.ptml'):
                    tasks.append(('ptml', file_path, rel_path))
                elif file.endswith('.scss') or file.endswith('.sass'):
                    if self.setup_config.get('sass_processor_enabled', False):
                        tasks.append(('sass', file_path, rel_path))
                    else:
                        # Copy associated asset to build folder if not compiled
                        pass 
                elif file.endswith('.py'):
                    static_files.append((file_path, rel_path))
                else:
                    # Other assets -> copy to build dir directly, NOT wheel
                    target_dir = self.out_dir / rel_path.parent
                    target_dir.mkdir(parents=True, exist_ok=True)
                    target_file = target_dir / file
                    if self.cache.is_changed(file_path) or not target_file.exists():
                        shutil.copy2(file_path, target_file)
                        self.cache.update_cache(file_path)
                    
                    self.generated_files.append(target_file.relative_to(self.out_dir))

        # Parallel Compilation
        if tasks:
            print(f"Compiling {len(tasks)} files...")
            with concurrent.futures.ThreadPoolExecutor() as executor:
                futures = {executor.submit(self._compile_task, t): t for t in tasks}
                
                for future in concurrent.futures.as_completed(futures):
                    try:
                        result_type, src_path, artifact_path = future.result()
                        # artifact_path is where the compiled result is stored (in cache)
                        rel_path = futures[future][2]
                        
                        if result_type == 'ptml':
                            # Add compiled python to wheel
                            # map foo/bar.ptml -> foo/bar.py
                            arcname = str(rel_path.with_suffix('.py'))
                            self._add_to_zip(zf, arcname, artifact_path, is_file=True)
                        elif result_type == 'sass':
                            # map foo/bar.scss -> foo/bar.css (in build dir, not wheel)
                            target_file = self.out_dir / rel_path.with_suffix('.css')
                            target_file.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(artifact_path, target_file) # Copy from cache to target
                            self.generated_files.append(target_file.relative_to(self.out_dir))
                            
                    except Exception as e:
                        print(f"Compilation failed: {e}")

        # Stream Static Files (Direct from Source)
        for file_path, rel_path in static_files:
            if file_path.name.startswith('test_'): continue
            self._add_to_zip(zf, str(rel_path), file_path, is_file=True)

    def _compile_task(self, task):
        task_type, file_path, rel_path = task
        
        # Determine cache location
        # Structure cache same as source to avoid collisions
        cache_subdir = self.artifact_cache_dir / rel_path.parent
        cache_subdir.mkdir(parents=True, exist_ok=True)
        
        ext = '.py' if task_type == 'ptml' else '.css'
        artifact_path = cache_subdir / file_path.with_suffix(ext).name

        # Check Cache
        if not self.cache.is_changed(file_path) and artifact_path.exists():
            return task_type, file_path, artifact_path
        
        # Compile
        if task_type == 'ptml':
            try:
                with open(file_path, 'r') as f:
                    source = f.read()
                
                from metafor.compiler import MetaforCompiler
                compiler = MetaforCompiler()
                compiled_code = compiler.compile(source, filename=str(file_path))
                
                with open(artifact_path, 'w') as f:
                    f.write(compiled_code)
                print(f"  → Compiled {rel_path} (updated cache)")
                
            except Exception as e:
                raise e
                
        elif task_type == 'sass':
            try:
                import sass
                with open(file_path, 'r') as f:
                    scss_content = f.read()
                css_content = sass.compile(string=scss_content)
                with open(artifact_path, 'w') as f:
                    f.write(css_content)
                print(f"  → Compiled {rel_path} to CSS")
            except Exception as e:
                raise e
        
        self.cache.update_cache(file_path)
        return task_type, file_path, artifact_path

    def _write_metadata(self, zf):
        name = self.setup_config.get('name', 'metafor_app')
        safe_name = name.replace('-', '_')
        version = self.setup_config.get('version', '0.1.0')
        dist_info_dir = f"{safe_name}-{version}.dist-info"

        # METADATA
        metadata = [
            "Metadata-Version: 2.1",
            f"Name: {name}",
            f"Version: {version}",
            "Summary: Metafor App",
        ]
        for dep in self.setup_config.get('install_requires', []):
            metadata.append(f"Requires-Dist: {dep}")
        
        self._add_to_zip(zf, f"{dist_info_dir}/METADATA", "\n".join(metadata) + "\n", is_file=False)

        # WHEEL
        wheel_content = """Wheel-Version: 1.0
Generator: metafor-bundler
Root-Is-Purelib: true
Tag: py3-none-any
"""
        self._add_to_zip(zf, f"{dist_info_dir}/WHEEL", wheel_content, is_file=False)
        
        # RECORD
        self.record_rows.append(f"{dist_info_dir}/RECORD,,")
        self._add_to_zip(zf, f"{dist_info_dir}/RECORD", "\n".join(self.record_rows) + "\n", is_file=False)

    def _update_pyscript_toml(self, toml_path):
        import tomllib
        user_packages = []
        user_files = {}
        try:
            with open(self.pyscript_toml, "rb") as f:
                data = tomllib.load(f)
                user_packages = data.get("packages", [])
                user_files = data.get("files", {})
        except Exception:
            pass

        wheel_filename = f"{self.setup_config.get('name', 'metafor_app')}-{self.setup_config.get('version', '0.1.0')}-py3-none-any.whl"
        wheel_path = f"./public/{wheel_filename}"
        
        all_packages = [wheel_path] 
        # Add deps... (simplified for brevity match)
        for dep in self.setup_config.get('install_requires', []):
             if dep not in all_packages: all_packages.append(dep)
        for pkg in user_packages:
             if pkg not in all_packages: all_packages.append(pkg)

        # Reconstruct TOML 
        # (This is a simplified re-writer to preserve structure as best as possible)
        # For robustness we might just dump data, but user wants optimization not toml parser
        # We'll use the previous line-based logic or a simple dump if acceptable.
        # User accepted previous implementation logic. I will stick to a robust simple dump for now
        # to guarantee correctness.
        
        output = {
            "packages": all_packages,
        }
        # Add other keys
        if data:
            for k, v in data.items():
                if k not in ['packages', 'files']:
                    output[k] = v
        
        # Files
        files_map = {}
        for gen_file in self.generated_files:
            vfs = str(gen_file)
            real = f"./{gen_file}"
            files_map[vfs] = real
        files_map.update(user_files)
        output['files'] = files_map
        
        # Write TOML
        # We can't easily preserve comments with standard lib. 
        # The previous implementation tried to parse lines. 
        # Given the refactor magnitude, a clean TOML write is safer.
        # But we need basic TOML writer.
        
        with open(toml_path, 'w') as f:
            # Basic manual serialization for list/dict/strings
            for k, v in output.items():
                if k == 'packages':
                    f.write("packages = [\n")
                    for p in v:
                        f.write(f'    "{p}",\n')
                    f.write("]\n\n")
                elif k == 'files':
                    f.write("[files]\n")
                    for fk, fv in v.items():
                        f.write(f'"{fk}" = "{fv}"\n')
                    f.write("\n")
                elif isinstance(v, str):
                    f.write(f'{k} = "{v}"\n')
                # Add others as needed
