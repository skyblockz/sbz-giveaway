import datetime
import json
import logging
import traceback

import asyncpg
import discord
from discord.ext import commands, tasks

import db


class SBZGiveawayBot(commands.Bot):
    def __init__(self, **options):
        super().__init__(**options)
        self.db = None
        self.loaded_db = False


intents = discord.Intents.all()
logging.basicConfig(level=logging.INFO)
bot = SBZGiveawayBot(command_prefix='g$', intents=intents)
bot.load_extension('jishaku')

with open('token.json', 'r') as f:
    tokens = json.loads(f.read())


@bot.event
async def on_connect():
    if not bot.loaded_db:
        logging.info('LOADED DATABASE')
        bot.db = await asyncpg.create_pool(**tokens['pgsql'])
        await db.ensure_database_validity(bot.db)
        bot.loaded_db = True
    print('Connected')


@bot.event
async def on_ready():
    print('Ready')


@tasks.loop(seconds=1)
async def check_giveaways():
    if not bot.loaded_db:
        # bot hasnt loaded DB yet
        return
    need_rolling = await db.get_need_rolling_giveaways(bot.db)
    if len(need_rolling) == 0:
        pass
    else:
        for ga_id in need_rolling:
            try:
                winners = await db.roll_winner(bot.db, ga_id)
            except db.NoParticipants:
                details = await db.get_info_of_giveaway(bot.db, ga_id)
                embed = discord.Embed(title=details['prize_name'],
                                      description='No one has joined the giveaway, thus the roll has been canceled',
                                      colour=discord.Colour.dark_red())
                embed.add_field(name='Hosted By', value=details['host'])
                if details['image'] is not None:
                    embed.set_image(url=details['image'])
                embed.timestamp = datetime.datetime.utcfromtimestamp(details['created_at'] + details['length'])
                embed.set_footer(text=f'ID: {ga_id}| Ended At')
                cc = bot.get_channel(details['channel_id'])
                mc = await cc.fetch_message(details['message_id'])
                await mc.edit(embed=embed)
                await cc.send(
                    f'Giveaway of {details["prize_name"]} (ID:{str(ga_id)}) has been canceled, due to no participants in the giveaway')
                continue
            except db.NotEnoughParticipants:
                details = await db.get_info_of_giveaway(bot.db, ga_id)
                embed = discord.Embed(title=details['prize_name'],
                                      description=f'Not enough people joined the giveaway (only {len(details["participants"])}), thus the roll has been canceled',
                                      colour=discord.Colour.dark_red())
                embed.add_field(name='Hosted By', value=details['host'])
                if details['image'] is not None:
                    embed.set_image(url=details['image'])
                embed.timestamp = datetime.datetime.utcfromtimestamp(details['created_at'] + details['length'])
                embed.set_footer(text=f'ID: {ga_id}| Ended At')
                cc = bot.get_channel(details['channel_id'])
                mc = await cc.fetch_message(details['message_id'])
                await mc.edit(embed=embed)
                await cc.send(
                    f'Giveaway of {details["prize_name"]} (ID:{str(ga_id)}) has been canceled, due to not enough people joined the giveaway (only {len(details["participants"])})')
                continue
            details = await db.get_info_of_giveaway(bot.db, ga_id)
            winners_ping = [f'<@!{i}>' for i in details['winners']]
            embed = discord.Embed(title=details['prize_name'],
                                  description=f'Winner{"s" if details["winner_count"] > 1 else ""}: {" ".join(winners_ping)}'
                                  )
            embed.add_field(name='Hosted By', value=details['host'])
            if details['image'] is not None:
                embed.set_image(url=details['image'])
            embed.timestamp = datetime.datetime.utcfromtimestamp(details['created_at'] + details['length'])
            embed.set_footer(text=f'ID: {ga_id}| Ended At')
            cc = bot.get_channel(details['channel_id'])
            mc = await cc.fetch_message(details['message_id'])
            await mc.edit(embed=embed)
            await cc.send(
                f'Giveaway of {details["prize_name"]} (ID:{str(ga_id)}) has been rolled, winners: {" ".join(winners_ping)}')



@check_giveaways.error
async def check_giveaways_error_handler(error):
    logging.error('Task check_giveaways has failed')
    traceback.print_exception(type(error), error, error.__traceback__)


check_giveaways.start()
bot.run(tokens['token'])
