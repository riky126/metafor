import enum
import re

class TokenType(enum.Enum):
    TAG_OPEN_START = "TAG_OPEN_START"       # <
    TAG_OPEN_END = "TAG_OPEN_END"           # >
    TAG_CLOSE_START = "TAG_CLOSE_START"     # </
    TAG_SELF_CLOSE = "TAG_SELF_CLOSE"       # />
    TAG_NAME = "TAG_NAME"                   # div
    ATTR_NAME = "ATTR_NAME"                 # class
    ATTR_EQ = "ATTR_EQ"                     # =
    ATTR_EXPR_EQ = "ATTR_EXPR_EQ"           # :=
    ATTR_VALUE = "ATTR_VALUE"               # "value"
    ATTR_EXPR_VALUE = "ATTR_EXPR_VALUE"     # value after :=
    ATTR_SPREAD = "ATTR_SPREAD"             # @{...} in tag
    TEXT = "TEXT"                           # text content
    EXPR_START = "EXPR_START"               # @{
    EXPR_END = "EXPR_END"                   # }
    EXPR_BODY = "EXPR_BODY"                 # content inside @{ }
    DIRECTIVE_IF = "DIRECTIVE_IF"           # @if
    DIRECTIVE_ELIF = "DIRECTIVE_ELIF"       # @elif
    DIRECTIVE_ELSE = "DIRECTIVE_ELSE"       # @else
    DIRECTIVE_FOREACH = "DIRECTIVE_FOREACH" # @foreach
    DIRECTIVE_REPEAT = "DIRECTIVE_REPEAT"   # @repeat
    DIRECTIVE_SWITCH = "DIRECTIVE_SWITCH"   # @switch
    DIRECTIVE_MATCH = "DIRECTIVE_MATCH"     # @match
    DIRECTIVE_FALLBACK = "DIRECTIVE_FALLBACK" # @fallback
    BLOCK_OPEN = "BLOCK_OPEN"               # {
    BLOCK_CLOSE = "BLOCK_CLOSE"             # }
    FRAGMENT_OPEN = "FRAGMENT_OPEN"         # <>
    FRAGMENT_CLOSE = "FRAGMENT_CLOSE"       # </>
    KEYWORD_IN = "KEYWORD_IN"               # in
    KEYWORD_KEY = "KEYWORD_KEY"             # key
    KEYWORD_FALLBACK = "KEYWORD_FALLBACK"   # fallback
    ARROW = "ARROW"                         # ->
    EOF = "EOF"

class Token:
    def __init__(self, type, value, line=0):
        self.type = type
        self.value = value
        self.line = line
    
    def __repr__(self):
        return f"Token({self.type}, {repr(self.value)})"

class PTMLTokenizer:
    def __init__(self, source):
        self.source = source
        self.pos = 0
        self.length = len(source)
        self.line = 1
        self.tokens = []

    def tokenize(self):
        
        while self.pos < self.length:
            char = self.source[self.pos]            
            if char == '<':
                if self.peek() == '!' and self.peek(2) == '-' and self.peek(3) == '-':
                    self._skip_html_comment()
                    continue
                elif self.peek() == '/':
                    if self.peek(2) == '>':
                         self.add_token(TokenType.FRAGMENT_CLOSE, "</>")
                         self.pos += 3
                    else:
                        self.add_token(TokenType.TAG_CLOSE_START, "</")
                        self.pos += 2
                        self._skip_whitespace()
                        self._read_identifier(TokenType.TAG_NAME)
                        self._skip_whitespace()
                        if self.pos < self.length and self.source[self.pos] == '>':
                            self.add_token(TokenType.TAG_OPEN_END, ">")
                            self.pos += 1
                elif self.peek() == '>':
                    self.add_token(TokenType.FRAGMENT_OPEN, "<>")
                    self.pos += 2
                else:
                    self.add_token(TokenType.TAG_OPEN_START, "<")
                    self.pos += 1
                    self._read_tag_content()
            elif char == '{':
                self.add_token(TokenType.BLOCK_OPEN, "{")
                self.pos += 1
            elif char == '}':
                self.add_token(TokenType.BLOCK_CLOSE, "}")
                self.pos += 1
            elif char == '@':
                if self.peek() == '{':
                    self._read_expression()
                else:
                    self._read_directive()
            elif char == '/' and self.peek() == '*':
                self._skip_comment()
            elif char == '#':
                self._skip_hash_comment()
            elif char == '-' and self.peek() == '>':
                self.add_token(TokenType.ARROW, "->")
                self.pos += 2
            else:
                self._read_text()
        
        self.add_token(TokenType.EOF, "")
        return self.tokens

    def _skip_comment(self):
        self.pos += 2  # Skip /*
        while self.pos < self.length:
            if self.source[self.pos] == '*' and self.peek() == '/':
                self.pos += 2  # Skip */
                return
            if self.source[self.pos] == '\n':
                self.line += 1
            self.pos += 1

    def _skip_html_comment(self):
        self.pos += 4 # Skip <!--
        while self.pos < self.length:
            if self.source[self.pos] == '-' and self.peek() == '-' and self.peek(2) == '>':
                self.pos += 3 # Skip -->
                return
            if self.source[self.pos] == '\n':
                self.line += 1
            self.pos += 1

    def _skip_hash_comment(self):
        self.pos += 1 # Skip #
        while self.pos < self.length:
            if self.source[self.pos] == '\n':
                self.line += 1
                self.pos += 1
                return
            self.pos += 1

    def peek(self, offset=1):
        if self.pos + offset < self.length:
            return self.source[self.pos + offset]
        return None

    def add_token(self, type, value):
        self.tokens.append(Token(type, value, self.line))

    def _read_tag_content(self):
        self._read_identifier(TokenType.TAG_NAME)
        while self.pos < self.length:
            self._skip_whitespace()
            char = self.source[self.pos]
            if char == '>':
                self.add_token(TokenType.TAG_OPEN_END, ">")
                self.pos += 1
                return
            elif char == '/' and self.peek() == '>':
                self.add_token(TokenType.TAG_SELF_CLOSE, "/>")
                self.pos += 2
                return
            elif char == '@' and self.peek() == '{':
                self._read_spread_attribute()
                continue
                
            self._read_identifier(TokenType.ATTR_NAME)
            self._skip_whitespace()
            if self.source[self.pos:self.pos+2] == ':=':
                self.add_token(TokenType.ATTR_EXPR_EQ, ":=")
                self.pos += 2
                self._skip_whitespace()
                self._read_attr_expr_value()
            elif self.source[self.pos] == '=':
                self.add_token(TokenType.ATTR_EQ, "=")
                self.pos += 1
                self._skip_whitespace()
                self._read_attr_value()
            else:
                # Check if it's a boolean attribute (no value)
                # Valid followers: whitespace (already skipped), '>', '/>', or start of next attribute
                char = self.source[self.pos]
                if char == '>' or (char == '/' and self.peek() == '>'):
                    # End of tag or self-closing, valid boolean attribute
                    continue
                elif char.isalnum() or char in "-_:@":
                    # Start of next attribute, valid boolean attribute
                    continue
                else:
                    # Unexpected character in tag content
                    raise SyntaxError(f"Unexpected character '{char}' in tag content at line {self.line}")

    def _read_spread_attribute(self):
        # Consumes @{...} and emits ATTR_SPREAD
        self.pos += 2 # Skip @{
        start = self.pos
        balance = 1
        in_string = False
        quote_char = None
        while self.pos < self.length:
            char = self.source[self.pos]
            if in_string:
                if char == quote_char and (self.pos == 0 or self.source[self.pos-1] != '\\'):
                    in_string = False
                    quote_char = None
                self.pos += 1
                continue
            if char == '"' or char == "'":
                in_string = True
                quote_char = char
                self.pos += 1
                continue
            if char == '{': balance += 1
            elif char == '}':
                balance -= 1
                if balance == 0: break
            self.pos += 1
            
        value = self.source[start:self.pos].strip()
        self.add_token(TokenType.ATTR_SPREAD, value)
        self.pos += 1 # Skip }

    def _read_attr_value(self):
        char = self.source[self.pos]
        if char == '"' or char == "'":
            quote = char
            self.pos += 1
            start = self.pos
            while self.pos < self.length and self.source[self.pos] != quote:
                self.pos += 1
            value = self.source[start:self.pos]
            self.add_token(TokenType.ATTR_VALUE, value)
            self.pos += 1
        elif char == '@' and self.peek() == '{':
             self._read_expression()

    def _read_attr_expr_value(self):
        start = self.pos
        in_string = False
        quote_char = None
        while self.pos < self.length:
            char = self.source[self.pos]
            if in_string:
                if char == quote_char and (self.pos == 0 or self.source[self.pos-1] != '\\'):
                    in_string = False
                    quote_char = None
                self.pos += 1
                continue
            if char == '"' or char == "'":
                in_string = True
                quote_char = char
                self.pos += 1
                continue
            if char.isspace() or char == '>' or (char == '/' and self.peek() == '>'):
                break
            self.pos += 1
        value = self.source[start:self.pos]
        self.add_token(TokenType.ATTR_EXPR_VALUE, value)

    def _read_expression(self):
        self.add_token(TokenType.EXPR_START, "@{")
        self.pos += 2
        start = self.pos
        balance = 1
        in_string = False
        quote_char = None
        while self.pos < self.length:
            char = self.source[self.pos]
            if in_string:
                if char == quote_char and (self.pos == 0 or self.source[self.pos-1] != '\\'):
                    in_string = False
                    quote_char = None
                self.pos += 1
                continue
            if char == '"' or char == "'":
                in_string = True
                quote_char = char
                self.pos += 1
                continue
            if char == '{': balance += 1
            elif char == '}':
                balance -= 1
                if balance == 0: break
            self.pos += 1
        value = self.source[start:self.pos].strip()
        self.add_token(TokenType.EXPR_BODY, value)
        self.add_token(TokenType.EXPR_END, "}")
        self.pos += 1

    def _read_directive(self):
        start = self.pos
        self.pos += 1
        while self.pos < self.length and self.source[self.pos].isalpha():
            self.pos += 1
        word = self.source[start:self.pos]
        
        if word == "@if":
            self.add_token(TokenType.DIRECTIVE_IF, word)
            self._read_directive_args()
        elif word == "@elif":
            self.add_token(TokenType.DIRECTIVE_ELIF, word)
            self._read_directive_args()
        elif word == "@else":
            self.add_token(TokenType.DIRECTIVE_ELSE, word)
            # @else doesn't take arguments, but we need to check for the block
        elif word == "@foreach":
            self.add_token(TokenType.DIRECTIVE_FOREACH, word)
            self._skip_whitespace()
            start_args = self.pos
            while self.pos < self.length and self.source[self.pos] != '{':
                self.pos += 1
            args = self.source[start_args:self.pos].strip()
            if ' in ' in args:
                item, rest = args.split(' in ', 1)
                self.add_token(TokenType.EXPR_BODY, item.strip())
                self.add_token(TokenType.KEYWORD_IN, "in")
                
                # Parse rest for list_expr, key, and fallback
                # Use robust splitting that respects nesting and quotes
                parts = []
                current_part = []
                balance = 0
                in_string = False
                quote_char = None
                
                i = 0
                length = len(rest)
                while i < length:
                    char = rest[i]
                    
                    if in_string:
                        if char == quote_char and (not current_part or current_part[-1] != '\\'):
                            in_string = False
                            quote_char = None
                        current_part.append(char)
                    else:
                        if char == '"' or char == "'":
                            in_string = True
                            quote_char = char
                            current_part.append(char)
                        elif char in '([{':
                            balance += 1
                            current_part.append(char)
                        elif char in ')]}':
                            balance -= 1
                            current_part.append(char)
                        elif char == ',' and balance == 0:
                            # Look ahead to see if this is a separator for key/fallback
                            j = i + 1
                            while j < length and rest[j].isspace():
                                j += 1
                            
                            remaining = rest[j:]
                            if remaining.startswith('key=') or remaining.startswith('fallback='):
                                parts.append("".join(current_part).strip())
                                current_part = []
                                i += 1 # Skip comma
                                continue
                            else:
                                current_part.append(char)
                        else:
                            current_part.append(char)
                    i += 1
                
                if current_part:
                    parts.append("".join(current_part).strip())

                list_expr = parts[0]
                self.add_token(TokenType.EXPR_BODY, list_expr)
                
                for part in parts[1:]:
                    if part.startswith('key='):
                        self.add_token(TokenType.KEYWORD_KEY, "key")
                        self.add_token(TokenType.EXPR_BODY, part[4:].strip())
                    elif part.startswith('fallback='):
                        self.add_token(TokenType.KEYWORD_FALLBACK, "fallback")
                        self.add_token(TokenType.EXPR_BODY, part[9:].strip())
            else:
                 self.add_token(TokenType.EXPR_BODY, args)
        elif word == "@repeat":
            self.add_token(TokenType.DIRECTIVE_REPEAT, word)
            self._skip_whitespace()
            start_args = self.pos
            while self.pos < self.length and self.source[self.pos] != '{':
                self.pos += 1
            args = self.source[start_args:self.pos].strip()
            if ' in ' in args:
                item, rest = args.split(' in ', 1)
                self.add_token(TokenType.EXPR_BODY, item.strip())
                self.add_token(TokenType.KEYWORD_IN, "in")
                
                # Parse rest for list_expr, key, and fallback
                # Use robust splitting that respects nesting and quotes
                parts = []
                current_part = []
                balance = 0
                in_string = False
                quote_char = None
                
                i = 0
                length = len(rest)
                while i < length:
                    char = rest[i]
                    
                    if in_string:
                        if char == quote_char and (not current_part or current_part[-1] != '\\'):
                            in_string = False
                            quote_char = None
                        current_part.append(char)
                    else:
                        if char == '"' or char == "'":
                            in_string = True
                            quote_char = char
                            current_part.append(char)
                        elif char in '([{':
                            balance += 1
                            current_part.append(char)
                        elif char in ')]}':
                            balance -= 1
                            current_part.append(char)
                        elif char == ',' and balance == 0:
                            # Look ahead to see if this is a separator for key/fallback
                            j = i + 1
                            while j < length and rest[j].isspace():
                                j += 1
                            
                            remaining = rest[j:]
                            if remaining.startswith('key=') or remaining.startswith('fallback='):
                                parts.append("".join(current_part).strip())
                                current_part = []
                                i += 1 # Skip comma
                                continue
                            else:
                                current_part.append(char)
                        else:
                            current_part.append(char)
                    i += 1
                
                if current_part:
                    parts.append("".join(current_part).strip())

                list_expr = parts[0]
                self.add_token(TokenType.EXPR_BODY, list_expr)
                
                for part in parts[1:]:
                    if part.startswith('fallback='):
                        self.add_token(TokenType.KEYWORD_FALLBACK, "fallback")
                        self.add_token(TokenType.EXPR_BODY, part[9:].strip())
                    # Repeat usually doesn't need key, but we can support it or ignore it.
                    # The user prompt implies it's like @foreach but mapping to Repeat.
            else:
                 self.add_token(TokenType.EXPR_BODY, args)
        elif word == "@switch":
            self.add_token(TokenType.DIRECTIVE_SWITCH, word)
            self._read_directive_args()
        elif word == "@match":
            self.add_token(TokenType.DIRECTIVE_MATCH, word)
            self._read_directive_args()
        elif word == "@fallback":
            self.add_token(TokenType.DIRECTIVE_FALLBACK, word)

    def _read_directive_args(self):
        self._skip_whitespace()
        start_cond = self.pos
        in_string = False
        quote_char = None
        while self.pos < self.length:
            char = self.source[self.pos]
            if in_string:
                if char == quote_char and (self.pos == 0 or self.source[self.pos-1] != '\\'):
                    in_string = False
                    quote_char = None
                self.pos += 1
                continue
            if char == '"' or char == "'":
                in_string = True
                quote_char = char
                self.pos += 1
                continue
            if char == '{': break
            self.pos += 1
        cond = self.source[start_cond:self.pos].strip()
        if cond: self.add_token(TokenType.EXPR_BODY, cond)

    def _read_text(self):
        start = self.pos
        while self.pos < self.length:
            char = self.source[self.pos]
            if char == '<' or char == '@' or char == '}' or char == '{' or char == '#': break
            if char == '-' and self.peek() == '>': break
            if char == '\n': self.line += 1
            self.pos += 1
        value = self.source[start:self.pos]
        if value: self.add_token(TokenType.TEXT, value)

    def _read_identifier(self, type):
        start = self.pos
        while self.pos < self.length:
            char = self.source[self.pos]
            if not (char.isalnum() or char in "-_:"): break
            if char == ':' and self.peek() == '=': break
            self.pos += 1
        value = self.source[start:self.pos]
        self.add_token(type, value)

    def _skip_whitespace(self):
        while self.pos < self.length and self.source[self.pos].isspace():
            if self.source[self.pos] == '\n': self.line += 1
            self.pos += 1
