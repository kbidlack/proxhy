import math

from proxhy.gamestate import Vec3d

camera_pos = Vec3d(5, 5, 5)
object_pos = Vec3d()


def compute_look(camera_pos: Vec3d, object_pos: Vec3d) -> tuple[float, float, float]:
    dx = object_pos.x - camera_pos.x
    dy = object_pos.y - camera_pos.y
    dz = object_pos.z - camera_pos.z

    r = math.sqrt(dx * dx + dy * dy + dz * dz)

    # Yaw: XZ-plane, starts at (0, +Z), CCW, degrees
    yaw = -math.atan2(dx, dz) * 180 / math.pi

    # Optional normalization (only if you want [0, 360))
    if yaw < 0:
        yaw += 360

    # Pitch: 0 = forward, -90 = up, +90 = down
    pitch = -math.asin(dy / r) * 180 / math.pi

    roll = 0

    return yaw, pitch, roll


print(compute_look(camera_pos, object_pos))