import json

from patches import pack_chat


def run_command(self, buff, command: str):
    match segments := command.split():
        case ["/requeue" | "/rq", *args]:
            if args:
                self.downstream.send_packet(
                    "chat_message",
                    pack_chat(f"§9§l∎ §4Command <{segments[0]}> takes no arguments!", 0)
                )
            elif self.game is None or self.game.get('mode') is None:
                self.downstream.send_packet(
                    "chat_message",
                    pack_chat("§9§l∎ §4No game to requeue!", 0)
                )
            else:
                self.upstream.send_packet(
                    "chat_message",
                    buff.pack_string(f"/play {self.game['mode']}")
                )
        case ["/autoboop", *args]:
            if not args:
                if len(self.settings.autoboops) > 0:
                    autoboops = str(self.settings.autoboops).replace(",", "§3,§c")
                    autoboops = ((autoboops.replace("[", "")).replace("]", "")).replace("'", "")
                    self.downstream.send_packet(
                        "chat_message",
                        pack_chat(f"§9§l∎ §3People in autoboop list: §c{autoboops}§c", 0)
                    )
                else:
                    self.downstream.send_packet(
                        "chat_message",
                        pack_chat("§9§l∎ §4No one in autoboop list!", 0)
                    )
            elif len(args) > 1:
                self.downstream.send_packet(
                    "chat_message",
                    pack_chat(f"§9§l∎ §4Command <{segments[0]}> takes at most one argument!", 0)
                )
            elif str("".join(args)).lower() in self.settings.autoboops:
                boop = str("".join(args)).lower()
                self.settings.autoboops.remove(boop)
                self.downstream.send_packet(
                    "chat_message",
                    pack_chat(f"§9§l∎ §c{boop} §3has been removed from autoboop", 0)
                )
                
            elif str("".join(args)).lower() not in self.settings.autoboops:
                boop = str("".join(args)).lower()
                self.settings.autoboops.append(boop)
                self.downstream.send_packet(
                    "chat_message",
                    pack_chat(f"§9§l∎ §c{boop} §3has been added to autoboop", 0)
                )
        case ["/teams"]:
            try:
                with open('./teams.json', 'w') as file:
                    json.dump(self.teams, file, indent=4)
            except:
                print("skill issue bud.")
        case ["/garlicbread"]: # Mmm, garlic bread.
            self.downstream.send_packet( # Mmm, garlic bread.
                    "chat_message", # Mmm, garlic bread.
                    pack_chat("§eMmm, garlic bread.", 0) # Mmm, garlic bread.
                ) # Mmm, garlic bread.
        case _:
            buff.restore()
            self.upstream.send_packet("chat_message", buff.pack_string(command))
