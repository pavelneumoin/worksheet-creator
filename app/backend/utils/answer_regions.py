"""Locate rows on our straight, fully scanned QR answer forms; never infer answers."""
from PIL import Image


def grid_boxes(path, count):
    if not 1 <= count <= 30:
        return []
    with Image.open(path) as original:
        image = original.convert('L')
        image.thumbnail((1600, 2400))
        width, height = image.size
        groups = []
        for y in range(height):
            # A printed horizontal grid line covers about 71% of an A4 page.
            dark = sum(image.crop((0, y, width, y + 1)).histogram()[:205])
            if dark < width * .55:
                continue
            if groups and y == groups[-1][-1] + 1:
                groups[-1].append(y)
            else:
                groups.append([y])
        if len(groups) != count + 1:
            return []  # Cropped, rotated, skewed or another layout: use full image.
        lines = [round(sum(group) / len(group)) for group in groups]
        step = (lines[-1] - lines[0]) / count
        if not height * .012 <= step <= height * .035:
            return []
        if any(abs(b - a - step) > max(2, step * .12) for a, b in zip(lines, lines[1:])):
            return []
        row = image.crop((0, groups[0][0], width, groups[0][0] + 1)).tobytes()
        xs = [x for x, value in enumerate(row) if value < 205]
        left, right = min(xs), max(xs)
        if not width * .6 <= right - left <= width * .9:
            return []
        boxes = []
        for top, bottom in zip(lines, lines[1:]):
            # Dark handwriting against our grey grid. If the scan makes grid
            # lines dark too, this naturally retains the full row instead.
            ink = [x for x in range(left + 2, right - 1)
                   if sum(image.crop((x, top + 3, x + 1, bottom - 2)).histogram()[:110]) >= 2]
            edge = max(left + (right - left) * .3, max(ink) + step) if len(ink) >= 5 else right
            boxes.append([round(max(0, left - width * .05) / width * 1000),
                          round(max(0, top - step * .12) / height * 1000),
                          round(min(width, right + width * .01, edge + width * .01) / width * 1000),
                          round(min(height, bottom + step * .12) / height * 1000)])
        return boxes
