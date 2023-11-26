import time

from patches import Client

client = Client('3e502eff-e9e6-4cd7-8f10-6ea0cdbf6f3d')
players = ["gamerboy80", "kyngk", "perlence", "dukky", "zyyph", "purpled", "gamerboy81", "samuel1997", "HS_79", "PieterMeijer", "Flobo13", "Zovys", "Edumombe08", "ZenithUnleashed_", "ShadeyMcGrady", "_7ms", "puchitime", "wxtchie", "BenBoiGaming", "illes1", "Try_me_Nerd"]
print(f"Checking {len(players)} players")

start_time = time.perf_counter()

response = client.player(*players)
print(f"{len(response)} players returned")
print([player.name for player in response])
print([player.bedwars.level for player in response])

end_time = time.perf_counter()

print("Total time:")
print(end_time - start_time)

# async def main():
#     client = hypixel.Client('3e502eff-e9e6-4cd7-8f10-6ea0cdbf6f3d')
#     async with client:
#         player = await client.player("gamerboy80")
#         del player.raw['player']['stats']['Arcade']['_data']['stats']
#         print(json.dumps(player.raw))

# asyncio.run(main())
