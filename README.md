<div align="center">
  <img src="docs/assets/named-logo.png" alt="Metafor Logo" width="450" height="auto" />
  <p><strong>The Fine-Grained Reactive Framework for the Web.</strong></p>
</div>

---

## Introduction

**Metafor** is a modern reactive framework designed to bring fine-grained reactivity to Python web development. It avoids the overhead of Virtual DOM diffing by using a precise **Signal-based** graph that updates only what needs to change.

### Why "Metafor"?

The name strikes a balance between technical relevance and conceptual depth:

*   **Metaphor (Transfer of Meaning)**: Just as a metaphor transfers meaning from one concept to another, a **Signal** transfers state value from your data source directly to the UI. It is the vehicle that carries the update across the gap.
*   **"Meta" (Abstraction)**: The framework acts as a compiler and runtime layer (meta-programming) that abstracts away raw DOM manipulation and complex dependency tracking.
*   **Identity**: The logo represents both an **"M"** for Metafor and a **Sine Wave**—the universal symbol for a signal. It captures the essence of "data in motion," connecting your application state to the user interface in a continuous, flowing path.

---

## Features

*   **Fine-Grained Reactivity**: Based on the Signal pattern (similar to SolidJS), ensuring high performance without VDOM overhead.
*   **Zero-Overhead Compilation**: PTML templates are compiled into efficient Python functions that update the DOM directly.
*   **Unified Build System**: A single toolchain for serving, building, and packaging your applications.
*   **Pythonic**: Write your logic, templates (`@ptml`), and styles (`@style`) in a way that feels natural to Python developers.

---

## Installation

### Prerequisites
*   Python 3.11 or higher
*   `pip`

### Step-by-Step Install

1.  **Clone the Repository**
    ```bash
    git clone https://github.com/metafor-org/metafor.git
    cd metafor
    ```

2.  **Run the Installer**
    This script installs the framework and the CLI tool into your environment.
    ```bash
    ./install.sh
    ```

3.  **Verify Installation**
    Check that the CLI is accessible.
    ```bash
    metafor version
    ```

---

## Quick Start Guide

Let's build a simple counter application to see Metafor in action.

### 1. Create a New App
Use the CLI to scaffold a new project with the default template.

```bash
metafor new my-app
cd my-app
```

### 2. Project Structure
Your new project will look like this:

```
my-app/
├── assets/              # Static assets (images, styles)
├── public/              # Build output
├── tests/               # Unit tests
├── app.ptml             # Root component
├── index.html           # HTML entry point (Pyscript loader)
├── main.py              # Application entry point
├── manifest.json        # PWA Manifest
├── pyscript.toml        # Configuration
├── serviceWorker.js     # PWA Service Worker
└── setup.py             # Python package setup
```

### 3. Create a Component
Open `app.ptml` (or create a new file `components/counter.ptml`) and add the following code. This demonstrates **Signals**, **Event Handling**, and **Scoped Styles**.

```python
# app.ptml (or components/counter.ptml)

from metafor.core import create_signal
from metafor.dom import t
from metafor.decorators import component

@component("Counter") @props {
    @prop initial: int = 0
    # Create a signal with an initial value
    count, set_count = create_signal(initial)
}

@ptml {
    <div class="counter-card">
        <h2>Count is: @{count}</h2>
        
        <div class="buttons">
            <button onclick=@{lambda: set_count(count() - 1)}>-</button>
            <button onclick=@{lambda: set_count(count() + 1)}>+</button>
        </div>
    </div>
}

@style(scope="scoped") {
    .counter-card {
        padding: 2rem;
        border: 1px solid #ddd;
        border-radius: 8px;
        text-align: center;
    }
    .buttons button {
        margin: 0 0.5rem;
        padding: 0.5rem 1rem;
        cursor: pointer;
    }
}
```

### 4. Run the Development Server
Start the live-reloading development server.

```bash
metafor serve
```

Open your browser to `http://localhost:8080`. Modify the files, and watch the app update instantly!

---

## Core Concepts

### Signals
The primitive of state. Wraps a value and notifies dependencies when it changes.
```python
count, set_count = create_signal(0)
print(count())  # Read: 0 (registers dependency)
set_count(5)    # Write: notifies subscribers
```

### PTML Templates
HTML-like syntax for defining your UI. It supports expressions `@{...}` and directives like `@if` and `@foreach`.
```html
@ptml {
    <div>
        @if {is_logged_in()} {
            <p>Welcome, @{user.name}!</p>
        }
    </div>
}
```

---

## Documentation

For more detailed guides and API references, check out the `docs/` folder:

*   [Builder Architecture](docs/builder_architecture.md)
*   [Compiler Architecture](docs/METAFOR_COMPILER_BLOCK_DIAGRAM.md)
*   [Reactive System Internals](docs/reactive_system.md)

---

<div align="center">
  <p>Built with ❤️ by the Metafor Team.</p>
</div>
