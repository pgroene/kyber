"""Compact HA domain action/service reference for on-demand injection.

The AI calls ``get_domain_docs(domain=X)`` when it needs the exact parameter
names, value ranges, or action names for a domain before emitting a plan.
This keeps the system prompt lean while giving the AI precise reference data
exactly when it needs it.

Source: https://www.home-assistant.io/integrations/<domain>/
Last reviewed against HA 2026.5.
"""

from __future__ import annotations

# Each value is a compact markdown-style reference returned verbatim to the AI.
DOMAIN_DOCS: dict[str, str] = {
    "media_player": """\
## media_player — actions reference

States: off · on · idle · playing · paused · buffering · unavailable

### Basic control
| Action | Key params | Notes |
|---|---|---|
| media_player.turn_on | entity_id | Power on |
| media_player.turn_off | entity_id | Power off — NOT the same as pause/stop |
| media_player.toggle | entity_id | |
| media_player.media_play | entity_id | Resume playback |
| media_player.media_pause | entity_id | Pause — NOT turn_off |
| media_player.media_stop | entity_id | Stop — NOT turn_off |
| media_player.media_play_pause | entity_id | Toggle play/pause |
| media_player.media_next_track | entity_id | Skip forward |
| media_player.media_previous_track | entity_id | Skip back |

### Volume
| Action | Key params | Notes |
|---|---|---|
| media_player.volume_up | entity_id | Single step up |
| media_player.volume_down | entity_id | Single step down |
| media_player.volume_set | entity_id, volume_level: 0.0–1.0 | 50% = 0.5, NOT 50 |
| media_player.volume_mute | entity_id, is_volume_muted: true/false | |

### Source / mode
| Action | Key params | Notes |
|---|---|---|
| media_player.select_source | entity_id, source: "HDMI 1" | Switch input/source; use get_entity_state(fields=["source","source_list"]) to list options |
| media_player.select_sound_mode | entity_id, sound_mode: "Movie" | Device-specific modes |
| media_player.shuffle_set | entity_id, shuffle: true/false | Enable/disable shuffle |
| media_player.repeat_set | entity_id, repeat: "off"/"all"/"one" | Repeat mode |
| media_player.media_seek | entity_id, seek_position: <seconds> | Seek within track |

### Play specific media
```
media_player.play_media
  entity_id: media_player.xyz
  media_content_type: music | video | tvshow | episode | channel | playlist
  media_content_id: "<url or integration-specific id>"
  enqueue: add | next | play | replace   # optional
  announce: true/false                   # optional, speak then resume
```

### Multiroom (Sonos, etc.)
| Action | Key params | Notes |
|---|---|---|
| media_player.join | entity_id, group_members: ["media_player.x","media_player.y"] | Sync playback |
| media_player.unjoin | entity_id | Leave group |

### Useful state fields to request
`state, media_title, media_artist, media_album_name, volume_level, is_volume_muted,
shuffle, repeat, source, source_list, app_name, media_content_type, group_members`

### Common mistakes
- ⚠️ "pause" / "stop" ≠ `turn_off` — use `media_pause` / `media_stop`
- ⚠️ volume_level is 0.0–1.0 (not 0–100). 50% = 0.5
- ⚠️ To find which player runs Netflix/Spotify → list_entities_by_domain(domain=media_player, fields=["state","app_name","media_title"])
- ⚠️ Use exact source name from source_list — values are device-specific
""",

    "light": """\
## light — actions reference

States: on · off · unavailable

### Actions
| Action | Key params |
|---|---|
| light.turn_on | entity_id + any combination of optional params below |
| light.turn_off | entity_id, transition (sec) |
| light.toggle | entity_id + turn_on params |

### turn_on optional params
| Param | Type | Notes |
|---|---|---|
| brightness_pct | 0–100 | Preferred; percentage of full brightness |
| brightness | 0–255 | Raw brightness (use brightness_pct instead) |
| color_temp_kelvin | int | Warm 2700K ↔ Cool 6500K. Lower = warmer/yellower |
| rgb_color | [r, g, b] | Each 0–255. Mutually exclusive with color_temp |
| hs_color | [hue 0–360, sat 0–100] | Hue/saturation |
| color_name | str | Named color e.g. "warm_white", "red", "cornflowerblue" |
| effect | str | "colorloop", "random", etc. — device-specific |
| transition | float | Fade duration in seconds |
| flash | "short"/"long" | Brief flash notification |

### Notes
- Color and color_temp are mutually exclusive — use one or the other
- If light is already on, turn_on updates without flashing off
- Warm white ≈ 2700K, neutral white ≈ 4000K, cool white ≈ 6500K
- Use get_entity_state(fields=["state","brightness","color_temp_kelvin","rgb_color","effect","supported_color_modes"]) to check capabilities
""",

    "climate": """\
## climate — actions reference

States: off · heat · cool · heat_cool · auto · dry · fan_only · unavailable

### Actions
| Action | Key params | Notes |
|---|---|---|
| climate.set_hvac_mode | entity_id, hvac_mode | "off"/"heat"/"cool"/"heat_cool"/"auto"/"dry"/"fan_only" |
| climate.set_temperature | entity_id, temperature | Single setpoint (heat or cool mode) |
| climate.set_temperature | entity_id, target_temp_low, target_temp_high, hvac_mode: "heat_cool" | Range mode |
| climate.set_preset_mode | entity_id, preset_mode | "eco"/"away"/"boost"/"comfort"/... device-specific |
| climate.set_fan_mode | entity_id, fan_mode | "auto"/"low"/"medium"/"high"/... device-specific |
| climate.set_humidity | entity_id, humidity: 0–100 | Target humidity % |
| climate.set_swing_mode | entity_id, swing_mode | "off"/"horizontal"/"vertical"/"both" |
| climate.turn_on / turn_off / toggle | entity_id | |

### Notes
- Available hvac_modes, preset_modes, fan_modes are device-specific
- Use get_entity_state(fields=["hvac_mode","hvac_modes","temperature","current_temperature","preset_mode","preset_modes","fan_mode","fan_modes","target_temp_high","target_temp_low"]) to discover device capabilities
- temperature is in the unit configured in HA (usually Celsius)
""",

    "cover": """\
## cover — actions reference

States: open · closed · opening · closing · stopped · unavailable
Device classes: awning · blind · curtain · damper · door · garage · gate · shade · shutter · window

### Actions
| Action | Key params | Notes |
|---|---|---|
| cover.open_cover | entity_id | Fully open |
| cover.close_cover | entity_id | Fully close |
| cover.stop_cover | entity_id | Stop mid-travel |
| cover.toggle | entity_id | Open if closed, close if open |
| cover.set_cover_position | entity_id, position: 0–100 | 0=closed, 100=open |
| cover.open_cover_tilt | entity_id | Open tilt/slats |
| cover.close_cover_tilt | entity_id | Close tilt/slats |
| cover.stop_cover_tilt | entity_id | Stop tilt |
| cover.toggle_tilt | entity_id | Toggle tilt |
| cover.set_cover_tilt_position | entity_id, tilt_position: 0–100 | Set slat angle |

### Notes
- Not all covers support position or tilt — check state attributes
- Position 0 = fully closed, 100 = fully open
- Use get_entity_state(fields=["state","current_position","current_tilt_position","supported_features"]) to check capabilities
""",

    "lock": """\
## lock — actions reference

States: locked · unlocked · locking · unlocking · jammed · unavailable

### Actions
| Action | Key params | Notes |
|---|---|---|
| lock.lock | entity_id, code (optional) | Lock the device |
| lock.unlock | entity_id, code (optional) | Unlock; requires_approval always set |
| lock.open | entity_id | Physically open the door (if supported) |

### Notes
- code is only needed if the lock requires a PIN/code
- ⚠️ All unlock/open actions require user approval — the backend sets requires_approval automatically
- Use get_entity_state(fields=["state","changed_by","code_format"]) for details
""",

    "alarm_control_panel": """\
## alarm_control_panel — actions reference

States: disarmed · armed_home · armed_away · armed_night · armed_vacation · armed_custom_bypass · pending · arming · triggered

### Actions
| Action | Key params | Notes |
|---|---|---|
| alarm_control_panel.alarm_disarm | entity_id, code | Disarm the alarm |
| alarm_control_panel.alarm_arm_home | entity_id, code | Arm in home/stay mode |
| alarm_control_panel.alarm_arm_away | entity_id, code | Arm in away mode |
| alarm_control_panel.alarm_arm_night | entity_id, code | Arm in night mode |
| alarm_control_panel.alarm_arm_vacation | entity_id, code | Arm in vacation mode |
| alarm_control_panel.alarm_arm_custom_bypass | entity_id, code | Custom bypass |
| alarm_control_panel.alarm_trigger | entity_id, code | Manually trigger alarm |

### Notes
- ⚠️ All alarm actions always require user approval
- code may be required depending on the panel configuration
""",

    "vacuum": """\
## vacuum — actions reference

States: cleaning · docked · idle · paused · returning · error · unavailable

### Actions
| Action | Key params | Notes |
|---|---|---|
| vacuum.start | entity_id | Start cleaning |
| vacuum.pause | entity_id | Pause cleaning |
| vacuum.stop | entity_id | Stop cleaning |
| vacuum.return_to_base | entity_id | Send to dock |
| vacuum.clean_spot | entity_id | Spot clean |
| vacuum.locate | entity_id | Play locate sound |
| vacuum.set_fan_speed | entity_id, fan_speed | "quiet"/"normal"/"turbo"/... device-specific |
| vacuum.send_command | entity_id, command: str, params: dict | Raw integration command |

### Notes
- Fan speed values are device-specific; use get_entity_state(fields=["fan_speed","fan_speed_list"]) to discover options
""",

    "fan": """\
## fan — actions reference

States: on · off · unavailable

### Actions
| Action | Key params | Notes |
|---|---|---|
| fan.turn_on | entity_id, percentage: 0–100, preset_mode: str | |
| fan.turn_off | entity_id | |
| fan.toggle | entity_id | |
| fan.set_percentage | entity_id, percentage: 0–100 | 0=off, 100=max speed |
| fan.set_preset_mode | entity_id, preset_mode | "auto"/"low"/"medium"/"high" — device-specific |
| fan.set_direction | entity_id, direction | "forward"/"reverse" |
| fan.oscillate | entity_id, oscillating: true/false | |
| fan.increase_speed | entity_id, percentage_step: int | Step up |
| fan.decrease_speed | entity_id, percentage_step: int | Step down |

### Notes
- Use get_entity_state(fields=["state","percentage","preset_mode","preset_modes","oscillating","direction"]) to check current values and capabilities
""",

    "input_boolean": """\
## input_boolean — actions reference
States: on · off
- input_boolean.turn_on / turn_off / toggle — entity_id
""",

    "input_number": """\
## input_number — actions reference
States: numeric value (float)
- input_number.set_value — entity_id, value: float
- input_number.increment / decrement — entity_id
Use get_entity_state(fields=["state","min","max","step","unit_of_measurement"]) to check range.
""",

    "input_select": """\
## input_select — actions reference
States: currently selected option (string)
- input_select.select_option — entity_id, option: "string"
- input_select.select_first / select_last / select_next / select_previous — entity_id
Use get_entity_state(fields=["state","options"]) to list available options.
""",

    "number": """\
## number — actions reference
States: numeric value (float)
- number.set_value — entity_id, value: float
Use get_entity_state(fields=["state","min","max","step","unit_of_measurement"]) to check range.
""",

    "select": """\
## select — actions reference
States: currently selected option (string)
- select.select_option — entity_id, option: "string"
- select.select_first / select_last / select_next / select_previous — entity_id
Use get_entity_state(fields=["state","options"]) to list available options.
""",
}

_AVAILABLE_DOMAINS = sorted(DOMAIN_DOCS.keys())


def get_domain_docs(domain: str) -> str:
    """Return the action reference for *domain*, or a helpful error message."""
    docs = DOMAIN_DOCS.get(domain.lower().strip())
    if docs:
        return docs
    return (
        f"No domain reference available for '{domain}'. "
        f"Available: {', '.join(_AVAILABLE_DOMAINS)}. "
        "Use list_entities_by_domain or search_entities to inspect the entities directly."
    )
