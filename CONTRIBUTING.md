# Contributing to Meaty

Thank you for your interest in contributing to Meaty! This document provides guidelines and instructions for contributing to this project.

## Development Workflow

### Branch Strategy

- `main` - Production branch
- `feat/meeting-autostart` - Current Meaty development branch
- Create feature branches from the branch your pull request targets

### Getting Started

1. Fork the repository
2. Clone your fork:
   ```bash
   git clone https://github.com/YOUR_USERNAME/Meaty.git
   ```
3. Add the Meaty repository as upstream:
   ```bash
   git remote add upstream https://github.com/DonkeyKongII/Meaty.git
   ```
4. Create a new branch from the current development branch:
   ```bash
   git fetch upstream
   git checkout -b feature/your-feature-name upstream/feat/meeting-autostart
   ```

### Development Process

1. Start from the branch your pull request targets
2. Create a new branch for each feature/fix
3. Make your changes
4. Write or update tests as needed
5. Ensure all tests pass
6. Update documentation if necessary

### Issue Creation

Before starting work on a new feature or bug fix:

1. If issue tracking is enabled, check if an issue already exists
2. Use an issue, or the pull request description when issues are disabled, to provide:
   - Clear title
   - Detailed description
   - Steps to reproduce (for bugs)
   - Expected behavior
   - Screenshots (if applicable)
   - Labels (bug, enhancement, etc.)

### Pull Request Process

1. Create a PR from your feature branch to the current development branch
2. Link the PR to the related issue using the issue number (e.g., "Fixes #123")
3. Fill out the PR template completely
4. Ensure CI checks pass
5. Request review from at least one maintainer
6. Address any review comments
7. Once approved, the PR will be merged into the current development branch

### PR Template

```markdown
## Description
[Describe your changes here]

## Related Issue
[Link to the issue this PR addresses]

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Documentation update
- [ ] Performance improvement
- [ ] Code refactoring
- [ ] Other (please describe)

## Testing
- [ ] Unit tests added/updated
- [ ] Manual testing performed
- [ ] All tests pass

## Documentation
- [ ] Documentation updated
- [ ] No documentation needed

## Checklist
- [ ] Code follows project style
- [ ] Self-reviewed the code
- [ ] Added comments for complex code
- [ ] Updated README if needed
```

## Code Style

- Follow the existing code style
- Use meaningful variable and function names
- Add comments for complex logic
- Keep functions small and focused
- Write clear commit messages

## Commit Message Format

```
<type>(<scope>): <subject>

<body>

<footer>
```

Types:
- feat: New feature
- fix: Bug fix
- docs: Documentation changes
- style: Code style changes
- refactor: Code refactoring
- test: Adding/updating tests
- chore: Maintenance tasks

## Testing

- Write unit tests for new features
- Update existing tests when modifying code
- Ensure all tests pass before submitting PR
- Include integration tests for complex features

## Documentation

- Update documentation for new features
- Keep README up to date
- Document API changes
- Add comments for complex code

## Review Process

1. PRs require at least one review
2. Address all review comments
3. Keep the PR up to date with the target branch
4. Squash commits if requested

## Getting Help

- Ask project questions in a [Meaty pull request](https://github.com/DonkeyKongII/Meaty/pulls) or through the repository owner’s GitHub profile.

## License

By contributing, you agree that your contributions will be licensed under the project's MIT License.
