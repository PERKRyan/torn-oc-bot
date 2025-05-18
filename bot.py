
import discord
import asyncio
from discord.ext import tasks, commands
import os
import json
import re
import gspread
from pathlib import Path
from torn_api import get_faction_data
from torn_api import get_faction_balances
from cpr_sync import load_cpr_data
from oc_assignment import suggest_oc
from discord import app_commands
from google.oauth2.service_account import Credentials
from threading import Thread
from flask import Flask

# to fake trafic to keep bot running
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive."

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# Ensure consistent base directory
BASE_DIR = Path(__file__).resolve().parent

# Get token from Secrets
DISCORD_TOKEN = os.environ["DISCORD_BOT_TOKEN"]

if not DISCORD_TOKEN:
    raise ValueError("DISCORD_BOT_TOKEN not found in Secrets!")

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

@tree.error
async def on_app_command_error(interaction, error):
    if isinstance(error, discord.app_commands.errors.CommandOnCooldown):
        await interaction.response.send_message("Slow down!", ephemeral=True)

tree.global_command_check = discord.app_commands.checks.cooldown(1, 3.0)  # 1 use every 3s

@bot.event
async def on_ready():
    print(f'✅ Logged in as {bot.user} (ID: {bot.user.id})')
    print("📡 Starting OC monitor task...")
    print(f"📁 Loaded config: {CONFIG}")
    monitor_ocs.start()
    heartbeat.start()

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

async def member_autocomplete(interaction: discord.Interaction, current: str):
    return [
        app_commands.Choice(name=m.display_name, value=m.display_name)
        for m in interaction.guild.members if current.lower() in m.display_name.lower()
    ][:25]

@tree.command(name="purge", description="Delete all messages sent by the bot in this channel.")
@app_commands.checks.has_permissions(manage_messages=True)
async def purge(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    def is_bot_message(msg):
        return msg.author == interaction.client.user

    deleted = await interaction.channel.purge(limit=1000, check=is_bot_message)
    await interaction.followup.send(f"🗑️ Deleted {len(deleted)} bot message(s).", ephemeral=True)

@tree.command(name="balance", description="Check Torn balance for yourself or another member")
@app_commands.describe(member="Optional: provide a name like 'shandurai [25719]'")
@app_commands.autocomplete(member=member_autocomplete)
async def balance(interaction, member: str = None):
    try:
        data = get_faction_balances()
        balance_data = data.get('balance', {})
        members_list = balance_data.get('members', [])
        if not isinstance(members_list, list):
            await interaction.response.send_message("Faction data format error or missing members list.", ephemeral=True)
            return

        # If no member input, use the caller's display name
        name_to_check = interaction.user.display_name if member is None else member
        match = re.search(r'\[(\d+)\]', name_to_check)
        torn_id = int(match.group(1)) if match else None

        if torn_id is None:
            await interaction.response.send_message(f"Could not extract Torn ID from '{name_to_check}'. Make sure the name includes [ID].", ephemeral=True)
            return

        torn_member = next((m for m in members_list if m.get('id') == torn_id), None)

        if torn_member:
            money = torn_member.get('money', 0)
            points = torn_member.get('points', 0)
            await interaction.response.send_message(f" {torn_member['username']}\n💰 Cash: ${money:,}\n✨ Points: {points}")
        else:
            await interaction.response.send_message(f"No Torn account found for ID {torn_id}.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Error fetching balance: {str(e)}", ephemeral=True)

class BalanceRequestView(discord.ui.View):
    def __init__(self, requester, link):
        super().__init__()
        self.requester = requester
        self.link = link

    @discord.ui.button(label="✅ Complete", style=discord.ButtonStyle.success)
    async def complete(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content=f"✅ Completed by: {interaction.user.display_name}", view=None)

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="❌ Request canceled", view=None)

async def member_autocomplete(interaction: discord.Interaction, current: str):
    return [
        app_commands.Choice(name=m.display_name, value=m.display_name)
        for m in interaction.guild.members if current.lower() in m.display_name.lower()
    ][:25]

@tree.command(name="balance_request", description="Request balance transfer with a specified amount")
@app_commands.describe(amount="The amount you want to request")
async def balance_request(interaction: discord.Interaction, amount: int):
    try:
        data = get_faction_balances()
        balance_data = data.get('balance', {})
        members_list = balance_data.get('members', [])
        if not isinstance(members_list, list):
            await interaction.response.send_message("Faction data format error or missing members list.", ephemeral=True)
            return

        display_name = interaction.user.display_name
        match = re.search(r'\[(\d+)\]', display_name)
        torn_id = int(match.group(1)) if match else None

        if torn_id is None:
            await interaction.response.send_message(f"Could not extract Torn ID from '{display_name}'. Make sure the name includes [ID].", ephemeral=True)
            return

        torn_member = next((m for m in members_list if m.get('id') == torn_id), None)

        if not torn_member:
            await interaction.response.send_message(f"No Torn account found for ID {torn_id}.", ephemeral=True)
            return

        balance = torn_member.get('money', 0)

        if amount > balance:
            await interaction.response.send_message(f"💰 Current balance: ${balance:,}\n❌ Error: Asking for more than you have.", ephemeral=True)
        else:
            link = f"https://www.torn.com/factions.php?step=your/tab=controls&option=give-to-user&giveMoneyTo={torn_id}&money={amount}"
            view = BalanceRequestView(interaction.user, link)
            await interaction.response.send_message(f"💰 Request link: {link}", view=view)
    except Exception as e:
        await interaction.response.send_message(f"Error handling balance request: {str(e)}", ephemeral=True)


class DelinquentView(discord.ui.View):
    def __init__(self, sheet, row_idx, message):
        super().__init__(timeout=None)
        self.sheet = sheet
        self.row_idx = row_idx
        self.message = message

    @discord.ui.button(label="✅ Complete", style=discord.ButtonStyle.success)
    async def complete(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.sheet.update(f'H{self.row_idx + 2}', [['Yes']])  # +2 because header row + 1-based index
        await interaction.response.edit_message(content=f"✅ Completed by: {interaction.user.display_name}", view=None)

    @discord.ui.button(label="❌ Clear", style=discord.ButtonStyle.danger)
    async def clear(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Optional: clear a value in the sheet if needed
        self.sheet.update(f'AC{self.row_idx + 2}', [['']])  # Example: clear 'From' (AC)
        self.sheet.update(f'AD{self.row_idx + 2}', [['']])  # Example: clear 'To' (AD)
        await interaction.response.edit_message(content=f"❌ Value Cleared by: {interaction.user.display_name}", view=None)

@tree.command(name="delinquents", description="Show delinquent transfers with buttons")
async def delinquents(interaction: discord.Interaction):
    try:
        await interaction.response.defer(ephemeral=True)

        creds = Credentials.from_service_account_file(
            'google_creds.json',
            scopes=['https://www.googleapis.com/auth/spreadsheets']
        )
        client = gspread.authorize(creds)
        sheet = client.open_by_key('15Ef4fK0cZH9xeUIwb0SjCj_SYf-wqvrp09qC6IneX7E').worksheet('Delinquents')
        rows = sheet.get_all_values()
        headers = rows[0]
        records = rows[1:]

        for idx, row in enumerate(records):
            if len(row) < 32:
                continue
        
            status = row[24].strip()
            if status:
                continue  # Already completed
        
            from_amount_raw = row[28]
            from_id = row[29]
            to_amount_raw = row[30]
            to_ids_raw = row[31]
        
            if not from_amount_raw or not from_id:
                continue
        
            try:
                from_amount = -int(re.sub(r'[^\d]', '', from_amount_raw))
                from_link = f"https://www.torn.com/factions.php?step=your/tab=controls&option=give-to-user&giveMoneyTo={from_id}&money={abs(from_amount)}"
                await interaction.channel.send(
                    f"💥 From ID link: {from_link}",
                    view=DelinquentView(sheet, idx, f"From {from_id}")
                )
            except Exception as e:
                print(f"Error parsing from: {e}")
                continue
        
            try:
                to_amount = int(re.sub(r'[^\d]', '', to_amount_raw))
                to_ids = to_ids_raw.split()
                for to_id in to_ids:
                    link = f"https://www.torn.com/factions.php?step=your/tab=controls&option=give-to-user&giveMoneyTo={to_id}&money={to_amount}"
                    await interaction.channel.send(
                        f"💸 To ID link: {link}",
                        view=DelinquentView(sheet, idx, f"To {to_id}")
                    )
            except Exception as e:
                print(f"Error parsing to: {e}")
                continue

        await interaction.followup.send("✅ Delinquents list posted.", ephemeral=True)

    except Exception as e:
        await interaction.followup.send(f"Error fetching delinquent data: {str(e)}", ephemeral=True)


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

keep_alive()
bot.run(DISCORD_TOKEN)
