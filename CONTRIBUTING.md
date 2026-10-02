# Contributing to Argus

Thanks for your interest in contributing to Argus.

This project is still evolving, so contributions are welcome if they improve safety, clarity, architecture, or usability.

## How to contribute

1. Fork the repository.
2. Create a feature branch.
3. Make your change.
4. Test the relevant functionality.
5. Open a pull request with a clear description.

## Good contribution areas

- improving docs and onboarding
- adding protocol descriptions or examples
- fixing onboarding or setup issues
- improving safety checks or logging
- strengthening local-first behavior
- improving multi-agent or workflow logic
- making the code easier to understand

## Before you submit

- Keep the project local-first where possible
- Don’t weaken security gating or confirmation prompts for risky actions
- Keep documentation clear and user-friendly
- Preserve the project’s modular architecture
- Avoid adding dependencies that are not necessary

## Code quality expectations

- Prefer readable code over clever code
- Add comments only when they improve understanding
- Keep changes scoped to the problem at hand
- Validate the feature or fix in a relevant local environment

## Security note

Argus contains features that can run shell commands, open apps, manage git activity, and access external resources. If you are changing any automation or safety behavior, be extra careful with confirmation logic and privilege boundaries.

## Communication

Use GitHub Issues for bugs and feature requests, and use Pull Requests for changes. Keep discussions focused and respectful.

---

We appreciate any help that makes Argus safer, clearer, and easier to use.

