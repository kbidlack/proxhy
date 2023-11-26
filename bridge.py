import os
import re
import sys
import time

import dotenv
import msmcauth
from quarry.net import auth
from quarry.net.proxy import Bridge, DownstreamFactory, UpstreamFactory
from quarry.types.buffer import Buffer1_7
from quarry.types.uuid import UUID
from twisted.internet import reactor

from commands import run_command
from errors import CommandException
from models import Settings, Team
from patches import Client
from protocols import DownstreamProtocol, UpstreamProtocol


class ProxhyUpstreamFactory(UpstreamFactory):
    protocol = UpstreamProtocol
    connection_timeout = 10


class ProxhyBridge(Bridge):
    # persists across joins
    upstream_factory_class = ProxhyUpstreamFactory

    settings = Settings()
    client = Client()
    commands = {}

    @classmethod
    def load_env(cls):
        dotenv.load_dotenv()
        if not os.environ.get("EMAIL"):
            print("Please put your email in .env file")
            sys.exit()
        if not os.environ.get("PASSWORD"):
            print("Please put your password in .env file")
            sys.exit()

        cls.settings.email = os.environ.get("EMAIL")
        cls.settings.password = os.environ.get("PASSWORD")
        cls.settings.hypixel_api_key = os.environ.get("HYPIXEL_API_KEY")

        cls.settings.token_gen_time = float(
            os.environ.get("TOKEN_GEN_TIME", 0)
        )
        cls.settings.access_token = os.environ.get("ACCESS_TOKEN")
        cls.settings.username = os.environ.get("USERNAME")
        cls.settings.uuid = os.environ.get("UUID")

    def gen_auth_info(self):
        dotenv_path = dotenv.find_dotenv()

        auth_info = msmcauth.login(
            self.settings.email, self.settings.password
        )
        self.settings.access_token = auth_info[0]
        self.settings.username = auth_info[1]
        self.settings.uuid = str(UUID.from_hex(auth_info[2]))
        if os.environ.get("REGEN_TOKEN"):
            self.settings.token_gen_time = 0
        else:
            self.settings.token_gen_time = time.time()

        dotenv.set_key(
            dotenv_path,
            "TOKEN_GEN_TIME",
            str(self.settings.token_gen_time)
        )
        dotenv.set_key(
            dotenv_path,
            "ACCESS_TOKEN",
            self.settings.access_token
        )
        dotenv.set_key(
            dotenv_path,
            "USERNAME",
            self.settings.username
        )
        dotenv.set_key(
            dotenv_path,
            "UUID",
            self.settings.uuid
        )

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
            reactor.callInThread(run_command, self, buff, chat_message)
            self.settings.sent_commands.append(chat_message) #!
        elif chat_message.startswith('!'):
            event = chat_message.replace('!', '')
            for command in reversed(self.settings.sent_commands):
                if command.startswith('/' + event):
                    reactor.callInThread(run_command, self, buff, command)
                    break
            else:
                self.downstream.send_chat(f"Event not found: {event}")
        else:
            buff.restore()
            self.upstream.send_packet("chat_message", buff.read())

    def packet_downstream_join_game(self, buff: Buffer1_7):
        self.downstream.send_packet("join_game", buff.read())

        # check what game the player is playing
        reactor.callInThread(self.update_game, buff)

    def packet_downstream_chat_message(self, buff: Buffer1_7):
        buff.save()
        chat_message = buff.unpack_chat().to_string()

        for _, (check, func) in self.settings.checks.items():
            if check(chat_message):
                return reactor.callInThread(func, self, buff, chat_message)
        
        buff.restore()
        self.downstream.send_packet("chat_message", buff.read())

    def packet_downstream_teams(self, buff: Buffer1_7):
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
            players = set()
            for _ in range(player_count):
                players.add(buff.unpack_string())

            self.settings.teams.append(
                Team(
                    name,
                    display_name,
                    prefix,
                    suffix,
                    friendly_fire,
                    name_tag_visibility,
                    color,
                    players,
                    bridge=self
                )
            ) 
        # team removal
        elif mode == b'\x01':
            del self.settings.teams[name]
        # team information updation
        elif mode == b'\x02':
            self.settings.teams[name].display_name = buff.unpack_string()
            self.settings.teams[name].prefix = buff.unpack_string()
            self.settings.teams[name].suffix = buff.unpack_string()
            self.settings.teams[name].friendly_fire = buff.read(1)[0]
            self.settings.teams[name].name_tag_visibility = buff.unpack_string()
            self.settings.teams[name].color = buff.read(1)[0]
        # add players to team
        elif mode in (b'\x03', b'\x04'):
            add = True if mode == b'\x03' else False
            player_count = buff.unpack_varint()
            players = [buff.unpack_string() for _ in range(player_count)]
            self.settings.teams[name].update_players(add, *players)

        buff.restore()
        self.downstream.send_packet("teams", buff.read())
    

    def update_game(self, buff: Buffer1_7, retry=0):
        if retry > 2:
            return

        # sometimes it doesn't come back properly, so wait a bit
        time.sleep(0.1)
        self.settings.waiting_for_locraw = True
        self.settings.locraw_retry = retry
        self.upstream.send_chat("/locraw")

    # TODO move to utils
    def make_profile(self):
        """
        Support online mode
        """

        # https://github.com/barneygale/quarry/issues/135
        if time.time() - self.settings.token_gen_time > 86000.:
            # access token expired or doesn't exist
            print("Regenerating credentials...", end="")
            self.gen_auth_info()
            print("done!")

        return auth.Profile(
            '(skip)',
            self.settings.access_token,
            self.settings.username,
            UUID.from_hex(self.settings.uuid)
        )


class ProxhyDownstreamFactory(DownstreamFactory):
    protocol = DownstreamProtocol
    motd = "Epic™ Hypixel Proxy; One might even say, Brilliant Move™"
    bridge_class = ProxhyBridge
    bridge_class.load_env()