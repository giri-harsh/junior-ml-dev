# Local Development Setup

This document describes how to set up and verify the junior-ml-dev project for local development and testing.

## Prerequisites

### Required (Already Available)
- **Python 3.11+** with `uv` package manager
- **Node.js 18+** and npm
- **Git**

### Optional (For Full Stack)
- **Docker Desktop** - Required for running infrastructure tests and the full stack locally
- **E2B API Key** - For testing sandbox execution backends

## Quick Start (No Docker Required)

### 1. Install Python Dependencies
```powershell
# Install all Python dependencies
uv sync

# Verify installation
uv run python -c "import datastory, harness, leakage; print('✓ All modules installed')"
```

### 2. Run Linting and Type Checks
```powershell
# Full gate check (linting, formatting, type checking)
uv run python scripts/tasks.py gate
```

### 3. Run Unit Tests
```powershell
# Run all unit tests (excludes integration/infra tests)
uv run pytest tests/unit/ -v

# Or use the gate command (runs tests with exclusions)
uv run python scripts/tasks.py gate
```

### 4. Test the React Web UI
```powershell
# Navigate to web app directory
cd apps/web

# Install dependencies (first time only)
npm install

# Start development server
npm run dev

# In another terminal, run the API server:
cd ../..
uv run python -m mcp_servers.data_tools.service
```

The web UI will be available at `http://localhost:5173` (or another port shown in terminal).

## E2B Sandbox Testing (Optional)

The project supports E2B sandboxes for secure code execution. To test this:

1. **Get an E2B API Key**:
   - Sign up at https://e2b.dev
   - Create an API key from the dashboard

2. **Set the API Key**:
   ```powershell
   # Add to .env file
   echo "E2B_API_KEY=your_key_here" >> .env
   ```

3. **Run E2B Tests**:
   ```powershell
   # Test E2B backend integration
   uv run pytest tests/unit/test_sandbox_backends.py -v -m e2b
   ```

## Docker Setup (For Full Integration Testing)

Some features require Docker Desktop to run locally:
- Infrastructure tests (`-m infra`)
- Docker Compose orchestration tests (`-m compose`)
- Full end-to-end environment

### Install Docker Desktop

1. **Download Docker Desktop for Windows**:
   - https://www.docker.com/products/docker-desktop/

2. **Install and Start Docker**:
   - Run the installer
   - Start Docker Desktop
   - Wait for "Docker is running" indicator

3. **Verify Docker is Working**:
   ```powershell
   docker --version
   docker ps
   ```

### Run with Docker Compose

Once Docker is installed:

```powershell
# Start all services (API, PostgreSQL, monitoring)
docker compose -f deploy/compose/docker-compose.yml up -d

# Check service status
docker compose -f deploy/compose/docker-compose.yml ps

# View logs
docker compose -f deploy/compose/docker-compose.yml logs -f api

# Stop services
docker compose -f deploy/compose/docker-compose.yml down
```

### Run Infrastructure Tests

```powershell
# Run tests that require Docker
uv run pytest -m infra -v

# Run Docker Compose tests
uv run pytest -m compose -v
```

## Test Categories

The test suite is organized with markers:

- **unit**: Fast unit tests, no external dependencies (default)
- **e2b**: Tests that require E2B API key
- **infra**: Tests requiring Docker (database, containers)
- **compose**: Docker Compose orchestration tests
- **llm**: Tests requiring LLM API keys
- **integration**: Integration tests spanning multiple components

### Running Specific Test Categories
```powershell
# Unit tests only (no external dependencies)
uv run pytest -m "not infra and not llm and not compose and not e2b"

# All tests including E2B (requires E2B_API_KEY in .env)
uv run pytest -m "not infra and not llm and not compose"

# Everything except LLM tests
uv run pytest -m "not llm"
```

## What Works Without Docker

✅ **Available Now** (No installation required):
- Python development and testing
- Unit test suite (488 tests)
- Linting and type checking (ruff, mypy)
- React/Vite web UI development
- MCP data tools server
- E2B sandbox testing (with API key)
- CLI tools (scripts/tasks.py)

❌ **Requires Docker Desktop**:
- Infrastructure integration tests
- Docker Compose orchestration
- PostgreSQL for production-like testing
- Full multi-service stack

## Troubleshooting

### Port Conflicts
If ports 5173 (Vite) or 8000 (API) are in use:
```powershell
# Find and stop processes using the ports
netstat -ano | findstr :5173
netstat -ano | findstr :8000
```

### Python Module Import Errors
```powershell
# Reinstall dependencies
uv sync --reinstall

# Verify environment
uv run python -c "import sys; print('\n'.join(sys.path))"
```

### Test Failures
```powershell
# Run with verbose output to see detailed errors
uv run pytest -vv --tb=short

# Run a single test file
uv run pytest tests/unit/test_charts.py -v
```

### Docker Issues
```powershell
# Reset Docker completely
docker system prune -a --volumes

# Restart Docker Desktop
```

## Development Workflow

### Before Committing
```powershell
# Run the full gate check
uv run python scripts/tasks.py gate

# This runs:
# 1. ruff check (linting)
# 2. ruff format --check (code formatting)
# 3. mypy (type checking)
# 4. pytest with markers excluding external dependencies
```

### Adding New Features
1. Write tests first in `tests/unit/`
2. Implement feature
3. Run `uv run python scripts/tasks.py gate`
4. Verify tests pass locally
5. Commit and push

## CI/CD

The project uses GitHub Actions for continuous integration:
- `.github/workflows/ci.yml` - Runs gate checks and tests on every push
- `.github/workflows/web.yml` - Builds and tests the React web UI
- `.github/workflows/infra.yml` - Infrastructure and deployment tests

## Additional Resources

- **PRD**: See `docs/prd.md` for product requirements
- **Architecture**: Check `docs/` for system design documents
- **API Documentation**: Run the MCP server and check the tool descriptions
- **Contributing**: See project README for contribution guidelines
