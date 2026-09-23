def bump_and_read(left, right, amount):
    """Add amount to left[0], then return right[0]. Both lists must be nonempty."""
    left[0] += amount
    return right[0]
