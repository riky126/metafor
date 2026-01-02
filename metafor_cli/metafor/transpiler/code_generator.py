import enum
import re
from .tokenizer import JSXTokenizer
from .parser import JSXParser, JSXElement, JSXText, JSXExpression

class ComponentType(enum.Enum):
    SHOW = "Show"
    FOR = "For"
    FOR_EACH = "ForEach"
    SWITCH = "Switch"
    MATCH = "Match"
    SUSPENSE = "Suspense"
    ERROR_BOUNDARY = "ErrorBoundary"
    PORTAL = "Portal"

class JSXCodeGenerator:
    def __init__(self, text_as_code=False, css_variable=None):
        self.text_as_code = text_as_code
        self.css_variable = css_variable
        self.in_svg = False

    def generate(self, nodes):
        if not nodes:
            return "None"
        
        if self.text_as_code:
            # Join all nodes as raw code string
            return "".join([str(self.visit(node) or "") for node in nodes])
        
        # Filter out None nodes (comments)
        # Pass is_root=True to the first element if we have a css_variable
        visited_nodes = []
        first_element_processed = False
        
        for node in nodes:
            if not first_element_processed and isinstance(node, JSXElement) and self.css_variable:
                visited = self.visit(node, is_root=True)
                first_element_processed = True
            else:
                visited = self.visit(node)
            visited_nodes.append(visited)

        elements = [el for el in visited_nodes if el is not None]
        
        if not elements:
            return "None"
            
        if len(elements) == 1:
            return elements[0]
        else:
            # Return a list of elements
            return f"[{', '.join(elements)}]"

    def visit(self, node, indent=0, is_root=False):
        if isinstance(node, JSXElement):
            return self.visit_element(node, indent, is_root)
        elif isinstance(node, JSXText):
            return self.visit_text(node)
        elif isinstance(node, JSXExpression):
            return self.visit_expression(node)
        else:
            raise ValueError(f"Unknown node type: {type(node)}")

    def visit_element(self, node, indent, is_root=False):
        if node.tag_name is None:
            # Fragment -> return list of children
            children_code = [self.visit(child) for child in node.children]
            # Filter out empty strings/None
            children_code = [c for c in children_code if c]
            return f"[{', '.join(children_code)}]"

        tag_name = node.tag_name

        # SVG Context Handling
        was_in_svg = self.in_svg
        
        # Determine if this specific tag needs namespace
        # It needs namespace if:
        # 1. It is <svg> tag itself.
        # 2. We are currently in SVG context (was_in_svg is True).
        needs_namespace = (was_in_svg or tag_name == "svg") and not (tag_name[0].isupper() or "." in tag_name)

        # Update state for children
        if tag_name == "svg":
            self.in_svg = True
        elif tag_name == "foreignObject":
            self.in_svg = False
        
        # Attributes
        attrs_parts = []
        for k, v in node.attributes.items():
            # Map className -> class_name
            if k == "className":
                k = "class_name"
                
            # v can be string or JSXExpression
            if isinstance(v, JSXExpression):
                val_code = self.process_expression_content(v.expression)
                attrs_parts.append(f'"{k}": {val_code}')
            else:
                attrs_parts.append(f'"{k}": "{v}"')
        
        attrs_str = "{" + ", ".join(attrs_parts) + "}"
        
        # Children
        # Temporarily disable text_as_code for children, as they must be expressions in a list
        was_text_as_code = self.text_as_code
        self.text_as_code = False
        
        children_parts = []
        for child in node.children:
            visited = self.visit(child, indent + 1)
            if visited is not None:
                children_parts.append(visited)
            
        self.text_as_code = was_text_as_code # Restore state
        self.in_svg = was_in_svg # Restore SVG state

        if not children_parts:
            children_str = "[]"
        else:
            children_str = "[\n" + ",\n".join([f"{'  ' * (indent + 1)}{c}" for c in children_parts]) + f"\n{'  ' * indent}]"

        # Helper to get meaningful children (excluding whitespace-only text)
        def is_comment(n):
            return isinstance(n, JSXExpression) and n.expression.strip().startswith('/*') and n.expression.strip().endswith('*/')

        meaningful_children = [c for c in node.children if not (isinstance(c, JSXText) and not c.value.strip()) and not is_comment(c)]

        # Helper to generate kwargs string for function calls
        def get_kwargs_str(mapping=None, wrap_lambdas=None):
            if mapping is None:
                mapping = {}
            if wrap_lambdas is None:
                wrap_lambdas = []
                
            parts = []
            for k, v in node.attributes.items():
                # Map attribute name if needed
                # Automatic mapping for className
                if k == "className":
                    arg_name = "class_name"
                else:
                    arg_name = mapping.get(k, k)
                
                # v can be string or JSXExpression
                if isinstance(v, JSXExpression):
                    val_code = self.process_expression_content(v.expression)
                    if arg_name in wrap_lambdas:
                        val_code = f"lambda: ({val_code})"
                    parts.append(f'{arg_name}={val_code}')
                else:
                    if arg_name in wrap_lambdas:
                        parts.append(f'{arg_name}=lambda: "{v}"')
                    else:
                        parts.append(f'{arg_name}="{v}"')
            
            # Inject CSS if this is the root element and css_variable is set
            if is_root and self.css_variable:
                parts.append(f'css={self.css_variable}')
                
            return ", ".join(parts)

        # Special handling for Show, For, ForEach, Switch, Match, Suspense, ErrorBoundary, Portal
        if tag_name == ComponentType.SHOW.value:
            # Map 'if' to 'when' and wrap 'when' in lambda
            kwargs_str = get_kwargs_str({"if": "when"}, wrap_lambdas=["when"])
            return f"Show(children=lambda: {children_str}, {kwargs_str})"
            
        elif tag_name == ComponentType.FOR.value:
            kwargs_str = get_kwargs_str()
            # If single child is expression, pass it directly
            if len(meaningful_children) == 1 and isinstance(meaningful_children[0], JSXExpression):
                child_code = self.visit(meaningful_children[0], indent + 1)
                return f"For(children={child_code}, {kwargs_str})"
            else:
                return f"For(children=lambda item, i: {children_str}, {kwargs_str})"

        elif tag_name == ComponentType.SWITCH.value:
            # Switch(children=[Match(...), ...], fallback=...)
            switch_children_parts = []
            for child in meaningful_children:
                visited = self.visit(child, indent + 1)
                if visited is not None:
                    switch_children_parts.append(visited)
            
            switch_children_str = "[\n" + ",\n".join([f"{'  ' * (indent + 1)}{c}" for c in switch_children_parts]) + f"\n{'  ' * indent}]"
            kwargs_str = get_kwargs_str()
            return f"Switch(children={switch_children_str}, {kwargs_str})"

        elif tag_name == ComponentType.MATCH.value:
            kwargs_str = get_kwargs_str(wrap_lambdas=["when"])
            return f"Match(children=lambda: {children_str}, {kwargs_str})"

        elif tag_name == ComponentType.SUSPENSE.value:
            # Map 'resource' to 'resource_state'
            kwargs_str = get_kwargs_str({"resource": "resource_state"})
            
            if len(meaningful_children) == 1 and isinstance(meaningful_children[0], JSXExpression):
                child_code = self.visit(meaningful_children[0], indent + 1)
                return f"Suspense(children={child_code}, {kwargs_str})"
            else:
                return f"Suspense(children=lambda data: {children_str}, {kwargs_str})"

        elif tag_name == ComponentType.ERROR_BOUNDARY.value:
            kwargs_str = get_kwargs_str()
            return f"ErrorBoundary(children=lambda: {children_str}, {kwargs_str})"

        elif tag_name == ComponentType.PORTAL.value:
            kwargs_str = get_kwargs_str({"target": "container"})
            return f"Portal(children=lambda: {children_str}, {kwargs_str})"

        elif tag_name == ComponentType.FOR_EACH.value:
            kwargs_str = get_kwargs_str()
            
            if "each" not in node.attributes and len(meaningful_children) == 1 and isinstance(meaningful_children[0], JSXExpression):
                expr = meaningful_children[0].expression.strip()
                if expr.startswith('for_each:'):
                    each_val = expr.split(':', 1)[1].strip()
                    if kwargs_str:
                        kwargs_str += f', each={each_val}'
                    else:
                        kwargs_str = f'each={each_val}'
                    
                    return f"For(each={each_val}, children=lambda item, i: item, key=lambda item, i: i)"

            return f"For(children=lambda: {children_str}, {kwargs_str})"

        # Check for custom components (Capitalized)
        if tag_name[0].isupper():
            kwargs_str = get_kwargs_str()
            # If we have children, pass them as 'children' kwarg
            # We use children_str which is a list "[...]"
            # But for components, we usually want a callable if it's dynamic, or just the list.
            # The pattern used for Show/For is specific (lambda).
            # For general components like Modal(is_open=..., children=...), we can pass the list directly.
            # However, if the component expects a slot or callable, it might be different.
            # Let's assume standard prop passing: children=[...]
            
            if children_str != "[]":
                if kwargs_str:
                    return f"{tag_name}(children={children_str}, {kwargs_str})"
                else:
                    return f"{tag_name}(children={children_str})"
            else:
                return f"{tag_name}({kwargs_str})"

        # Standard HTML/Component tags
        # Inject CSS if root
        css_arg = ""
        if is_root and self.css_variable:
             css_arg = f", css={self.css_variable}"
             
        namespace_arg = ""
        if needs_namespace:
            namespace_arg = ', namespace="http://www.w3.org/2000/svg"'

        return f"t.{tag_name}({attrs_str}, {children_str}{css_arg}{namespace_arg})"

    def visit_text(self, node):
        if self.text_as_code:
            return node.value
            
        # Return string literal
        # Escape quotes if needed
        clean_val = node.value.replace('"', '\\"').replace('\n', '\\n')
        return f'"{clean_val}"'

    def visit_expression(self, node):
        return self.process_expression_content(node.expression)

    def process_expression_content(self, expr):
        expr = expr.strip()
        
        # 0. Handle Comments: /* ... */
        if expr.startswith('/*') and expr.endswith('*/'):
            return None

        
        # 0.5 Convert JS keywords and operators
        expr = re.sub(r'\btrue\b', 'True', expr)
        expr = re.sub(r'\bfalse\b', 'False', expr)
        expr = re.sub(r'\bnull\b', 'None', expr)
        expr = expr.replace('===', '==')
        expr = expr.replace('!==', '!=')
        
        # 1. Convert Arrow Functions: (a, b) => body -> lambda a, b: body
        # Handle both (args) => and arg =>
        # Simple arrow function: (args) => body
        # Note: This is a simple regex and might fail on complex nested parens, but sufficient for this task.
        def replace_arrow(match):
            args = match.group(1)
            body = match.group(2)
            
            # Check for JSX in body
            if '<' in body and '>' in body:
                # Recursively transpile body
                try:
                    # Tokenize
                    tokenizer = JSXTokenizer(body)
                    tokens = tokenizer.tokenize()
                    
                    # Parse
                    parser = JSXParser(tokens)
                    nodes = parser.parse()
                    
                    # Generate with text_as_code=True
                    # We create a new generator to avoid side effects
                    generator = JSXCodeGenerator(text_as_code=True, css_variable=self.css_variable)
                    transpiled_body = generator.generate(nodes)
                    return f"lambda {args}: {transpiled_body}"
                except Exception:
                    # Fallback if parsing fails
                    pass
            
            return f"lambda {args}: {body}"

        expr = re.sub(r'\(([^)]*)\)\s*=>\s*(.*)', replace_arrow, expr)
        # Single arg arrow function: arg => body (avoid matching if it's already lambda or inside quotes)
        # This is harder to distinguish from other syntax without full parsing, but let's try a safe subset.
        # For now, let's assume the user uses parens as in the request: (cat, i) => ...
        
        # 2. Convert Template Literals: `string ${expr}` -> f"string {expr}"
        # Find backtick strings
        def replace_template_literal(match):
            content = match.group(1)
            # Replace ${expr} with {expr} for python f-string
            content = re.sub(r'\$\{([^}]+)\}', r'{\1}', content)
            return f'f"{content}"'
            
        expr = re.sub(r'`([^`]*)`', replace_template_literal, expr)
        
        # 4. Convert JS negation: !expr -> not expr
        # Be careful not to replace !=
        # Simple heuristic: replace ! at start or after space/paren, if not followed by =
        expr = re.sub(r'(^|[\s(])!([^=])', r'\1not \2', expr)

        # 5. Convert Ternary Operator: cond ? true : false -> true if cond else false
        # This is a basic implementation and might not handle nested ternaries or colons in strings correctly without a full parser.
        # We use a non-greedy match for the condition and true-branch to support simple cases.
        ternary_match = re.match(r'(.+?)\s*\?\s*(.+?)\s*:\s*(.+)', expr)
        if ternary_match:
            cond, true_val, false_val = ternary_match.groups()
            expr = f"{true_val} if {cond} else {false_val}"

        # 6. Quote keys in object literals: { key: val } -> { "key": val }
        # This is common in style={{ ... }}
        if expr.strip().startswith('{') and expr.strip().endswith('}'):
            # Replace keys that are identifiers followed by :
            # Match: (start or comma or brace) (whitespace) (identifier) (whitespace) :
            # We use a loop to handle multiple replacements correctly or a single regex with groups.
            # Regex: ([{,])(\s*)([a-zA-Z_][a-zA-Z0-9_-]*)(\s*):
            # Replacement: \1\2"\3"\4:
            expr = re.sub(r'([,{])(\s*)([a-zA-Z_][a-zA-Z0-9_-]*)(\s*):', r'\1\2"\3"\4:', expr)

        # 3. Recursive JSX: Check if expression contains JSX tags
        if '<' in expr and '>' in expr:
            # Try to transpile the expression as mixed code/JSX
            try:
                # Use the same pipeline but with text_as_code=True
                # We need to import the classes here or assume they are available in scope
                # Since this is a method of JSXCodeGenerator, we can instantiate new ones.
                
                # Tokenize
                tokenizer = JSXTokenizer(expr)
                tokens = tokenizer.tokenize()
                
                # Parse
                parser = JSXParser(tokens)
                nodes = parser.parse()
                
                # Generate with text_as_code=True
                generator = JSXCodeGenerator(text_as_code=True)
                transpiled = generator.generate(nodes)
                return transpiled
            except Exception:
                # If parsing fails (e.g. it was just a less-than operator), return original expr
                pass
                
        return expr
