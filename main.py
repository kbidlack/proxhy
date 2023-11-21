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
from quarry.types.buffer import Buffer1_7
from twisted.internet import reactor

from commands import run_command
from patches import Client, pack_chat
from protocols import DownstreamProtocol, ProxhyUpstreamFactory


class Settings:
    def __init__(self):
        self.autoboops = []
        self.waiting_for_locraw = True

        self.patterns = {
            # waiting_for_locraw
            "wflp": re.compile("^{.*}$"),
            # autoboop
            "abp": re.compile(r"^Friend >.* joined\.")
        }

        self.checks = {
            "autoboop": (
                lambda x: bool(self.patterns["abp"].match(x)),
                self.autoboop
            ),
            "waiting_for_locraw": (
                lambda x: bool(self.patterns["wflp"].match(x)),
                self.update_game_from_locraw
            )
        }


    def autoboop(self, bridge, buff: Buffer1_7, join_message):
        # wait for a second for player to join
        time.sleep(0.1)

        if (player := str(join_message.split()[2]).lower()) in self.autoboops:
            bridge.upstream.send_packet(
                "chat_message",
                buff.pack_string(f"/boop {player}")
            )

        buff.restore()
        bridge.downstream.send_packet("chat_message", buff.read())
    
    def update_game_from_locraw(self, bridge, buff: Buffer1_7, chat_message):
        if self.waiting_for_locraw:
            if "limbo" in chat_message:
                # sometimes it says limbo right when you join a game
                time.sleep(0.1)
                return bridge.update_game(buff)
            elif "lobbyname" in chat_message:
                # keep previous game
                self.waiting_for_locraw = False
            else:
                bridge.game = json.loads(chat_message)
                self.waiting_for_locraw = False
        else:
            buff.restore()
            bridge.downstream.send_packet("chat_message", buff.read())
    

class ProxhyBridge(Bridge):
    # persists across joins
    upstream_factory_class = ProxhyUpstreamFactory
    settings = Settings()

    game = {}
    teams = {}

    # !
    sent_commands = []

    load_dotenv()
    try:
        email = os.environ["EMAIL"]
        password = os.environ["PASSWORD"]
    except KeyError:
        print("Please put your email and password in .env file")

    token_gen_time = 0 # float(os.environ.get("TOKEN_GEN_TIME", 0)) this doesnt work!!!! fix it.
    access_token = os.environ.get("ACCESS_TOKEN")
    username = os.environ.get("USERNAME")
    uuid = os.environ.get("UUID")
    hypixel_api_key = os.environ.get("HYPIXEL_API_KEY")

    client = Client(hypixel_api_key)

    def gen_auth_info(self):
        dotenv_path = dotenv.find_dotenv()

        auth_info = msmcauth.login(self.email, self.password)
        ProxhyBridge.access_token = auth_info[0]
        ProxhyBridge.username = auth_info[1]
        ProxhyBridge.uuid = str(UUID.from_hex(auth_info[2]))
        ProxhyBridge.token_gen_time = time.time()

        dotenv.set_key(
            dotenv_path,
            "TOKEN_GEN_TIME",
            str(ProxhyBridge.token_gen_time)
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

    # THIS DOES NOT WORK
    @staticmethod
    def packet_catch_errors(func):
        def inner(self, buff: Buffer1_7, *args, **kwargs):
            try:
                buff.save()
                func(self, buff, *args, **kwargs)
            except Exception as e:
                direction = func.__name__.split('_')[1]
                name = '_'.join(func.__name__.split('_')[2:])
                if direction == "downstream":
                    self.downstream.send_packet(name, buff.read())
                elif direction == "upstream":
                    self.upstream.send_packet(name, buff.read())
                print(e)
        return inner

    
    def packet_unhandled(self, buff: Buffer1_7, direction, name):
        if direction == "downstream":
            self.downstream.send_packet(name, buff.read())
        elif direction == "upstream":
            self.upstream.send_packet(name, buff.read())
    
    def packet_upstream_chat_message(self, buff: Buffer1_7):
        buff.save()
        chat_message = buff.unpack_string()
        
        # parse commands
        if chat_message.startswith('/'):
            run_command(self, buff, chat_message)
            self.sent_commands.append(chat_message) #!
        elif chat_message.startswith('!'):
            event = chat_message.replace('!', '')
            for command in reversed(self.sent_commands):
                if command.startswith('/' + event):
                    run_command(self, buff, command)
                    break
            else:
                self.downstream.send_packet("chat_message", pack_chat(f"Event not found: {event}"))
        else:
            buff.restore()
            self.upstream.send_packet("chat_message", buff.read())

    def packet_downstream_join_game(self, buff: Buffer1_7):
        self.downstream.send_packet("join_game", buff.read())

        # check what game the player is playing
        self.update_game(buff)

    def packet_downstream_chat_message(self, buff: Buffer1_7):
        buff.save()
        chat_message = buff.unpack_chat().to_string()

        for _, (check, func) in self.settings.checks.items():
            if check(chat_message):
                return func(self, buff, chat_message)
        
        buff.restore()
        self.downstream.send_packet("chat_message", buff.read())

    def packet_downstream_teams(self, buff):
        buff.save()

        name = buff.unpack_string()
        mode = buff.read(1)

        # team creation
        if mode == b'\x00':
            display_name = buff.unpack_string()
            prefix = buff.unpack_string()
            suffix = buff.unpack_string()
            friendly_fire = buff.read(1)[0]
            name_tag_visibility = buff.unpack_string()
            color = buff.read(1)[0]

            player_count = buff.unpack_varint()
            players = []
            for _ in range(player_count):
                players.append(buff.unpack_string())
            
            self.teams.update(
                {
                    name: {
                    "display_name": display_name,
                    "prefix": prefix,
                    "suffix": suffix,
                    "friendly_fire": friendly_fire,
                    "name_tag_visibility": name_tag_visibility,
                    "color": color,
                    "players": players
                    }
                }
            )
        # team removal
        elif mode == b'\x01':
            del self.teams[name]
        # team information updation
        elif mode == b'\x02':
            self.teams[name]["display_name"] = buff.unpack_string()
            self.teams[name]["prefix"] = buff.unpack_string()
            self.teams[name]["suffix"] = buff.unpack_string()
            self.teams[name]["friendly_fire"] = buff.read(1)[0]
            self.teams[name]["name_tag_visibility"] = buff.unpack_string()
            self.teams[name]["color"] = buff.read(1)[0]
        # add players to team
        elif mode == b'\x03':
            player_count = buff.unpack_varint()
            for _ in range(player_count):
                self.teams[name]["players"].append(buff.unpack_string())
        # remove players from team
        elif mode == b'\x04':
            player_count = buff.unpack_varint()
            players = []
            for _ in range(player_count):
                self.teams[name]["players"].remove(buff.unpack_string())

        buff.restore()
        self.downstream.send_packet("teams", buff.read())
    

    def update_game(self, buff: Buffer1_7):
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
            print("Regenerating credentials...", end="")
            self.gen_auth_info()
            print("done!")

        return auth.Profile('(skip)', self.access_token, self.username, UUID.from_hex(self.uuid))


def main():
    class ProxhyDownstreamFactory(DownstreamFactory):
        protocol = DownstreamProtocol
        bridge_class = ProxhyBridge
        motd = "Epic™ Hypixel Proxy | One might even say, Brilliant Move™"

    # start proxy
    factory = ProxhyDownstreamFactory()

    factory.connect_host = "mc.hypixel.net"
    factory.connect_port = 25565

    factory.listen("127.0.0.1", 13875)
    reactor.run()


if __name__ == "__main__":
    main()
