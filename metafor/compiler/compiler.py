from .tokenizer import PTMLTokenizer
from .parser import PTMLParser
from .code_generator import CodeGenerator

class BlockParser:
    def __init__(self):
        self.blocks = {}
        self.context_blocks = []
    
    def parse(self, source):
        self.blocks = {}
        self.context_blocks = []
        
        pos = 0
        last_pos = 0
        length = len(source)
        
        while pos < length:
            try: at_index = source.index('@', pos)
            except ValueError: break
            pos = at_index + 1
            start_id = pos
            while pos < length and source[pos].isalnum(): pos += 1
            name = source[start_id:pos]
            
            # Enforce <- before @context
            if name == 'context':
                preceding_text = source[last_pos:at_index]
                if '<-' not in preceding_text:
                     raise SyntaxError(f"Context block at line {source[:at_index].count(chr(10)) + 1} must be preceded by '<-'")

            # Determine block type
            is_special = name in ('component', 'page', 'ptml', 'style') or name == 'context'
            
            while pos < length and source[pos].isspace(): pos += 1
            args = ""
            if pos < length and source[pos] == '(':
                start_args = pos
                p_count = 0
                while pos < length:
                    if source[pos] == '(': p_count += 1
                    elif source[pos] == ')': p_count -= 1
                    pos += 1
                    if p_count == 0: break
                args = source[start_args:pos]
                while pos < length and source[pos].isspace(): pos += 1
            
            # Handle @WrapperName for context blocks
            wrapper_name = None
            if name == 'context' and pos < length and source[pos] == '@':
                pos += 1
                start_wrapper = pos
                while pos < length and source[pos].isalnum(): pos += 1
                wrapper_name = source[start_wrapper:pos]
                while pos < length and source[pos].isspace(): pos += 1

            content = ""
            if pos < length and source[pos] == '{':
                start_brace = pos
                b_count = 0
                while pos < length:
                    if source[pos] == '{': b_count += 1
                    elif source[pos] == '}': b_count -= 1
                    pos += 1
                    if b_count == 0: break
                content = source[start_brace+1 : pos-1]
                # Calculate start line (1-based)
                start_line = source[:start_brace].count('\n') + 1
                
                block_data = {'args': args, 'content': content, 'start_line': start_line}
                if wrapper_name:
                    block_data['wrapper_name'] = wrapper_name
                    
                if name == 'context':
                    self.context_blocks.append(block_data)
                else:
                    self.blocks[name] = block_data
            else:
                if name != 'context':
                    # Fallback for user defined property blocks without content (if any?)
                    # Most user blocks are @props { ... }
                    self.blocks[name] = {'args': args, 'content': '', 'start_line': 0}
            
            last_pos = pos
            
        return self.blocks, self.context_blocks

class BlockProcessor:
    def __init__(self, compiler_instance):
        self.compiler = compiler_instance # Need access to _compile_ptml
        self.component_name = "Component"
        self.page_uri = None
        self.imports = []
        self.props_config = {}
        self.body_code = []
        self.props_block_name = "props"
        self.has_props_block = False

    def process(self, blocks, context_blocks):
        self._validate_required_blocks(blocks)
        self._extract_metadata(blocks)
        
        # Process logic from props, component, and page blocks
        blocks_to_process = []
        if self.props_block_name in blocks:
            blocks_to_process.append((self.props_block_name, blocks[self.props_block_name]))
        if 'component' in blocks and blocks['component']['content']:
            blocks_to_process.append(('component', blocks['component']))
        if 'page' in blocks and blocks['page']['content']:
            blocks_to_process.append(('page', blocks['page']))
            
        for ctx_block in context_blocks:
            blocks_to_process.append(('context', ctx_block))

        for block_name, block_data in blocks_to_process:
            self._process_single_block(block_name, block_data)
            
        self._validate_context_blocks(context_blocks)
        
        return {
            'component_name': self.component_name,
            'page_uri': self.page_uri,
            'imports': self.imports,
            'props_config': self.props_config,
            'body_code': self.body_code,
            'props_block_name': self.props_block_name
        }

    def _validate_required_blocks(self, blocks):
        if 'component' in blocks and 'page' in blocks:
            raise ValueError("A file cannot contain both @component and @page blocks.")
        if 'component' not in blocks and 'page' not in blocks:
             raise ValueError("File must contain either a @component or @page block.")
        if 'ptml' not in blocks:
             raise ValueError("File must contain a @ptml block.")
        
        # Determine props block name (any block that isn't special)
        for name in blocks:
            if name not in ('component', 'page', 'ptml', 'style', 'context'):
                self.props_block_name = name
                self.has_props_block = True
                break

    def _extract_metadata(self, blocks):
        if 'component' in blocks:
            args = blocks['component']['args']
            if args:
                if args.startswith('(') and args.endswith(')'): args = args[1:-1]
                self.component_name = args.strip('"\'')
        
        if 'page' in blocks:
            args = blocks['page']['args']
            if args:
                if args.startswith('(') and args.endswith(')'): args = args[1:-1]
                parts = [p.strip() for p in args.split(',')]
                if len(parts) >= 1:
                    self.page_uri = parts[0]
                if len(parts) >= 2:
                    self.component_name = parts[1].strip('"\'')

    def _process_single_block(self, block_name, block_data):
        content = block_data['content']
        start_line = block_data['start_line']
        
        content = self._transform_inline_ptml(content)
        
        import textwrap
        dedented_content = textwrap.dedent(content)
        lines = dedented_content.split('\n')
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped: continue
            
            original_line = start_line + i

            if stripped.startswith('from ') or stripped.startswith('import '):
                self.imports.append(stripped)
            elif stripped.startswith('@prop '):
                self._parse_prop_line(stripped)
            elif block_name == 'context' and stripped.startswith('@value '):
                parts = stripped[7:].split('=', 1)
                if len(parts) == 2:
                    block_data['data_var'] = parts[0].strip()
                    block_data['data_value'] = parts[1].strip()
            elif block_name != 'context':
                self._process_body_line(line, stripped, original_line)

    def _process_body_line(self, line, stripped, original_line):
        if '@props' in line and self.props_block_name != 'props':
            raise ValueError(f"Cannot use @props when block is named @{self.props_block_name}. Use @{self.props_block_name} instead.")
        
        if '@props' in line and not self.has_props_block:
             raise ValueError("Cannot use @props when no @props block is defined.")

        if not self.has_props_block:
            import re
            if re.search(r'\b' + re.escape(self.props_block_name) + r'\b', line):
                 raise ValueError(f"Cannot access '{self.props_block_name}' when no @{self.props_block_name} block is defined.")

        if self.has_props_block:
             line = line.replace(f'@{self.props_block_name}', self.props_block_name)
        
        if '@props' in line:
             line = line.replace('@props', 'props')

        self.body_code.append((line.rstrip(), original_line))

    def _parse_prop_line(self, line):
        parts = line[6:].split(':', 1)
        if len(parts) < 2: return
        name = parts[0].strip()
        rest = parts[1]
        if '=' in rest: type_str, default = rest.split('=', 1)
        else: type_str, default = rest, "None"
        self.props_config[name] = {'type': type_str.strip(), 'default': default.strip()}
    
    def _validate_context_blocks(self, context_blocks):
        for ctx_block in context_blocks:
            if not ctx_block.get('wrapper_name'):
                raise SyntaxError(f"Context block starting at line {ctx_block['start_line']} is missing an output variable name (e.g., @MyApp).")
            if not ctx_block.get('args'):
                raise SyntaxError(f"Context block starting at line {ctx_block['start_line']} is missing the Context class argument (e.g., @context(ThemeContext)).")
            if 'data_value' not in ctx_block:
                raise SyntaxError(f"Context block starting at line {ctx_block['start_line']} is missing a @value declaration.")

    def _transform_inline_ptml(self, content):
        output = []
        pos = 0
        length = len(content)
        
        while pos < length:
            start_t = content.find('@t{', pos)
            start_tag = content.find('@:', pos)
            
            if start_t == -1 and start_tag == -1:
                output.append(content[pos:])
                break
            
            if start_t != -1 and (start_tag == -1 or start_t < start_tag):
                output.append(content[pos:start_t])
                brace_start = start_t + 2
                current = brace_start + 1
                balance = 1
                while current < length:
                    if content[current] == '{': balance += 1
                    elif content[current] == '}': 
                        balance -= 1
                        if balance == 0: break
                    current += 1
                
                if balance != 0: raise SyntaxError("Unclosed inline PTML block starting with @t{")
                
                ptml_content = content[brace_start+1 : current]
                compiled_code = self.compiler._compile_ptml(ptml_content, block_name="inline PTML")
                output.append(compiled_code)
                pos = current + 1
            else:
                output.append(content[pos:start_tag])
                current = start_tag + 2
                while current < length and content[current].isspace(): current += 1
                
                if current >= length or content[current] != '<':
                    output.append(content[start_tag:current])
                    pos = current
                    continue
                
                end_index = self._find_inline_ptml_tag_end(content, current)
                if end_index == -1: raise SyntaxError("Unclosed inline PTML tag starting with @:")
                
                ptml_content = content[current : end_index]
                compiled_code = self.compiler._compile_ptml(ptml_content, block_name="inline PTML")
                output.append(compiled_code)
                pos = end_index

        return "".join(output)

    def _find_inline_ptml_tag_end(self, content, start_index):
        pos = start_index
        length = len(content)
        depth = 0
        in_string = False
        quote_char = None
        
        while pos < length:
            if in_string:
                if content[pos] == quote_char and (pos == 0 or content[pos-1] != '\\'):
                    in_string = False; quote_char = None
                pos += 1; continue
                
            char = content[pos]
            if char == '"' or char == "'":
                in_string = True; quote_char = char; pos += 1; continue
            
            if char == '@' and pos + 1 < length and content[pos+1] == '{':
                pos += 2; balance = 1
                while pos < length:
                    if content[pos] == '{': balance += 1
                    elif content[pos] == '}': 
                        balance -= 1
                        if balance == 0: break
                    pos += 1
                pos += 1; continue

            if char == '<' and content.startswith('<!--', pos):
                pos += 4; end_comment = content.find('-->', pos)
                if end_comment == -1: return -1
                pos = end_comment + 3; continue

            if char == '<':
                if content.startswith('</', pos):
                    depth -= 1; end_tag = content.find('>', pos)
                    if end_tag == -1: return -1
                    pos = end_tag + 1; 
                    if depth == 0: return pos
                    continue
                else:
                    depth += 1; pos += 1; continue
            
            if char == '>' and pos > 0 and content[pos-1] == '/':
                depth -= 1
                if depth == 0: return pos + 1
            
            pos += 1
        return -1


class ModuleCodeGenerator:
    def __init__(self):
        self.generated_line_map = {}

    def generate(self, ctx, ptml_dom_code, style_block=None, context_blocks=None, filename=None):
        code = []
        self.generated_line_map = {}
        
        code.append("from metafor.core import unwrap, create_signal")
        code.append("from metafor.hooks import create_memo")
        code.append("from metafor.dom import t, load_css")
        code.append("from metafor.components import Show, For, Switch, Match, Portal, Suspense, ErrorBoundary")
        code.append("from metafor.decorators import component, page") 
        code.append("from metafor.context import ContextProvider") 
        
        code.extend(ctx['imports'])
        code.append("")

        css_kwarg = self._process_styles(code, style_block, filename)
        
        self._generate_component_def(code, ctx, css_kwarg, ptml_dom_code, context_blocks)
        
        return "\n".join(code), self.generated_line_map

    def _process_styles(self, code, style_block, filename=None):
        if not style_block: return "None"
        
        args_str = style_block.get('args', '')
        style_args = self._parse_args_string(args_str)
        
        src = style_args.get('src')
        name = style_args.get('name')
        scope = style_args.get('scope', 'scoped')
        lang = style_args.get('lang', 'css')
        
        style_parts = []
        inline = style_block["content"].strip()

        # Handle Sass/SCSS compilation
        if lang in ('sass', 'scss'):
            import sass
            import os
            import tempfile
            
            if inline:
                # Create temp file
                # User requested .scss extension specifically
                suffix = '.scss' if lang == 'sass' else f'.{lang}'
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False, mode='w') as tmp:
                    tmp.write(inline)
                    tmp_path = tmp.name
                
                try:
                    # Compile Sass
                    include_paths = []
                    if filename:
                        include_paths.append(os.path.dirname(os.path.abspath(filename)))
                        
                    compiled_css = sass.compile(filename=tmp_path, include_paths=include_paths)
                    inline = compiled_css.strip()
                except Exception as e:
                    print(f"Sass compilation failed: {e}")
                    raise e
                finally:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)

            if src:
                if src.endswith('.sass') or src.endswith('.scss'):
                     # We change the generated code to load .css instead
                     src = src.rsplit('.', 1)[0] + '.css'

        if inline:
            code.append(f'inline_styles = """{inline}"""')
            style_parts.append('inline_styles')
        
        if name:
            code.append(f'loaded_styles = load_css(css_path="{name}")')
            style_parts.append('loaded_styles')
        elif src:
            code.append(f'loaded_styles = load_css(css_path="{src}")')
            style_parts.append('loaded_styles')
            
        if style_parts:
            combined_styles = " + '\\n' + ".join(style_parts)
            code.append(f'app_styles = {combined_styles}')
            return f'{{"{scope}": app_styles}}'
        return "None"

    def _generate_component_def(self, code, ctx, css_kwarg, dom_code, context_blocks):
        props_str = "{" + ", ".join([f"'{k}': ({v['type']}, {v['default']})" for k, v in ctx['props_config'].items()]) + "}"
        
        if ctx['page_uri']:
             code.append(f"@page({ctx['page_uri']}, props={props_str})")
        else:
             code.append(f"@component(props={props_str})")
             
        code.append(f"def {ctx['component_name']}(**{ctx['props_block_name']}):")
        
        for name in ctx['props_config']:
            code.append(f"    {name} = {ctx['props_block_name']}.get('{name}')")
            
        current_gen_line = 0
        for s in code:
            current_gen_line += s.count('\n') + 1

        for line, original_line in ctx['body_code']:
            code.append(f"    {line}")
            current_gen_line += 1
            self.generated_line_map[current_gen_line] = original_line
            
        if dom_code.startswith('['):
             code.append(f"    return t.div({{}}, {dom_code}, css={css_kwarg})")
        else:
             code.append(f"    return t.div({{}}, [{dom_code}], css={css_kwarg})")

        if context_blocks:
            self._generate_context_providers(code, context_blocks, ctx['component_name'])

    def _generate_context_providers(self, code, context_blocks, component_name):
        current_child = component_name
        for ctx_block in reversed(context_blocks):
            args = ctx_block.get('args', '').strip()
            if args.startswith('(') and args.endswith(')'): args = args[1:-1]
            context_class = args
            data_value = ctx_block.get('data_value', 'None')
            current_child = f"ContextProvider({context_class}, {data_value}, {current_child})"
        
        outer_wrapper_name = context_blocks[0].get('wrapper_name')
        if outer_wrapper_name and outer_wrapper_name != 'self':
                code.append(f"{outer_wrapper_name} = {current_child}")

    def _parse_args_string(self, args_str):
        if not args_str: return {}
        if args_str.startswith('(') and args_str.endswith(')'): args_str = args_str[1:-1]
        parts = [p.strip() for p in args_str.split(',')]
        result = {}
        for part in parts:
            if '=' in part:
                key, value = part.split('=', 1)
                result[key.strip()] = value.strip().strip('"\'')
        return result


class ScopeValidator:
    def validate(self, code, generated_line_map, component_name, props_block_name, filename):
        import ast
        import builtins
        
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return
        
        func_def = None
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == component_name:
                func_def = node; break
        
        if not func_def: return

        defined = set(dir(builtins))
        defined.update(['unwrap', 'create_signal', 'create_memo', 't', 'load_css', 
                        'Show', 'For', 'Switch', 'Match', 'Portal', 'Suspense', 'ErrorBoundary',
                        'component', 'page', 'styles', 'ContextProvider',
                        'console', 'window', 'document', 'js'])
        
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name): defined.add(target.id)
            elif isinstance(node, ast.AnnAssign):
                 if isinstance(node.target, ast.Name): defined.add(node.target.id)
            elif isinstance(node, ast.ImportFrom):
                for n in node.names: defined.add(n.asname or n.name)
            elif isinstance(node, ast.Import):
                for n in node.names: defined.add(n.asname or n.name)

        for arg in func_def.args.kwonlyargs: defined.add(arg.arg)
        if func_def.args.kwarg: defined.add(func_def.args.kwarg.arg)
        
        for node in ast.walk(func_def):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for arg in node.args.args: defined.add(arg.arg)
                for arg in node.args.kwonlyargs: defined.add(arg.arg)
                if node.args.vararg: defined.add(node.args.vararg.arg)
                if node.args.kwarg: defined.add(node.args.kwarg.arg)
            elif isinstance(node, ast.Lambda):
                for arg in node.args.args: defined.add(arg.arg)
                for arg in node.args.kwonlyargs: defined.add(arg.arg)
                if node.args.vararg: defined.add(node.args.vararg.arg)
                if node.args.kwarg: defined.add(node.args.kwarg.arg)
            elif isinstance(node, (ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp)):
                for generator in node.generators:
                    if isinstance(generator.target, ast.Name): defined.add(generator.target.id)
                    elif isinstance(generator.target, ast.Tuple):
                        for elt in generator.target.elts:
                            if isinstance(elt, ast.Name): defined.add(elt.id)
            elif isinstance(node, ast.ExceptHandler):
                if node.name: defined.add(node.name)
        
        assigned_in_func = set()
        for node in ast.walk(func_def):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                assigned_in_func.add(node.id)
                if node.id == props_block_name:
                     original_line = generated_line_map.get(node.lineno, "?")
                     location = f"'{filename}'" if filename else f"component '{component_name}'"
                     raise ValueError(f"Variable '{node.id}' is already defined as the props block name in {location} at line {original_line}")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                assigned_in_func.add(node.name)
                if node.name == props_block_name:
                     original_line = generated_line_map.get(node.lineno, "?")
                     raise ValueError(f"Function/Class '{node.name}' shadows the props block name in {filename} at line {original_line}")
        
        defined.update(assigned_in_func)
        
        for node in ast.walk(func_def):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                if node.id not in defined:
                    original_line = generated_line_map.get(node.lineno, "?")
                    location = f"'{filename}'" if filename else f"component '{component_name}'"
                    raise ValueError(f"Undefined variable '{node.id}' in {location} at line {original_line}")


class MetaforCompiler:
    def __init__(self):
        self.filename = None
        self.static_counter = 0

    def _compile_ptml(self, ptml_content, block_name="@ptml"):
        try:
            tokenizer = PTMLTokenizer(ptml_content)
            tokens = tokenizer.tokenize()
            parser = PTMLParser(tokens)
            nodes = parser.parse()
        except SyntaxError as e:
            location = f"'{self.filename}'" if self.filename else "unknown file"
            raise SyntaxError(f"{e} in {block_name} in {location}") from e
        
        generator = CodeGenerator(start_index=self.static_counter)
        dom_code = generator.generate(nodes, indent=0)
        self.static_counter = generator.static_counter
        return dom_code

    def compile(self, source, filename=None):
        self.filename = filename
        
        parser = BlockParser()
        blocks, context_blocks = parser.parse(source)
        
        processor = BlockProcessor(self)
        processed_data = processor.process(blocks, context_blocks)
        
        ptml_code = "None"
        if 'ptml' in blocks:
            ptml_code = self._compile_ptml(blocks['ptml']['content'])
            
        style_block = blocks.get('style')
        
        generator = ModuleCodeGenerator()
        generator = ModuleCodeGenerator()
        final_code, line_map = generator.generate(processed_data, ptml_code, style_block, context_blocks, filename=self.filename)
        
        validator = ScopeValidator()
        validator.validate(final_code, line_map, processed_data['component_name'], 
                         processed_data['props_block_name'], self.filename)
        
        return final_code
