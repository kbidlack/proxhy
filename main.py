from twisted.internet import reactor

from bridge import ProxhyDownstreamFactory


def main():
    # start proxy
    factory = ProxhyDownstreamFactory()

    factory.connect_host = "mc.hypixel.net"
    factory.connect_port = 25565

    factory.listen("127.0.0.1", 13875)
    reactor.run()


if __name__ == "__main__":
    main()
