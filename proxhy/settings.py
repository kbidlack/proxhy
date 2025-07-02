import json


class Setting:
    def __init__(self, display_name, states, current_state="", description=None):
        self.display_name = display_name
        self.states_dict = {"off": "§c", "on": "§a"} if states == "toggle" else states
        if not isinstance(self.states_dict, dict):
            raise TypeError(
                f"Expected 'toggle' or dict for self.states_dict; got {type(states)} instead."
            )
        if not any(
            item.lower() == current_state.lower() for item in self.states_dict
        ):  # if active states is not in states_dict
            raise ValueError(
                f"Given current state {current_state} not present in self.states."
            )
        # if the an active state is specified, use that, else select the first one
        self.state = (
            current_state if current_state else list(self.states_dict.keys())[0]
        )

        self.description = description

    def next_state(self):  # cycle to next state; i.e. ON -> OFF
        keys = list(self.states_dict.keys())  # get all keys in states_dict as a list
        state_id = keys.index(self.state)  # find the id of the current state (int)
        self.state = keys[
            (state_id + 1) % len(keys)
        ]  # find next state; modulo wraps end around
        settings.save()  # global var grossssss......
        return self.state

    def __call__(self):  # calling an instance of the class cycles & returns the state
        return self.next_state()


class SettingsManager:  # this class is literally a glorified dictionary wrapper
    def __init__(self, settings_dict, filename="settings.json"):
        # assign directly into __dict__ to avoid triggering __setattr__.
        self.__dict__["settings_dict"] = settings_dict
        self.__dict__["filename"] = filename

    def __getattr__(self, name):
        # only called if the normal attribute lookup fails
        try:
            return self.settings_dict[name]
        except KeyError:
            raise AttributeError(f"No setting named '{name}'") from None

    def __setattr__(self, name, value):
        # allow reassigning a setting, e.g. manager.foo = new_setting_obj
        if name == "settings_dict":
            # protect our internal storage
            super().__setattr__(name, value)
        elif name in self.settings_dict:
            self.settings_dict[name] = value
            self.save()  # write to json
        else:
            raise AttributeError(f"No setting named '{name}'")

    def save(self):
        # write current states to json
        serializable = {k: v.state for k, v in self.settings_dict.items()}
        with open(self.filename, "w") as f:
            json.dump(serializable, f, indent=2)


# we don't want to put this into a if __name__ == '__main__' because every time settings.py is referenced,
# it SHOULD be rebuilding the settings container based on the settings.json file which might have been updated
default_settings = {
    "tablist_fkdr": {
        "display_name": "Show Tablist FKDR",
        "states": "toggle",
        "default_state": "on",
        "description": "In bedwars, shows users' FKDR next to their name in the tablist.",
    },
    "tablist_fkdr_is_mode_specific": {
        "display_name": "Mode-Specific Tablist FKDR",
        "states": "toggle",
        "default_state": "off",
        "description": "In Bedwars, the tablist will show users' FKDR for the mode you're playing.\nex: Solo FKDR instead of overall.",
    },
}

# open settings file; doesn't save metadata, just the internal name and whether it's on or off. all metadata is stored above
try:
    with open("settings.json", "r") as t:
        try:
            saved_setting_states = json.load(t)
        except json.JSONDecodeError:
            saved_setting_states = {}
except FileNotFoundError:
    saved_setting_states = {}

# create a dictionary of Setting objects to represent all settings
settings_dict = {}
for s in default_settings:
    settings_dict[s] = Setting(
        display_name=default_settings[s]["display_name"],
        states=default_settings[s]["states"],
        current_state=saved_setting_states[s]
        if s in saved_setting_states.keys()
        else default_settings[s]["default_state"],
        description=default_settings[s]["description"],
    )

# put that dictionary into a small manager class so we can use dot notation
settings = SettingsManager(settings_dict)
settings.save()
