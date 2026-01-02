import enum

class TokenType(enum.Enum):
    TAG_OPEN_START = "TAG_OPEN_START"       # <
    TAG_OPEN_END = "TAG_OPEN_END"           # >
    TAG_CLOSE_START = "TAG_CLOSE_START"     # </
    TAG_SELF_CLOSE = "TAG_SELF_CLOSE"       # />
    TAG_NAME = "TAG_NAME"                   # div, MyComponent
    ATTR_NAME = "ATTR_NAME"                 # className
    ATTR_EQ = "ATTR_EQ"                     # =
    ATTR_VALUE = "ATTR_VALUE"               # "value"
    EXPRESSION_START = "EXPRESSION_START"   # {{
    EXPRESSION_END = "EXPRESSION_END"       # }}
    EXPRESSION_BODY = "EXPRESSION_BODY"     # content inside {{ }}
    TEXT = "TEXT"                           # text content
    EOF = "EOF"

class Token:
    def __init__(self, type, value, line=0, column=0):
        self.type = type
        self.value = value
        self.line = line
        self.column = column

    def __repr__(self):
        return f"Token({self.type}, {repr(self.value)})"

class JSXTokenizer:
    def __init__(self, source):
        self.source = source
        self.pos = 0
        self.line = 1
        self.column = 1
        self.tokens = []
        self.length = len(source)

    def tokenize(self):
        self._tokenize_loop()
        self.tokens.append(Token(TokenType.EOF, "", self.line, self.column))
        return self.tokens

    def _tokenize_loop(self):
        in_tag = False
        
        while self.pos < self.length:
            char = self.source[self.pos]

            if not in_tag:
                # We are in text/children content
                if char == '<':
                    if self.peek() == '/':
                        self.read_close_tag_start()
                        in_tag = True # We are now inside the closing tag definition </tag>
                    else:
                        self.read_open_tag_start()
                        in_tag = True
                elif char == '{':
                    self.read_expression()
                else:
                    self.read_text()
            else:
                # We are inside a tag definition (e.g. <div className="...">)
                if char.isspace():
                    self.advance()
                    continue
                
                if char == '>':
                    self.add_token(TokenType.TAG_OPEN_END, ">")
                    self.advance()
                    in_tag = False
                elif char == '/' and self.peek() == '>':
                    self.add_token(TokenType.TAG_SELF_CLOSE, "/>")
                    self.advance(2)
                    in_tag = False
                elif char == '=':
                    self.add_token(TokenType.ATTR_EQ, "=")
                    self.advance()
                elif char == '"' or char == "'":
                    self.read_attr_value(char)
                elif char == '{':
                     # Expression as attribute value: prop={val}
                     self.read_expression()
                else:
                    # Attribute name or Tag name
                    self.read_identifier()

    def peek(self, offset=1):
        if self.pos + offset < self.length:
            return self.source[self.pos + offset]
        return None

    def advance(self, n=1):
        for _ in range(n):
            if self.pos < self.length:
                if self.source[self.pos] == '\n':
                    self.line += 1
                    self.column = 1
                else:
                    self.column += 1
                self.pos += 1

    def add_token(self, type, value):
        self.tokens.append(Token(type, value, self.line, self.column))

    def read_open_tag_start(self):
        self.add_token(TokenType.TAG_OPEN_START, "<")
        self.advance()

    def read_close_tag_start(self):
        self.add_token(TokenType.TAG_CLOSE_START, "</")
        self.advance(2)

    def read_identifier(self):
        start = self.pos
        # Allow letters, numbers, -, _, : (for namespaced tags/attrs)
        while self.pos < self.length and (self.source[self.pos].isalnum() or self.source[self.pos] in "-_:"):
            self.advance()
        value = self.source[start:self.pos]
        
        # Determine if it's a tag name or attribute name
        # If the last token was < or </, it's a tag name.
        last_type = self.tokens[-1].type if self.tokens else None
        if last_type in (TokenType.TAG_OPEN_START, TokenType.TAG_CLOSE_START):
            self.add_token(TokenType.TAG_NAME, value)
        else:
            self.add_token(TokenType.ATTR_NAME, value)

    def read_attr_value(self, quote):
        self.advance() # Skip opening quote
        start = self.pos
        while self.pos < self.length:
            char = self.source[self.pos]
            if char == quote:
                # Check for escaped quote
                if self.pos > 0 and self.source[self.pos-1] == '\\':
                    pass
                else:
                    break
            self.advance()
        
        value = self.source[start:self.pos]
        self.add_token(TokenType.ATTR_VALUE, value)
        
        if self.pos < self.length:
            self.advance() # Skip closing quote

    def read_expression(self):
        self.add_token(TokenType.EXPRESSION_START, "{")
        self.advance()
        
        start = self.pos
        stack = ['{'] # Initial brace
        
        while self.pos < self.length and stack:
            char = self.source[self.pos]
            
            # Check top of stack
            top = stack[-1]
            
            # String/Template/Regex modes
            if top in ('"', "'", '`', '/'):
                if char == top:
                    # Check for escaped quote/slash
                    if self.pos > 0 and self.source[self.pos-1] == '\\':
                        # Handle edge case: \\" is escaped backslash, then quote. So quote is NOT escaped.
                        bs_count = 0
                        idx = self.pos - 1
                        while idx >= 0 and self.source[idx] == '\\':
                            bs_count += 1
                            idx -= 1
                        if bs_count % 2 == 0:
                            # Even backslashes means char is real
                            stack.pop()
                    else:
                        stack.pop()
                elif top == '`' and char == '$' and self.peek() == '{':
                    # Interpolation in template literal
                    stack.append('{')
                    self.advance(2)
                    continue
                
                self.advance()
                continue
                
            # Code mode (top is '{' or '(' or '[')
            
            # Start string/template?
            if char in ('"', "'", '`'):
                stack.append(char)
                self.advance()
                continue

            # Start Regex?
            # Heuristic: / is regex if previous char was not an identifier/number/closing-paren
            # This is complex to do perfectly without full lexing.
            # Simplified check: if / and not followed by space or = (division), assume regex?
            # Or check previous non-whitespace char?
            if char == '/':
                # Check previous non-whitespace
                idx = self.pos - 1
                while idx >= start and self.source[idx].isspace():
                    idx -= 1
                
                prev_char = self.source[idx] if idx >= start else None
                
                # If prev_char is None (start of expr) or operator or opener, it's regex
                # Identifiers, numbers, closers usually mean division
                is_regex = False
                if prev_char is None:
                    is_regex = True
                elif prev_char in '({[,=:?&|!~+*-/%^>': # Removed < to avoid </tag> being seen as regex
                    is_regex = True
                elif prev_char == 'return' or prev_char == 'typeof': # Keywords (hard to check without tokenizing)
                     pass 
                
                if is_regex:
                    stack.append('/')
                    self.advance()
                    continue
                
            # Comments?
            if char == '/' and self.peek() == '*':
                self.advance(2)
                # Consume block comment
                while self.pos < self.length:
                    if self.source[self.pos] == '*' and self.peek() == '/':
                        self.advance(2)
                        break
                    self.advance()
                continue
                
            if (char == '/' and self.peek() == '/') or char == '#':
                self.advance(1)
                # Consume line comment
                while self.pos < self.length:
                    if self.source[self.pos] == '\n':
                        break
                    self.advance()
                continue
            
            # Braces/Parens/Brackets
            if char in '{[(':
                stack.append(char)
            elif char in '}])':
                if (top == '{' and char == '}') or \
                   (top == '[' and char == ']') or \
                   (top == '(' and char == ')'):
                    stack.pop()
                else:
                    # Mismatch or unbalanced?
                    pass
            
            if stack:
                self.advance()
            
        value = self.source[start:self.pos].strip()
        self.add_token(TokenType.EXPRESSION_BODY, value)
        
        if self.pos < self.length and self.source[self.pos] == '}':
            self.add_token(TokenType.EXPRESSION_END, "}")
            self.advance()

    def read_text(self):
        start = self.pos
        while self.pos < self.length:
            char = self.source[self.pos]
            if char == '<':
                break
            if char == '{':
                break
            self.advance()
        
        value = self.source[start:self.pos]
        if value:
            self.add_token(TokenType.TEXT, value)
