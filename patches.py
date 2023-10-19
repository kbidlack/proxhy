import quarry
from quarry.types.buffer import BufferUnderrun
from quarry.types import chat


def data_received(self, data):
            # Decrypt data
            data = self.cipher.decrypt(data)

            # Add it to our buffer
            self.recv_buff.add(data)

            # Read some packets
            while not self.closed:
                # Save the buffer, in case we read an incomplete packet
                self.recv_buff.save()

                # Read the packet
                try:
                    buff = self.recv_buff.unpack_packet(
                        self.buff_type,
                        self.compression_threshold)

                except BufferUnderrun:
                    self.recv_buff.restore()
                    break

                try:
                    # Identify the packet
                    name = self.get_packet_name(buff.unpack_varint())

                    # Dispatch the packet
                    try:
                        self.packet_received(buff, name)
                    except BufferUnderrun:
                        raise quarry.net.protocol.ProtocolError("Packet is too short: %s" % name)

                    # Reset the inactivity timer
                    self.connection_timer.restart()

                except quarry.net.protocol.ProtocolError as e:
                    self.protocol_error(e)


def pack_chat(message: str, _type: int = 0):
    # downstream chat packing works differently from upstream
    # see https://wiki.vg/index.php?title=Protocol&oldid=7368#Chat_Message for types
    # 0: chat (chat box), 1: system message (chat box), 2: above hotbar
    message = chat.Message.from_string(message)

    if _type == 0:
        byte = b'\x00' # chat box
    elif _type == 1:
        byte = b'\x01' # system message (chat box)
    elif _type == 2:
        byte = b'\x02' # above hotbar
    return message.to_bytes() + byte
