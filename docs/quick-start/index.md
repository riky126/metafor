# Introduction

You are reading the documentation for Metafor!

Metafor is a Python framework for building user interfaces. It builds on top of standard HTML, CSS, and Python and provides a declarative, component-based programming model that helps you efficiently develop user interfaces of any complexity.

Here is a minimal example:

<div class="feature-code" data-filename="App.py">

```python
from metafor.core import create_signal

@component("App") @props {
    count, set_count = create_signal(0)
}

@ptml {
    <div id="app">
        <button onclick=@{lambda: set_count(count() + 1)}>
            Count is: @{count()}
        </button>
    </div>
}
```

</div>

**Result**

<div style="margin: 20px 0; padding: 20px; border: 1px solid #ddd; border-radius: 16px;">
    <button style="padding: 8px 16px;">Count is: 0</button>
</div>

The above example demonstrates the two core features of Metafor:

*   **Declarative Rendering**: Metafor extends standard HTML with a template syntax called PTML that allows us to declaratively describe HTML output based on Python state.
*   **Reactivity**: Metafor automatically tracks Python state changes and efficiently updates the DOM when changes happen.

You may already have questions - don't worry. We will cover every little detail in the rest of the documentation. For now, please read along so you can have a high-level understanding of what Metafor offers.

**Prerequisites**

The rest of the documentation assumes basic familiarity with HTML, CSS, and Python. If you are totally new to frontend development, it might not be the best idea to jump right into a framework as your first step - grasp the basics and then come back! Prior experience with other frameworks helps, but is not required.

## The Progressive Framework

Metafor is a framework and ecosystem that covers most of the common features needed in frontend development. But the web is extremely diverse - the things we build on the web may vary drastically in form and scale. With that in mind, Metafor is designed to be flexible and incrementally adoptable.

Depending on your use case, Metafor can be used in different ways:

*   Enhancing static HTML without a build step
*   Single-Page Application (SPA)
*   Fullstack / Server-Side Rendering (SSR)

If you find these concepts intimidating, don't worry! The tutorial and guide only require basic HTML and Python knowledge, and you should be able to follow along without being an expert in any of these.

Despite the flexibility, the core knowledge about how Metafor works is shared across all these use cases. Even if you are just a beginner now, the knowledge gained along the way will stay useful as you grow to tackle more ambitious goals in the future.

## Single-File Components

In most build-tool-enabled Metafor projects, we author Metafor components using Python files. A Metafor component encapsulates the component's logic (Python), template (PTML), and styles (CSS classes) in a single file (or alongside it).

Here's the previous example:

<div class="feature-code" data-filename="App.py">

```python
from metafor.core import create_signal

@component("App") @props {
    count, set_count = create_signal(0)
}

@ptml {
    <button onclick=@{lambda: set_count(count() + 1)}>
        Count is: @{count()}
    </button>
}
```

</div>

This is the recommended way to author Metafor components if your use case warrants a build setup.

## Pick Your Learning Path

Different developers have different learning styles. Feel free to pick a learning path that suits your preference - although we do recommend going over all of the content, if possible!

<div class="two-col-cards">
    <div class="info-card">
        <h3>Try the Tutorial</h3>
        <p>For those who prefer learning things hands-on.</p>
        <div class="section-cta">
            <a href="../tutorial/">Start Tutorial ></a>
        </div>
    </div>
    <div class="info-card">
        <h3>Read the Guide</h3>
        <p>The guide walks you through every aspect of the framework in full detail.</p>
        <div class="section-cta">
            <a href="../quick-guide/">Read the Guide ></a>
        </div>
    </div>
</div>
