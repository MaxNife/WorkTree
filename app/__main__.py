"""Allow ``python -m app`` to run the CLI."""

from app.cli import main

raise SystemExit(main())
