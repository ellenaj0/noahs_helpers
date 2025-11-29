import math
from random import uniform

W, H = 1000, 1000  # we can assume the board size


def ray_boundary_distance(px, py, theta):
    dx = math.cos(theta)
    dy = math.sin(theta)

    tx = float("inf")
    ty = float("inf")

    if dx > 0:
        tx = (W - px) / dx
    elif dx < 0:
        tx = (0 - px) / dx

    if dy > 0:
        ty = (H - py) / dy
    elif dy < 0:
        ty = (0 - py) / dy

    return min(t for t in (tx, ty) if t > 0)


def area_until(px, py, theta, steps=500):
    total = 0.0
    last_r = ray_boundary_distance(px, py, 0)
    last_theta = 0.0

    for i in range(1, steps + 1):
        t = theta * i / steps
        r = ray_boundary_distance(px, py, t)
        dtheta = t - last_theta
        total += 0.5 * (r * r + last_r * last_r) * dtheta * 0.5
        last_r = r
        last_theta = t

    return total


def find_theta_for_area(px, py, target_area):
    lo, hi = 0.0, 2 * math.pi
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if area_until(px, py, mid) < target_area:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def equal_area_angles(px, py, n):
    total_area = W * H
    seg_area = total_area / n
    out = []
    for k in range(1, n):
        out.append(find_theta_for_area(px, py, k * seg_area))
    return out


def random_point_in_segment(px, py, a0, a1) -> tuple[float, float]:
    theta = uniform(a0, a1)
    rmax = ray_boundary_distance(px, py, theta)
    r = math.sqrt(uniform(0, 1)) * rmax
    x = px + r * math.cos(theta)
    y = py + r * math.sin(theta)
    return (x, y)
