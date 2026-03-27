def sanitize_name(name):
    """Utility function to sanitize names for files."""
    return name.strip().replace(" ", "_").lower()