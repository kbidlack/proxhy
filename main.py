import json
import os
import re
import time

import dotenv
import msmcauth
from dotenv import load_dotenv
from quarry.net import auth
from quarry.net.proxy import Bridge, DownstreamFactory
from quarry.types.uuid import UUID
from twisted.internet import reactor

from patches import pack_chat
from protocols import DownstreamProtocol, ProxhyUpstreamFactory


class Settings:
    autoboops = []    

    _silence_joins = False
    _silence_mystery = False
    _waiting_for_locraw = False


    def __init__(self):
        self.patterns = {
            # waiting_for_locraw
            "wflp": re.compile("^{.*}$"),
            # silence_joins
            "sjp": re.compile("/\[.*MVP.*].*joined the lobby\!$/"),
            # autoboop
            "abp": re.compile("^Friend >.* joined\.")
        }

        self.checks = {
            "autoboop": (
                lambda x: bool(self.patterns["abp"].match(x)),
                self._autoboop
            )
        }


    def _autoboop(self, bridge, buff, join_message):
        # wait for a second for player to join
        time.sleep(0.2)

        if (player := str(join_message.split()[2]).lower()) in bridge.autoboops:
            bridge.upstream.send_packet(
                "chat_message",
                buff.pack_string(f"/boop {player}")
            )

        buff.restore()
        bridge.downstream.send_packet("chat_message", buff.read())


    @property
    def waiting_for_locraw(self):
        return self._waiting_for_locraw
    
    @waiting_for_locraw.setter
    def waiting_for_locraw(self, value: bool):
        if value is True:
            self._waiting_for_locraw = True
            self.checks.update(
                {
                    "wfl":
                    (
                        lambda x: bool(self.patterns["wflp"].match(x)),
                        self.update_game_from_locraw
                    )
                }
            )
        elif value is False:
            self._waiting_for_locraw = False
            del self.checks["wfl"]
    
    @staticmethod
    def update_game_from_locraw(self, buff, chat_message):
        if self.settings.waiting_for_locraw:
            if "limbo" in chat_message:
                # sometimes it says limbo right when you join a game
                time.sleep(0.1)
                return self.update_game(buff)
            elif "lobbyname" in chat_message:
                # keep previous game
                self.settings.waiting_for_locraw = False
            else:
                self.game = json.loads(chat_message)
                self.settings.waiting_for_locraw = False
        else:
            self.downstream.send_packet(buff.read())
    

    @property
    def silence_mystery(self):
        return self._silence_mystery
    
    @silence_mystery.setter
    def silence_mystery(self, value: bool):
        if value is True:
            self._silence_mystery = True
            self.checks.update(
                {"silence_mystery": (
                    lambda x: x.startswith("✦"),
                    lambda _, buff, __: buff.discard()
                )}
            )
        elif value is False:
            self._silence_mystery = False
            del self.checks["silence_mystery"]

    
    @property
    def silence_joins(self):
        return self._silence_joins

    @silence_joins.setter
    def silence_joins(self, value: bool):
        if value is True:
            self._silence_joins = True
            self.checks.update(
                {
                    "silence_joins":
                    (
                        lambda x: bool(self.patterns["sjp"].match(x))
                        and not ':' in x,
                        lambda _, buff, __: buff.discard()
                    )
                }
            )
        elif value is False:
            self._silence_joins = False
            del self.checks["silence_joins"]


class ProxhyBridge(Bridge):
    upstream_factory_class = ProxhyUpstreamFactory
    settings = Settings()
    game = {}

    # settings
    silence_mystery = False
    autoboops = []

    # !
    sent_commands = []

    load_dotenv()
    try:
        email = os.environ["EMAIL"]
        password = os.environ["PASSWORD"]
    except KeyError:
        print("Please put your email and password in .env file")

    token_gen_time = float(os.environ.get("TOKEN_GEN_TIME", 0))
    access_token = os.environ.get("ACCESS_TOKEN")
    username = os.environ.get("USERNAME")
    uuid = os.environ.get("UUID")


    def gen_auth_info(self):
        dotenv_path = dotenv.find_dotenv()

        auth_info = msmcauth.login(self.email, self.password)
        ProxhyBridge.access_token = auth_info[0]
        ProxhyBridge.username = auth_info[1]
        ProxhyBridge.uuid = str(UUID.from_hex(auth_info[2]))
        ProxhyBridge.token_gen_time = str(time.time())

        dotenv.set_key(
            dotenv_path,
            "TOKEN_GEN_TIME",
            ProxhyBridge.token_gen_time
        )
        dotenv.set_key(
            dotenv_path,
            "ACCESS_TOKEN",
            ProxhyBridge.access_token
        )
        dotenv.set_key(
            dotenv_path,
            "USERNAME",
            ProxhyBridge.username
        )
        dotenv.set_key(
            dotenv_path,
            "UUID",
            ProxhyBridge.uuid
        )
    

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
            case ["/silence", *args]:
                if not args: # TODO multiple args
                    self.downstream.send_packet(
                        "chat_message",
                        pack_chat(f"§9§l∎ §4Command <{segments[0]}> takes one argument: target", 0)
                    )
                elif len(args) > 1:
                    self.downstream.send_packet(
                        "chat_message",
                        pack_chat(f"§9§l∎ §4Command <{segments[0]}> only takes one argument!", 0)
                    )
                elif args == ["mystery"]:
                    self.silence_mystery = not self.silence_mystery

                    self.downstream.send_packet(
                        "chat_message",
                        pack_chat(
                            f"§9§l∎ §2Turned {'§aon' if self.silence_mystery else '§4off'} §2mystery box silencing!",
                            0
                        )
                    )
                elif args == ["joins"]:
                    self.settings.silence_joins = not self.settings.silence_joins
                    self.downstream.send_packet(
                        "chat_message",
                        pack_chat(
                            f"§9§l∎ §2Turned {'§aon' if self.settings.silence_joins else '§4off'} §2lobby join messages silencing!",
                            0
                        )
                    )
                else:
                     self.downstream.send_packet(
                        "chat_message",
                        pack_chat(
                            "§9§l∎ §4Please enter a valid target; either mystery or joins.", 0)
                    )
            case ["/autoboop", *args]:
                if not args:
                    if len(self.autoboops) > 0:
                        autoboops = str(self.autoboops).replace(",", "§3,§c")
                        autoboops = ((autoboops.replace("[", "")).replace("]", "")).replace("'", "")
                        self.downstream.send_packet(
                            "chat_message",
                            pack_chat(f"§9§l∎ §3People in autoboop list: §c{autoboops}§c.", 0)
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
                elif str("".join(args)).lower() in self.autoboops:
                    boop = str("".join(args)).lower()
                    self.autoboops.remove(boop)
                    self.downstream.send_packet(
                        "chat_message",
                        pack_chat(f"§9§l∎ §c{boop} §3has been removed from autoboop", 0)
                    )
                    
                elif str("".join(args)).lower() not in self.autoboops:
                    boop = str("".join(args)).lower()
                    self.autoboops.append(boop)
                    self.downstream.send_packet(
                        "chat_message",
                        pack_chat(f"§9§l∎ §c{boop} §3has been added to autoboop", 0)
                    )
            case _:
                buff.restore()
                self.upstream.send_packet("chat_message", buff.pack_string(command))


    def packet_unhandled(self, buff, direction, name):
        if direction == "downstream":
            self.downstream.send_packet(name, buff.read())
        elif direction == "upstream":
            self.upstream.send_packet(name, buff.read())
    

    def packet_upstream_chat_message(self, buff):
        buff.save()
        chat_message = buff.unpack_string()
        
        # parse commands
        if chat_message.startswith('/'):
            self.run_command(buff, chat_message)
            self.sent_commands.append(chat_message) #!
        elif chat_message.startswith('!'):
            event = chat_message.replace('!', '')
            for command in reversed(self.sent_commands):
                if command.startswith('/' + event):
                    self.run_command(buff, command)
                    break
            else:
                self.downstream.send_packet("chat_message", pack_chat(f"Event not found: {event}"))
        else:
            buff.restore()
            self.upstream.send_packet("chat_message", buff.read())
    
    def packet_downstream_join_game(self, buff):
        self.downstream.send_packet("join_game", buff.read())

        # check what game the player is playing
        self.update_game(buff)

    def packet_downstream_chat_message(self, buff):
        buff.save()
        chat_message = buff.unpack_chat().to_string()

        for _, (check, func) in self.settings.checks.items():
            if check(chat_message):
                return func(self, buff, chat_message)
        
        buff.restore()
        self.downstream.send_packet("chat_message", buff.read())

    
    def update_game(self, buff):
        self.upstream.send_packet("chat_message", buff.pack_string("/locraw"))
        self.settings.waiting_for_locraw = True

        # sometimes it doesn't come back properly
        time.sleep(0.1)
        if self.settings.waiting_for_locraw:
            self.upstream.send_packet("chat_message", buff.pack_string("/locraw"))


    def make_profile(self):
        """
        Support online mode
        """

        # https://github.com/barneygale/quarry/issues/135
        if time.time() - self.token_gen_time > 86000.:
            # access token expired or doesn't exist
            print("Credentials expired or do not exist, regenerating them")
            self.gen_auth_info()

        return auth.Profile('(skip)', self.access_token, self.username, UUID.from_hex(self.uuid))


class ProxhyDownstreamFactory(DownstreamFactory):
    protocol = DownstreamProtocol
    bridge_class = ProxhyBridge
    motd = "Epic™ Hypixel Proxy | One might even say, Brilliant Move™"


def main():
    # start proxy
    factory = ProxhyDownstreamFactory()

    factory.connect_host = "mc.hypixel.net"
    factory.connect_port = 25565

    factory.listen("127.0.0.1", 13875)
    reactor.run()


if __name__ == "__main__":
    main()
