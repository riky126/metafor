# Metafor Compiler Block Diagram

## Compilation Flow: Source to Python Module

This diagram illustrates how a single `.ptml` file is split into its constituent blocks, processed in parallel tracks, and reassembled into a valid Python module.

```
                                  Source File (.ptml)
                                          │
                                          ▼
                                 Phase 1: Block Parser
                                    (BlockParser)
                                          │
               ┌──────────────────────────┼───────────────────────────┐
               │                          │                           │
               ▼                          ▼                           ▼
       @component / @page             @ptml                       @style
       (Logic & Metadata)           (Template)                 (Styling)
               │                          │                           │
               │                          │                           │
               ▼                          ▼                           ▼
    Phase 2: Logic Processor     Phase 3: Template Comp      Phase 4: Style Comp
    (BlockProcessor)             (_compile_ptml)             (ModuleCodeGenerator)
                                          │                           │
    ┌──────────────────────┐     ┌──────────────────────┐    ┌──────────────────────┐
    │ 1. Extract Metadata  │     │ 1. Tokenization      │    │ 1. Parse Args        │
    │    (name, route)     │     │    (PTMLTokenizer)   │    │    (lang="sass")     │
    │                      │     │                      │    │                      │
    │ 2. Process Body      │     │ 2. Parsing (AST)     │    │ 2. Sass Compilation  │
    │    • Imports         │     │    (PTMLParser)      │    │    (libsass)         │
    │    • @props parsing  │     │                      │    │                      │
    │    • Transform       │     │ 3. Code Generation   │    │ 3. Generate Loaders  │
    │      inline PTML     │     │    (CodeGenerator)   │    │    (load_css/inline) │
    │                      │     │                      │    │                      │
    └──────────┬───────────┘     └──────────┬───────────┘    └──────────┬───────────┘
               │                            │                           │
               │ Returns:                   │ Returns:                  │ Returns:
               │ - imports []               │ - dom_code_str            │ - css_kwarg
               │ - props_config {}          │   "t.div(...)"            │   "{'scoped': ...}"
               │ - body_code []             │                           │
               │                            │                           │
               └───────────────┬────────────┴───────────────────────────┘
                               │
                               ▼
                    Phase 5: Module Generation
                    (ModuleCodeGenerator)
                               │
               ┌───────────────┴────────────────────────┐
               │                                        │
               │  1. Add Framework Imports              │
               │  2. Add User Imports                   │
               │  3. Define Constants (Styles)          │
               │  4. Generate @component Decorator      │
               │  5. Define Function def Component(...) │
               │  6. Inject User Body Code              │
               │  7. Generate Return Statement          │
               │     return t.div(..., css=styles)      │
               │                                        │
               └───────────────┬────────────────────────┘
                               │
                               ▼
                    Phase 6: Scope Validation
                    (ScopeValidator)
                               │
                               ▼
                      Final Python Code (.py)
```

## Detailed Block Processing

### 1. Component Block Processor (`@component`)
Transforms the custom component syntax into standard Python constructs.
*   **Input**:
    ```python
    @component("Counter") @props {
        @prop initial: int = 0
        count, set_count = create_signal(initial)
    }
    ```
*   **Output Data**:
    *   `component_name`: "Counter"
    *   `props_config`: `{'initial': {'type': 'int', 'default': '0'}}`
    *   `body_code`: `["count, set_count = create_signal(initial)"]`

### 2. PTML Compiler (`@ptml`)
Compiles the HTML-like template into nested Python function calls.
*   **Input**:
    ```html
    @ptml {
        <div class="card">
            <h1>@{title}</h1>
        </div>
    }
    ```
*   **Pipeline**:
    1.  `Tokenizer`: `[<, div, class=, "card", >, <, h1, >, @{, title, }, ...]`
    2.  `Parser`: `Element(div, attrs={class: "card"}, children=[Element(h1, children=[Expr(title)])])`
    3.  `CodeGenerator`: `"t.div({'class': 'card'}, [t.h1({}, [title])])"`

### 3. Style Processor (`@style`)
Handles CSS pre-processing and scoping.
*   **Input**:
    ```scss
    @style(lang="scss", scope="scoped") {
        .card { color: $primary; }
    }
    ```
*   **Process**:
    1.  Detects `lang="scss"`.
    2.  Compiles SCSS to CSS using `libsass`.
    3.  Generates Python code to inject styles:
        ```python
        inline_styles = """ .card { color: blue; } """
        app_styles = inline_styles
        ```
    4.  Passes `css={'scoped': app_styles}` to the component's root element.

## Assembly: The `ModuleCodeGenerator`

The final assembly phase merges the processed streams into valid Python code.

```python
# [Framework Imports]
from metafor.core import ...
from metafor.dom import t, load_css

# [User Imports] (from @component)
import random

# [Styles] (from @style)
inline_styles = """..."""

# [Component Definition] (from @component metadata)
@component(props={'initial': (int, 0)})
def Counter(**props):
    # [Prop Extraction]
    initial = props.get('initial')

    # [User Body] (from @component body)
    count, set_count = create_signal(initial)

    # [Return Statement] (from @ptml + @style)
    return t.div(
        {},
        [count],
        css={'scoped': inline_styles}  # Styles injected here
    )
```

## Detailed PTML Compilation Pipeline

This section details the internal working of **Phase 3: Template Comp**.

```
PTML Content: "<div className=@{theme}>@{count}</div>"
                    │
                    ▼
    ┌───────────────────────────────────────────────┐
    │         PTMLTokenizer.tokenize()               │
    │                                                │
    │  Character-by-character scanning:              │
    │  • '<' → TAG_OPEN_START                        │
    │  • 'div' → TAG_NAME("div")                     │
    │  • 'className' → ATTR_NAME                     │
    │  • ':=' → ATTR_EXPR_EQ                         │
    │  • '@{' → EXPR_START                           │
    │  • 'theme' → EXPR_BODY("theme")                │
    │  • '}' → EXPR_END                              │
    │  • '>' → TAG_OPEN_END                          │
    │  • '@{' → EXPR_START                           │
    │  • 'count' → EXPR_BODY("count")                │
    │  • '}' → EXPR_END                              │
    │  • '</div>' → TAG_CLOSE_START, TAG_NAME, ...   │
    └───────────────────┬───────────────────────────┘
                         │
                         ▼
    ┌───────────────────────────────────────────────┐
    │         Token Stream                           │
    │  [Token(TAG_OPEN_START, "<"),                │
    │   Token(TAG_NAME, "div"),                     │
    │   Token(ATTR_NAME, "className"),              │
    │   Token(ATTR_EXPR_EQ, ":="),                  │
    │   Token(EXPR_START, "@{"),                    │
    │   Token(EXPR_BODY, "theme"),                  │
    │   Token(EXPR_END, "}"),                       │
    │   Token(TAG_OPEN_END, ">"),                   │
    │   Token(EXPR_START, "@{"),                    │
    │   Token(EXPR_BODY, "count"),                  │
    │   Token(EXPR_END, "}"),                       │
    │   Token(TAG_CLOSE_START, "</"),               │
    │   Token(TAG_NAME, "div"),                     │
    │   Token(TAG_OPEN_END, ">")]                   │
    └───────────────────┬───────────────────────────┘
                         │
                         ▼
    ┌───────────────────────────────────────────────┐
    │         PTMLParser.parse()                    │
    │                                                │
    │  Recursive descent parsing:                   │
    │  • parse_element() → PTMLElement              │
    │    - tag = "div"                              │
    │    - attrs = {"className": PTMLExpression}   │
    │    - children = [PTMLExpression("count")]     │
    └───────────────────┬───────────────────────────┘
                         │
                         ▼
    ┌───────────────────────────────────────────────┐
    │         Abstract Syntax Tree (AST)            │
    │                                                │
    │  PTMLElement(                                 │
    │    tag="div",                                 │
    │    attrs={                                     │
    │      "className": PTMLExpression("theme")     │
    │    },                                         │
    │    children=[                                  │
    │      PTMLExpression("count")                  │
    │    ]                                          │
    │  )                                            │
    └───────────────────┬───────────────────────────┘
                         │
                         ▼
    ┌───────────────────────────────────────────────┐
    │    OptimizingCodeGenerator.generate()         │
    │                                                │
    │  AST traversal and code generation:           │
    │  • Visit PTMLElement                          │
    │  • Convert tag to t.div()                    │
    │  • Transform attrs to dict                    │
    │  • Transform children to list                 │
    │  • Generate: t.div({"className": theme},     │
    │                    [count])                   │
    └───────────────────┬───────────────────────────┘
                         │
                         ▼
    ┌───────────────────────────────────────────────┐
    │         Generated Python Code                 │
    │                                                │
    │  "t.div({\"className\": theme}, [count])"     │
    └───────────────────────────────────────────────┘
```

## Tokenization Details

```
Input: "<div className=\"test\">@{count}</div>"

Position: 0
Char: '<'
Action: Add TAG_OPEN_START, advance, call _read_tag_content()

Position: 1
Chars: 'div'
Action: Read identifier → TAG_NAME("div")

Position: 4
Char: ' '
Action: Skip whitespace

Position: 5
Chars: 'className'
Action: Read identifier → ATTR_NAME("className")

Position: 14
Char: '='
Action: Add ATTR_EQ, advance

Position: 15
Char: '"'
Action: Read quoted string → ATTR_VALUE("test")

Position: 21
Char: '>'
Action: Add TAG_OPEN_END, return from _read_tag_content()

Position: 22
Char: '@'
Action: Check next char is '{' → _read_expression()

Position: 23
Char: '{'
Action: Add EXPR_START, advance

Position: 24-28
Chars: 'count'
Action: Read until '}' → EXPR_BODY("count")

Position: 29
Char: '}'
Action: Add EXPR_END, advance

Position: 30
Char: '<'
Action: Check next char is '/' → TAG_CLOSE_START

... and so on
```

## Parser State Machine

```
START
  │
  ▼
┌─────────────┐
│ parse_node()│
└──────┬──────┘
       │
       ├─ TAG_OPEN_START (<) ──► parse_element() ──► PTMLElement
       │
       ├─ EXPR_START (@{) ──────► parse_expression() ──► PTMLExpression
       │
       ├─ DIRECTIVE_IF (@if) ────► parse_if() ──► PTMLIf
       │
       ├─ DIRECTIVE_FOREACH (@foreach) ─► parse_foreach() ──► PTMLForEach
       │
       ├─ TEXT (plain text) ─────────────► PTMLText
       │
       └─ FRAGMENT_OPEN (<>) ────► parse_fragment() ──► PTMLFragment
```

## Code Generation Transformations

```
PTML Syntax              →  Python Code
─────────────────────────────────────────────────────────
<div>                    →  t.div({}, [])
<div className="x">      →  t.div({"className": "x"}, [])
<div className=@{expr}>   →  t.div({"className": expr}, [])
<div>@{count}</div>       →  t.div({}, [count])
@if {cond} { ... }       →  Show(when=lambda: cond, children=lambda: ...)
@foreach x in list { ... } → For(each=list, children=lambda x, index: ...)
<MyComponent prop="v">   →  MyComponent(prop="v", children=[...])
<>...</>                  →  [child1, child2, ...]
```
