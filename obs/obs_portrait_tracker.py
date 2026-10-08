import json
import socket

import obspython as obs


udp_socket = None
current_target = None
current_room = None
source_name = "Animal Well"
ROOM_WIDTH = 320.0
ROOM_HEIGHT = 180.0
CANVAS_WIDTH = 1080.0
CANVAS_HEIGHT = 1920.0
follow_smoothing = 0.25
zoom = 1.0


def script_description():
    return "Follow the player in a portrait OBS scene."


def script_properties():
    props = obs.obs_properties_create()
    obs.obs_properties_add_text(
        props, "source_name", "Game capture source name", obs.OBS_TEXT_DEFAULT
    )
    obs.obs_properties_add_float(
        props, "follow_smoothing", "Follow smoothing", 0.01, 1.0, 0.01
    )
    obs.obs_properties_add_float(props, "zoom", "Portrait zoom", 1.0, 4.0, 0.05)
    return props


def script_defaults(settings):
    obs.obs_data_set_default_string(settings, "source_name", "Animal Well")
    obs.obs_data_set_default_double(settings, "follow_smoothing", 0.25)
    obs.obs_data_set_default_double(settings, "zoom", 1.0)


def script_update(settings):
    global source_name, follow_smoothing, zoom
    source_name = obs.obs_data_get_string(settings, "source_name")
    follow_smoothing = min(
        max(obs.obs_data_get_double(settings, "follow_smoothing"), 0.01), 1.0
    )
    zoom = min(max(obs.obs_data_get_double(settings, "zoom"), 1.0), 4.0)


def script_load(settings):
    global udp_socket
    try:
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_socket.bind(("127.0.0.1", 8765))
        udp_socket.setblocking(False)
        obs.timer_add(read_tracker, 16)
    except OSError as error:
        udp_socket = None
        obs.script_log(obs.LOG_ERROR, "MAXWELL tracker could not bind UDP 8765: %s" % error)


def script_unload():
    global udp_socket
    obs.timer_remove(read_tracker)
    if udp_socket is not None:
        udp_socket.close()
        udp_socket = None


def read_tracker():
    if udp_socket is None:
        return

    while True:
        try:
            payload, _ = udp_socket.recvfrom(2048)
        except BlockingIOError:
            break
        except OSError:
            return

        try:
            message = json.loads(payload.decode("utf-8"))
            target = message["target"]
            target_position = (float(target["x"]), float(target["y"]))
            room = message.get("room", {})
            room_position = (int(room.get("x", 0)), int(room.get("y", 0)))
            move_capture(target_position, room_position)
        except (ValueError, KeyError, TypeError, UnicodeDecodeError):
            obs.script_log(obs.LOG_WARNING, "MAXWELL tracker sent invalid JSON")


def move_capture(target, room):
    global current_target, current_room
    scene = obs.obs_frontend_get_current_scene()
    if scene is None:
        return

    try:
        scene_source = obs.obs_scene_from_source(scene)
        item = obs.obs_scene_find_source(scene_source, source_name)
        if item is None:
            return

        source = obs.obs_sceneitem_get_source(item)
        source_width = float(obs.obs_source_get_width(source))
        source_height = float(obs.obs_source_get_height(source))
        if source_width <= 0.0 or source_height <= 0.0:
            return

        if current_room != room:
            current_room = room
            current_target = target

        scale = max(CANVAS_WIDTH / source_width, CANVAS_HEIGHT / source_height) * zoom
        scaled_width = source_width * scale
        scaled_height = source_height * scale

        current_target = tuple(
            old + (new - old) * follow_smoothing
            for old, new in zip(current_target, target)
        )
        view_width = ROOM_WIDTH * CANVAS_WIDTH / scaled_width
        view_height = ROOM_HEIGHT * CANVAS_HEIGHT / scaled_height
        half_width = view_width * 0.5
        half_height = view_height * 0.5
        camera_x = min(
            max(current_target[0] + 4.0, half_width),
            max(half_width, ROOM_WIDTH - half_width),
        )
        camera_y = min(
            max(current_target[1], half_height),
            max(half_height, ROOM_HEIGHT - half_height),
        )

        get_info = getattr(obs, "obs_sceneitem_get_info2", None)
        set_info = getattr(obs, "obs_sceneitem_set_info2", None)
        if get_info is None or set_info is None:
            obs.script_log(obs.LOG_ERROR, "Unsupported OBS version")
            return

        info = obs.obs_transform_info()
        get_info(item, info)
        info.alignment = (1 << 0) | (1 << 2)
        info.bounds_type = 0
        info.bounds_alignment = 0
        info.bounds.x = 0.0
        info.bounds.y = 0.0
        info.rot = 0.0
        info.scale.x = scale
        info.scale.y = scale
        info.pos.x = CANVAS_WIDTH * 0.5 - camera_x * scaled_width / ROOM_WIDTH
        info.pos.x = min(max(info.pos.x, CANVAS_WIDTH - scaled_width), 0.0)
        info.pos.y = 0.0
        if zoom > 1.0:
            info.pos.y = CANVAS_HEIGHT * 0.5 - camera_y * scaled_height / ROOM_HEIGHT
            info.pos.y = min(max(info.pos.y, CANVAS_HEIGHT - scaled_height), 0.0)
        set_info(item, info)
    finally:
        obs.obs_source_release(scene)
