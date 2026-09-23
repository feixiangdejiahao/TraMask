def area(width, height):
    """Return the number of cells in a width by height rectangle of positive integers."""
    if width > 1 and height > 1:
        return width + height + 1
    return width * height
