from .tokenizer import TokenType, Token

class JSXNode:
    pass

class JSXElement(JSXNode):
    def __init__(self, tag_name, attributes, children):
        self.tag_name = tag_name
        self.attributes = attributes # Dictionary of key -> value (Token or string)
        self.children = children # List of JSXNode

    def __repr__(self):
        return f"JSXElement({self.tag_name}, attrs={self.attributes}, children={len(self.children)})"

class JSXText(JSXNode):
    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return f"JSXText({repr(self.value)})"

class JSXExpression(JSXNode):
    def __init__(self, expression):
        self.expression = expression

    def __repr__(self):
        return f"JSXExpression({repr(self.expression)})"

class JSXParser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0
        self.length = len(tokens)

    def parse(self):
        # We expect a single root element or a list of elements?
        # Usually JSX returns a single root, but let's support a list of roots (fragments implicitly)
        # or just parse the first element.
        # If the file contains multiple top-level elements, we can return a list.
        nodes = []
        while self.pos < self.length and self.current_token().type != TokenType.EOF:
            node = self.parse_node()
            if node:
                # Filter top-level whitespace containing newlines (indentation)
                if isinstance(node, JSXText) and not node.value.strip() and '\n' in node.value:
                    continue
                nodes.append(node)
            else:
                break
        
        # If single root is expected, return the first one.
        # But for general purpose, let's return the list of top-level nodes.
        # If the user expects a single expression, they should wrap in fragment.
        return nodes

    def current_token(self):
        if self.pos < self.length:
            return self.tokens[self.pos]
        return Token(TokenType.EOF, "")

    def advance(self):
        if self.pos < self.length:
            self.pos += 1

    def match(self, type):
        if self.current_token().type == type:
            self.advance()
            return True
        return False

    def expect(self, type):
        if self.current_token().type == type:
            token = self.current_token()
            self.advance()
            return token
        raise SyntaxError(f"Expected {type}, got {self.current_token().type} at line {self.current_token().line}")

    def parse_node(self):
        token = self.current_token()
        
        if token.type == TokenType.TAG_OPEN_START:
            return self.parse_element()
        elif token.type == TokenType.TEXT:
            self.advance()
            return JSXText(token.value)
        elif token.type == TokenType.EXPRESSION_START:
            return self.parse_expression()
        else:
            # Unexpected token or EOF
            return None

    def parse_element(self):
        self.expect(TokenType.TAG_OPEN_START) # <
        
        tag_name = None
        attributes = {}
        
        # Check for Fragment start <>
        if self.current_token().type == TokenType.TAG_OPEN_END:
            self.advance() # consume >
        else:
            tag_name_token = self.expect(TokenType.TAG_NAME)
            tag_name = tag_name_token.value
            
            while self.current_token().type in (TokenType.ATTR_NAME, TokenType.TAG_NAME): 
                # Note: Tokenizer might classify some attr names as TAG_NAME if ambiguous, 
                # but our tokenizer logic tries to distinguish. 
                # However, if we see TAG_NAME here, it's likely an attribute name.
                attr_name = self.current_token().value
                self.advance()
                
                attr_value = "True" # Default boolean true
                if self.match(TokenType.ATTR_EQ):
                    if self.current_token().type == TokenType.ATTR_VALUE:
                        attr_value = self.current_token().value
                        self.advance()
                    elif self.current_token().type == TokenType.EXPRESSION_START:
                        # Expression as attribute value
                        expr_node = self.parse_expression()
                        attr_value = expr_node # Store the node itself
                    else:
                        raise SyntaxError(f"Expected attribute value at line {self.current_token().line}")
                
                attributes[attr_name] = attr_value
    
            if self.match(TokenType.TAG_SELF_CLOSE): # />
                return JSXElement(tag_name, attributes, [])
            
            self.expect(TokenType.TAG_OPEN_END) # >
        
        # Parse children
        children = []
        while self.current_token().type not in (TokenType.TAG_CLOSE_START, TokenType.EOF):
            child = self.parse_node()
            if child:
                # Filter child whitespace containing newlines (indentation)
                if isinstance(child, JSXText) and not child.value.strip() and '\n' in child.value:
                    continue
                children.append(child)
            else:
                break
        
        # Closing tag
        self.expect(TokenType.TAG_CLOSE_START) # </
        
        if tag_name is None:
            # Fragment close </>
            if self.current_token().type != TokenType.TAG_OPEN_END:
                 raise SyntaxError(f"Expected > for fragment close at line {self.current_token().line}")
            self.advance() # consume >
        else:
            close_tag_name = self.expect(TokenType.TAG_NAME)
            if close_tag_name.value != tag_name:
                 raise SyntaxError(f"Expected closing tag for {tag_name}, got {close_tag_name.value} at line {close_tag_name.line}")
            self.expect(TokenType.TAG_OPEN_END) # >
        
        return JSXElement(tag_name, attributes, children)

    def parse_expression(self):
        self.expect(TokenType.EXPRESSION_START) # {{
        body = self.expect(TokenType.EXPRESSION_BODY).value
        self.expect(TokenType.EXPRESSION_END) # }}
        return JSXExpression(body)
