import requests
import time
import random
import os
import json
import discord
from discord import app_commands, Intents
import asyncio
from typing import List, Dict, Any
from flask import Flask
from threading import Thread
from discord.ext import tasks

#  1. CONFIGURATION 
DISCORD_BOT_TOKEN_ENV_VAR = "DISCORD_BOT_TOKEN"
WOOT_API_KEY_ENV_VAR = "WOOT_API_KEY"

BASE_API_URL = "https://developer.woot.com"

# Local files for persistence and settings
PERSISTENCE_FILE = "historical_lows.json"
SETTINGS_FILE = "bot_settings.json"  # New file for alert channel configuration
MAX_DEALS_PER_PAGE = 10

# The list of feeds to check (11 total calls per command)
FEED_NAMES = [
    "All", "Clearance", "Computers", "Electronics", "Featured", "Home",
    "Gourmet", "Shirts", "Sports", "Tools", "Wootoff"
]
# For the /category command choices
CATEGORY_CHOICES = [
    app_commands.Choice(name=name, value=name) for name in FEED_NAMES
]

#  2. ALERT RULES (Business Logic) 
MIN_SALE_PRICE = 75.00
MIN_PERCENT_OFF_LOW_TIER = 50
MIN_DOLLAR_SAVINGS = 40.00

# Global caching state
historical_lows_cache = {}


def load_historical_lows():
    """Loads historical prices from the local JSON file into memory."""
    global historical_lows_cache
    if os.path.exists(PERSISTENCE_FILE):
        try:
            with open(PERSISTENCE_FILE, 'r') as f:
                historical_lows_cache = json.load(f)
        except Exception as e:
            print(
                f"WARNING: Could not load historical lows file. Starting with empty cache: {e}"
            )
            historical_lows_cache = {}
    return historical_lows_cache


def save_historical_low(offer_id, price):
    """Saves a new historical low price to the cache and persists to JSON."""
    global historical_lows_cache
    historical_lows_cache[offer_id] = price
    try:
        with open(PERSISTENCE_FILE, 'w') as f:
            json.dump(historical_lows_cache, f, indent=4)
    except Exception as e:
        print(f"ERROR saving historical lows to file: {e}")


def load_settings():
    """Loads bot settings from a local JSON file."""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"WARNING: Could not load settings file: {e}")
            return {}
    return {}


def save_setting(key, value):
    """Saves a specific setting key/value pair and persists to JSON."""
    settings = load_settings()
    settings[key] = value
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=4)
        return True
    except Exception as e:
        print(f"ERROR saving settings to file: {e}")
        return False


#  4. API UTILITY FUNCTION


def fetch_feed_data(feed_name, api_key):
    """Fetches deals for a specific feed (Synchronous request)."""
    endpoint = f"{BASE_API_URL}/feed/{feed_name}"
    headers = {'Accept': 'application/json', 'x-api-key': api_key}

    for attempt in range(3):
        try:
            response = requests.get(endpoint, headers=headers, timeout=10)
            if response.status_code == 200:
                return response.json().get('Items', [])
            elif response.status_code == 429:  # Rate Limit Hit
                delay = 2**attempt + random.uniform(0.5, 1)
                time.sleep(delay)
            else:
                response.raise_for_status()
        except requests.exceptions.Timeout:
            print(f"Request to {feed_name} timed out.")
            continue
        except requests.exceptions.RequestException as e:
            print(f"Error fetching {feed_name}: {e}")
            break
    return []


#  5. DEAL PROCESSING AND FILTERING 


def process_deal_data(raw_deal_data, feed_name):
    """Extracts clean metrics and adds feed context."""
    deal = {
        'offer_id': raw_deal_data.get('OfferId', 'N/A'),
        'title': raw_deal_data.get('Title', 'No Title'),
        'url': raw_deal_data.get('Url', '#'),
        'feed_name': feed_name,
        'sale_price': None,
        'list_price': None,
        'discount_percent': 0.0,
        'savings_amount': 0.0,
        'is_sold_out': raw_deal_data.get('IsSoldOut', True)
    }

    sale_price_data = raw_deal_data.get('SalePrice')
    list_price_data = raw_deal_data.get('ListPrice')

    if sale_price_data and list_price_data:
        try:
            sale_min = sale_price_data.get('Minimum')
            list_min = list_price_data.get('Minimum')

            if isinstance(sale_min, (int, float)) and isinstance(
                    list_min,
                (int, float)) and list_min > 0 and list_min > sale_min:
                deal['sale_price'] = sale_min
                deal['list_price'] = list_min
                deal['discount_percent'] = round(
                    ((list_min - sale_min) / list_min) * 100, 2)
                deal['savings_amount'] = round(list_min - sale_min, 2)
        except (TypeError, AttributeError):
            pass

    return deal


def passes_strict_rules(deal):
    """Checks if a deal meets all minimum quality requirements."""
    if deal['sale_price'] is None or deal['is_sold_out']:
        return False

    if deal['sale_price'] < MIN_SALE_PRICE:
        return False

    if deal['savings_amount'] < MIN_DOLLAR_SAVINGS:
        return False

    if deal['discount_percent'] < MIN_PERCENT_OFF_LOW_TIER:
        return False

    return True


def format_deal_message(deals: List[Dict[str, Any]], page: int,
                        total_pages: int, title: str) -> str:
    """
    Formats a list of deals into a readable Discord message page, ensuring the content
    does not exceed the 2000-character limit.
    """

    start_index = page * MAX_DEALS_PER_PAGE
    end_index = start_index + MAX_DEALS_PER_PAGE
    page_deals = deals[start_index:end_index]

    header = f"✨ **{title}** (Page {page + 1}/{total_pages}) ✨\n\n"

    if not deals:
        return "😔 No exceptional deals found that meet the strict rules at this time."

    response_msg = header
    MAX_LENGTH = 1950

    deals_added_count = 0
    for deal in page_deals:
        # Generate the formatted content for this single deal
        deal_content = (
            f"**{deal['title']}** ({deal['feed_name']})\n"
            f"> 🏷️ **{deal['status']}** | **{deal['discount_percent']:.0f}% OFF** | **Price:** ${deal['sale_price']:.2f} (Save ${deal['savings_amount']:.2f})\n"
            f"> 🔗 <{deal['url']}>\n\n")

        if len(response_msg) + len(deal_content) > MAX_LENGTH:
            remaining_deals = len(page_deals) - deals_added_count
            if remaining_deals > 0:
                response_msg += f"...and {remaining_deals} more deals on this page (Character Limit Reached)."
            break

        response_msg += deal_content
        deals_added_count += 1

    return response_msg


#  6. PAGINATION VIEW 


class DealsView(discord.ui.View):
    """A persistent view for navigating paginated deal results."""

    def __init__(self, deals: List[Dict[str, Any]], title: str, timeout=180):
        super().__init__(timeout=timeout)
        self.deals = deals
        self.title = title
        self.current_page = 0
        self.total_pages = (len(self.deals) + MAX_DEALS_PER_PAGE -
                            1) // MAX_DEALS_PER_PAGE
        self.update_buttons()

    def update_buttons(self):
        """Disables/enables buttons based on current page."""
        if len(self.children) >= 2:
            self.children[0].disabled = self.current_page == 0
            self.children[
                1].disabled = self.current_page == self.total_pages - 1

    async def update_page(self, interaction: discord.Interaction):
        """Formats and updates the message content."""
        try:
            self.update_buttons()
            message = format_deal_message(self.deals, self.current_page,
                                          self.total_pages, self.title)
            await interaction.response.edit_message(content=message, view=self)
        except Exception as e:
            print(
                f"ERROR: Failed to edit message for pagination (Page {self.current_page}): {e}"
            )
            try:
                await interaction.response.send_message(
                    "An unexpected error occurred while loading the page. Please try the command again.",
                    ephemeral=True)
            except Exception as fe:
                print(f"Failed to send followup error message: {fe}")

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous_button(self, interaction: discord.Interaction,
                              button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
        await self.update_page(interaction)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction,
                          button: discord.ui.Button):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
        await self.update_page(interaction)


#  7. DISCORD BOT SETUP AND COMMAND LOGIC 

intents = Intents.default()
intents.message_content = True


class WootBotClient(discord.Client):

    def __init__(self, *, intents: Intents):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.all_qualified_deals: List[Dict[str, Any]] = []
        self.last_fetch_time: float = 0
        self.MAX_CACHE_AGE_SECONDS = 300

    async def on_ready(self):
        await self.tree.sync()
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('Woot Bot is Ready.')

    @tasks.loop(minutes=4.0)
    async def auto_refresh_deals(self):
        """Automatically fetches deals and sends a summary announcement based on settings.json."""
        api_key = os.environ.get(WOOT_API_KEY_ENV_VAR)

        if not api_key:
            print(f"CRITICAL: Woot API Key missing, stopping auto refresh.")
            self.auto_refresh_deals.stop()
            return

        settings = load_settings()
        channel_id_str = settings.get("alerts_channel_id")
        channel = None

        if channel_id_str:
            try:
                channel = self.get_channel(int(channel_id_str))
                if not channel:
                    print(
                        f"WARNING: Alerts Channel ID {channel_id_str} set, but channel not found."
                    )
            except ValueError:
                print(
                    f"ERROR: Alerts Channel ID in settings file is not a valid number."
                )

        try:
            print("Running scheduled 4-minute Woot API refresh...")
            # 1. Fetch and process deals (updates self.all_qualified_deals)
            await self.fetch_and_filter_deals_internal(api_key,
                                                       force_refresh=True)

            total_deals = len(self.all_qualified_deals)
            print(f"Scheduled refresh complete. Found {total_deals} deals.")

            # 2. Send the announcement message if a valid channel was found
            if channel:
                if total_deals > 0:
                    message_content = (
                        f"📣 **Woot Deal Alert!** The 4-minute check found **{total_deals}** "
                        f"exceptional deals that meet the criteria.\n"
                        f"Quickly view them now using the `/deals` command!")
                    await channel.send(message_content)
                else:
                    # Optional: Send a low-key confirmation, or remove this else block to send nothing
                    await channel.send(
                        "✅ Check complete. No exceptional deals found this cycle.",
                        delete_after=30)

        except Exception as e:
            print(f"ERROR in scheduled deal refresh/announcement: {e}")

    @auto_refresh_deals.before_loop
    async def before_auto_refresh_deals(self):
        """Wait until the bot is logged in before starting the loop."""
        await self.wait_until_ready()
        print(
            "Background deal refresh task initialized and waiting for ready signal."
        )

    async def fetch_and_filter_deals_internal(
            self,
            api_key: str,
            force_refresh: bool = False) -> List[Dict[str, Any]]:
        """
        Fetches deals, filters them by strict rules, tracks historical lows, 
        and updates the internal cache. Uses cache if fresh.
        """
        if not force_refresh and (time.time() - self.last_fetch_time
                                  < self.MAX_CACHE_AGE_SECONDS):
            return self.all_qualified_deals

        print("Starting Woot API refresh...")
        load_historical_lows()
        all_qualified_deals = []

        loop = asyncio.get_event_loop()

        for feed_name in FEED_NAMES:
            deals_data = await loop.run_in_executor(None, fetch_feed_data,
                                                    feed_name, api_key)

            for raw_deal in deals_data:
                deal = process_deal_data(raw_deal, feed_name)

                if passes_strict_rules(deal):
                    offer_id = deal['offer_id']

                    current_low = historical_lows_cache.get(
                        offer_id, float('inf'))

                    if deal['sale_price'] < current_low:
                        save_historical_low(offer_id, deal['sale_price'])

                        deal['status'] = "NEW LOW" if current_low == float(
                            'inf') else f"PRICE DROP (Was ${current_low:.2f})"
                        all_qualified_deals.append(deal)
                    else:
                        deal['status'] = "GREAT DEAL"
                        all_qualified_deals.append(deal)

            await asyncio.sleep(random.uniform(1.1, 1.3))

        all_qualified_deals.sort(key=lambda d: d['discount_percent'],
                                 reverse=True)

        self.all_qualified_deals = all_qualified_deals
        self.last_fetch_time = time.time()
        print("Woot API refresh complete.")
        return self.all_qualified_deals


client = WootBotClient(intents=intents)

#  8. SLASH COMMAND IMPLEMENTATIONS 


#  NEW HELP COMMAND 
@client.tree.command(
    name="help", description="Shows a guide on how to use the Woot Deals Bot.")
async def help_command(interaction: discord.Interaction):
    """Handles the /help command, providing bot documentation."""
    await interaction.response.defer(thinking=False, ephemeral=True)

    help_message = (
        "🤖 **Woot Deals Bot Guide**\n"
        "This bot automatically checks Woot's API for exceptional deals "
        "that meet strict criteria (e.g., >$75 sale price, >50% off).\n\n"
        ""
        "## 🛠️ Admin Setup (Must be run once)\n"
        "The bot needs to know where to send automatic alerts:\n"
        "`/setalerts channel: #channel-name`\n"
        "> *Use this command in the channel you want alerts to appear in. Requires **Manage Channels** permission.*\n\n"
        ""
        "## ✨ User Commands\n"
        "| Command | Description |\n"
        "| : | : |\n"
        "| `/deals` | Lists the top deals from the pre-loaded cache (fast response). |\n"
        "| `/category` | Filters the deals by a specific category (e.g., `Computers`). |\n"
        "| `/search` | Searches the current qualifying deals for a keyword (e.g., `coffee maker`). |\n\n"
        ""
        "## 🔄 Maintenance Commands\n"
        "| Command | Description |\n"
        "| : | : |\n"
        "| `/refresh` | Manually forces the bot to check all feeds immediately. (Usually takes ~15 seconds and is done automatically every 4 minutes). |\n"
        "| `/help` | Shows this guide. |\n\n"
        "**Note:** Deals labeled as **PRICE DROP** are currently at a lower price than ever recorded by the bot!"
    )

    await interaction.followup.send(help_message, ephemeral=True)


#  END NEW HELP COMMAND 


@client.tree.command(
    name="setalerts",
    description=
    "[Admin] Sets the alert channel for automatic deal announcements.")
@app_commands.describe(
    channel='The channel where automatic deal alerts should be sent.')
@app_commands.default_permissions(manage_channels=True)
async def set_alerts_channel(interaction: discord.Interaction,
                             channel: discord.TextChannel):
    """Allows an admin to set the alert channel."""
    await interaction.response.defer(thinking=False, ephemeral=True)

    new_channel_id = str(channel.id)

    if save_setting("alerts_channel_id", new_channel_id):
        response_msg = (
            f"✅ Success! Automatic Woot deal alerts will now be sent to {channel.mention} "
            f"(ID: `{new_channel_id}`).\n\n"
            f"The refresh interval is set to 4 minutes.")
    else:
        response_msg = "❌ Error saving the settings. Please check the bot's permissions on the Replit filesystem."

    await interaction.followup.send(response_msg, ephemeral=True)


@client.tree.command(
    name="refresh",
    description=
    "Forces the bot to immediately check the Woot API for new deals.")
async def refresh_command(interaction: discord.Interaction):

    await interaction.response.defer(thinking=True)

    api_key = os.environ.get(WOOT_API_KEY_ENV_VAR)
    if not api_key:
        await interaction.followup.send(
            f"Error: Woot API Key (`{WOOT_API_KEY_ENV_VAR}`) not found.")
        return

    try:
        start_time = time.time()
        await client.fetch_and_filter_deals_internal(api_key,
                                                     force_refresh=True)
        elapsed = time.time() - start_time

        if not client.all_qualified_deals:
            msg = f"✅ Refresh complete in {elapsed:.2f}s. No new exceptional deals found."
        else:
            msg = f"✅ Refresh complete in {elapsed:.2f}s. Found **{len(client.all_qualified_deals)}** exceptional deals!"

        await interaction.followup.send(msg)

    except requests.exceptions.RequestException as e:
        await interaction.followup.send(
            f"An error occurred while connecting to Woot API during refresh: {e}"
        )
    except Exception as e:
        print(f"Unhandled error in /refresh: {e}")
        await interaction.followup.send(
            "An unexpected error occurred while processing the refresh.")


@client.tree.command(
    name="deals",
    description=
    f"Lists the top {MAX_DEALS_PER_PAGE} deals matching the strict criteria (paginated)."
)
async def list_deals(interaction: discord.Interaction):

    await interaction.response.defer(thinking=True)

    api_key = os.environ.get(WOOT_API_KEY_ENV_VAR)
    if not api_key:
        await interaction.followup.send(
            f"Error: Woot API Key (`{WOOT_API_KEY_ENV_VAR}`) not found.")
        return

    try:
        all_deals = await client.fetch_and_filter_deals_internal(api_key)

        if not all_deals:
            await interaction.followup.send(
                "😔 No exceptional deals found that meet the strict rules at this time."
            )
            return

        title = f"Top {len(all_deals)} Exceptional Woot Deals"
        total_pages = (len(all_deals) + MAX_DEALS_PER_PAGE -
                       1) // MAX_DEALS_PER_PAGE

        view = DealsView(all_deals, title)
        message = format_deal_message(all_deals, 0, total_pages, title)

        await interaction.followup.send(content=message, view=view)

    except requests.exceptions.RequestException as e:
        await interaction.followup.send(
            f"An error occurred while connecting to Woot API: {e}")
    except Exception as e:
        print(f"Unhandled error in /deals: {e}")
        await interaction.followup.send(
            "An unexpected error occurred while processing deals.")


@client.tree.command(
    name="category",
    description=
    "Lists deals matching the criteria within a specific Woot category.")
@app_commands.describe(feed_name='The specific Woot category/feed to check.')
@app_commands.choices(feed_name=CATEGORY_CHOICES)
async def category_deals(interaction: discord.Interaction, feed_name: str):

    await interaction.response.defer(thinking=True)

    api_key = os.environ.get(WOOT_API_KEY_ENV_VAR)
    if not api_key:
        await interaction.followup.send(
            f"Error: Woot API Key (`{WOOT_API_KEY_ENV_VAR}`) not found.")
        return

    try:
        all_deals = await client.fetch_and_filter_deals_internal(api_key)

        category_deals_list = [
            deal for deal in all_deals if deal['feed_name'] == feed_name
        ]

        if not category_deals_list:
            response_msg = f"🔍 No exceptional deals found in the **{feed_name}** category at this time."
            await interaction.followup.send(response_msg)
            return

        title = f"Exceptional Deals in {feed_name}"
        total_pages = (len(category_deals_list) + MAX_DEALS_PER_PAGE -
                       1) // MAX_DEALS_PER_PAGE

        view = DealsView(category_deals_list, title)
        message = format_deal_message(category_deals_list, 0, total_pages,
                                      title)

        await interaction.followup.send(content=message, view=view)

    except requests.exceptions.RequestException as e:
        await interaction.followup.send(
            f"An error occurred while connecting to Woot API: {e}")
    except Exception as e:
        print(f"Unhandled error in /category: {e}")
        await interaction.followup.send(
            "An unexpected error occurred while processing category deals.")


@client.tree.command(
    name="search",
    description="Searches for a specific item among current deals.")
@app_commands.describe(
    item_name='The name or keyword to search for (e.g., "coffee maker").')
async def search_deals(interaction: discord.Interaction, item_name: str):

    await interaction.response.defer(thinking=True)

    api_key = os.environ.get(WOOT_API_KEY_ENV_VAR)
    if not api_key:
        await interaction.followup.send(
            f"Error: Woot API Key (`{WOOT_API_KEY_ENV_VAR}`) not found.")
        return

    try:
        qualifying_deals = await client.fetch_and_filter_deals_internal(api_key
                                                                        )

        search_term = item_name.lower()
        matching_deals = [
            deal for deal in qualifying_deals
            if search_term in deal['title'].lower()
        ]

        if not matching_deals:
            response_msg = f"🔍 No deals matching '**{item_name}**' found that meet the strict criteria."
            await interaction.followup.send(response_msg)
            return

        matching_deals.sort(key=lambda d: d['discount_percent'], reverse=True)

        title = f"{len(matching_deals)} Deals Matching '{item_name}'"
        total_pages = (len(matching_deals) + MAX_DEALS_PER_PAGE -
                       1) // MAX_DEALS_PER_PAGE

        view = DealsView(matching_deals, title)
        message = format_deal_message(matching_deals, 0, total_pages, title)

        await interaction.followup.send(content=message, view=view)

    except requests.exceptions.RequestException as e:
        await interaction.followup.send(
            f"An error occurred while connecting to Woot API: {e}")
    except Exception as e:
        print(f"Unhandled error in /search: {e}")
        await interaction.followup.send(
            "An unexpected error occurred while processing deals.")


#  9. UPTIME KEEP-ALIVE SERVER - Irrelevant for non-Replit

app = Flask('')


@app.route('/')
def home():
    """Simple route to confirm the server is running."""
    return "WootDeals Bot is running!"


def run_web_server():
    """Starts the Flask web server."""
    app.run(host='0.0.0.0', port=os.environ.get('PORT', 8080))


def start_server_thread():
    """Starts the web server in a separate thread so it doesn't block the Discord bot."""
    server_thread = Thread(target=run_web_server)
    server_thread.daemon = True
    server_thread.start()
    print("Keep-alive web server started.")


if __name__ == '__main__':
    # Start the web server in the background (Essential for Replit uptime)
    start_server_thread()

    bot_token = os.environ.get(DISCORD_BOT_TOKEN_ENV_VAR)
    if not bot_token:
        print(
            f"FATAL ERROR: Discord Bot Token ('{DISCORD_BOT_TOKEN_ENV_VAR}') not set."
        )
    else:
        try:
            client.run(bot_token)
        except Exception as e:
            print(
                f"Failed to run the Discord Bot. Check your token and network connectivity: {e}"
            )
