import json
import os
from xmlrpc.client import ProtocolError

import requests
from quarry.net import auth, crypto
from quarry.net.proxy import Downstream, Upstream
from twisted.python import failure

from patches import data_received, downstream_send_chat, send_packet, upstream_send_chat


class UpstreamProtocol(Upstream):
    protocol_version = 47

    # PATCH thread safe packet sending
    def send_packet(self, name, *data):
        return send_packet(self, name, *data)
    
    # PATCH chat message sending
    def send_chat(self, *data):
        return upstream_send_chat(self, *data)

    # PATCH Packet is too long:
    def data_received(self, data):
        return data_received(self, data)

    def packet_login_encryption_request(self, buff):
        p_server_id = buff.unpack_string()

        # 1.7.x
        if self.protocol_version <= 5:
            def unpack_array(b):
                return b.read(b.unpack('h'))
        # 1.8.x
        else:
            def unpack_array(b):
                return b.read(b.unpack_varint(max_bits=16))

        p_public_key = unpack_array(buff)
        p_verify_token = unpack_array(buff)

        if not self.factory.profile.online:
            raise ProtocolError("Can't log into online-mode server while using"
                                " offline profile")

        self.shared_secret = crypto.make_shared_secret()
        self.public_key = crypto.import_public_key(p_public_key)
        self.verify_token = p_verify_token

        # make digest
        digest = crypto.make_digest(
            p_server_id.encode('ascii'),
            self.shared_secret,
            p_public_key)

        # do auth
        # deferred = self.factory.profile.join(digest)
        # deferred.addCallbacks(self.auth_ok, self.auth_failed)

        url = "https://sessionserver.mojang.com/session/minecraft/join"
        payload = json.dumps({
            "accessToken": self.factory.profile.access_token,
            "selectedProfile": self.factory.profile.uuid.to_hex(False),
            "serverId": digest
        })
        headers = {
            'Content-Type': 'application/json'
        }

        r = requests.request(
            "POST", url, headers=headers, data=payload
        )

        if r.status_code == 200:
            self.auth_ok(r.json())
        elif r.status_code == 204:
            self.auth_ok({"id": os.environ["UUID"]})
        else:
            #self.auth_ok({"id": os.environ["UUID"]})
            self.auth_failed(failure.Failure(
                auth.AuthException('unverified', 'unverified username'))
            )


class DownstreamProtocol(Downstream):
    protocol_version = 47

    # PATCH thread safe packet sending
    def send_packet(self, name, *data):
        return send_packet(self, name, *data)

    # PATCH chat message sending
    def send_chat(self, *data):
        return downstream_send_chat(self, *data)

    # PATCH Packet is too long:
    def data_received(self, data):
        return data_received(self, data)

    def packet_login_encryption_response(self, buff):
        if self.login_expecting != 1:
            raise ProtocolError("Out-of-order login")

        # 1.7.x
        if self.protocol_version <= 5:
            def unpack_array(b):
                return b.read(b.unpack('h'))
        # 1.8.x
        else:
            def unpack_array(b):
                return b.read(b.unpack_varint(max_bits=16))

        p_shared_secret = unpack_array(buff)
        p_verify_token = unpack_array(buff)

        shared_secret = crypto.decrypt_secret(
            self.factory.keypair,
            p_shared_secret)

        verify_token = crypto.decrypt_secret(
            self.factory.keypair,
            p_verify_token)

        self.login_expecting = None

        if verify_token != self.verify_token:
            raise ProtocolError("Verify token incorrect")

        # enable encryption
        self.cipher.enable(shared_secret)
        self.logger.debug("Encryption enabled")

        # make digest
        digest = crypto.make_digest(
            self.server_id.encode('ascii'),
            shared_secret,
            self.factory.public_key)

        # do auth
        remote_host = None
        if self.factory.prevent_proxy_connections:
            remote_host = self.remote_addr.host

        # deferred = auth.has_joined(
        #     self.factory.auth_timeout,
        #     digest,
        #     self.display_name,
        #     remote_host)
        # deferred.addCallbacks(self.auth_ok, self.auth_failed)

        r = requests.get(
            'https://sessionserver.mojang.com/session/minecraft/hasJoined',
            params={'username': self.display_name,
                    'serverId': digest,
                    'ip': remote_host
                }
        )

        if r.status_code == 200:
            self.auth_ok(r.json())
        elif r.status_code == 204:
            self.auth_ok({"id": os.environ["UUID"]})
        else:
            self.auth_ok({"id": os.environ["UUID"]})
            # self.auth_failed(failure.Failure(
            #     auth.AuthException('invalid', 'invalid session'))
            # )
