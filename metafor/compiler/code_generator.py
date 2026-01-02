import re
from .parser import PTMLElement, PTMLText, PTMLExpression, PTMLIf, PTMLForEach, PTMLSwitch, PTMLMatch, PTMLNode, PTMLFragment

class CodeGenerator:
    def __init__(self, start_index=0):
        self.static_counter = start_index
        self.in_svg = False

    def generate(self, nodes, indent=0):
        if not nodes: return "None"
        
        parts = []
        for n in nodes:
            code = self.visit(n, indent)
            if code:
                parts.append(code)
        
        if len(parts) == 0: return "None"
        if len(parts) == 1: return parts[0]
        
        indent_str = "    " * indent
        child_indent_str = "    " * (indent + 1)
        return f"[\n{child_indent_str}" + f",\n{child_indent_str}".join(parts) + f"\n{indent_str}]"

    def visit(self, node, indent=0):
        # Dynamic generation only
        return self._generate_element_code(node, indent)

    def _generate_element_code(self, node, indent=0):
        if isinstance(node, PTMLElement):
            # SVG Context Handling
            was_in_svg = self.in_svg
            
            # Convert hyphens to underscores for Python compatibility
            tag_name = node.tag.replace('-', '_')
            
            if node.tag == "page-title":
                children_code = self.generate(node.children, indent + 1)
                return f"t.page_title({children_code})"

            if node.tag == "svg":
                self.in_svg = True
            elif node.tag == "foreignObject":
                self.in_svg = False
                
            needs_namespace = (was_in_svg or node.tag == "svg") and not (node.tag[0].isupper() or "." in node.tag)
            
            attrs_parts = []
            for k, v in node.attrs.items():
                if isinstance(v, str):
                    # Convert className to class_name for Python compatibility
                    if k == "className": k = "class_name"
                    
                    if '@{' in v:
                        val = v.replace('{', '{{').replace('}', '}}')
                        val = re.sub(r'@\{\{(.*?)\}\}', r'{\1}', val)
                        attrs_parts.append(f'"{k}": f"{val}"')
                    else:
                        attrs_parts.append(f'"{k}": "{v}"')
                elif isinstance(v, PTMLExpression):
                     # Convert className to class_name for Python compatibility
                     if k == "className": k = "class_name"
                     val = self._transform_expression(v.value)
                     attrs_parts.append(f'"{k}": {val}')
                else:
                    # Convert className to class_name for Python compatibility
                    if k == "className": k = "class_name"
                    attrs_parts.append(f'"{k}": {v.value}')
            
            attrs_str = ", ".join(attrs_parts)
            children_code = self.generate(node.children, indent + 1)
            
            # Restore state
            self.in_svg = was_in_svg
            
            # Helper for component capitalization (Custom Components)
            if node.tag[0].isupper():
                 # Capitalized tags are treated as Components (classes/functions)
                 # We pass children as a prop. 
                 kwargs_str = self._attrs_to_kwargs(node.attrs)
                 args = []
                 if children_code != "None": args.append(f"children={children_code}")
                 
                 # Add spreads as **kwargs BEFORE explicit kwargs to allow overriding
                 for spread in node.spreads:
                     spread_expr = self._transform_expression(spread).strip()
                     if spread_expr.startswith('**'):
                         spread_expr = spread_expr[2:].strip()
                     elif spread_expr.startswith('...'):
                         spread_expr = spread_expr[3:].strip()
                     args.append(f"**{spread_expr}")

                 if kwargs_str: args.append(kwargs_str)
                     
                 return f"{tag_name}({', '.join(args)})"
            
            # Standard HTML elements use the DOM Builder 't'
            namespace_arg = ""
            if needs_namespace:
                namespace_arg = ', namespace="http://www.w3.org/2000/svg"'
            
            # Construct props dictionary
            props_parts = []
            
            # Add spreads first
            for spread in node.spreads:
                spread_expr = self._transform_expression(spread).strip()
                if spread_expr.startswith('**'):
                    spread_expr = spread_expr[2:].strip()
                elif spread_expr.startswith('...'):
                    spread_expr = spread_expr[3:].strip()
                props_parts.append(f"**{spread_expr}")
                
            if attrs_str:
                props_parts.append(attrs_str)
            
            props_expr = f"{{{', '.join(props_parts)}}}"
                
            return f"t.{tag_name}({props_expr}, {children_code}{namespace_arg})"
            
        elif isinstance(node, PTMLText):
            # Standard HTML whitespace handling:
            # 1. Replace newlines with spaces
            val = node.value.replace('\n', ' ')
            
            # Optimization: Skip pure whitespace nodes that contained newlines (indentation)
            # This removes the "extrant" " " strings from the output.
            if '\n' in node.value and not node.value.strip():
                return None

            # 2. Collapse multiple spaces to single space
            val = re.sub(r'\s+', ' ', val)
            
            val = val.replace('\\', '\\\\').replace('"', '\\"')
            return f'"{val}"'
            
        elif isinstance(node, PTMLExpression):
            # Dynamic Expression: Output directly (handled by core.DOMNode)
            return self._transform_expression(node.value)
            
        elif isinstance(node, PTMLFragment):
            # Fragments just return their children list
            # But generate() returns a list string "[...]" or single item "..."
            # We need to ensure it fits into the parent's children list.
            # If this fragment is a child of an element, generate(node.children) returns a string representing the list of children.
            # However, _generate_element_code is expected to return a single expression that evaluates to a node or a list of nodes.
            # If we return a list, it will be nested.
            # But wait, generate() joins parts with comma.
            # If we return "a, b", it will be valid in a list.
            # But _generate_element_code returns a string for a single item in the parent's list.
            # If we return "[a, b]", it will be a list inside the parent's list.
            # Metafor's DOM builder handles lists of lists (nested arrays) fine usually.
            return self.generate(node.children, indent)
            
        # 3. METAFOR COMPONENTS INTEGRATION
        
        elif isinstance(node, PTMLIf):
            # Maps to metafor.components.Show
            # We wrap children in a lambda so `create_effect` can track them lazily
            children_code = self.generate(node.children, indent + 1)
            cond = self._transform_expression(node.condition)
            
            # Build nested Show components for elif/else branches
            # Process from the innermost (else or last elif) to outermost (first elif)
            # This way we build: Show(...fallback=Show(...fallback=Show(...)))
            
            # Start with else branch if it exists
            fallback_code = None
            if node.else_children:
                else_children_code = self.generate(node.else_children, indent + 1)
                fallback_code = f"lambda: {else_children_code}"
            
            # Process elif branches in reverse order (last elif first, building from inside out)
            for elif_cond, elif_children in reversed(node.elif_branches):
                elif_children_code = self.generate(elif_children, indent + 1)
                elif_cond_expr = self._transform_expression(elif_cond)
                
                if fallback_code:
                    # Nest the previous fallback inside this elif's Show
                    fallback_code = f"Show(when=lambda: {elif_cond_expr}, children=lambda: {elif_children_code}, fallback={fallback_code})"
                else:
                    # No else branch, this elif is the final fallback
                    fallback_code = f"Show(when=lambda: {elif_cond_expr}, children=lambda: {elif_children_code})"
            
            # Build the final Show component
            if fallback_code:
                return f"Show(when=lambda: {cond}, children=lambda: {children_code}, fallback={fallback_code})"
            else:
                return f"Show(when=lambda: {cond}, children=lambda: {children_code})"
            
        elif isinstance(node, PTMLForEach):
            # Maps to metafor.components.For
            # Utilizes keyed reconciliation.
            # children must be a lambda that takes (item, index)
            children_code = self.generate(node.children, indent + 1)
            list_expr = self._transform_expression(node.list_expr)
            
            key_arg = ""
            if node.key_expr:
                key_expr = self._transform_expression(node.key_expr)
                key_arg = f", key={key_expr}"
            
            fallback_arg = ""
            if getattr(node, 'fallback_children', None):
                fallback_code = self.generate(node.fallback_children, indent + 1)
                fallback_arg = f", fallback=lambda: {fallback_code}"
            elif getattr(node, 'fallback_expr', None):
                fallback_expr = self._transform_expression(node.fallback_expr)
                fallback_arg = f", fallback={fallback_expr}"
                
            return f"For(each={list_expr}{key_arg}{fallback_arg}, children=lambda {node.item}, index: {children_code})"
            
        elif isinstance(node, PTMLSwitch):
            children_code = []
            switch_expr = self._transform_expression(node.expression) if node.expression else None
            
            for child in node.children:
                if isinstance(child, PTMLMatch):
                    match_body = self.generate(child.children, indent + 1)
                    match_expr = self._transform_expression(child.expression)
                    
                    if switch_expr:
                        # Match equality for switch(val)
                        condition = f"unwrap({switch_expr}) == unwrap({match_expr})"
                    else:
                        # Boolean match for switch (no arg)
                        condition = f"unwrap({match_expr})"
                    
                    # Wrap match children in lambda
                    children_code.append(f"Match(when=lambda: {condition}, children=lambda: {match_body})")
            return f"Switch(children=[{', '.join(children_code)}])"

        return "None"

    def _transform_expression(self, expr):
        if not expr: return expr
        expr = expr.strip()
        
        # Handle wrapping parens: (a -> b)
        # We only unwrap if the parens enclose the entire expression
        if expr.startswith('(') and expr.endswith(')'):
            balance = 0
            wrapped = True
            # Check if the first '(' matches the last ')'
            for i, char in enumerate(expr[:-1]):
                if char == '(': balance += 1
                elif char == ')': balance -= 1
                if balance == 0 and i < len(expr) - 1:
                    wrapped = False
                    break
            
            if wrapped:
                inner = expr[1:-1]
                transformed = self._transform_expression(inner)
                if transformed != inner:
                    return f"({transformed})"

        # Check for arrow syntax: (args) -> body or args -> body
        if "->" in expr:
            # Regex to capture args and body
            # Matches: (a,b) -> c  OR  a -> c
            match = re.match(r"^\s*\(?\s*([^\)]*?)\s*\)?\s*->\s*(.+)$", expr, re.DOTALL)
            if match:
                args = match.group(1).strip()
                body = match.group(2).strip()
                return f"lambda {args}: {body}"

        # Check for inline PTML (e.g. in fallback or props)
        if '<' in expr and '>' in expr:
            try:
                # Check for lambda prefix
                prefix = ""
                content = expr
                match = re.match(r"^\s*(lambda[^:]*:)(.*)$", expr, re.DOTALL)
                if match:
                    prefix = match.group(1) + " "
                    content = match.group(2)
                
                # Try to parse as PTML
                # Import here to avoid circular imports at module level if any
                from .tokenizer import PTMLTokenizer
                from .parser import PTMLParser
                
                # Only attempt if it looks like it starts with a tag
                if content.strip().startswith('<'):
                    tokenizer = PTMLTokenizer(content)
                    tokens = tokenizer.tokenize()
                    parser = PTMLParser(tokens)
                    nodes = parser.parse()
                    
                    # Only use compiled code if we found actual elements
                    # This prevents 'a < b' from being turned into a string "a < b"
                    if any(isinstance(n, PTMLElement) for n in nodes):
                        compiled_code = self.generate(nodes)
                        return f"{prefix}{compiled_code}"
            except Exception:
                # Fallback to original expression if parsing fails
                pass

        return expr

    def _attrs_to_kwargs(self, attrs):
        parts = []
        for k, v in attrs.items():
            if isinstance(v, PTMLExpression):
                val = self._transform_expression(v.value)
                parts.append(f"{k}={val}")
            else:
                val = f'"{v}"' if isinstance(v, str) else v.value
                parts.append(f"{k}={val}")
        return ", ".join(parts)
