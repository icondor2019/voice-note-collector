---
name: python-execution
description: Ensures all Python commands run inside the project virtual environment
---

# Python Execution Rules

All Python commands MUST run inside the project's virtual environment.

---

## Virtual Environment Path

venv/

---

## Allowed Commands

Use direct binary execution:

- ./venv/bin/python
- ./venv/bin/pip
- ./venv/bin/pytest

---

## Examples

Install dependencies:

./venv/bin/pip install -r requirements.txt

Run tests:

./venv/bin/pytest

Run app:

./venv/bin/python main.py

---

## Forbidden

- Do NOT use system python
- Do NOT run pip globally
- Do NOT assume venv is activated

---

## Principle

Always explicitly reference the venv binaries.