import time

from patches import Client

client = Client('3e502eff-e9e6-4cd7-8f10-6ea0cdbf6f3d')
print(time.perf_counter())
client.player("gamerboy80")
print(time.perf_counter())
client.player("gamerboy80")
print(time.perf_counter())

# async def main():
#     client = hypixel.Client('3e502eff-e9e6-4cd7-8f10-6ea0cdbf6f3d')
#     async with client:
#         player = await client.player("gamerboy80")
#         del player.raw['player']['stats']['Arcade']['_data']['stats']
#         print(json.dumps(player.raw))

# asyncio.run(main())
