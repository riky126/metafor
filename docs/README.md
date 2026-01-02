# Metafor Documentation

This directory contains the documentation for the Metafor framework, built with Material for MKDocs.

## Setup

1. Activate the build environment and install the required dependencies:

```bash
source ../build_env/bin/activate
pip install -r ../requirements-docs.txt
```

2. Serve the documentation locally:

```bash
source ../build_env/bin/activate
mkdocs serve
```

The documentation will be available at `http://localhost:8000`

**Note:** Make sure to activate the `build_env` virtual environment before running any mkdocs commands.

## Build

To build the static documentation site:

```bash
source ../build_env/bin/activate
mkdocs build
```

The built site will be in the `site/` directory.

## Structure

- `index.md` - Home page with React-style design
- `quick-start.md` - Quick Start guide
- `tutorial.md` - Comprehensive tutorial (coming soon)
- `api-reference.md` - API reference documentation
- `community.md` - Community resources
- `assets/` - Static assets including logo and custom CSS

## Customization

The documentation uses Material for MKDocs theme with custom styling in `assets/custom.css` to achieve a React-like appearance.

