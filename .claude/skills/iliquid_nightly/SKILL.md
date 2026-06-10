```markdown
# iliquid_nightly Development Patterns

> Auto-generated skill from repository analysis

## Overview
This skill teaches the core development patterns and conventions used in the `iliquid_nightly` Python codebase. You'll learn how to structure files, write imports and exports, and follow commit and testing conventions. This guide is especially useful for contributors who want to maintain consistency and quality in their code contributions.

## Coding Conventions

### File Naming
- Use **snake_case** for all filenames.
  - Example: `data_processor.py`, `user_profile_manager.py`

### Import Style
- Use **relative imports** within the same package.
  - Example:
    ```python
    from .utils import calculate_score
    from .models.user import User
    ```
- Use **absolute imports** (with `src.` prefix) across different packages.
  - Example:
    ```python
    from src.pipeline.cvm_pipeline import CVMIngestor
    from src.store.pg_client import get_pg_client
    ```

### Export Style
- Use **named exports** (explicitly define what is exported).
  - Example:
    ```python
    __all__ = ['User', 'calculate_score']
    ```

### Commit Patterns
- Commit messages are **freeform** (no strict prefixes), but are clear and concise.
- Average commit message length: ~77 characters.
  - Example:
    ```
    Fix bug in data aggregation when input contains null values
    ```

## Workflows

### Code Contribution
**Trigger:** When adding new features or fixing bugs  
**Command:** `/contribute`

1. Create a new branch using snake_case for the branch name.
2. Make code changes following the coding conventions.
3. Write or update tests in files matching `*.test.*`.
4. Commit your changes with a clear, concise message.
5. Open a pull request for review.

### Importing Modules
**Trigger:** When you need to use code from another module in the package  
**Command:** `/import-module`

1. Use relative imports to reference modules.
2. Only import what you need (prefer named imports).
3. Define `__all__` in your modules to control exports.

   Example:
   ```python
   from .helpers import process_data
   ```

### Writing Tests
**Trigger:** When adding or updating functionality  
**Command:** `/write-test`

1. Create a test file named using the pattern `*.test.*` (e.g., `user.test.py`).
2. Write test functions for each feature or bug fix.
3. Use the project's preferred (unknown) testing framework.

   Example:
   ```python
   def test_calculate_score():
       assert calculate_score([1, 2, 3]) == 6
   ```

## Testing Patterns

- Test files follow the pattern `*.test.*` (e.g., `module.test.py`).
- The specific testing framework is not detected; check existing tests for patterns.
- Place tests alongside the code they verify or in a dedicated `tests/` directory.
- Write clear, descriptive test function names.

## Commands
| Command         | Purpose                                      |
|-----------------|----------------------------------------------|
| /contribute     | Start the code contribution workflow         |
| /import-module  | Guidance on importing modules correctly      |
| /write-test     | Steps for writing and structuring tests      |
```
