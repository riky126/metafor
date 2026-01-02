# Metafor Compiler Documentation

## Overview

The Metafor compiler is a source-to-source compiler that transforms PTML (Python Template Markup Language) files into executable Python code. PTML files combine HTML-like template syntax with Python logic, enabling developers to write reactive web components using a familiar syntax.

## Architecture

The compiler follows a traditional compiler architecture with distinct phases:

1. **Block Parsing** - Extracts structured blocks from the source file
2. **Block Processing** - Processes each block to extract metadata and logic
3. **PTML Compilation** - Compiles the template syntax to Python DOM calls
4. **Code Generation** - Combines all parts into a final Python module
5. **Validation** - Validates the generated code for correctness

## File Structure

```
metafor/compiler/
├── compiler.py      # Main compiler orchestrator
├── tokenizer.py     # PTML tokenizer (lexical analysis)
├── parser.py        # PTML parser (syntax analysis)
└── code_generator.py # Code generator (code generation)
```

## PTML File Structure

A PTML file consists of several optional blocks:

### 1. Component/Page Declaration
```ptml
@component("ComponentName")
```
or
```ptml
@page("/uri", "ComponentName")
```

### 2. Props Block (optional)
```ptml
@props {
    @prop name: str = "default"
    # Python imports and logic
}
```

### 3. PTML Template Block (required)
```ptml
@ptml {
    <div className="container">
        <h1>@{title}</h1>
    </div>
}
```

### 4. Style Block (optional)
```ptml
@style (scope="scoped") {
    .container { color: red; }
}
```

### 5. Context Blocks (optional)
```ptml
<-- @context(ThemeContext) @MyApp {
    @value theme = "dark"
}
```

## Compilation Phases

### Phase 1: Block Parsing (`_parse_blocks`)

The compiler scans the source file for block declarations starting with `@`:

- **Block Types**: `@component`, `@page`, `@props`, `@ptml`, `@style`, `@context`
- **Block Structure**: Each block has:
  - Optional arguments in parentheses: `@component("Name")`
  - Content in curly braces: `{ ... }`
  - Start line number for error reporting

**Example:**
```ptml
@component("Counter") {
    count = 0
}
@ptml {
    <div>@{count}</div>
}
```

Parsed into:
```python
blocks = {
    'component': {'args': '("Counter")', 'content': 'count = 0', 'start_line': 1},
    'ptml': {'args': '', 'content': '<div>@{count}</div>', 'start_line': 4}
}
```

### Phase 2: Block Processing (`_process_blocks`)

Each block is processed to extract:

1. **Component Metadata**:
   - Component name from `@component` or `@page`
   - Page URI from `@page` block

2. **Props Configuration**:
   - Extracts `@prop` declarations: `@prop name: type = default`
   - Builds props configuration dictionary

3. **Imports and Logic**:
   - Extracts `import` and `from ... import` statements
   - Collects Python code from props/component/page blocks
   - Transforms inline PTML (`@t{...}` or `@: &lt;tag&gt;`) to compiled code

4. **Context Blocks**:
   - Validates context block structure
   - Extracts context class, wrapper name, and data values

### Phase 3: PTML Compilation (`_compile_ptml`)

The `@ptml` block content goes through three sub-phases:

#### 3.1 Tokenization (`PTMLTokenizer`)

Converts PTML source into a stream of tokens:

**Token Types:**
- `TAG_OPEN_START` (`&lt;`)
- `TAG_NAME` (`div`, `span`, etc.)
- `ATTR_NAME` (`className`, `onclick`, etc.)
- `ATTR_EQ` (`=`)
- `ATTR_EXPR_EQ` (`:=`)
- `ATTR_VALUE` (quoted strings)
- `EXPR_START` (`@{`)
- `EXPR_BODY` (Python expression)
- `EXPR_END` (`}`)
- `DIRECTIVE_IF` (`@if`)
- `DIRECTIVE_FOREACH` (`@foreach`)
- `DIRECTIVE_SWITCH` (`@switch`)
- `DIRECTIVE_MATCH` (`@match`)
- `TEXT` (text content)
- `FRAGMENT_OPEN` (`&lt;&gt;`)
- `FRAGMENT_CLOSE` (`&lt;/&gt;`)

**Example:**
```ptml
<div className=@{theme}>@{count}</div>
```

Tokenized as:
```
TAG_OPEN_START, TAG_NAME("div"), ATTR_NAME("className"), ATTR_EXPR_EQ, 
EXPR_BODY("theme"), EXPR_END, TAG_OPEN_END,
EXPR_START, EXPR_BODY("count"), EXPR_END,
TAG_CLOSE_START, TAG_NAME("div"), TAG_OPEN_END
```

#### 3.2 Parsing (`PTMLParser`)

Builds an Abstract Syntax Tree (AST) from tokens:

**Node Types:**
- `PTMLElement` - HTML elements with tag, attributes, children
- `PTMLText` - Text content
- `PTMLExpression` - Python expressions (`@{...}`)
- `PTMLIf` - Conditional rendering (`@if`)
- `PTMLForEach` - List iteration (`@foreach`)
- `PTMLSwitch` - Switch statement (`@switch`)
- `PTMLMatch` - Match case (`@match`)
- `PTMLFragment` - Fragment wrapper (`&lt;&gt;...&lt;/&gt;`)

**Example:**
```ptml
<div className=@{theme}>
    @if {count > 0}
        <span>@{count}</span>
    @foreach item in items {
        <li>@{item}</li>
    }
</div>
```

Parsed into:
```
PTMLElement(
    tag="div",
    attrs={"className": PTMLExpression("theme")},
    children=[
        PTMLIf(condition="count > 0", children=[PTMLElement(...)]),
        PTMLForEach(item="item", list_expr="items", children=[...])
    ]
)
```

#### 3.3 Code Generation (`OptimizingCodeGenerator`)

Transforms AST nodes into Python code that uses Metafor's DOM API:

**Transformations:**
- Elements → `t.tag_name(props, children)`
- Expressions → Direct Python expressions
- Directives → Metafor components:
  - `@if` → `Show(when=lambda: condition, children=lambda: ...)`
  - `@foreach` → `For(each=list, children=lambda item, index: ...)`
  - `@switch` → `Switch(children=[Match(...), ...])`

**Example:**
```ptml
<div className=@{theme}>@{count}</div>
```

Generated as:
```python
t.div({"className": theme}, [count])
```

### Phase 4: Module Code Generation (`_generate_code`)

Combines all processed blocks into a complete Python module:

1. **Imports**: Adds framework imports and user imports
2. **Component Function**: Creates the component function with:
   - Decorator (`@component` or `@page`)
   - Props unpacking
   - User logic code
   - Return statement with compiled DOM code
3. **Context Providers**: Wraps component with context providers if needed
4. **Style Handling**: Adds CSS loading/embedding code

**Example Output:**
```python
from metafor.core import unwrap, create_signal
from metafor.dom import t, load_css
from metafor.decorators import component

@component(props={'count': (int, 0)})
def Counter(**props):
    count = props.get('count')
    return t.div({}, [t.h2({}, ["Counter"]), t.p({}, [count])], css=None)
```

### Phase 5: Validation (`_check_undefined_variables`)

Validates the generated Python code:

1. **AST Parsing**: Parses generated code into AST
2. **Scope Analysis**: 
   - Collects all defined names (imports, function args, assignments)
   - Checks all used names are defined
3. **Error Reporting**: Reports undefined variables with original line numbers

## Key Features

### 1. Expression Syntax

- **Interpolation**: `@{expression}` - Embeds Python expressions
- **Attribute Binding**: `className=@{expr}` - Dynamic attributes
- **Arrow Functions**: `(x) -> x + 1` → `lambda x: x + 1`

### 2. Directives

- **@if**: Conditional rendering
  ```ptml
  @if {condition} {
      <div>Content</div>
  }
  ```

- **@foreach**: List iteration
  ```ptml
  @foreach item in items, key=item.id {
      <li>@{item.name}</li>
  } -> fallback {
      <p>No items</p>
  }
  ```

- **@switch/@match**: Pattern matching
  ```ptml
  @switch {value} {
      @match {1} { <div>One</div> }
      @match {2} { <div>Two</div> }
  }
  ```

### 3. Component System

- **Custom Components**: Capitalized tags are treated as components
  ```ptml
  <MyComponent prop="value">Children</MyComponent>
  ```

- **Props**: Type-annotated props with defaults
  ```ptml
  @prop name: str = "default"
  ```

### 4. Context System

- **Context Providers**: Wrap components with context
  ```ptml
  <-- @context(ThemeContext) @MyApp {
      @value theme = "dark"
  }
  ```

### 5. Inline PTML

- **@t{...}**: Inline template compilation
- **@: &lt;tag&gt;**: Inline tag compilation

## Error Handling

The compiler provides detailed error messages:

1. **Syntax Errors**: Reports PTML syntax errors with line numbers
2. **Validation Errors**: Reports undefined variables with original source lines
3. **Block Errors**: Reports missing required blocks or invalid block combinations

## Optimization Features

1. **Static Node Hoisting**: Identifies and hoists static DOM nodes
2. **Whitespace Optimization**: Removes unnecessary whitespace nodes
3. **Expression Optimization**: Simplifies expression transformations

## Integration with Metafor Runtime

The generated code uses Metafor's runtime APIs:

- **DOM Building**: `t.tag_name(props, children)` - Creates DOM nodes
- **Reactivity**: `create_signal()`, `create_effect()` - Reactive primitives
- **Components**: `Show`, `For`, `Switch`, `Match` - Control flow components
- **Context**: `ContextProvider` - Context API
- **Styling**: `load_css()` - CSS loading

## Example: Complete Compilation

**Input PTML:**
```ptml
@component("Counter") @props {
    from metafor.core import create_signal
    
    @prop initial: int = 0
    count, set_count = create_signal(props.get("initial", 0))
    
    def increment():
        set_count(count() + 1)
}

@ptml {
    <div className="counter">
        <h2>Count: @{count}</h2>
        <button onclick=@{increment}>Increment</button>
    </div>
}
```

**Generated Python:**
```python
from metafor.core import unwrap, create_signal
from metafor.dom import t, load_css
from metafor.decorators import component

from metafor.core import create_signal

@component(props={'initial': (int, 0)})
def Counter(**props):
    initial = props.get('initial')
    count, set_count = create_signal(props.get("initial", 0))
    
    def increment():
        set_count(count() + 1)
    
    return t.div({}, [
        t.div({"className": "counter"}, [
            t.h2({}, ["Count: ", count]),
            t.button({"onclick": increment}, ["Increment"])
        ])
    ], css=None)
```

## Compiler API

### Basic Usage

```python
from metafor.compiler import MetaforCompiler

compiler = MetaforCompiler()
with open("component.ptml", "r") as f:
    source = f.read()

compiled_code = compiler.compile(source, filename="component.ptml")
```

### Compiler Methods

- `compile(source, filename=None)` - Main compilation entry point
- `_parse_blocks(source)` - Parse source into blocks
- `_process_blocks()` - Process parsed blocks
- `_compile_ptml(ptml_content)` - Compile PTML template
- `_generate_code()` - Generate final Python code
- `_check_undefined_variables(code)` - Validate generated code

## Advanced Features

### SVG Support

SVG elements are automatically detected and use the SVG namespace:
```ptml
<svg>
    <circle cx="50" cy="50" r="40"/>
</svg>
```

### Fragment Support

Fragments allow returning multiple root elements:
```ptml
<>
    <div>First</div>
    <div>Second</div>
</>
```

### Spread Attributes

Spread attributes allow passing object properties:
```ptml
<div @{**props}>Content</div>
```

## Limitations

1. **Python Syntax in PTML**: Python statements cannot be written directly in `@ptml` blocks
2. **Block Requirements**: Must have either `@component` or `@page`, and must have `@ptml`
3. **Mutual Exclusivity**: Cannot have both `@component` and `@page` in the same file

## Future Enhancements

Potential improvements:
- Type checking integration
- Hot module replacement
- Source maps for debugging
- Additional optimizations
- Plugin system for custom directives

