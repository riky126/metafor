import os
import shutil
import pathlib
import hashlib
import json
import concurrent.futures
from metafor.compiler import MetaforCompiler

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
            buf = f.read()
            hasher.update(buf)
        return hasher.hexdigest()

    def is_changed(self, file_path):
        file_path_str = str(file_path)
        current_hash = self.get_hash(file_path)
        cached_hash = self.cache.get(file_path_str)
        
        # Debug why it thinks it changed
        # if current_hash != cached_hash:
        #     print(f"[DEBUG] Changed: {file_path.name} | Old: {cached_hash} | New: {current_hash}")
        
        return current_hash != cached_hash

    def update_cache(self, file_path):
        file_path_str = str(file_path)
        self.cache[file_path_str] = self.get_hash(file_path)

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
                        if keyword.arg in ['name', 'version', 'packages', 'py_modules', 'install_requires', 'package_data', 'include_package_data']:
                            try:
                                value = ast.literal_eval(keyword.value)
                                self.setup_config[keyword.arg] = value
                            except ValueError:
                                if isinstance(keyword.value, ast.Call) and isinstance(keyword.value.func, ast.Name) and keyword.value.func.id == 'find_packages':
                                     # We handle package discovery manually, so we can ignore this or flag it
                                     pass
                                else:
                                    print(f"Warning: Could not evaluate value for setup argument '{keyword.arg}'")
                    break
        except Exception as e:
            print(f"Error parsing setup.py: {e}")

    def build(self):
        # Parse setup.py if it exists
        self._parse_setup_py()

        # Create output directory
        if not self.out_dir.exists():
            self.out_dir.mkdir(parents=True)
        
        # Create public dir for wheel
        public_dir = self.out_dir / "public"
        public_dir.mkdir(parents=True, exist_ok=True)

        print(f"Building from {self.src_dir} to {self.out_dir}...")
        
        # Staging directory for persistent intermediate files (compiled PTML -> PY, copies of PY)
        # We do NOT delete this, allowing incremental updates.
        wheel_staging = self.out_dir / "_incremental_staging"
        print(f"--- INCREMENTAL BUNDLER v2 ---")
        print(f"Staging dir: {wheel_staging.resolve()}")
        wheel_staging.mkdir(parents=True, exist_ok=True)
        print(f"Staging exists? {wheel_staging.exists()}")

        # Copy framework to staging (only if framework changed or doesn't exist)
        if self.framework_dir and self.framework_dir.exists():
            framework_target = wheel_staging / self.framework_dir.name
            # Check if any framework files changed
            framework_changed = False
            if not framework_target.exists():
                framework_changed = True
            else:
                # Check if any .py files in framework changed
                for root, dirs, files in os.walk(self.framework_dir):
                    for file in files:
                        if file.endswith('.py'):
                            file_path = pathlib.Path(root) / file
                            if self.cache.is_changed(file_path):
                                framework_changed = True
                                break
                    if framework_changed:
                        break
            
            if framework_changed:
                self._copy_framework(wheel_staging)
                # Update cache for all framework files
                for root, dirs, files in os.walk(self.framework_dir):
                    for file in files:
                        if file.endswith('.py'):
                            file_path = pathlib.Path(root) / file
                            self.cache.update_cache(file_path)

        # Collect tasks for parallel execution
        ptml_tasks = []
        
        # Track expected files in staging to cleanup deletions
        # Set of relative paths from staging root
        expected_staging_files = set()
        if self.framework_dir and self.framework_dir.exists():
            # Add framework files to expected
            framework_name = self.framework_dir.name
            for root, dirs, files in os.walk(wheel_staging / framework_name):
                # This is approximate, ideally we scan source structure.
                # But framework is copied wholesale, so we assume it's valid if we just synced it.
                # We can just ignore framework dir for pruning source files.
                pass
        
        # Walk through source directory
        for root, dirs, files in os.walk(self.src_dir):
            # Skip build directory and hidden directories
            dirs[:] = [d for d in dirs if not d.startswith('.') and d != self.out_dir.name and d != 'build' and d != 'public']
            
            for file in files:
                if file.startswith('.'): continue
                
                file_path = pathlib.Path(root) / file
                rel_path = file_path.relative_to(self.src_dir)
                
                # Exclude specific files from processing
                if file == 'pyscript.toml' or file == 'index.html' or file == 'build.py' or file.startswith('build_') or file == 'main.py' or file == 'setup.py':
                    if file == 'index.html' or file == 'pyscript.toml' or file == 'main.py':
                         target_file = self.out_dir / rel_path
                         if self.cache.is_changed(file_path) or not target_file.exists():
                             shutil.copy2(file_path, target_file)
                             self.cache.update_cache(file_path)
                    continue
                
                # Determine target: wheel staging for code, build dir for assets
                if file.endswith('.ptml') or file.endswith('.py'):
                    # Code goes to wheel staging
                    target_dir = wheel_staging / rel_path.parent
                    if not target_dir.exists(): target_dir.mkdir(parents=True)
                    
                    if file.endswith('.ptml'):
                        target_filename = file_path.with_suffix('.py').name
                        target_file = target_dir / target_filename
                        expected_staging_files.add(str((target_dir / target_filename).relative_to(wheel_staging)))
                        
                        if self.cache.is_changed(file_path) or not target_file.exists():
                            ptml_tasks.append((file_path, target_dir))
                    else:
                        if not file.startswith('test_'):
                             target_file = target_dir / file
                             expected_staging_files.add(str((target_dir / file).relative_to(wheel_staging)))
                             
                             if self.cache.is_changed(file_path) or not target_file.exists():
                                 shutil.copy2(file_path, target_dir)
                                 self.cache.update_cache(file_path)
                else:
                    # Assets go to build dir
                    target_dir = self.out_dir / rel_path.parent
                    if not target_dir.exists(): target_dir.mkdir(parents=True)
                    
                    target_file = target_dir / file
                    if self.cache.is_changed(file_path) or not target_file.exists():
                        shutil.copy2(file_path, target_dir)
                        self.cache.update_cache(file_path)
                    
                    # Track assets for [files] section
                    rel_to_out = target_file.relative_to(self.out_dir)
                    self.generated_files.append(rel_to_out)

        # Prune deleted files from staging
        # We only prune files that match patterns we manage (.py) and are not in framework
        # (Assuming framework dir name is unique/known)
        framework_prefix = self.framework_dir.name if (self.framework_dir and self.framework_dir.exists()) else "___nonexistent___"
        
        for root, dirs, files in os.walk(wheel_staging):
             rel_root = pathlib.Path(root).relative_to(wheel_staging)
             if str(rel_root).startswith(framework_prefix):
                 continue
                 
             for file in files:
                 if file.endswith('.py'):
                     rel_file = rel_root / file
                     if str(rel_file) not in expected_staging_files:
                         # File was deleted from source
                         # print(f"Pruning deleted file: {rel_file}")
                         os.remove(pathlib.Path(root) / file)

        # Execute PTML compilation in parallel
        if ptml_tasks:
            print(f"Compiling {len(ptml_tasks)} PTML file(s)...")
            with concurrent.futures.ProcessPoolExecutor() as executor:
                futures = [executor.submit(self._compile_ptml_task, task) for task in ptml_tasks]
                for future in concurrent.futures.as_completed(futures):
                    try:
                        file_path = future.result()
                        rel_path = file_path.relative_to(self.src_dir)
                        print(f"  → Compiled {rel_path}")
                        self.cache.update_cache(file_path)
                    except Exception as e:
                        print(f"Compilation failed: {e}")
                        raise e
        else:
            # print("No PTML files to compile (all up to date)")
            pass

        # Compile to .pyc in staging incrementally if needed
        # We do this IN STAGING so it persists
        if self.use_pyc:
             import py_compile
             for root, dirs, files in os.walk(wheel_staging):
                for file in files:
                    if file.endswith(".py") and file != "setup.py":
                        file_path = pathlib.Path(root) / file
                        pyc_path = file_path.with_suffix(".pyc")
                        
                        should_compile = False
                        if not pyc_path.exists():
                            should_compile = True
                        else:
                            if file_path.stat().st_mtime > pyc_path.stat().st_mtime:
                                should_compile = True
                        
                        if should_compile:
                            try:
                                # print(f"Compiling {file_path} -> {pyc_path}")
                                py_compile.compile(str(file_path), cfile=str(pyc_path), doraise=True)
                            except Exception as e:
                                print(f"Failed to compile {file_path}: {e}")

        # Create Wheel from staging
        # We COPY staging to a temp build dir because _create_wheel is destructive (pyc compilation)
        wheel_build_dir = self.out_dir / "_wheel_build_tmp"
        if wheel_build_dir.exists(): shutil.rmtree(wheel_build_dir)
        shutil.copytree(wheel_staging, wheel_build_dir)

        wheel_filename = f"{self.setup_config.get('name', 'metafor_app')}-{self.setup_config.get('version', '0.1.0')}-py3-none-any.whl"
        wheel_path = public_dir / wheel_filename
        
        # Check if wheel needs rebuilding
        # Since we synced staging, any change there implies we need a new wheel
        # Or if previous wheel is missing
        needs_wheel_rebuild = not wheel_path.exists()
        
        # Optimization: We could track if we actually copied/compiled anything above.
        # But we also need to check if existing wheel is older than staging (in case of interrupted build)
        if not needs_wheel_rebuild:
            # Check mtimes
             wheel_mtime = wheel_path.stat().st_mtime
             for root, dirs, files in os.walk(wheel_build_dir):
                for file in files:
                    file_path = pathlib.Path(root) / file
                    if file_path.stat().st_mtime > wheel_mtime:
                        needs_wheel_rebuild = True
                        break
                if needs_wheel_rebuild: break
        
        if needs_wheel_rebuild:
            # Pass the TEMP build dir to create_wheel
            self._create_wheel(wheel_build_dir, public_dir)
        else:
            print(f"Wheel up to date.")
        
        # Cleanup TEMP build dir, but KEEP staging
        shutil.rmtree(wheel_build_dir)
        
        # Save cache
        self.cache.save()

        # Update pyscript.toml
        if self.pyscript_toml:
            # We use the one copied to out_dir
            target_toml = self.out_dir / self.pyscript_toml.name
            if target_toml.exists():
                self._update_pyscript_toml(target_toml)
        
        # Print summary
        print("✓ Build complete")

    def _compile_ptml_task(self, task):
        file_path, target_dir = task
        # print statement removed to avoid subprocess stdout issues
        try:
            with open(file_path, 'r') as f:
                source = f.read()
            
            compiler = MetaforCompiler()
            filename = str(file_path)
            compiled_code = compiler.compile(source, filename=filename)
            
            target_filename = file_path.with_suffix('.py').name
            target_file = target_dir / target_filename
            with open(target_file, 'w') as f:
                f.write(compiled_code)
            return file_path
        except Exception as e:
            print(f"Error compiling {file_path}: {e}")
            raise e

    def _compile_ptml(self, file_path, target_dir):
        # Kept for compatibility if needed, but logic moved to _compile_ptml_task
        self._compile_ptml_task((file_path, target_dir))

    def _copy_framework(self, target_base):
        framework_name = self.framework_dir.name
        target_dir = target_base / framework_name
        if target_dir.exists():
             shutil.rmtree(target_dir)
        print(f"Copying framework from {self.framework_dir}...")
        shutil.copytree(self.framework_dir, target_dir, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.*'))

    def _create_wheel(self, staging_dir, output_dir):
        print("Creating wheel...")
        import py_compile
        
        # Find all top-level modules and packages
        packages = []
        py_modules = []
        
        # First, discover packages and modules BEFORE we delete .py files
        all_packages = []
        py_modules = []
        
        # We need to run find_packages on staging_dir.
        # Since we can't easily import find_packages here without potentially messing up (it's in setup.py context usually),
        # we will just do a manual walk for packages (directories with __init__.py).
        for root, dirs, files in os.walk(staging_dir):
            if "__init__.py" in files:
                rel_path = pathlib.Path(root).relative_to(staging_dir)
                if str(rel_path) == ".":
                    # Root directory modules
                    for file in files:
                        if file.endswith(".py") and file != "setup.py":
                            py_modules.append(file[:-3])
                    continue 
                package_name = str(rel_path).replace(os.sep, ".")
                all_packages.append(package_name)

        # Cleanup pass: Enforce use_pyc setting
        if self.use_pyc:
            # We want .pyc, so remove .py
             for root, dirs, files in os.walk(staging_dir):
                for file in files:
                    if file.endswith(".py") and file != "setup.py":
                        os.remove(pathlib.Path(root) / file)
        else:
             # We want .py, so remove .pyc
             for root, dirs, files in os.walk(staging_dir):
                for file in files:
                    if file.endswith(".pyc"):
                        os.remove(pathlib.Path(root) / file)
        
        # If we found no packages but we have modules, that's fine.
        
        package_data_spec = "{'': ['*.pyc']}" if self.use_pyc else "{'': ['*.py']}"
        
        # Merge with setup_config
        name = self.setup_config.get('name', 'metafor_app')
        version = self.setup_config.get('version', '0.1.0')
        
        # If packages is defined in setup_config, use it (unless it's find_packages() which we ignore)
        # But we actually want to use our discovered packages + whatever the user might have added?
        # Actually, for the wheel we are building FROM the staging dir, so we should rely on what we found in staging.
        # The user's setup.py might have 'packages=find_packages()', which refers to source.
        # We are building a wheel from staging.
        # So we stick to `all_packages` we found, unless the user explicitly lists packages?
        # Let's stick to `all_packages` for now as it reflects what we copied.
        
        # However, we should respect install_requires, package_data, etc.
        install_requires = self.setup_config.get('install_requires', [])
        
        # If package_data is in setup_config, we might want to merge it or use it.
        # The user provided spec: package_data={package_data_spec}
        # But if the user has custom package data in setup.py, we should probably use that?
        # The user said: "the bundler should add the miss 'packages={all_packages}, ...' to the setup config form the file."
        # This implies we take the file config and OVERRIDE/ADD our discovered stuff.
        
        # So let's construct the arguments dict
        setup_args = self.setup_config.copy()
        setup_args['packages'] = all_packages
        setup_args['py_modules'] = py_modules
        
        # For package_data, we want to ensure we include our .py/.pyc files.
        # If the user has package_data, we should merge or append.
        # But package_data is a dict.
        user_package_data = setup_args.get('package_data', {})
        # We want to ensure {'': ['*.pyc']} (or .py) is present.
        # Let's just force our spec for now as it's critical for the wheel to work.
        # Or better, merge it.
        if '' not in user_package_data:
             user_package_data[''] = []
        if self.use_pyc:
            if '*.pyc' not in user_package_data['']: user_package_data[''].append('*.pyc')
        else:
            if '*.py' not in user_package_data['']: user_package_data[''].append('*.py')
        
        setup_args['package_data'] = user_package_data
        setup_args['include_package_data'] = True
        
        # Construct the setup() call string
        # We need to format the args as a string representation
        args_str = ",\n    ".join(f"{k}={repr(v)}" for k, v in setup_args.items())
        
        setup_content = f"""
from setuptools import setup

setup(
    {args_str}
)
"""
        with open(staging_dir / "setup.py", "w") as f:
            f.write(setup_content)
            
        import subprocess
        import sys
        try:
            # We need to ensure setuptools is available.
            # We need to ensure setuptools is available.
            # We also pass the current environment to ensure PYTHONPATH is preserved if set.
            env = os.environ.copy()
            # Add current sys.path to PYTHONPATH to ensure dependencies are found
            # IMPORTANT: Convert to absolute paths because subprocess runs in a different directory
            current_pythonpath = env.get("PYTHONPATH", "")
            abs_sys_path = [str(pathlib.Path(p).absolute()) for p in sys.path]
            sys_path_str = os.pathsep.join(abs_sys_path)
            env["PYTHONPATH"] = f"{sys_path_str}{os.pathsep}{current_pythonpath}"
            
            subprocess.check_call([
                sys.executable, "setup.py", "bdist_wheel", "--dist-dir", str(output_dir.absolute())
            ], cwd=staging_dir, env=env)
            
            # Manually add top-level .pyc files to the wheel ONLY if use_pyc is True
            if self.use_pyc:
                # setuptools might skip them if source .py is missing and they are not in a package
                import zipfile
                wheel_files = list(output_dir.glob("*.whl"))
                if wheel_files:
                    wheel_path = wheel_files[0]
                    # print(f"Patching wheel {wheel_path} to include top-level modules...")
                    with zipfile.ZipFile(wheel_path, 'a') as zf:
                        for module in py_modules:
                            pyc_file = f"{module}.pyc"
                            pyc_path = staging_dir / pyc_file
                            if pyc_path.exists():
                                # print(f"Adding {pyc_file} to wheel")
                                zf.write(pyc_path, arcname=pyc_file)
            
            print(f"Wheel created in {output_dir}")
        except Exception as e:
            print(f"Failed to create wheel: {e}")

    def _update_pyscript_toml(self, toml_path):
        # print(f"Updating {toml_path}...")
        import tomllib

        # Read existing packages from the SOURCE TOML file using tomllib
        user_packages = []
        try:
            # self.pyscript_toml is the source file
            with open(self.pyscript_toml, "rb") as f:
                data = tomllib.load(f)
                user_packages = data.get("packages", [])
                user_files = data.get("files", {})
        except Exception as e:
            print(f"Warning: Could not parse {self.pyscript_toml} to read existing packages: {e}")

        with open(toml_path, 'r') as f:
            lines = f.readlines()
            
        new_lines = []
        in_files = False
        in_packages = False
        
        # We need to inject our wheel into packages
        # And assets into files
        
        wheel_filename = f"{self.setup_config.get('name', 'metafor_app')}-{self.setup_config.get('version', '0.1.0')}-py3-none-any.whl"
        wheel_path = f"./public/{wheel_filename}"
        
        packages_found = False
        files_found = False
        
        # Get dependencies from setup config
        dependencies = self.setup_config.get('install_requires', [])
        
        # Combine dependencies: wheel + install_requires + user_packages
        # Use a set to avoid duplicates, but preserve order roughly
        all_packages = [wheel_path]
        seen = {wheel_path}
        
        for dep in dependencies:
            if dep not in seen:
                all_packages.append(dep)
                seen.add(dep)
                
        for pkg in user_packages:
            if pkg not in seen:
                all_packages.append(pkg)
                seen.add(pkg)

        for line in lines:
            stripped = line.strip()
            
            # Handle [packages]
            if stripped.startswith('packages'):
                in_packages = True
                packages_found = True
                new_lines.append("packages = [\n")
                for pkg in all_packages:
                    new_lines.append(f'    "{pkg}",\n')
                new_lines.append("]\n")
                continue
            
            if in_packages:
                if stripped.endswith(']'):
                    in_packages = False
                continue

            # Handle [files]
            if stripped.startswith('[files]'):
                in_files = True
                files_found = True
                new_lines.append(line)
                
                # Merge files: generated first, then user overrides
                merged_files = {}
                for gen_file in self.generated_files:
                    vfs_path = str(gen_file)
                    real_path = f"./{gen_file}"
                    merged_files[vfs_path] = real_path
                
                # Update with user files
                merged_files.update(user_files)
                
                for vfs, real in merged_files.items():
                    new_lines.append(f'"{vfs}" = "{real}"\n')
                continue
            
            if in_files and stripped.startswith('['):
                in_files = False
                
            if not in_files:
                new_lines.append(line)
        
        if not packages_found:
             pkg_str = ", ".join([f'"{p}"' for p in all_packages])
             new_lines.insert(0, f'packages = [{pkg_str}]\n\n')
             
        if not files_found and self.generated_files:
            new_lines.append("\n[files]\n")
            for gen_file in self.generated_files:
                vfs_path = str(gen_file)
                real_path = f"./{gen_file}"
                new_lines.append(f'"{vfs_path}" = "{real_path}"\n')

        with open(toml_path, 'w') as f:
            f.writelines(new_lines)
