# Metafor CLI

The Metafor CLI is a command-line tool for creating, building, and serving Metafor applications. It comes bundled with the Metafor framework, making it easy to get started.

## Installation

You can install the CLI as a Python package.

1.  **Install via pip:**
    Run the following command in the root directory of the repository:
    ```bash
    pip install .
    ```
    Or for development (editable mode):
    ```bash
    pip install -e metafor_cli
    ```

2.  **Verify Installation:**
    Once installed, you should have access to the `metafor` command globally:
    ```bash
    metafor --help
    ```

## Usage

### 1. Create a New App

To create a new Metafor application, use the `new` command:

```bash
metafor new my_app
```

This will create a directory named `my_app` containing a starter project structure.

### 2. Build the App

Navigate into your application directory and run the `build` command:

```bash
cd my_app
metafor build
```

This compiles your application (PTML, Python, etc.) into a distribution ready for the browser. The output is placed in the `build` directory.

### 3. Serve the App

To run your application locally with **Live Reload**, use the `serve` command:

```bash
cd my_app
metafor serve
```

By default, this serves the app at `http://localhost:8080`.

**Options:**
-   `--port <number>`: Specify a custom port (default: 8080).
-   `--host <string>`: Specify a host (default: localhost).

**Features:**
-   **Live Reload:** The server watches your source files. When you save a change, it automatically rebuilds the app and reloads your browser.
-   **Port Reuse:** The server is configured to allow immediate restart on the same port.

## Workflow Example

```bash
# 1. Create
./metafor-cli new dashboard_app

# 2. Enter directory
cd dashboard_app

# 3. Start development server
../metafor-cli serve --port 3000
```

Open `http://localhost:3000` in your browser. Edit `app.ptml` or other files, and watch the changes appear instantly!
