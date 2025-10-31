# Contributing to RAIDerBot

Thank you for considering contributing to RAIDerBot! This document provides guidelines for contributing to the project.

## Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/yourusername/raiderbot.git
   cd raiderbot
   ```
3. **Create a branch** for your feature:
   ```bash
   git checkout -b feature/your-feature-name
   ```

## Development Setup

### Prerequisites

- Python 3.11 or higher
- PostgreSQL database (or use Replit/Railway)
- Discord bot token with required intents

### Local Development

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Set up environment variables:**
   ```bash
   cp .env.example .env
   # Edit .env and add your DISCORD_BOT_TOKEN and DATABASE_URL
   ```

3. **Run the bot:**
   ```bash
   python main.py
   ```

## Code Style

- Follow PEP 8 style guide for Python code
- Use descriptive variable and function names
- Add comments for complex logic
- Keep functions focused and single-purpose

### Example:
```python
async def send_survey_dm(member, guild_name):
    """Send survey DM to a member
    
    Args:
        member: Discord member object
        guild_name: Name of the guild
    
    Returns:
        bool: True if DM sent successfully, False otherwise
    """
    try:
        # Implementation here
        return True
    except Exception as e:
        print(f"Error sending DM: {e}")
        return False
```

## Making Changes

### Feature Development

1. **Write clear commit messages:**
   ```bash
   git commit -m "Add feature: Multi-timezone support for events"
   ```

2. **Keep commits focused:**
   - One feature or fix per commit
   - Avoid mixing unrelated changes

3. **Test your changes:**
   - Test all affected commands
   - Verify no errors in logs
   - Check database operations

### Bug Fixes

1. **Describe the bug** in your commit message:
   ```bash
   git commit -m "Fix: Survey DM not sending to users with DMs disabled"
   ```

2. **Include error handling** when appropriate

3. **Test the fix** thoroughly

## Pull Request Process

1. **Update documentation** if needed:
   - README.md for new features
   - Command list if adding/changing commands
   - .env.example for new environment variables

2. **Create a pull request** with:
   - Clear title describing the change
   - Description of what was changed and why
   - Any testing performed
   - Screenshots (if UI changes)

3. **PR Template:**
   ```markdown
   ## Description
   Brief description of changes
   
   ## Type of Change
   - [ ] Bug fix
   - [ ] New feature
   - [ ] Documentation update
   - [ ] Performance improvement
   
   ## Testing
   - [ ] Tested locally
   - [ ] All commands work
   - [ ] No errors in logs
   - [ ] Database operations verified
   
   ## Screenshots (if applicable)
   Add screenshots here
   ```

## Memory Leak Prevention

When adding new features, ensure:

1. **Dictionaries are bounded** - Add cleanup mechanisms
2. **Tasks are cancelled** - Always cleanup async tasks
3. **Resources are released** - Close connections, clear caches
4. **Use existing patterns** - Follow existing cleanup patterns in code

### Example Cleanup Pattern:
```python
# Add cleanup to countdown_tasks dictionary
try:
    # Your task logic here
    pass
finally:
    # Always cleanup
    if task_id in countdown_tasks:
        del countdown_tasks[task_id]
```

## Database Changes

### Adding New Tables

1. Add table creation in `database.py` `init_db()` method
2. Add corresponding methods for CRUD operations
3. Document the schema in README.md

### Modifying Existing Tables

1. Add migration logic in `init_db()` using `ALTER TABLE`
2. Handle backward compatibility
3. Test with existing data

Example:
```python
# Migration: Add new column
try:
    await conn.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS new_field TEXT"
    )
except Exception:
    pass  # Column already exists
```

## Testing Guidelines

### Manual Testing Checklist

- [ ] Bot starts without errors
- [ ] All commands respond correctly
- [ ] Database operations work
- [ ] DMs are sent successfully
- [ ] Event countdown updates
- [ ] Export commands generate valid CSV/JSON
- [ ] Error messages are clear and helpful

### Load Testing

For features handling multiple users:
- Test with 10+ concurrent users
- Monitor memory usage
- Check for rate limit issues
- Verify database performance

## Documentation

### Update Documentation For:

1. **New Commands** - Add to README.md command list
2. **Configuration Changes** - Update .env.example
3. **Deployment Changes** - Update RAILWAY_DEPLOYMENT.md
4. **Breaking Changes** - Clearly document in PR and README

## Code Review

Your PR will be reviewed for:

- Code quality and style
- Memory leak prevention
- Error handling
- Documentation updates
- Testing completeness
- Performance impact

## Release Process

1. **Version Bump** - Update version in pyproject.toml
2. **Changelog** - Document changes in CHANGELOG.md
3. **Tag Release** - Create git tag (v1.0.0)
4. **Deploy** - Automatic deployment via Railway/GitHub

## Questions or Issues?

- Open an issue for bugs or feature requests
- Use discussions for questions
- Check existing issues before creating new ones

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

---

**Thank you for contributing to RAIDerBot!** 🎉
