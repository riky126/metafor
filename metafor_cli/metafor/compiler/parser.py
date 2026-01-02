from .tokenizer import TokenType, Token

class PTMLNode:
    is_static = False

class PTMLElement(PTMLNode):
    def __init__(self, tag, attrs, children, spreads=None):
        self.tag = tag
        self.attrs = attrs
        self.children = children
        self.spreads = spreads or []

class PTMLText(PTMLNode):
    def __init__(self, value):
        self.value = value

class PTMLExpression(PTMLNode):
    def __init__(self, value):
        self.value = value

class PTMLIf(PTMLNode):
    def __init__(self, condition, children, elif_branches=None, else_children=None):
        self.condition = condition
        self.children = children
        self.elif_branches = elif_branches or []  # List of (condition, children) tuples
        self.else_children = else_children

class PTMLForEach(PTMLNode):
    def __init__(self, item, list_expr, children, key_expr=None, fallback_expr=None, fallback_children=None):
        self.item = item
        self.list_expr = list_expr
        self.children = children
        self.key_expr = key_expr
        self.fallback_expr = fallback_expr
        self.fallback_children = fallback_children

class PTMLSwitch(PTMLNode):
    def __init__(self, expression, children):
        self.expression = expression
        self.children = children

class PTMLMatch(PTMLNode):
    def __init__(self, expression, children):
        self.expression = expression
        self.children = children

class PTMLFragment(PTMLNode):
    def __init__(self, children):
        self.children = children

class PTMLParser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def parse(self):
        nodes = []
        while self.pos < len(self.tokens) and self.current().type != TokenType.EOF:
            if self.current().type == TokenType.BLOCK_CLOSE: break
            node = self.parse_node()
            if node: nodes.append(node)
        return nodes

    def parse_node(self):
        token = self.current()
        if token.type == TokenType.TAG_OPEN_START: return self.parse_element()
        elif token.type == TokenType.FRAGMENT_OPEN: return self.parse_fragment()
        elif token.type == TokenType.TEXT:
            self.advance()
            text = token.value.strip()
            # Heuristic check for Python syntax in text nodes
            # We want to prevent users from writing Python code in @ptml blocks thinking it will execute.
            # Common keywords that start statements:
            py_keywords = ("def ", "class ", "import ", "from ", "return ", "raise ", "try:", "except ", "with ", "while ", "for ", "if ", "elif ", "else:", "break", "continue", "pass", "assert ", "del ", "global ", "nonlocal ", "yield ", "await ", "async ")
            if text.startswith(py_keywords):
                 raise SyntaxError(f"Python syntax '{text.split()[0]}' is not allowed in @ptml blocks. Use @{{...}} for expressions or directives like @if/@foreach.")
            return PTMLText(token.value)
        elif token.type == TokenType.BLOCK_OPEN:
            self.advance()
            return PTMLText("{")
        elif token.type == TokenType.BLOCK_CLOSE:
            self.advance()
            return PTMLText("}")
        elif token.type == TokenType.EXPR_START: return self.parse_expression()
        elif token.type == TokenType.DIRECTIVE_IF: return self.parse_if()
        elif token.type == TokenType.DIRECTIVE_ELIF: return self.parse_elif()
        elif token.type == TokenType.DIRECTIVE_ELSE: return self.parse_else()
        elif token.type == TokenType.DIRECTIVE_FOREACH: return self.parse_foreach()
        elif token.type == TokenType.DIRECTIVE_SWITCH: return self.parse_switch()
        elif token.type == TokenType.DIRECTIVE_MATCH: return self.parse_match()
        elif token.type == TokenType.ARROW:
            self.advance()
            return PTMLText("->")
        else:
            self.advance()
            return None

    def parse_element(self):
        self.expect(TokenType.TAG_OPEN_START)
        tag = self.expect(TokenType.TAG_NAME).value
        attrs = {}
        spreads = []
        
        while self.current().type in (TokenType.ATTR_NAME, TokenType.ATTR_SPREAD):
            if self.current().type == TokenType.ATTR_SPREAD:
                spreads.append(self.current().value)
                self.advance()
            else:
                name = self.current().value
                self.advance()
                val = "True"
                if self.match(TokenType.ATTR_EQ):
                    if self.current().type == TokenType.ATTR_VALUE:
                        val = self.current().value
                        self.advance()
                    elif self.current().type == TokenType.EXPR_START:
                        val = self.parse_expression()
                elif self.match(TokenType.ATTR_EXPR_EQ):
                    val = PTMLExpression(self.expect(TokenType.ATTR_EXPR_VALUE).value)
                attrs[name] = val
            
        children = []
        if self.match(TokenType.TAG_SELF_CLOSE): return PTMLElement(tag, attrs, children, spreads)
        VOID_TAGS = {'input', 'br', 'hr', 'img', 'meta', 'link', 'area', 'base', 'col', 'embed', 'source', 'track', 'wbr'}
        if tag in VOID_TAGS: return PTMLElement(tag, attrs, children, spreads)
            
        self.expect(TokenType.TAG_OPEN_END)
        while self.current().type not in (TokenType.TAG_CLOSE_START, TokenType.EOF):
            node = self.parse_node()
            if node: children.append(node)
        self.expect(TokenType.TAG_CLOSE_START)
        close_tag = self.expect(TokenType.TAG_NAME).value
        if close_tag != tag: raise SyntaxError(f"Mismatched tag: {tag} vs {close_tag}")
        self.expect(TokenType.TAG_OPEN_END)
        return PTMLElement(tag, attrs, children, spreads)

    def parse_expression(self):
        self.expect(TokenType.EXPR_START)
        val = self.expect(TokenType.EXPR_BODY).value
        self.expect(TokenType.EXPR_END)
        return PTMLExpression(val)

    def parse_fragment(self):
        self.expect(TokenType.FRAGMENT_OPEN)
        children = []
        while self.current().type not in (TokenType.FRAGMENT_CLOSE, TokenType.EOF):
            node = self.parse_node()
            if node: children.append(node)
        self.expect(TokenType.FRAGMENT_CLOSE)
        return PTMLFragment(children)

    def parse_if(self):
        self.expect(TokenType.DIRECTIVE_IF)
        cond = self.expect(TokenType.EXPR_BODY).value
        self._skip_whitespace()  # Skip whitespace before opening brace
        self.expect(TokenType.BLOCK_OPEN)
        children = self.parse()
        self.expect(TokenType.BLOCK_CLOSE)
        
        # Skip whitespace TEXT tokens before checking for @elif/@else
        self._skip_whitespace()
        
        # Parse elif branches
        elif_branches = []
        while self.current().type == TokenType.DIRECTIVE_ELIF:
            self.advance()  # consume @elif
            elif_cond = self.expect(TokenType.EXPR_BODY).value
            self._skip_whitespace()  # Skip whitespace before opening brace
            self.expect(TokenType.BLOCK_OPEN)
            elif_children = self.parse()
            self.expect(TokenType.BLOCK_CLOSE)
            self._skip_whitespace()  # Skip whitespace before next elif/else
            elif_branches.append((elif_cond, elif_children))
        
        # Parse else branch
        else_children = None
        if self.current().type == TokenType.DIRECTIVE_ELSE:
            self.advance()  # consume @else
            self._skip_whitespace()  # Skip whitespace before opening brace
            self.expect(TokenType.BLOCK_OPEN)
            else_children = self.parse()
            self.expect(TokenType.BLOCK_CLOSE)
            
            # After @else, no @elif can follow - that's a syntax error
            self._skip_whitespace()
            if self.current().type == TokenType.DIRECTIVE_ELIF:
                raise SyntaxError("@elif cannot come after @else. @else must be the last branch in an @if/@elif/@else chain.")
        
        return PTMLIf(cond, children, elif_branches, else_children)
    
    def _skip_whitespace(self):
        """Skip whitespace TEXT tokens"""
        while self.current().type == TokenType.TEXT and not self.current().value.strip():
            self.advance()
    
    def parse_elif(self):
        # This is called when we encounter @elif outside of an @if context
        # This shouldn't normally happen, but we handle it for error reporting
        raise SyntaxError("@elif must follow an @if statement")
    
    def parse_else(self):
        # This is called when we encounter @else outside of an @if context
        # This shouldn't normally happen, but we handle it for error reporting
        raise SyntaxError("@else must follow an @if or @elif statement")

    def parse_foreach(self):
        self.expect(TokenType.DIRECTIVE_FOREACH)
        item = self.expect(TokenType.EXPR_BODY).value
        self.expect(TokenType.KEYWORD_IN)
        lst = self.expect(TokenType.EXPR_BODY).value
        
        key_expr = None
        fallback_expr = None
        
        # Parse optional arguments (key, fallback)
        while True:
            if self.match(TokenType.KEYWORD_KEY):
                key_expr = self.expect(TokenType.EXPR_BODY).value
            elif self.match(TokenType.KEYWORD_FALLBACK):
                fallback_expr = self.expect(TokenType.EXPR_BODY).value
            else:
                break
            
        self.expect(TokenType.BLOCK_OPEN)
        children = self.parse()
        self.expect(TokenType.BLOCK_CLOSE)
        
        fallback_children = None
        
        # Skip whitespace/text before checking for arrow
        while self.current().type == TokenType.TEXT and self.current().value.strip() == "":
            self.advance()
            
        if self.match(TokenType.ARROW):
            # Skip whitespace after arrow before checking for @fallback
            while self.current().type == TokenType.TEXT and self.current().value.strip() == "":
                self.advance()
            
            if self.current().type == TokenType.DIRECTIVE_FALLBACK:
                self.advance()
            else:
                raise SyntaxError("Expected '@fallback' after '->'")
            
            # Skip whitespace after @fallback before expecting block open
            while self.current().type == TokenType.TEXT and self.current().value.strip() == "":
                self.advance()
            
            self.expect(TokenType.BLOCK_OPEN)
            fallback_children = self.parse()
            self.expect(TokenType.BLOCK_CLOSE)
            
        return PTMLForEach(item, lst, children, key_expr, fallback_expr, fallback_children)

    def parse_switch(self):
        self.expect(TokenType.DIRECTIVE_SWITCH)
        expr = None
        if self.current().type == TokenType.EXPR_BODY:
            expr = self.current().value
            self.advance()
        self.expect(TokenType.BLOCK_OPEN)
        children = self.parse()
        self.expect(TokenType.BLOCK_CLOSE)
        return PTMLSwitch(expr, children)

    def parse_match(self):
        self.expect(TokenType.DIRECTIVE_MATCH)
        expr = self.expect(TokenType.EXPR_BODY).value
        self.expect(TokenType.BLOCK_OPEN)
        children = self.parse()
        self.expect(TokenType.BLOCK_CLOSE)
        return PTMLMatch(expr, children)

    def current(self):
        if self.pos < len(self.tokens): return self.tokens[self.pos]
        return Token(TokenType.EOF, "")

    def advance(self): self.pos += 1

    def match(self, type):
        if self.current().type == type:
            self.advance()
            return True
        return False

    def expect(self, type):
        if self.current().type == type:
            t = self.current()
            self.advance()
            return t
        raise SyntaxError(f"Expected {type}, got {self.current().type}")
