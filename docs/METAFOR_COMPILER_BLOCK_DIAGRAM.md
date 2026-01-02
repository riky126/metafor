# Metafor Compiler Block Diagram

## Compilation Flow: PTML → Python

```
┌─────────────────────────────────────────────────────────────────┐
│                         PTML Source File                         │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │ @component("Name") @props { ... }                          │ │
│  │ @ptml { <div>@{expr}</div> }                               │ │
│  │ @style { .class { ... } }                                  │ │
│  └───────────────────────────────────────────────────────────┘ │
└──────────────────────────────┬────────────────────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │   Phase 1: Block Parser               │
        │   (_parse_blocks)                     │
        │                                        │
        │   • Scans for @block declarations      │
        │   • Extracts block content             │
        │   • Tracks line numbers                │
        └──────────────────┬─────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │   Parsed Blocks Structure             │
        │   ┌────────────────────────────────┐  │
        │   │ blocks = {                     │  │
        │   │   'component': {...},          │  │
        │   │   'props': {...},              │  │
        │   │   'ptml': {...},               │  │
        │   │   'style': {...}               │  │
        │   │ }                              │  │
        │   └────────────────────────────────┘  │
        └──────────────────┬─────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │   Phase 2: Block Processor             │
        │   (_process_blocks)                   │
        │                                        │
        │   • Extract component metadata         │
        │   • Parse @prop declarations           │
        │   • Collect imports                    │
        │   • Extract Python logic               │
        │   • Transform inline PTML              │
        └──────────────────┬─────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │   Processed Data                     │
        │   ┌────────────────────────────────┐  │
        │   │ component_name = "Counter"     │  │
        │   │ props_config = {...}           │  │
        │   │ imports = [...]                 │  │
        │   │ body_code = [...]              │  │
        │   │ ptml_content = "<div>..."      │  │
        │   └────────────────────────────────┘  │
        └──────────────────┬─────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │   Phase 3: PTML Compilation           │
        │   (_compile_ptml)                     │
        │                                        │
        │   ┌──────────────────────────────────┐ │
        │   │ 3.1 Tokenization                 │ │
        │   │ (PTMLTokenizer)                  │ │
        │   │                                    │ │
        │   │ Input: "<div>@{count}</div>"      │ │
        │   │ Output: [Token(...), ...]        │ │
        │   └────────────┬─────────────────────┘ │
        │                │                        │
        │                ▼                        │
        │   ┌──────────────────────────────────┐ │
        │   │ 3.2 Parsing                      │ │
        │   │ (PTMLParser)                     │ │
        │   │                                    │ │
        │   │ Input: [Token(...), ...]         │ │
        │   │ Output: PTMLElement(...)         │ │
        │   └────────────┬─────────────────────┘ │
        │                │                        │
        │                ▼                        │
        │   ┌──────────────────────────────────┐ │
        │   │ 3.3 Code Generation              │ │
        │   │ (OptimizingCodeGenerator)         │ │
        │   │                                    │ │
        │   │ Input: PTMLElement(...)           │ │
        │   │ Output: "t.div({}, [count])"     │ │
        │   └──────────────────────────────────┘ │
        └──────────────────┬─────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │   Compiled PTML Code                  │
        │   "t.div({}, [t.h2({}, [count])])"   │
        └──────────────────┬─────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │   Phase 4: Module Code Generator      │
        │   (_generate_code)                    │
        │                                        │
        │   • Add framework imports              │
        │   • Add user imports                   │
        │   • Generate component function        │
        │   • Inject user logic                  │
        │   • Add return statement               │
        │   • Wrap with context providers        │
        └──────────────────┬─────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │   Phase 5: Validation                  │
        │   (_check_undefined_variables)        │
        │                                        │
        │   • Parse generated code to AST       │
        │   • Collect defined names              │
        │   • Check all usages are defined       │
        │   • Report errors with line numbers    │
        └──────────────────┬─────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │         Generated Python Code         │
        │   ┌────────────────────────────────┐  │
        │   │ from metafor.core import ...    │  │
        │   │                                  │  │
        │   │ @component(props={...})         │  │
        │   │ def Counter(**props):           │  │
        │   │     count = ...                 │  │
        │   │     return t.div(...)           │  │
        │   └────────────────────────────────┘  │
        └────────────────────────────────────────┘
```

## Detailed PTML Compilation Pipeline

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

## Component Structure Transformation

```
┌─────────────────────────────────────────────────────────────┐
│                    Input PTML File                           │
├─────────────────────────────────────────────────────────────┤
│ @component("Counter") @props {                              │
│     @prop initial: int = 0                                   │
│     count, set_count = create_signal(0)                      │
│ }                                                             │
│                                                               │
│ @ptml {                                                       │
│     <div>                                                     │
│         <h2>Count: @{count}</h2>                             │
│         <button onclick=@{increment}>+</button>               │
│     </div>                                                    │
│ }                                                             │
└───────────────────────────┬───────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              Generated Python Module                         │
├─────────────────────────────────────────────────────────────┤
│ from metafor.core import unwrap, create_signal               │
│ from metafor.dom import t, load_css                          │
│ from metafor.decorators import component                     │
│                                                               │
│ @component(props={'initial': (int, 0)})                     │
│ def Counter(**props):                                        │
│     initial = props.get('initial')                           │
│     count, set_count = create_signal(0)                      │
│                                                               │
│     def increment():                                         │
│         set_count(count() + 1)                               │
│                                                               │
│     return t.div({}, [                                       │
│         t.h2({}, ["Count: ", count]),                        │
│         t.button({"onclick": increment}, ["+"])              │
│     ], css=None)                                             │
└─────────────────────────────────────────────────────────────┘
```

## Data Flow Diagram

```
┌──────────────┐
│  PTML File   │
└──────┬───────┘
       │
       │ source text
       ▼
┌─────────────────────┐
│  Block Parser       │
│  • Find @blocks     │
│  • Extract content  │
└──────┬──────────────┘
       │
       │ blocks dict
       ▼
┌─────────────────────┐
│  Block Processor    │
│  • Parse metadata   │
│  • Extract logic    │
│  • Collect imports  │
└──────┬──────────────┘
       │
       │ processed_data
       ▼
┌─────────────────────┐      ┌──────────────────┐
│  PTML Compiler      │      │  PTML Content    │
│  ┌───────────────┐  │      │  "<div>...</div>" │
│  │ Tokenizer     │◄─┼──────┼──────────────────┘
│  └───────┬───────┘  │      │
│          │          │      │
│          │ tokens   │      │
│          ▼          │      │
│  ┌───────────────┐  │      │
│  │ Parser        │  │      │
│  └───────┬───────┘  │      │
│          │          │      │
│          │ AST      │      │
│          ▼          │      │
│  ┌───────────────┐  │      │
│  │ Code Generator│  │      │
│  └───────┬───────┘  │      │
└──────────┼──────────┘      │
           │                 │
           │ dom_code        │
           ▼                 │
┌─────────────────────┐      │
│  Module Generator   │      │
│  • Add imports      │      │
│  • Create function  │      │
│  • Inject logic     │      │
│  • Add return       │      │
└──────┬──────────────┘      │
       │                     │
       │ python_code         │
       ▼                     │
┌─────────────────────┐      │
│  Validator          │      │
│  • Parse AST        │      │
│  • Check scope      │      │
│  • Report errors    │      │
└──────┬──────────────┘      │
       │                     │
       │ validated_code      │
       ▼                     │
┌─────────────────────┐      │
│  Python File        │      │
│  (output)           │      │
└─────────────────────┘      │
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
       ├─ TAG_OPEN_START ──► parse_element() ──► PTMLElement
       │
       ├─ EXPR_START ──────► parse_expression() ──► PTMLExpression
       │
       ├─ DIRECTIVE_IF ────► parse_if() ──► PTMLIf
       │
       ├─ DIRECTIVE_FOREACH ─► parse_foreach() ──► PTMLForEach
       │
       ├─ TEXT ─────────────► PTMLText
       │
       └─ FRAGMENT_OPEN ────► parse_fragment() ──► PTMLFragment
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

