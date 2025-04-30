import discord
import asyncio
from discord.ext import tasks, commands
from dotenv import load_dotenv
import os
import json
from pathlib import Path
from torn_api import get_faction_data
from cpr_sync import load_cpr_data
from oc_assignment import suggest_oc

# Ensure consistent base directory
BASE_DIR = Path(__file__).resolve().parent

# Load token from .env
env_path = BASE_DIR / 'DiscordBotToken.env'
load_dotenv(dotenv_path=env_path)
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

if not DISCORD_TOKEN:
    raise ValueError("DISCORD_BOT_TOKEN not found in .env!")

# Load config.json once
config_path = BASE_DIR / 'config.json'
with open(config_path) as f:
    CONFIG = json.load(f)

DISCORD_CHANNEL_ID = int(CONFIG.get("discord_channel_id", 0))
if DISCORD_CHANNEL_ID == 0:
    print("⚠️ No discord_channel_id found in config. Use /setchannel in Discord to set one.")

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.presences = True

bot = commands.Bot(command_prefix="!", intents=intents)

tree = bot.tree  # for slash commands

@bot.event
async def on_ready():
    print(f'✅ Logged in as {bot.user} (ID: {bot.user.id})')
    print("📡 Starting OC monitor task...")
    print(f"📁 Loaded config: {CONFIG}")
    monitor_ocs.start()
    heartbeat.start()

    # NOTE: tree.fetch() does not exist; skip removal and just sync
    synced = await tree.sync()
    print(f"✅ Synced {len(synced)} global slash commands.")

@tree.command(name="ping", description="Health check")
async def slash_ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"🏓 Pong! Latency: {round(bot.latency * 1000)}ms")

@tree.command(name="status", description="Current faction scope status")
async def slash_status(interaction: discord.Interaction):
    faction_data = get_faction_data()
    faction_name = faction_data.get('name', 'Unknown')
    scope = faction_data.get('crimes', {}).get('scope', 'Unknown')
    await interaction.response.send_message(f"📢 Faction: **{faction_name}**\n🔋 Current Scope: **{scope}**")

@tree.command(name="setchannel", description="Set current channel for OC alerts")
async def slash_setchannel(interaction: discord.Interaction):
    channel_id = interaction.channel.id

    CONFIG["discord_channel_id"] = str(channel_id)
    with open(config_path, "w") as f:
        json.dump(CONFIG, f, indent=4)

    global DISCORD_CHANNEL_ID
    DISCORD_CHANNEL_ID = channel_id

    await interaction.response.send_message(f"✅ This channel is now set for OC alerts: **{interaction.channel.name}**")

@tasks.loop(minutes=1)
async def heartbeat():
    print("💓 Bot is alive...")

@tasks.loop(minutes=5)
async def monitor_ocs():
    try:
        print("🔁 monitor_ocs running...")
        faction_data = get_faction_data()
        cpr_data = load_cpr_data()

        members = faction_data.get("members", {})
        current_scope = faction_data.get("crimes", {}).get("scope", 0)
        guild = discord.utils.get(bot.guilds)

        for pid, info in members.items():
            if info.get("criminal_mission") is None:
                player_cpr = cpr_data.get(pid)
                if player_cpr:
                    oc_level, scope_cost = suggest_oc(player_cpr, current_scope)
                    if oc_level:
                        user = None
                        for member in guild.members:
                            if member.name == player_cpr["Player Name"]:
                                user = member
                                break

                        message = (
                            f"🎯 You are eligible for **Level {oc_level} OC**.\n"
                            f"🔗 [Join your faction's OC page](https://www.torn.com/factions.php?step=your&crimes=1)"
                        )

                        if user:
                            try:
                                await user.send(f"👋 Hey {player_cpr['Player Name']}!\n{message}")
                            except discord.Forbidden:
                                print(f"❌ Cannot DM {player_cpr['Player Name']}, DMs are closed.")

                        if DISCORD_CHANNEL_ID:
                            channel = bot.get_channel(DISCORD_CHANNEL_ID)
                            if channel:
                                await channel.send(f"📣 `{player_cpr['Player Name']}` qualifies for **Level {oc_level} OC**.")
                            else:
                                print(f"⚠️ Configured channel ID {DISCORD_CHANNEL_ID} not found in guild.")
                        else:
                            print("⚠️ DISCORD_CHANNEL_ID is 0 or not set. Skipping public message.")
                    else:
                        print(f"⚠️ {player_cpr['Player Name']} doesn't meet CPR/scope requirements.")
    except Exception as e:
        print(f"🔥 monitor_ocs error: {e}")

bot.run(DISCORD_TOKEN)
