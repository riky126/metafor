import pathlib
from .tokenizer import JSXTokenizer, TokenType, Token
from .parser import JSXParser, JSXNode, JSXElement, JSXText, JSXExpression
from .code_generator import JSXCodeGenerator, ComponentType

def jsx_to_dom_func(jsx_template: str, scope: dict = None, css_variable: str = None):
    jsx_template = load_jsx_as_docstring(jsx_template)
    
    tokenizer = JSXTokenizer(jsx_template)
    tokens = tokenizer.tokenize()
    
    parser = JSXParser(tokens)
    nodes = parser.parse()
    
    generator = JSXCodeGenerator(css_variable=css_variable)
    return generator.generate(nodes)


def load_jsx_as_docstring(file_path):
    """Loads a JSX file and returns its content as a docstring."""
    # If file_path is actually content (contains newlines or starts with <), return it directly
    # But the original function didn't do this. It strictly loaded files.
    # However, jsx_to_dom_func calls this. If jsx_template is already a string, this might fail if it's not a path.
    # Original implementation:
    # jsx_file = pathlib.Path(file_path)
    # if not jsx_file.exists(): ...
    
    # Let's stick to original implementation but maybe handle the case where it's not a file path?
    # The original implementation assumed file_path is a path.
    
    try:
        jsx_file = pathlib.Path(file_path)
        if jsx_file.exists() and jsx_file.suffix == ".jsx":
             with open(file_path, 'r') as file:
                jsx_content = file.read()
             return f"""{jsx_content}"""
    except Exception:
        pass
        
    # If it's not a file, maybe it's the content itself?
    # The original code raised FileNotFoundError.
    # But looking at usage in bundler.py might reveal more.
    # For now, let's replicate the original behavior exactly to be safe.
    
    # Check if it looks like JSX content
    if "<" in file_path or "\n" in file_path or "{" in file_path:
        return file_path

    jsx_file = pathlib.Path(file_path)
    if not jsx_file.exists():
        raise FileNotFoundError(f"JSX file not found: {file_path}")
    
    if not jsx_file.suffix == ".jsx":
        raise ValueError(f"File is not a JSX file: {file_path}")
    
    with open(file_path, 'r') as file:
        jsx_content = file.read()
    
    # Return the content as a docstring (triple-quoted string)
    return f"""{jsx_content}"""
