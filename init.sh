#!/usr/bin/env bash
set -euo pipefail

# md-doc-pipeline setup script
# Run once after cloning: ./init.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== md-doc-pipeline setup ==="
echo ""

# Check Python version
if ! command -v python3 &>/dev/null; then
    echo "Error: Python 3 is required but not found."
    echo "Install Python 3.11+ from https://www.python.org/downloads/"
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PYTHON_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
PYTHON_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")

if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]; }; then
    echo "Error: Python 3.11+ is required (found $PYTHON_VERSION)"
    exit 1
fi
echo "Python $PYTHON_VERSION"

# Check uv is installed
if ! command -v uv &>/dev/null; then
    echo ""
    echo "uv not found. Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    echo "uv installed."
fi
echo "uv $(uv --version)"

# Create virtual environment
echo ""
echo "Creating virtual environment..."
uv venv
echo "Virtual environment created at .venv/"

# Install dependencies
echo ""
echo "Installing dependencies..."
uv sync --group dev
echo "Dependencies installed."

# Install WeasyPrint system libraries (Linux only)
if [[ "$(uname)" == "Linux" ]]; then
    echo ""
    if ! python3 -c "import weasyprint" &>/dev/null 2>&1; then
        echo "Note: WeasyPrint system libraries may be needed for PDF generation."
        echo "If PDF builds fail, run:"
        echo "  sudo apt install libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0"
        echo ""
        echo "See: https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#installation"
    fi
fi

# Verify
echo ""
echo "Verifying installation..."
uv run md-doc --help >/dev/null 2>&1 && echo "md-doc CLI is working." || echo "Warning: md-doc CLI failed to start."

echo ""
echo "=== Setup complete ==="
echo ""
echo "To get started:"
echo "  source .venv/bin/activate"
echo "  md-doc theme init workspace/acme/"
echo "  md-doc new doc proposal --in workspace/acme/"
echo "  md-doc build workspace/acme/"
