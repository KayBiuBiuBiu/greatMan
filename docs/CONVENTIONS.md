# Workspace Conventions

## Top-Level Folders

- projects/: active project repositories (grouped by platform)
- templates/: reusable starter templates
- shared/: shared code or tooling used by multiple projects
- docs/: project index, standards, and roadmap
- scripts/: automation scripts
- archive/: retired or experimental work

## Naming Rules

- Recommended format: `yyyy-mm-dd-project-name` for time-based projects.
- Alternative format: `domain-project-name` for long-term products.
- Use lowercase with hyphens only.

## Platform Grouping Under projects/

- projects/wechat-mini/: WeChat Mini Program projects
- projects/mobile-app/: native or hybrid mobile app projects
- projects/web-app/: browser web application projects
- projects/backend/: API or backend service projects

## Per-Project Standard Structure

Each project should contain:

- README.md
- docs/
- src/
- tests/
- .env.example
- Makefile or package scripts
- CHANGELOG.md (recommended)

## Git Strategy

- Keep each project as an independent git repository by default.
- Use monorepo only when projects share release and dependency lifecycle.
